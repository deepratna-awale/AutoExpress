"""
Backend for a SwarmUI server, driven through its HTTP API (/API/...).

SwarmUI has ADetailer style face refining built into its prompt syntax:
"<segment:face,creativity,threshold>" (CLIPSeg) or "<segment:yolo-model.pt,...>"
(YOLOv8). The character image is sent as the init image with creativity 0, so
the base pass keeps it as is, and the segment pass inpaints only the face with
the expression prompt.
"""

import io

import requests
from PIL import Image

from ..images import b64_to_pil, pil_to_b64
from ..log import log
from .base import BackendError, FaceEditRequest, RemoteBackend, match_choice
from .comfyui_api import SAMPLERS, SCHEDULERS, pick


def _value(option: str) -> str:
    """Swarm lists some values as 'id///Display Name'."""
    return option.split("///", 1)[0]


class SwarmUIClient(RemoteBackend):

    kind = "swarmui"
    label = "SwarmUI"
    default_url = "http://127.0.0.1:7801"

    def __init__(self, url: str | None = None, timeout: float = 30) -> None:
        super().__init__(url, timeout)
        self._session_id: str | None = None
        self._params: dict[str, dict] | None = None

    def on_url_changed(self) -> None:
        self._session_id = None
        self._params = None

    # API helpers ----------------------------------------------------------
    def _new_session(self) -> str:
        self._session_id = self._post_json("/API/GetNewSession", {})["session_id"]
        return self._session_id

    def _call(self, route: str, body: dict | None = None, timeout: float | None = None) -> dict:
        """POST to /API/<route> with a session, renewing it once if the server dropped it."""
        for attempt in range(2):
            session_id = self._session_id or self._new_session()
            result = self._post_json(f"/API/{route}", {"session_id": session_id, **(body or {})}, timeout=timeout)
            if result.get("error_id") == "invalid_session_id" and attempt == 0:
                self._session_id = None
                continue
            if "error" in result:
                raise BackendError(f"SwarmUI: {result['error']}")
            return result
        raise BackendError("SwarmUI keeps rejecting the session.")

    def params(self) -> dict[str, dict]:
        if self._params is None:
            self._params = {param["id"]: param for param in self._call("ListT2IParams").get("list", [])}
        return self._params

    def param_values(self, param_id: str) -> list[str]:
        return [_value(v) for v in (self.params().get(param_id, {}).get("values") or [])]

    def _list_models(self, subtype: str) -> list[str]:
        result = self._call("ListModels", {"path": "", "depth": 10, "subtype": subtype})
        return [model["name"] for model in result.get("files", [])]

    # Listings -------------------------------------------------------------
    @property
    def models(self) -> list[str]:
        return self._safe_list("models", lambda: self._list_models("Stable-Diffusion"))

    @property
    def loras(self) -> list[str]:
        return self._safe_list("loras", lambda: self._list_models("LoRA"))

    @property
    def samplers(self) -> list[str]:
        return self._safe_list("samplers", lambda: self.param_values("sampler"))

    @property
    def schedulers(self) -> list[str]:
        return self._safe_list("schedulers", lambda: self.param_values("scheduler"))

    def check_ready(self) -> tuple[bool, str]:
        try:
            self._session_id = None
            self._params = None
            models = self._list_models("Stable-Diffusion")
        except (requests.RequestException, BackendError, ValueError) as e:
            return False, f"Could not reach SwarmUI at {self._base_url}. ({e})"
        if not models:
            return False, "SwarmUI has no Stable Diffusion models."
        return True, "ok"

    # Generation -----------------------------------------------------------
    def segment_target(self, detector: str | None) -> str:
        """A YOLO face model SwarmUI has, else CLIPSeg's 'face'."""
        try:
            yolo_models = self.param_values("yolomodelinternal")
        except (requests.RequestException, BackendError):
            yolo_models = []
        model = match_choice(detector, yolo_models) or next((m for m in yolo_models if "face" in m.lower()), None)
        return f"yolo-{model}" if model else "face"

    def build_request(self, request: FaceEditRequest) -> dict:
        models = self._list_models("Stable-Diffusion")
        model = match_choice(request.checkpoint, models)
        if not model:
            if not models:
                raise BackendError("SwarmUI has no models.")
            model = models[0]
            log.warning(
                f"Checkpoint '{request.checkpoint or 'not set'}' not found in SwarmUI, using {model}. "
                "Pick a model to choose another one."
            )

        image = b64_to_pil(request.image)
        width, height = image.size
        loras = " ".join(f"<lora:{name}:{weight}>" for name, weight in request.loras)
        face_prompt = ", ".join(part for part in (request.prompt, loras) if part)
        segment = f"<segment:{self.segment_target(request.detector)},{request.denoise},{request.confidence}>"

        body = {
            "images": 1,
            "prompt": f"{request.prompt} {segment} {face_prompt}".strip(),
            "negativeprompt": request.negative_prompt,
            "model": model,
            "steps": request.steps,
            "cfgscale": request.cfg_scale,
            "seed": request.seed,
            "width": width,
            "height": height,
            "aspectratio": "Custom",
            "initimage": pil_to_b64(image),
            "initimagecreativity": 0,
            "segmentmaskblur": request.mask_blur,
            "segmentmaskgrow": request.dilation,
            "donotsave": True,
        }
        samplers = self.param_values("sampler")
        if request.sampler and samplers:
            body["sampler"] = pick(request.sampler, samplers, SAMPLERS, "euler")
        schedulers = self.param_values("scheduler")
        if request.scheduler and schedulers:
            body["scheduler"] = pick(request.scheduler, schedulers, SCHEDULERS, "normal")
        if request.clip_skip > 1:
            body["clipstopatlayer"] = -request.clip_skip
        return body

    def _load_image(self, ref: str) -> Image.Image:
        if ref.startswith("data:"):
            return b64_to_pil(ref)
        response = self._request("GET", "/" + ref.lstrip("/"))
        response.raise_for_status()
        result = Image.open(io.BytesIO(response.content))
        result.load()
        return result

    def img2img(self, payload: dict) -> Image.Image | None:
        try:
            body = self.build_request(FaceEditRequest.from_payload(payload))
            result = self._call("GenerateText2Image", body, timeout=None)
            images = result.get("images") or []
            if not images:
                log.error("SwarmUI returned no image.")
                return None
            ref = images[0]["image"] if isinstance(images[0], dict) else images[0]
            return self._load_image(ref)
        except (BackendError, requests.RequestException, KeyError, ValueError) as e:
            log.error(f"SwarmUI generation failed: {e}")
            return None

    def interrupt(self) -> None:
        try:
            self._call("InterruptAll", {"other_sessions": False})
        except (requests.RequestException, BackendError) as e:
            log.error(f"Interrupt failed: {e}")
