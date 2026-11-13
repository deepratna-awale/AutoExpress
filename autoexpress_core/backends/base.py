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
from contextlib import contextmanager
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import requests
import sdmux
from sdmux.backends import BACKENDS as SDMUX_BACKENDS
from sdmux.backends.base import Backend as SdmuxBackend
from sdmux.names import extract_loras, lora_stem, match_choice  # noqa: F401
from sdmux.transport import Options as ConnectionOptions
from sdmux.transport import RESERVED_HEADERS, normalize_url, redact_url, split_credentials  # noqa: F401
from sdmux.transport import parse_headers as _parse_headers

from ..animation import ANIMATE
from ..instruction_edit import INPAINT, INSTRUCT, METHODS
from ..live2d import DECOMPOSE
from ..payload import SAME_CHECKPOINT, find_nested_key
from ..log import log

def same_origin(a: str | None, b: str | None) -> bool:
    """True when two URLs point at the same scheme, host and port (credentials ignored)."""
    def origin(url: str | None):
        if not url:
            return None
        try:
            parts = urlsplit(url if re.match(r"^[a-z][a-z0-9+.-]*://", url, re.IGNORECASE) else f"http://{url}")
            port = parts.port or {"http": 80, "https": 443}.get(parts.scheme.lower())
        except ValueError:
            return None
        return parts.scheme.lower(), (parts.hostname or "").lower(), port

    first, second = origin(a), origin(b)
    return first is not None and first == second


class HeaderError(ValueError):
    """Extra headers that can't be sent as written."""


def parse_headers(value) -> dict[str, str]:
    """
    Extra headers for a WebUI behind a login proxy (e.g. Cloudflare Access service tokens).

    Takes a dict, a JSON object, or "Name: value" lines (newline separated).

    Raises:
        HeaderError: A malformed or reserved header, or a value with a line break.
    """
    try:
        return _parse_headers(value)
    except ValueError as e:
        raise HeaderError(str(e).replace("sdmux", "AutoExpress")) from e


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


# sdmux raises its own typed errors; the app and UI switch on these codes instead.
_FROM_SDMUX = (
    (sdmux.Unreachable, BackendUnavailable),
    (sdmux.TimedOut, BackendTimeout),
    (sdmux.AuthRefused, BackendAuthError),
    (sdmux.NotReady, BackendNotReady),
    (sdmux.Rejected, BackendRejected),
    (sdmux.Cancelled, GenerationCancelled),
)


def backend_error(error: Exception) -> BackendError:
    """The BackendError for an sdmux error (or any other failure talking to a WebUI)."""
    if isinstance(error, BackendError):
        return error
    cls = next((ours for theirs, ours in _FROM_SDMUX if isinstance(error, theirs)), BackendError)
    translated = cls(str(error))
    translated.__cause__ = error
    return translated


@contextmanager
def sdmux_errors():
    """Re-raise sdmux errors as BackendErrors."""
    try:
        yield
    except sdmux.SdmuxError as e:
        raise backend_error(e) from e


# Capabilities -----------------------------------------------------------------
@dataclass
class Fix:
    """How to fix a missing capability: steps to follow, commands to copy and links to open."""

    steps: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)

    @staticmethod
    def link(label: str, url: str) -> dict:
        return {"label": label, "url": url}


@dataclass
class Capability:
    """One thing AutoExpress needs (or can use) on a WebUI, checked over its API."""

    key: str
    label: str
    ok: bool
    detail: str = ""
    required: bool = True
    fix: Fix | None = None

    def to_dict(self) -> dict:
        data = dataclasses.asdict(self)
        data["fix"] = None if self.ok or self.fix is None else dataclasses.asdict(self.fix)
        return data


def capability_report(backend: "RemoteBackend", items: list[Capability], error: "BackendError | None" = None) -> dict:
    missing = [item for item in items if item.required and not item.ok]
    return {
        "backend": backend.kind,
        "name": backend.label,
        "url": backend.get_url(),
        "ready": error is None and not missing,
        "error": error.to_dict() if error else None,
        "missing": [item.label for item in missing],
        "items": [item.to_dict() for item in items],
    }


def listed(what: str, names: list[str], fix: Fix | None = None, required: bool = True, key: str | None = None) -> Capability:
    """A capability that is met when the WebUI lists at least one of something."""
    shown = ", ".join(names[:5]) + (f" and {len(names) - 5} more" if len(names) > 5 else "")
    return Capability(
        key or what.lower().replace(" ", "_"),
        what,
        bool(names),
        f"{len(names)} found: {shown}" if names else "None found",
        required,
        fix,
    )


