"""
Backend for a ComfyUI server, driven through its HTTP API (/prompt, /history, /view).

Each expression is one small workflow: load checkpoint (+ loras), encode the
prompts, and run Impact Pack's FaceDetailer with an Ultralytics face detector
on the uploaded character image. That is the ComfyUI equivalent of an
ADetailer pass, so ComfyUI needs ComfyUI-Impact-Pack and ComfyUI-Impact-Subpack.

Node inputs are filled in from the server's /object_info, so required inputs
added by newer Impact Pack versions get their defaults instead of failing
validation. Step progress is read from ComfyUI's websocket when the optional
websocket-client package is installed; completion is always confirmed through
/history, so the websocket is never required.

The instruction edit mode (see instruction_edit) runs a Qwen-Image-Edit-2509
workflow instead, built only from nodes that ship with ComfyUI, so it does not
need Impact Pack.
"""

import dataclasses
import hashlib
import io
import json
import pathlib
import random
import threading
import time
import uuid

from PIL import Image

from .. import instruction_edit
from ..civitai_key import comfyui_sources
from ..images import b64_to_pil
from ..log import log
from .base import (
    BackendError,
    BackendNotReady,
    BackendRejected,
    BackendTimeout,
    FaceEditRequest,
    GenerationCancelled,
    RemoteBackend,
    match_choice,
)

