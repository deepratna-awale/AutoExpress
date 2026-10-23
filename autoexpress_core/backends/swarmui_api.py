"""
Backend for a SwarmUI server, driven through its HTTP API (/API/...).

SwarmUI has ADetailer style face refining built into its prompt syntax:
"<segment:face,creativity,threshold>" (CLIPSeg) or "<segment:yolo-model.pt,...>"
(YOLOv8). The character image is sent as the init image with creativity 0, so
the base pass keeps it as is, and the segment pass inpaints only the face with
the expression prompt.

When SwarmUI requires accounts, pass a Swarm auth token (sent as the
swarm_token cookie, as SwarmUI expects) or a username and password (logged in
through /API/Login).
"""

import io
from PIL import Image

from ..images import b64_to_pil, pil_to_b64
from ..log import log
from .base import (
    BackendAuthError,
    BackendError,
    BackendNotReady,
    BackendRejected,
    Capability,
    FaceEditRequest,
    Fix,
    RemoteBackend,
    listed,
    match_choice,
)
from .comfyui_api import SAMPLERS, SCHEDULERS, pick


def _value(option: str) -> str:
    """Swarm lists some values as 'id///Display Name'."""
    return option.split("///", 1)[0]


class SwarmUIClient(RemoteBackend):

    kind = "swarmui"
    label = "SwarmUI"
    default_url = "http://127.0.0.1:7801"

    def __init__(self, url: str | None = None, timeout: float | None = None, **options) -> None:
        self._session_id: str | None = None
        self._params: dict[str, dict] | None = None
        self._server: dict = {}
        self._logged_in = False
        super().__init__(url, timeout, **options)

    def _apply_auth(self, url_user: str | None, url_password: str | None) -> None:
        super()._apply_auth(url_user, url_password)
        # SwarmUI reads its auth token from a cookie, not the Authorization header,
        # and does its own login, so neither goes out as HTTP auth.
        self.session.headers.pop("Authorization", None)
        self.session.auth = None
        self.session.cookies.clear()
        if self.connection.token:
            self.session.cookies.set("swarm_token", self.connection.token)
        self._login = (self.connection.username or url_user, self.connection.password if self.connection.username else url_password)
        self._logged_in = False

    def on_url_changed(self) -> None:
        self._session_id = None
        self._params = None
        self._server = {}

    # API helpers ----------------------------------------------------------
    def _log_in(self) -> None:
        username, password = self._login
        if not username or self._logged_in or self.connection.token:
            return
        result = self._post_json("/API/Login", {"username": username, "password": password or ""})
        if result.get("error_id") or result.get("error"):
            raise BackendAuthError(f"SwarmUI login failed: {result.get('error_id') or result.get('error')}")
        self._logged_in = True

    def _new_swarm_session(self) -> str:
        self._log_in()
        result = self._post_json("/API/GetNewSession", {})
        if "session_id" not in result:
            raise BackendAuthError(f"SwarmUI did not open a session: {result.get('error') or result.get('error_id') or result}")
        self._server = {key: result.get(key) for key in ("version", "server_id", "user_id")}
        self._session_id = result["session_id"]
        return self._session_id

    def _call(self, route: str, body: dict | None = None, timeout: float | None = None) -> dict:
        """POST to /API/<route> with a session, renewing it once if the server dropped it."""
        for attempt in range(2):
            session_id = self._session_id or self._new_swarm_session()
            result = self._post_json(f"/API/{route}", {"session_id": session_id, **(body or {})}, timeout=timeout)
            if result.get("error_id") == "invalid_session_id" and attempt == 0:
                self._session_id = None
                continue
            if "error" in result or "error_id" in result:
                raise BackendRejected(f"SwarmUI: {result.get('error') or result.get('error_id')}")
            return result
        raise BackendAuthError("SwarmUI keeps rejecting the session.")

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

    def ensure_ready(self) -> None:
        self._session_id = None
        self._params = None
        if not self._list_models("Stable-Diffusion"):
            raise BackendNotReady("SwarmUI has no Stable Diffusion models.")

    def capabilities(self) -> list[Capability]:
        self._session_id = None
        self._params = None
        self._new_swarm_session()
        items = [Capability("api", "SwarmUI API", True)]
        items.append(
            listed(
                "Models",
                self._list_models("Stable-Diffusion"),
                Fix(["Put a Stable Diffusion checkpoint in SwarmUI's Models/Stable-Diffusion folder, or download one from the Models tab, then re-check."]),
            )
        )
        try:
            faces = [m for m in self.param_values("yolomodelinternal") if "face" in m.lower()]
        except BackendError:
            faces = []
        items.append(
            listed(
                "YOLO face model",
                faces,
                Fix(
                    [
                        "Optional. Without one, AutoExpress finds the face with CLIPSeg (<segment:face>), which works but is less exact.",
                        "For better masks, put face_yolov8m.pt in SwarmUI's Models/yolov8 folder and restart SwarmUI.",
                    ],
                    links=[Fix.link("face_yolov8m.pt", "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8m.pt")],
                ),
                required=False,
                key="face_model",
            )
        )
        items.append(listed("LoRAs", self.loras, required=False))
        items.append(
            Capability(
                "lora_folder",
                "Automatic expression LoRA downloads",
                False,
                "SwarmUI's LoRA folder isn't reachable from AutoExpress",
                required=False,
                fix=Fix(
                    [
                        "Optional. AutoExpress lists any missing expression LoRA with its download link when you generate.",
                        "Download each one in SwarmUI's Models tab (Download from URL, type LoRA), or put it in Models/Lora.",
                    ]
                ),
            )
        )
        return items

    def server_info(self) -> dict:
        if not self._server:
            self._new_swarm_session()
        return dict(self._server)

    def refresh_loras(self) -> bool:
        try:
            self._call("TriggerRefresh", {"strong": False}, timeout=120)
        except BackendError:
            return False
        return True

    # Generation -----------------------------------------------------------
    def segment_target(self, detector: str | None) -> str:
        """A YOLO face model SwarmUI has, else CLIPSeg's 'face'."""
        try:
            yolo_models = self.param_values("yolomodelinternal")
        except BackendError:
            yolo_models = []
        model = match_choice(detector, yolo_models) or next((m for m in yolo_models if "face" in m.lower()), None)
        return f"yolo-{model}" if model else "face"

    def build_request(self, request: FaceEditRequest) -> dict:
        models = self._list_models("Stable-Diffusion")
        model = match_choice(request.checkpoint, models)
        if not model:
            if not models:
                raise BackendNotReady("SwarmUI has no models.")
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
        response = self._check(self._request("GET", "/" + ref.lstrip("/"), timeout=120), "image download")
        result = Image.open(io.BytesIO(response.content))
        result.load()
        return result

    def img2img(self, payload: dict) -> Image.Image | None:
        self.last_error = None
        try:
            body = self.build_request(FaceEditRequest.from_payload(payload))
            result = self._call("GenerateText2Image", body, timeout=self.connection.job_timeout)
            images = result.get("images") or []
            if not images:
                raise BackendRejected("SwarmUI returned no image.")
            ref = images[0]["image"] if isinstance(images[0], dict) else images[0]
            return self._load_image(ref)
        except BackendError as e:
            return self._fail(e)
        except (KeyError, ValueError, TypeError) as e:
            return self._fail(BackendRejected(f"Unexpected response from SwarmUI: {e}"))

    def interrupt(self) -> None:
        try:
            self._call("InterruptAll", {"other_sessions": False}, timeout=10)
        except BackendError as e:
            log.error(f"Interrupt failed: {e}")
