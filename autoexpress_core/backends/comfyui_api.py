"""
Backend for a ComfyUI server, driven through its HTTP API (/prompt, /history, /view).

Each expression is one small workflow: load checkpoint (+ loras), encode the
prompts, and run Impact Pack's FaceDetailer with an Ultralytics face detector
on the uploaded character image. That is the ComfyUI equivalent of an
ADetailer pass, so ComfyUI needs ComfyUI-Impact-Pack and ComfyUI-Impact-Subpack.

Node inputs are filled in from the server's /object_info, so required inputs
added by newer Impact Pack versions get their defaults instead of failing
validation.
"""

import hashlib
import io
import random
import time
import uuid

import requests
from PIL import Image

from ..images import b64_to_pil
from ..log import log
from .base import BackendError, FaceEditRequest, RemoteBackend, match_choice

REQUIRED_NODES = ("CheckpointLoaderSimple", "FaceDetailer", "UltralyticsDetectorProvider")

# A1111 sampler / scheduler names that the image metadata and the default payload use.
SAMPLERS = {
    "euler": "euler",
    "euler a": "euler_ancestral",
    "heun": "heun",
    "lms": "lms",
    "dpm2": "dpm_2",
    "dpm2 a": "dpm_2_ancestral",
    "dpm fast": "dpm_fast",
    "dpm adaptive": "dpm_adaptive",
    "dpm++ 2s a": "dpmpp_2s_ancestral",
    "dpm++ sde": "dpmpp_sde",
    "dpm++ 2m": "dpmpp_2m",
    "dpm++ 2m sde": "dpmpp_2m_sde",
    "dpm++ 3m sde": "dpmpp_3m_sde",
    "ddim": "ddim",
    "ddpm": "ddpm",
    "lcm": "lcm",
    "unipc": "uni_pc",
    "uni_pc": "uni_pc",
}
SCHEDULERS = {
    "automatic": "normal",
    "uniform": "normal",
    "karras": "karras",
    "exponential": "exponential",
    "sgm uniform": "sgm_uniform",
    "simple": "simple",
    "ddim": "ddim_uniform",
    "beta": "beta",
    "normal": "normal",
}


def combo_options(spec) -> list[str]:
    """Options of a combo input from /object_info, in either the old or the newer COMBO format."""
    if not spec:
        return []
    first = spec[0]
    if isinstance(first, list):
        return first
    if first == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict):
        return list(spec[1].get("options", []))
    return []


def input_default(spec):
    """Default value of an input from /object_info, or None for links and inputs without one."""
    options = combo_options(spec)
    if options:
        return options[0]
    if len(spec) > 1 and isinstance(spec[1], dict):
        return spec[1].get("default")
    if spec and spec[0] == "STRING":
        return ""
    return None


def pick(value: str | None, choices: list[str], aliases: dict[str, str], fallback: str) -> str:
    """Use value if the server has it, else its ComfyUI alias, else the fallback (or the first choice)."""
    if not choices:
        return aliases.get((value or "").lower(), value or fallback)
    if value in choices:
        return value
    alias = aliases.get((value or "").strip().lower())
    if alias in choices:
        return alias
    return fallback if fallback in choices else choices[0]