REQUIRED_NODES = ("CheckpointLoaderSimple", "FaceDetailer", "UltralyticsDetectorProvider")
# Core ComfyUI nodes of the Qwen-Image-Edit workflow. TextEncodeQwenImageEditPlus came with ComfyUI 0.3.60.
EDIT_NODES = ("UNETLoader", "CLIPLoader", "VAELoader", "ModelSamplingAuraFlow", "KSampler", "VAEEncode", "VAEDecode", "ImageScaleToTotalPixels")
EDIT_ENCODERS = ("TextEncodeQwenImageEditPlus", "TextEncodeQwenImageEdit")

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
    edit_methods = (instruction_edit.INPAINT, instruction_edit.INSTRUCT)

    def __init__(self, url: str | None = None, timeout: float | None = None, poll_interval: float = 0.5, **options) -> None:
        self._object_info: dict[str, dict] = {}
        self._uploaded: dict[str, str] = {}
        super().__init__(url, timeout, **options)
        self.client_id = uuid.uuid4().hex
        self.poll_interval = poll_interval
        self._interrupted = threading.Event()
        self._prompt_id: str | None = None
        self._progress: dict | None = None

    @property
    def job_timeout(self) -> float:
        return self.connection.job_timeout

    def on_url_changed(self) -> None:
        self._object_info.clear()
        self._uploaded.clear()

    def refresh_loras(self) -> bool:
        """ComfyUI rescans its model folders on every /object_info call, so dropping the cache is enough."""
        self._object_info.clear()
        return True

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

    def ensure_ready(self) -> None:
        self._object_info.clear()
        missing = [node for node in REQUIRED_NODES if not self.object_info(node)]
        if missing:
            raise BackendNotReady(
                f"ComfyUI is missing {', '.join(missing)}. Install ComfyUI-Impact-Pack and "
                "ComfyUI-Impact-Subpack (for UltralyticsDetectorProvider)."
            )
        if not self.options("CheckpointLoaderSimple", "ckpt_name"):
            raise BackendNotReady("ComfyUI has no checkpoints in models/checkpoints.")
        if not self.options("UltralyticsDetectorProvider", "model_name"):
            raise BackendNotReady("ComfyUI has no face detection model. Put face_yolov8m.pt in models/ultralytics/bbox.")

    def ensure_edit_ready(self) -> None:
        """What the Qwen-Image-Edit workflow needs: recent core nodes and the three model files."""
        self._object_info.clear()
        missing = [node for node in EDIT_NODES if not self.object_info(node)]
        if not any(self.object_info(node) for node in EDIT_ENCODERS):
            missing.append(EDIT_ENCODERS[0])
        if missing:
            raise BackendNotReady(f"ComfyUI is missing {', '.join(missing)}. Update ComfyUI to 0.3.60 or newer for Qwen-Image-Edit-2509.")
        if "qwen_image" not in self.options("CLIPLoader", "type"):
            raise BackendNotReady("This ComfyUI's CLIPLoader has no qwen_image type. Update ComfyUI for Qwen-Image-Edit.")
        lists = {
            "diffusion_model": self.options("UNETLoader", "unet_name"),
            "text_encoder": self.options("CLIPLoader", "clip_name"),
            "vae": self.options("VAELoader", "vae_name"),
        }
        missing_files = [
            f"models/{instruction_edit.MODEL_BY_ROLE[role].folder}/{instruction_edit.MODEL_BY_ROLE[role].name}"
            for role, choices in lists.items()
            if not instruction_edit.find_model(role, choices)
        ]
        if missing_files:
            raise BackendNotReady(
                f"ComfyUI is missing the Qwen-Image-Edit files {', '.join(missing_files)}. "
                "Run: python -m autoexpress_core.instruction_edit download <ComfyUI folder>. " + instruction_edit.VRAM_NOTE
            )

    def server_info(self) -> dict:
        stats = self._get_json("/system_stats", timeout=10)
        system = stats.get("system", {})
        return {
            "version": system.get("comfyui_version"),
            "python": system.get("python_version"),
            "devices": [device.get("name") for device in stats.get("devices", [])],
        }

    def progress(self) -> dict | None:
        return self._progress

    def civitai_key_sources(self) -> list[tuple[str, str | None]]:
        """A key saved by ComfyUI LoRA Manager, when ComfyUI runs on this machine."""
        custom_nodes = []
        try:
            argv = self._get_json("/system_stats", timeout=10).get("system", {}).get("argv") or []
            main = pathlib.Path(argv[0]) if argv else None
            if main and (main.parent / "custom_nodes").is_dir():
                custom_nodes.append(main.parent / "custom_nodes")
        except (BackendError, ValueError, AttributeError, TypeError):
            pass
        return comfyui_sources(custom_nodes)

    # Workflow -------------------------------------------------------------
    def detector_model(self, wanted: str | None) -> str:
        choices = self.options("UltralyticsDetectorProvider", "model_name")
        if not choices:
            raise BackendNotReady("ComfyUI has no Ultralytics detection models.")
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
                raise BackendNotReady("ComfyUI has no checkpoints.")
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
                # Wider feathering than A1111's mask blur: ComfyUI pastes the face back with a harder edge.
                "feather": max(request.mask_blur * 3, 12),
                "noise_mask": True,
                "noise_mask_feather": 20,
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

    def build_edit_workflow(self, instruction: str, image_name: str, settings: instruction_edit.EditSettings) -> dict:
        """A Qwen-Image-Edit-2509 workflow that applies one edit instruction to the uploaded image."""
        unet = instruction_edit.find_model("diffusion_model", self.options("UNETLoader", "unet_name"), settings.model)
        text_encoder = instruction_edit.find_model("text_encoder", self.options("CLIPLoader", "clip_name"))
        vae_name = instruction_edit.find_model("vae", self.options("VAELoader", "vae_name"))
        if not (unet and text_encoder and vae_name):
            self.ensure_edit_ready()  # raises with the list of missing files
        lightning = None
        if settings.lightning:
            lightning = instruction_edit.find_model("lightning_lora", self.options("LoraLoaderModelOnly", "lora_name"))
            if not lightning:
                log.warning("Qwen-Image-Edit Lightning LoRA not found, sampling 40 steps at CFG 4 instead of 8 at CFG 1.")

        workflow = {"unet": self._node("UNETLoader", {"unet_name": unet, "weight_dtype": "default"})}
        model = ["unet", 0]
        if lightning:
            workflow["lightning"] = self._node("LoraLoaderModelOnly", {"model": model, "lora_name": lightning, "strength_model": 1.0})
            model = ["lightning", 0]
        workflow["shift"] = self._node("ModelSamplingAuraFlow", {"model": model, "shift": settings.shift})
        model = ["shift", 0]
        if self.object_info("CFGNorm"):
            workflow["cfg_norm"] = self._node("CFGNorm", {"model": model, "strength": 1.0})
            model = ["cfg_norm", 0]

        workflow["clip"] = self._node("CLIPLoader", {"clip_name": text_encoder, "type": "qwen_image", "device": "default"})
        workflow["vae"] = self._node("VAELoader", {"vae_name": vae_name})
        workflow["image"] = self._node("LoadImage", {"image": image_name})
        # Qwen-Image-Edit works at about one megapixel; the result is scaled back to the input size afterwards.
        workflow["scaled"] = self._node(
            "ImageScaleToTotalPixels", {"image": ["image", 0], "upscale_method": "lanczos", "megapixels": settings.megapixels}
        )

        if self.object_info("TextEncodeQwenImageEditPlus"):
            encoder, image_input = "TextEncodeQwenImageEditPlus", "image1"
        else:
            encoder, image_input = "TextEncodeQwenImageEdit", "image"
        for node_id, text in (("positive", instruction), ("negative", "")):
            workflow[node_id] = self._node(encoder, {"clip": ["clip", 0], "prompt": text, "vae": ["vae", 0], image_input: ["scaled", 0]})

        workflow["latent"] = self._node("VAEEncode", {"pixels": ["scaled", 0], "vae": ["vae", 0]})
        seed = settings.seed if settings.seed >= 0 else random.randint(0, 2**32 - 1)
        workflow["sampler"] = self._node(
            "KSampler",
            {
                "model": model,
                "seed": seed,
                "steps": settings.resolved_steps(bool(lightning)),
                "cfg": settings.resolved_cfg(bool(lightning)),
                "sampler_name": pick(settings.sampler, self.options("KSampler", "sampler_name"), SAMPLERS, "euler"),
                "scheduler": pick(settings.scheduler, self.options("KSampler", "scheduler"), SCHEDULERS, "simple"),
                "positive": ["positive", 0],
                "negative": ["negative", 0],
                "latent_image": ["latent", 0],
                "denoise": 1.0,
            },
        )
        workflow["decode"] = self._node("VAEDecode", {"samples": ["sampler", 0], "vae": ["vae", 0]})
        workflow["output"] = {"class_type": "PreviewImage", "inputs": {"images": ["decode", 0]}}
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
            timeout=120,
        )
        result = self._json(self._check(response, "image upload"))
        name = f"{result['subfolder']}/{result['name']}" if result.get("subfolder") else result["name"]
        self._uploaded[digest] = name
        return name

    def queue_prompt(self, workflow: dict) -> str:
        response = self._request("POST", "/prompt", json={"prompt": workflow, "client_id": self.client_id})
        if response.status_code != 200:
            raise BackendRejected(f"ComfyUI rejected the workflow: {self._describe_rejection(response)}")
        return self._json(response)["prompt_id"]

    @staticmethod
    def _describe_rejection(response) -> str:
        """Turn ComfyUI's validation error body into one readable line per failing node input."""
        try:
            body = response.json()
        except ValueError:
            return response.text[:2000]
        lines = []
        error = body.get("error") or {}
        if isinstance(error, dict) and error.get("message"):
            lines.append(error["message"])
        for node_id, node in (body.get("node_errors") or {}).items():
            for err in node.get("errors", []):
                lines.append(f"{node.get('class_type', node_id)}: {err.get('message')} {err.get('details', '')}".strip())
        return "; ".join(lines) or response.text[:2000]

    def wait_for(self, prompt_id: str) -> dict:
        """Poll /history until the prompt finished and return its history entry."""
        deadline = time.monotonic() + self.job_timeout
        while time.monotonic() < deadline:
            history = self._get_json(f"/history/{prompt_id}")
            entry = history.get(prompt_id)
            if entry:
                status = entry.get("status", {})
                if status.get("status_str") == "error" or (status and not status.get("completed", True)):
                    messages = status.get("messages", [])
                    if any(m and m[0] == "execution_interrupted" for m in messages) or self._interrupted.is_set():
                        raise GenerationCancelled("Interrupted.")
                    details = [m[1] for m in messages if m and m[0] == "execution_error" and len(m) > 1]
                    detail = details[0] if details else {}
                    raise BackendRejected(
                        f"ComfyUI failed in {detail.get('node_type', 'the workflow')}: "
                        f"{detail.get('exception_message', 'unknown error').strip()}"
                    )
                return entry
            if self._interrupted.is_set():
                raise GenerationCancelled("Interrupted.")
            time.sleep(self.poll_interval)
        raise BackendTimeout(f"ComfyUI job {prompt_id} did not finish within {self.job_timeout:.0f}s.")

    def fetch_image(self, entry: dict) -> Image.Image:
        images = entry.get("outputs", {}).get("output", {}).get("images", [])
        if not images:
            raise BackendRejected("ComfyUI finished without an output image (was a face detected?).")
        image = images[0]
        response = self._request(
            "GET",
            "/view",
            params={"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "temp")},
            timeout=120,
        )
        self._check(response, "image download")
        result = Image.open(io.BytesIO(response.content))
        result.load()
        return result

    def _listen_for_progress(self) -> "threading.Event | None":
        """Follow step progress on ComfyUI's websocket. Returns a stop event, or None without websocket-client."""
        try:
            import websocket  # websocket-client, optional
        except ImportError:
            return None

        ws_url = "ws" + self._base_url[len("http"):] + f"/ws?clientId={self.client_id}"
        headers = [f"{k}: {v}" for k, v in self.session.headers.items() if k.lower() == "authorization"]
        try:
            ws = websocket.create_connection(ws_url, timeout=self.connection.connect_timeout, header=headers)
        except Exception as e:  # progress is optional, never fail the job over it
            log.debug(f"ComfyUI progress websocket unavailable: {e}")
            return None

        stop = threading.Event()

        def run():
            ws.settimeout(1)
            try:
                while not stop.is_set():
                    try:
                        message = ws.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not isinstance(message, str):
                        continue  # binary preview frames
                    event = json.loads(message)
                    data = event.get("data") or {}
                    if event.get("type") == "progress" and data.get("prompt_id") in (None, self._prompt_id) and data.get("max"):
                        self._progress = {"fraction": data["value"] / data["max"], "eta": None}
            except Exception as e:
                log.debug(f"ComfyUI progress websocket closed: {e}")
            finally:
                ws.close()

        threading.Thread(target=run, name="comfyui-progress", daemon=True).start()
        return stop

    def img2img(self, payload: dict) -> Image.Image | None:
        self._interrupted.clear()
        self.last_error = None
        self._progress = None
        stop_listening = None
        try:
            request = FaceEditRequest.from_payload(payload)
            if request.seed < 0:
                request = dataclasses.replace(request, seed=random.randint(0, 2**32 - 1))
            workflow = self.build_workflow(request, self.upload_image(request.image))
            stop_listening = self._listen_for_progress()
            self._prompt_id = self.queue_prompt(workflow)
            image = self.fetch_image(self.wait_for(self._prompt_id))
            detailer = workflow["face_detailer"]["inputs"]
            checkpoint = workflow["ckpt"]["inputs"].get("ckpt_name")
            image.info["parameters"] = dataclasses.replace(request, checkpoint=checkpoint).infotext(
                image.size, sampler=detailer.get("sampler_name"), version="ComfyUI"
            )
            return image
        except BackendError as e:
            return self._fail(e)
        except (KeyError, ValueError, TypeError) as e:
            return self._fail(BackendRejected(f"Unexpected response from ComfyUI: {e}"))
        finally:
            if stop_listening:
                stop_listening.set()
            self._prompt_id = None
            self._progress = None

    def instruction_edit(self, image: str, instruction: str, settings: instruction_edit.EditSettings) -> Image.Image | None:
        """
        Apply one edit instruction to a base64 image with Qwen-Image-Edit.

        Returns the edited image at the input's size, or None on failure (the reason is in last_error).
        """
        self._interrupted.clear()
        self.last_error = None
        self._progress = None
        stop_listening = None
        try:
            if settings.seed < 0:
                settings = dataclasses.replace(settings, seed=random.randint(0, 2**32 - 1))
            workflow = self.build_edit_workflow(instruction, self.upload_image(image), settings)
            stop_listening = self._listen_for_progress()
            self._prompt_id = self.queue_prompt(workflow)
            result = self.fetch_image(self.wait_for(self._prompt_id))
            source_size = b64_to_pil(image).size
            if settings.keep_size and result.size != source_size:
                result = result.convert("RGB").resize(source_size, Image.LANCZOS)
            sampler = workflow["sampler"]["inputs"]
            fields = {
                "Steps": sampler["steps"],
                "Sampler": sampler["sampler_name"],
                "Schedule type": sampler["scheduler"],
                "CFG scale": f"{sampler['cfg']:g}",
                "Seed": sampler["seed"],
                "Size": f"{result.size[0]}x{result.size[1]}",
                "Model": workflow["unet"]["inputs"]["unet_name"],
                "Lora": workflow.get("lightning", {}).get("inputs", {}).get("lora_name"),
                "Version": "ComfyUI",
            }
            params = ", ".join(f"{key}: {value}" for key, value in fields.items() if value not in (None, ""))
            result.info["parameters"] = f"{instruction}\nNegative prompt: \n{params}"
            return result
        except BackendError as e:
            return self._fail(e, "instruction edit")
        except (KeyError, ValueError, TypeError) as e:
            return self._fail(BackendRejected(f"Unexpected response from ComfyUI: {e}"), "instruction edit")
        finally:
            if stop_listening:
                stop_listening.set()
            self._prompt_id = None
            self._progress = None

    def interrupt(self) -> None:
        """Stop this client's prompt: drop it from the queue if it hasn't started, interrupt it if it has."""
        self._interrupted.set()
        prompt_id = self._prompt_id
        try:
            if prompt_id:
                self._request("POST", "/queue", json={"delete": [prompt_id]}, timeout=10)
                self._request("POST", "/interrupt", json={"prompt_id": prompt_id}, timeout=10)
            else:
                self._request("POST", "/interrupt", timeout=10)
        except BackendError as e:
            log.error(f"Interrupt failed: {e}")
