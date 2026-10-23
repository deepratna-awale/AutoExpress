"""
Shared plumbing for backends that talk to a WebUI over HTTP.

The standalone app builds the same A1111 + ADetailer request body for every
backend. Backends whose WebUI does not speak the A1111 API read the face edit
settings back out of that body with FaceEditRequest and translate them into
their own request format.
"""

import dataclasses
import re
import time
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit, urlunsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import ReadTimeoutError
from urllib3.util.retry import Retry

from ..payload import SAME_CHECKPOINT, find_nested_key
from ..log import log

LORA_PATTERN = re.compile(r"<\s*lora\s*:\s*([^:>]+?)\s*(?::\s*([-\d.]+)\s*)?>", re.IGNORECASE)


def normalize_url(url: str | None, default: str) -> str:
    """Turn what the user typed (host:port, full URL, trailing slash, nothing) into a base URL."""
    url = (url or "").strip()
    if not url:
        return default
    if not re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE):
        url = "http://" + url
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Not a valid http(s) URL: {url}")
    return url.rstrip("/")


def split_credentials(url: str) -> tuple[str, str | None, str | None]:
    """Move user:password@ out of a URL so it can be sent as basic auth instead."""
    parts = urlsplit(url)
    if parts.username is None:
        return url, None, None
    netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
    clean = urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    return clean, unquote(parts.username), unquote(parts.password or "")


def lora_stem(name: str) -> str:
    """'SDXL/detail_tweaker.safetensors' -> 'detail_tweaker', the name A1111 style prompts use."""
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.(safetensors|ckpt|pt|pth|bin)$", "", name, flags=re.IGNORECASE)


def extract_loras(prompt: str) -> tuple[str, list[tuple[str, float]]]:
    """
    Pull A1111 style <lora:name:weight> tags out of a prompt.

    Returns:
        tuple[str, list[tuple[str, float]]]: The prompt without the tags, and each lora name with its weight.
    """
    loras = []
    for name, weight in LORA_PATTERN.findall(prompt or ""):
        try:
            loras.append((name.strip(), float(weight) if weight else 1.0))
        except ValueError:
            loras.append((name.strip(), 1.0))
    cleaned = LORA_PATTERN.sub("", prompt or "")
    cleaned = re.sub(r"\s*,\s*(,\s*)+", ", ", cleaned)
    return cleaned.strip().strip(",").strip(), loras


def match_choice(value: str | None, choices: list[str]) -> str | None:
    """
    Find value in a list of names a WebUI offers, ignoring folders, file extensions and case.

    "animagine.safetensors", "SDXL/animagine.safetensors" and "animagine [hash]" all match "animagine".
    """
    if not value or not choices:
        return None
    if value in choices:
        return value

    def stem(name: str) -> str:
        name = re.sub(r"\s*\[[0-9a-fA-F]+\]\s*$", "", name)
        name = name.replace("\\", "/").rsplit("/", 1)[-1]
        name = re.sub(r"\.(safetensors|ckpt|pt|pth|bin|gguf|sft)$", "", name, flags=re.IGNORECASE)
        return name.strip().lower()

    wanted = stem(value)
    return next((choice for choice in choices if stem(choice) == wanted), None)


def _number(value, cast, default):
    try:
        if value is None or value == "":
            return default
        return cast(float(value)) if cast is int else cast(value)
    except (TypeError, ValueError):
        return default


