"""
Shared plumbing for backends that talk to a WebUI over HTTP.

The standalone app builds the same A1111 + ADetailer request body for every
backend. Backends whose WebUI does not speak the A1111 API read the face edit
settings back out of that body with FaceEditRequest and translate them into
their own request format.
"""

import re
from dataclasses import dataclass, field

import requests

from ..payload import SAME_CHECKPOINT, find_nested_key
from ..log import log

LORA_PATTERN = re.compile(r"<\s*lora\s*:\s*([^:>]+?)\s*(?::\s*([-\d.]+)\s*)?>", re.IGNORECASE)


def normalize_url(url: str | None, default: str) -> str:
    """Turn what the user typed (host:port, full URL, trailing slash, nothing) into a base URL."""
    url = (url or "").strip()
    if not url:
        return default
    if not re.match(r"^https?://", url, re.IGNORECASE):
        url = "http://" + url
    return url.rstrip("/")


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


class BackendError(RuntimeError):
    """Raised when the WebUI answers with an error the user should see."""


class RemoteBackend:
    """
    Base for backends that reach a WebUI over HTTP.

    Subclasses implement img2img, interrupt, check_ready and the model listings.
    Listings return an empty list when the server cannot be reached, so the UI
    simply shows nothing instead of failing.
    """

    kind = ""
    label = ""
    default_url = "http://127.0.0.1:7860"

    def __init__(self, url: str | None = None, timeout: float = 30) -> None:
        self.session = requests.Session()
        self.timeout = timeout
        self._base_url = normalize_url(url, self.default_url)

    # URL handling ---------------------------------------------------------
    def set_url(self, url: str | None) -> None:
        self._base_url = normalize_url(url, self.default_url)
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
        return self.session.request(method, f"{self._base_url}{path}", timeout=timeout or self.timeout, **kwargs)

    def _get_json(self, path: str, **kwargs):
        response = self._request("GET", path, **kwargs)
        response.raise_for_status()
        return response.json()

    def _post_json(self, path: str, body=None, **kwargs):
        response = self._request("POST", path, json=body, **kwargs)
        response.raise_for_status()
        return response.json()

    def _safe_list(self, what: str, fetch) -> list[str]:
        try:
            return list(fetch())
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            log.warning(f"Could not fetch {what} from {self.label} at {self._base_url}: {e}")
            return []

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

    def check_ready(self) -> tuple[bool, str]:
        """Check the server is reachable and has what AutoExpress needs. Returns (ok, message)."""
        raise NotImplementedError

    def img2img(self, payload: dict):
        raise NotImplementedError

    def interrupt(self) -> None:
        raise NotImplementedError