def connection_fix(error: "BackendError", label: str = "the WebUI") -> Fix:
    """What to do when a WebUI can't be reached or refuses the login. Nothing assumes it runs on this machine."""
    if isinstance(error, BackendAuthError):
        return Fix(
            [
                f"{label[:1].upper()}{label[1:]} asked for a login. Open Login under the URL and enter its username and password, or a token.",
                "Behind a login proxy (e.g. Cloudflare Access), add the headers it expects under Extra headers.",
                "Or put the username and password in the URL: https://user:password@host",
            ]
        )
    if isinstance(error, (BackendUnavailable, BackendTimeout)):
        return Fix(
            [
                f"Check that {label} is running and that the address is right, including http:// or https:// and any sub-path.",
                "A WebUI on another machine must listen on the network: start it with --listen (A1111, Forge, SD.Next), "
                "--listen 0.0.0.0 (ComfyUI) or --host 0.0.0.0 (SwarmUI, InvokeAI).",
                "On RunPod and similar hosts, use the proxy URL the host shows for the WebUI's port, "
                "e.g. https://<pod-id>-7860.proxy.runpod.net",
            ]
        )
    return Fix([f"Check the address and that {label} is running."])


# Base backend -----------------------------------------------------------------
class RemoteBackend:
    """
    Base for backends that reach a WebUI over HTTP.

    The connection itself is an sdmux client (self.client): its transport gives every backend
    connect/read timeouts, retries with backoff on connection errors (and on 502/503/504 for
    reads), basic or bearer auth, extra headers and typed errors, and it runs each WebUI's
    session, login, upload, queue and download steps. The backends add what is specific to
    AutoExpress on top: the face edit, instruction edit, animation and Live2D workflows and the
    capability checks with fixes. Listings return an empty list when the server cannot be
    reached, so the UI shows nothing instead of failing.

    img2img keeps the core Backend protocol (an image, or None on failure); the
    reason for a failure is kept in last_error for callers that want it.
    """

    kind = ""
    label = ""
    default_url = "http://127.0.0.1:7860"
    # The sdmux client class this backend drives, by sdmux kind (defaults to kind).
    sdmux_kind: str | None = None
    # Ways this WebUI can change an expression, see instruction_edit.METHODS.
    edit_methods: tuple[str, ...] = (INPAINT,)
    # True when the WebUI can turn a still into a looping clip (Wan 2.2 image to video, see animation).
    can_animate = False
    # True when the WebUI can split a character picture into Live2D layers (See-through, see live2d).
    can_decompose = False

    def __init__(self, url: str | None = None, timeout: float | None = None, options: ConnectionOptions | None = None, **option_overrides) -> None:
        overrides = {key: value for key, value in option_overrides.items() if value is not None}
        if timeout is not None:
            overrides["timeout"] = timeout
        self.last_error: BackendError | None = None
        self.client: SdmuxBackend | None = None
        self._connect(url, ConnectionOptions.build(options, **overrides))

    # Connection -----------------------------------------------------------
    def _connect(self, url: str | None, options: ConnectionOptions) -> None:
        """Open a new sdmux client for url (which may carry user:password@) with options."""
        # A backend sdmux has no client for (a test double, say) still gets sdmux's transport.
        cls = SDMUX_BACKENDS.get(self.sdmux_kind or self.kind, SdmuxBackend)
        # defaults="fixed": AutoExpress sends every setting itself and never wants a model profile looked up.
        self.client = cls(normalize_url(url, self.default_url), options, defaults="fixed")

    @property
    def http(self):
        """The sdmux transport: a requests session bound to the WebUI's base URL."""
        return self.client.http

    @property
    def connection(self) -> ConnectionOptions:
        return self.client.options

    @property
    def session(self) -> requests.Session:
        return self.client.http.session

    @session.setter
    def session(self, session) -> None:
        self.client.http.session = session

    @property
    def _base_url(self) -> str:
        return self.client.url

    @property
    def poll_interval(self) -> float:
        return self.connection.poll_interval

    @poll_interval.setter
    def poll_interval(self, value: float) -> None:
        self.connection.poll_interval = value

    @property
    def job_timeout(self) -> float:
        return self.connection.job_timeout

    def auth_headers(self) -> dict[str, str]:
        """
        The headers that carry this backend's login, for connections the session doesn't make (websockets).

        Includes basic auth as an Authorization header, a bearer token and any extra headers.
        """
        return self.http.auth_headers()

    def auth_summary(self) -> dict:
        """Which login is set, without any secret: safe to send to the browser."""
        return {
            "username": self.connection.username,
            "password": bool(self.connection.password),
            "token": bool(self.connection.token),
            "headers": sorted(self.connection.headers or {}),
        }

    # URL handling ---------------------------------------------------------
    def set_url(self, url: str | None, notify: bool = True) -> None:
        # Credentials from the previous URL stay with the options, as they did before.
        self._connect(url, dataclasses.replace(self.connection))
        if notify:
            self.on_url_changed()

    def set_credentials(self, username: str | None = None, password: str | None = None, token: str | None = None) -> None:
        options = dataclasses.replace(self.connection, username=username or None, password=password or None, token=token or None)
        self._connect(self._base_url, options)
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
        with sdmux_errors():
            return self.http.request(method, path, timeout, **kwargs)

    def _json(self, response: requests.Response):
        with sdmux_errors():
            return self.http.json(response)

    def _check(self, response: requests.Response, what: str) -> requests.Response:
        with sdmux_errors():
            return self.http.check(response, what)

    def _get_json(self, path: str, **kwargs):
        return self._json(self._check(self._request("GET", path, **kwargs), f"GET {path}"))

    def _post_json(self, path: str, body=None, **kwargs):
        return self._json(self._check(self._request("POST", path, json=body, **kwargs), f"POST {path}"))

    def _safe_list(self, what: str, fetch) -> list[str]:
        try:
            return list(fetch())
        except (BackendError, sdmux.SdmuxError, requests.RequestException, ValueError, KeyError, TypeError) as e:
            log.warning(f"Could not fetch {what} from {self.label} at {self._base_url}: {e}")
            return []

    def _fail(self, error: Exception, what: str = "generation"):
        """Record why img2img failed and return None, as the Backend protocol expects."""
        if isinstance(error, sdmux.SdmuxError):
            error = backend_error(error)
        elif not isinstance(error, BackendError):
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

    def lora_identities(self) -> dict[str, set[str]]:
        """Installed LoRA names (as <lora:name> uses them) to identifiers that survive renaming: hashes, training name."""
        return {}

    @property
    def lora_dir(self) -> str | None:
        """The WebUI's LoRA folder when this machine can see it. Unknown for most WebUIs."""
        return None

    def civitai_key_sources(self) -> list[tuple[str, str | None]]:
        """(source, key) pairs for a Civitai key the WebUI already has, for civitai_key.find_civitai_key."""
        return []

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

    def check_ready(self, method: str = INPAINT) -> tuple[bool, str]:
        """Check the server is reachable and has what AutoExpress needs for a method. Returns (ok, message)."""
        try:
            if method == INPAINT:
                self.ensure_ready()
            elif method == ANIMATE:
                self.ensure_animate_ready()
            elif method == DECOMPOSE:
                self.ensure_decompose_ready()
            else:
                self.ensure_edit_ready()
        except (BackendError, sdmux.SdmuxError) as e:
            e = backend_error(e)
            self.last_error = e
            return False, str(e)
        return True, "ok"

    def ensure_ready(self) -> None:
        """Raise a BackendError explaining what is missing; return quietly when ready."""
        raise NotImplementedError

    def ensure_edit_ready(self) -> None:
        """Like ensure_ready, for the instruction edit mode."""
        if INSTRUCT not in self.edit_methods:
            raise BackendNotReady(f"{self.label} has no {METHODS[INSTRUCT]['name']} mode. Use the ComfyUI backend for it.")
        raise NotImplementedError

    def instruction_edit(self, image: str, instruction: str, settings):
        """Apply one edit instruction to a base64 image. Only backends listing INSTRUCT in edit_methods have it."""
        raise NotImplementedError

    def ensure_animate_ready(self) -> None:
        """Like ensure_ready, for animated sprites."""
        raise BackendNotReady(f"{self.label} can't animate sprites. Use the ComfyUI backend with Wan 2.2 for animated sprites.")

    def animate(self, image: str, prompt: str, negative: str, settings) -> list | None:
        """Turn a base64 still into a list of frames (a looping clip). Only backends with can_animate have it."""
        raise NotImplementedError

    def ensure_decompose_ready(self) -> None:
        """Like ensure_ready, for splitting a character into Live2D layers."""
        raise BackendNotReady(f"{self.label} can't split a character into layers. Use the ComfyUI backend with the See-through nodes for Live2D models.")

    def upscale(self, image: str):
        """A base64 picture upscaled with an upscale model (PIL image), or None when the backend has none."""
        return None

    def pose_keypoints(self, image: str) -> list | None:
        """
        The body keypoints in a base64 picture (OpenPose JSON's "people" list, in the picture's
        pixels), or None when the backend has no pose detector.
        """
        return None

    def decompose_layers(self, image: str, settings) -> tuple[list, tuple[int, int]] | None:
        """Split a base64 character picture into layers. Only backends with can_decompose have it."""
        raise NotImplementedError

    def capabilities(self) -> list[Capability]:
        """Everything this WebUI needs for AutoExpress, checked over its API. Override per WebUI."""
        self.ensure_ready()
        return [Capability("api", f"{self.label} API", True)]

    def connection_fix(self, error: "BackendError") -> Fix:
        """What to do when the WebUI can't be reached or refuses the login."""
        return connection_fix(error, self.label)

    def can_install_models(self) -> bool:
        """True when the WebUI can download a LoRA itself through its API (see install_lora)."""
        return False

    def install_lora(self, url: str, name: str, access_token: str | None = None) -> bool:
        """Ask the WebUI to download a LoRA from url into its own LoRA folder. Returns True once installed."""
        return False

    def check_capabilities(self) -> dict:
        """
        A readiness report the UI can show item by item: what is there, what is missing and how to fix it.

        Never raises: an unreachable WebUI or refused login is reported in "error".
        """
        try:
            items = self.capabilities()
        except (BackendError, sdmux.SdmuxError) as e:
            e = backend_error(e)
            self.last_error = e
            item = Capability("api", f"{self.label} API", False, str(e), fix=self.connection_fix(e))
            if isinstance(e, BackendNotReady):
                return capability_report(self, [item])
            return capability_report(self, [item], e)
        return capability_report(self, items)

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
            except (BackendError, sdmux.SdmuxError, requests.RequestException, ValueError, KeyError, TypeError):
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