@dataclass
class FaceEditRequest:
    """The face inpainting settings of an AutoExpress request, independent of any WebUI."""

    image: str
    prompt: str = ""
    negative_prompt: str = ""
    loras: list[tuple[str, float]] = field(default_factory=list)
    checkpoint: str | None = None
    steps: int = 28
    cfg_scale: float = 7.0
    sampler: str | None = None
    scheduler: str | None = None
    denoise: float = 0.4
    seed: int = -1
    clip_skip: int = 1
    detector: str = "face_yolov8n.pt"
    confidence: float = 0.3
    dilation: int = 4
    mask_blur: int = 4
    padding: int = 32
    inpaint_size: int | None = None

    @classmethod
    def from_payload(cls, payload: dict) -> "FaceEditRequest":
        """Read the settings out of an A1111 img2img body built by build_expression_payload."""

        def get(key, default=None):
            value = find_nested_key(payload, key)
            return default if value is None else value

        prompt, loras = extract_loras(get("ad_prompt", ""))
        checkpoint = get("ad_checkpoint") if get("ad_use_checkpoint", True) else None
        if checkpoint in ("", SAME_CHECKPOINT, "None"):
            checkpoint = None

        inpaint_size = None
        if get("ad_use_inpaint_width_height", False):
            inpaint_size = max(_number(get("ad_inpaint_width"), int, 512), _number(get("ad_inpaint_height"), int, 512))

        return cls(
            image=(payload.get("init_images") or [""])[0],
            prompt=prompt,
            negative_prompt=get("ad_negative_prompt", ""),
            loras=loras,
            checkpoint=checkpoint,
            steps=_number(get("ad_steps"), int, 28),
            cfg_scale=_number(get("ad_cfg_scale"), float, 7.0),
            sampler=get("ad_sampler") or None,
            scheduler=get("ad_scheduler") or None,
            denoise=_number(get("ad_denoising_strength"), float, 0.4),
            seed=_number(payload.get("seed"), int, -1),
            clip_skip=max(1, _number(get("ad_clip_skip"), int, 1)),
            detector=get("ad_model", "face_yolov8n.pt"),
            confidence=_number(get("ad_confidence"), float, 0.3),
            dilation=_number(get("ad_dilate_erode"), int, 4),
            mask_blur=_number(get("ad_mask_blur"), int, 4),
            padding=_number(get("ad_inpaint_only_masked_padding"), int, 32),
            inpaint_size=inpaint_size,
        )

    def infotext(self, size: tuple[int, int], sampler: str | None = None, seed: int | None = None, version: str = "") -> str:
        """A1111 style generation parameters, so PNGs from any WebUI read back like A1111's."""
        prompt = self.prompt + "".join(f" <lora:{name}:{weight:g}>" for name, weight in self.loras)
        seed = self.seed if seed is None else seed
        fields = {
            "Steps": self.steps,
            "Sampler": sampler or self.sampler,
            "Schedule type": self.scheduler,
            "CFG scale": f"{self.cfg_scale:g}",
            "Seed": seed if seed is not None and seed >= 0 else None,
            "Size": f"{size[0]}x{size[1]}",
            "Model": self.checkpoint,
            "Denoising strength": f"{self.denoise:g}",
            "Clip skip": self.clip_skip if self.clip_skip > 1 else None,
            "ADetailer model": self.detector,
            "ADetailer confidence": f"{self.confidence:g}",
            "ADetailer mask blur": self.mask_blur,
            "Version": version or None,
        }
        params = ", ".join(f"{key}: {value}" for key, value in fields.items() if value not in (None, ""))
        return f"{prompt.strip()}\nNegative prompt: {self.negative_prompt}\n{params}"


# Errors ---------------------------------------------------------------------
class BackendError(RuntimeError):
    """A WebUI request failed. code is a stable id the app and UI can switch on, http_status what the app answers with."""

    code = "backend_error"
    http_status = 502

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self)}

    @staticmethod
    def status_for(code: str | None) -> int:
        """The HTTP status for an error code, 502 for anything unknown."""
        for cls in (BackendError, *BackendError.__subclasses__()):
            if cls.code == code:
                return cls.http_status
        return 502


class BackendUnavailable(BackendError):
    """The WebUI could not be reached at all."""

    code = "backend_unavailable"
    http_status = 503


class BackendTimeout(BackendError):
    """The WebUI accepted the connection but did not answer in time."""

    code = "backend_timeout"
    http_status = 504


class BackendAuthError(BackendError):
    """The WebUI refused the credentials (HTTP 401/403)."""

    code = "backend_auth"
    http_status = 401


class BackendNotReady(BackendError):
    """The WebUI is up but lacks something AutoExpress needs (extension, nodes, models)."""

    code = "backend_not_ready"
    http_status = 409


class BackendRejected(BackendError):
    """The WebUI rejected the request itself (validation error, unknown model, ...)."""

    code = "backend_rejected"
    http_status = 502


class GenerationCancelled(BackendError):
    code = "cancelled"
    http_status = 409


# Base backend -----------------------------------------------------------------
@dataclass
class ConnectionOptions:
    """How to reach a WebUI. Every field has a sensible default for a local install."""

    username: str | None = None
    password: str | None = None
    token: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    connect_timeout: float = 5.0
    timeout: float = 30.0
    job_timeout: float = 1800.0
    retries: int = 2
    verify_tls: bool = True