class ComfyUIClient(RemoteBackend):

    kind = "comfyui"
    label = "ComfyUI"
    default_url = "http://127.0.0.1:8188"

    def __init__(self, url: str | None = None, timeout: float = 30, job_timeout: float = 1800, poll_interval: float = 0.5) -> None:
        super().__init__(url, timeout)
        self.client_id = uuid.uuid4().hex
        self.job_timeout = job_timeout
        self.poll_interval = poll_interval
        self._object_info: dict[str, dict] = {}
        self._uploaded: dict[str, str] = {}
        self._interrupted = False

    def on_url_changed(self) -> None:
        self._object_info.clear()
        self._uploaded.clear()

    # Server info ----------------------------------------------------------
    def object_info(self, node: str) -> dict:
        """The /object_info entry of a node class, {} when the server does not have it."""
        if node not in self._object_info:
            info = self._get_json(f"/object_info/{node}")
            if node not in info:
                return {}
            self._object_info[node] = info[node]
        return self._object_info[node]

    def _input_spec(self, node: str, name: str):
        inputs = self.object_info(node).get("input", {})
        return inputs.get("required", {}).get(name) or inputs.get("optional", {}).get(name)

    def options(self, node: str, name: str) -> list[str]:
        return combo_options(self._input_spec(node, name))

    @property
    def models(self) -> list[str]:
        return self._safe_list("models", lambda: self.options("CheckpointLoaderSimple", "ckpt_name"))

    @property
    def samplers(self) -> list[str]:
        return self._safe_list("samplers", lambda: self.options("KSampler", "sampler_name"))

    @property
    def schedulers(self) -> list[str]:
        return self._safe_list("schedulers", lambda: self.options("KSampler", "scheduler"))

    @property
    def loras(self) -> list[str]:
        return self._safe_list("loras", lambda: self.options("LoraLoader", "lora_name"))

    def check_ready(self) -> tuple[bool, str]:
        try:
            self._object_info.clear()
            missing = [node for node in REQUIRED_NODES if not self.object_info(node)]
        except requests.RequestException as e:
            return False, f"Could not reach ComfyUI at {self._base_url}. ({e})"

        if missing:
            return False, (
                f"ComfyUI is missing {', '.join(missing)}. Install ComfyUI-Impact-Pack and "
                "ComfyUI-Impact-Subpack (for UltralyticsDetectorProvider)."
            )
        if not self.options("CheckpointLoaderSimple", "ckpt_name"):
            return False, "ComfyUI has no checkpoints in models/checkpoints."
        if not self.options("UltralyticsDetectorProvider", "model_name"):
            return False, "ComfyUI has no face detection model. Put face_yolov8m.pt in models/ultralytics/bbox."
        return True, "ok"

    # Workflow -------------------------------------------------------------
    def detector_model(self, wanted: str | None) -> str:
        choices = self.options("UltralyticsDetectorProvider", "model_name")
        if not choices:
            raise BackendError("ComfyUI has no Ultralytics detection models.")
        match = match_choice(wanted, choices)
        if match:
            return match
        faces = [c for c in choices if "face" in c.lower()]
        bbox_faces = [c for c in faces if c.startswith("bbox/")]
        return (bbox_faces or faces or choices)[0]

    def _node(self, class_type: str, inputs: dict) -> dict:
        """A workflow node with every required input this server expects that was not given set to its default."""
        info = self.object_info(class_type).get("input", {})
        declared = {**info.get("required", {}), **info.get("optional", {})}
        if declared:
            inputs = {k: v for k, v in inputs.items() if k in declared}
            for name, spec in info.get("required", {}).items():
                if name not in inputs:
                    default = input_default(spec)
                    if default is not None:
                        inputs[name] = default
        return {"class_type": class_type, "inputs": inputs}

    def build_workflow(self, request: FaceEditRequest, image_name: str) -> dict:
        """Turn a FaceEditRequest into a ComfyUI API format workflow."""
        checkpoints = self.options("CheckpointLoaderSimple", "ckpt_name")
        checkpoint = match_choice(request.checkpoint, checkpoints)
        if not checkpoint:
            if not checkpoints:
                raise BackendError("ComfyUI has no checkpoints.")
            checkpoint = checkpoints[0]
            log.warning(
                f"Checkpoint '{request.checkpoint or 'not set'}' not found in ComfyUI, using {checkpoint}. "
                "Pick a model to choose another one."
            )

        workflow = {"ckpt": self._node("CheckpointLoaderSimple", {"ckpt_name": checkpoint})}
        model, clip, vae = ["ckpt", 0], ["ckpt", 1], ["ckpt", 2]

        lora_names = self.options("LoraLoader", "lora_name")
        for i, (name, weight) in enumerate(request.loras):
            lora = match_choice(name, lora_names)
            if not lora:
                log.warning(f"Lora '{name}' not found in ComfyUI, skipping it.")
                continue
            node_id = f"lora_{i}"
            workflow[node_id] = self._node(
                "LoraLoader",
                {"model": model, "clip": clip, "lora_name": lora, "strength_model": weight, "strength_clip": weight},
            )
            model, clip = [node_id, 0], [node_id, 1]

        if request.clip_skip > 1:
            workflow["clip_skip"] = self._node("CLIPSetLastLayer", {"clip": clip, "stop_at_clip_layer": -request.clip_skip})
            clip = ["clip_skip", 0]

        workflow["positive"] = self._node("CLIPTextEncode", {"text": request.prompt, "clip": clip})
        workflow["negative"] = self._node("CLIPTextEncode", {"text": request.negative_prompt, "clip": clip})
        workflow["image"] = self._node("LoadImage", {"image": image_name})
        workflow["detector"] = self._node("UltralyticsDetectorProvider", {"model_name": self.detector_model(request.detector)})

        seed = request.seed if request.seed >= 0 else random.randint(0, 2**32 - 1)
        workflow["face_detailer"] = self._node(
            "FaceDetailer",
            {
                "image": ["image", 0],
                "model": model,
                "clip": clip,
                "vae": vae,
                "positive": ["positive", 0],
                "negative": ["negative", 0],
                "bbox_detector": ["detector", 0],
                "guide_size": request.inpaint_size or 512,
                "guide_size_for": True,
                "max_size": max(1024, request.inpaint_size or 0),
                "seed": seed,
                "steps": request.steps,
                "cfg": request.cfg_scale,
                "sampler_name": pick(request.sampler, self.options("FaceDetailer", "sampler_name"), SAMPLERS, "euler"),
                "scheduler": pick(request.scheduler, self.options("FaceDetailer", "scheduler"), SCHEDULERS, "normal"),
                "denoise": min(max(request.denoise, 0.0001), 1.0),
                "feather": request.mask_blur,
                "noise_mask": True,
                "force_inpaint": True,
                "bbox_threshold": request.confidence,
                "bbox_dilation": request.dilation,
                "bbox_crop_factor": 3.0,
                "sam_detection_hint": "center-1",
                "sam_dilation": 0,
                "sam_threshold": 0.93,
                "sam_bbox_expansion": 0,
                "sam_mask_hint_threshold": 0.7,
                "sam_mask_hint_use_negative": "False",
                "drop_size": 10,
                "wildcard": "",
                "cycle": 1,
            },
        )
        workflow["output"] = {"class_type": "PreviewImage", "inputs": {"images": ["face_detailer", 0]}}
        return workflow

    # Running --------------------------------------------------------------
    def upload_image(self, b64_image: str) -> str:
        """Upload the input image once per server and return the name LoadImage should use."""
        digest = hashlib.sha1(b64_image.encode("utf-8")).hexdigest()[:16]
        if digest in self._uploaded:
            return self._uploaded[digest]

        buffer = io.BytesIO()
        b64_to_pil(b64_image).save(buffer, format="PNG")
        response = self._request(
            "POST",
            "/upload/image",
            files={"image": (f"autoexpress_{digest}.png", buffer.getvalue(), "image/png")},
            data={"type": "input", "overwrite": "true"},
        )
        response.raise_for_status()
        result = response.json()
        name = f"{result['subfolder']}/{result['name']}" if result.get("subfolder") else result["name"]
        self._uploaded[digest] = name
        return name

    def queue_prompt(self, workflow: dict) -> str:
        response = self._request("POST", "/prompt", json={"prompt": workflow, "client_id": self.client_id})
        if response.status_code != 200:
            raise BackendError(f"ComfyUI rejected the workflow: {response.text[:2000]}")
        return response.json()["prompt_id"]

    def wait_for(self, prompt_id: str) -> dict | None:
        """Poll /history until the prompt finished. Returns its history entry, or None when interrupted or timed out."""
        deadline = time.monotonic() + self.job_timeout
        while time.monotonic() < deadline:
            history = self._get_json(f"/history/{prompt_id}")
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error" or (status and not status.get("completed", True)):
                    messages = [m for m in status.get("messages", []) if m and m[0] in ("execution_error", "execution_interrupted")]
                    log.error(f"ComfyUI job {prompt_id} failed: {messages}")
                    return None
                return entry
            if self._interrupted:
                return None
            time.sleep(self.poll_interval)
        log.error(f"ComfyUI job {prompt_id} did not finish within {self.job_timeout}s.")
        return None

    def fetch_image(self, entry: dict) -> Image.Image | None:
        images = entry.get("outputs", {}).get("output", {}).get("images", [])
        if not images:
            log.error("ComfyUI finished without an output image.")
            return None
        image = images[0]
        response = self._request(
            "GET",
            "/view",
            params={"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "temp")},
        )
        response.raise_for_status()
        result = Image.open(io.BytesIO(response.content))
        result.load()
        return result

    def img2img(self, payload: dict) -> Image.Image | None:
        self._interrupted = False
        try:
            request = FaceEditRequest.from_payload(payload)
            workflow = self.build_workflow(request, self.upload_image(request.image))
            prompt_id = self.queue_prompt(workflow)
            entry = self.wait_for(prompt_id)
            return self.fetch_image(entry) if entry else None
        except (BackendError, requests.RequestException, KeyError, ValueError) as e:
            log.error(f"ComfyUI generation failed: {e}")
            return None

    def interrupt(self) -> None:
        self._interrupted = True
        try:
            self._request("POST", "/interrupt")
        except requests.RequestException as e:
            log.error(f"Interrupt failed: {e}")