class RemoteBackend:
    """
    Base for backends that reach a WebUI over HTTP.

    Gives every backend the same transport: connect/read timeouts, retries with
    backoff on connection errors (and on 502/503/504 for reads), basic or
    bearer auth, and typed errors. Subclasses implement img2img, interrupt,
    check_ready and the model listings. Listings return an empty list when the
    server cannot be reached, so the UI shows nothing instead of failing.

    img2img keeps the core Backend protocol (an image, or None on failure); the
    reason for a failure is kept in last_error for callers that want it.
    """

    kind = ""
    label = ""
    default_url = "http://127.0.0.1:7860"

    def __init__(self, url: str | None = None, timeout: float | None = None, options: ConnectionOptions | None = None, **option_overrides) -> None:
        self.connection = dataclasses.replace(options) if options else ConnectionOptions()
        for key, value in option_overrides.items():
            if value is not None:
                setattr(self.connection, key, value)
        if timeout is not None:
            self.connection.timeout = timeout
        self.last_error: BackendError | None = None
        self.session = self._new_session()
        self._base_url = self.default_url
        self.set_url(url, notify=False)

    # Transport ------------------------------------------------------------
    def _new_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=self.connection.retries,
            connect=self.connection.retries,
            read=self.connection.retries,
            status=self.connection.retries,
            backoff_factor=0.5,
            status_forcelist=(502, 503, 504),
            allowed_methods=frozenset({"GET", "HEAD", "OPTIONS"}),
            raise_on_status=False,
            respect_retry_after_header=True,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.verify = self.connection.verify_tls
        session.headers.update({"Accept": "application/json", "User-Agent": "AutoExpress"})
        return session

    def _apply_auth(self, url_user: str | None, url_password: str | None) -> None:
        username = self.connection.username or url_user
        password = self.connection.password if self.connection.username else url_password
        self.session.auth = (username, password or "") if username else None
        self.session.headers.pop("Authorization", None)
        if self.connection.token:
            self.session.headers["Authorization"] = f"Bearer {self.connection.token}"
        self.session.headers.update(self.connection.headers or {})

    # URL handling ---------------------------------------------------------
    def set_url(self, url: str | None, notify: bool = True) -> None:
        clean, user, password = split_credentials(normalize_url(url, self.default_url))
        self._base_url = clean
        if user and not self.connection.username:
            # Keep URL credentials with the other options so copies of this backend have them too.
            self.connection.username, self.connection.password = user, password
        self._apply_auth(None, None)
        if notify:
            self.on_url_changed()

    def set_credentials(self, username: str | None = None, password: str | None = None, token: str | None = None) -> None:
        self.connection.username, self.connection.password, self.connection.token = username or None, password or None, token or None
        self._apply_auth(None, None)
        self.on_url_changed()

    def get_url(self) -> str:
        return self._base_url

    # Kept for the standalone app's older call sites.
    def setURL(self, url: str) -> None:
        self.set_url(url)

    def getURL(self) -> str:
        return self.get_url()

    def on_url_changed(self) -> None:
        """Drop anything cached for the previous server."""

    # HTTP helpers ---------------------------------------------------------
    def _request(self, method: str, path: str, timeout: float | None = None, **kwargs) -> requests.Response:
        """
        Send a request and turn transport failures into typed BackendErrors.

        Args:
            timeout (float | None): Read timeout in seconds; defaults to options.timeout.
        """
        url = f"{self._base_url}{path}"
        read_timeout = timeout if timeout is not None else self.connection.timeout
        try:
            response = self.session.request(method, url, timeout=(self.connection.connect_timeout, read_timeout), **kwargs)
        except requests.exceptions.ConnectTimeout as e:
            raise BackendUnavailable(f"Timed out connecting to {self.label} at {self._base_url}.") from e
        except requests.exceptions.ReadTimeout as e:
            raise BackendTimeout(f"{self.label} did not answer {method} {path} within {read_timeout:g}s.") from e
        except requests.exceptions.SSLError as e:
            raise BackendUnavailable(f"TLS error talking to {self.label} at {self._base_url}: {e}") from e
        except requests.exceptions.ConnectionError as e:
            # Once retries are used up, urllib3 reports a read timeout as a connection error.
            if isinstance(getattr(e.args[0] if e.args else None, "reason", None), ReadTimeoutError):
                raise BackendTimeout(f"{self.label} did not answer {method} {path} within {read_timeout:g}s.") from e
            raise BackendUnavailable(f"Could not reach {self.label} at {self._base_url}. Is it running?") from e
        except requests.exceptions.RequestException as e:
            raise BackendError(f"{self.label} request {method} {path} failed: {e}") from e

        if response.status_code in (401, 403):
            raise BackendAuthError(
                f"{self.label} refused the request ({response.status_code}). Check the username/password or token."
            )
        return response

    @staticmethod
    def _json(response: requests.Response):
        try:
            return response.json()
        except ValueError as e:
            raise BackendRejected(f"Expected JSON but got: {response.text[:300]!r}") from e

    def _check(self, response: requests.Response, what: str) -> requests.Response:
        if response.status_code >= 400:
            raise BackendRejected(f"{self.label} {what} failed ({response.status_code}): {response.text[:1000]}")
        return response

    def _get_json(self, path: str, **kwargs):
        return self._json(self._check(self._request("GET", path, **kwargs), f"GET {path}"))

    def _post_json(self, path: str, body=None, **kwargs):
        return self._json(self._check(self._request("POST", path, json=body, **kwargs), f"POST {path}"))

    def _safe_list(self, what: str, fetch) -> list[str]:
        try:
            return list(fetch())
        except (BackendError, requests.RequestException, ValueError, KeyError, TypeError) as e:
            log.warning(f"Could not fetch {what} from {self.label} at {self._base_url}: {e}")
            return []

    def _fail(self, error: Exception, what: str = "generation"):
        """Record why img2img failed and return None, as the Backend protocol expects."""
        if not isinstance(error, BackendError):
            error = BackendError(f"{what} failed: {error}")
        self.last_error = error
        log.error(f"{self.label} {what} failed: {error}")
        return None

    # Interface ------------------------------------------------------------
    @property
    def models(self) -> list[str]:
        return []

    @property
    def samplers(self) -> list[str]:
        return []

    @property
    def schedulers(self) -> list[str]:
        return []

    @property
    def loras(self) -> list[str]:
        return []

    @property
    def lora_stems(self) -> list[str]:
        """LoRA names as A1111 style <lora:name> tags use them, whatever this WebUI calls the files."""
        return [lora_stem(name) for name in self.loras]

    @property
    def lora_dir(self) -> str | None:
        """The WebUI's LoRA folder when this machine can see it. Unknown for most WebUIs."""
        return None

    def refresh_loras(self) -> bool:
        """Ask the WebUI to rescan its LoRA folder. Returns True if it did."""
        self.on_url_changed()
        return False

    def server_info(self) -> dict:
        """Whatever the WebUI says about itself (version, devices, ...). {} when it says nothing."""
        return {}

    def progress(self) -> dict | None:
        """Progress of the image being generated: {"fraction": 0..1, "eta": seconds or None}, or None if unknown."""
        return None

    def check_ready(self) -> tuple[bool, str]:
        """Check the server is reachable and has what AutoExpress needs. Returns (ok, message)."""
        try:
            self.ensure_ready()
        except BackendError as e:
            self.last_error = e
            return False, str(e)
        return True, "ok"

    def ensure_ready(self) -> None:
        """Raise a BackendError explaining what is missing; return quietly when ready."""
        raise NotImplementedError

    def health(self) -> dict:
        """Reachability, readiness and server info in one dict, for status endpoints."""
        started = time.monotonic()
        ready, message = self.check_ready()
        latency_ms = round((time.monotonic() - started) * 1000)
        error = self.last_error.to_dict() if not ready and self.last_error else None
        info = {}
        if ready or (error and error["code"] not in (BackendUnavailable.code, BackendAuthError.code)):
            try:
                info = self.server_info()
            except (BackendError, requests.RequestException, ValueError, KeyError, TypeError):
                info = {}
        return {
            "backend": self.kind,
            "name": self.label,
            "url": self._base_url,
            "ready": ready,
            "message": message,
            "error": error,
            "latency_ms": latency_ms,
            "info": info,
        }

    def img2img(self, payload: dict):
        raise NotImplementedError

    def interrupt(self) -> None:
        raise NotImplementedError
