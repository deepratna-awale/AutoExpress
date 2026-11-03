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

The instruction edit mode (see instruction_edit) runs a Qwen-Image-Edit-2511
workflow instead, built only from nodes that ship with ComfyUI. On photos it
also detects the face with Impact Pack, when installed, so only the edited face
is pasted back onto the original.
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

from PIL import Image, ImageDraw, ImageFilter

from .. import animation, instruction_edit
from ..live2d import layers as live2d_layers
from ..civitai_key import comfyui_sources
from ..images import b64_to_pil
from ..log import log
from .base import (
    BackendError,
    BackendNotReady,
    BackendRejected,
    BackendTimeout,
    Capability,
    FaceEditRequest,
    Fix,
    GenerationCancelled,
    RemoteBackend,
    listed,
    match_choice,
)

REQUIRED_NODES = ("CheckpointLoaderSimple", "FaceDetailer", "UltralyticsDetectorProvider")
# Core ComfyUI nodes of the Qwen-Image-Edit workflow. TextEncodeQwenImageEditPlus came with ComfyUI 0.3.60.
EDIT_NODES = ("UNETLoader", "CLIPLoader", "VAELoader", "ModelSamplingAuraFlow", "KSampler", "VAEEncode", "VAEDecode", "ImageScaleToTotalPixels")
EDIT_ENCODERS = ("TextEncodeQwenImageEditPlus", "TextEncodeQwenImageEdit")
# Impact Pack nodes that find the face for pasting a photo edit back onto the original.
FACE_MASK_NODES = ("UltralyticsDetectorProvider", "BboxDetectorSEGS", "SegsToCombinedMask", "MaskToImage")
# Core ComfyUI nodes of the Wan 2.2 image to video workflow for animated sprites.
ANIMATE_NODES = ("UNETLoader", "CLIPLoader", "VAELoader", "ModelSamplingSD3", "KSamplerAdvanced", "WanFirstLastFrameToVideo", "CLIPTextEncode", "VAEDecode")

# ComfyUI-See-through's nodes, which split a character picture into Live2D layers.
SEETHROUGH_NODES = (
    "SeeThrough_LoadLayerDiffModel",
    "SeeThrough_LoadDepthModel",
    "SeeThrough_GenerateLayers",
    "SeeThrough_GenerateDepth",
    "SeeThrough_PostProcess",
    "SeeThrough_SavePSD",
)
SEETHROUGH_INFO_LOG = "seethrough_psd_info.log"
# The depth pass only orders the layers, and above about 1280 px its kernels fail on some GPUs
# (CUDA "invalid configuration argument" at 2048 on an RTX PRO 6000).
DEPTH_MAX = 1280

IMPACT_PACK = "https://github.com/ltdrdata/ComfyUI-Impact-Pack"
IMPACT_SUBPACK = "https://github.com/ltdrdata/ComfyUI-Impact-Subpack"
FACE_MODEL_URL = "https://huggingface.co/Bingsu/adetailer/resolve/main/face_yolov8m.pt"


# ComfyUI's "Edit Model Reference Method" node.
REFERENCE_METHOD_NODE = "FluxKontextMultiReferenceLatentMethod"
FACE_MASK_OUTPUT = "face_mask_output"


def paste_face(original: Image.Image, edited: Image.Image, mask: Image.Image) -> Image.Image:
    """
    The original photo with only the edited face pasted in, through a feathered mask.

    mask is the detector's face box (white on black) at any size. With no face found the whole edit is kept.
    """
    mask = mask.convert("L").resize(original.size, Image.NEAREST)
    box = mask.getbbox()
    if not box:
        log.warning("No face found in the photo, keeping the whole edit.")
        return edited
    # Grow the box past the chin and brows, then feather it so the seam disappears into the skin.
    size = min(box[2] - box[0], box[3] - box[1])
    grow = max(4, round(size * 0.12))
    grown = Image.new("L", original.size, 0)
    ImageDraw.Draw(grown).rectangle((box[0] - grow, box[1] - grow, box[2] + grow, box[3] + grow), fill=255)
    feathered = grown.filter(ImageFilter.GaussianBlur(max(3, size * 0.08)))
    result = Image.composite(edited.convert("RGB"), original.convert("RGB"), feathered)
    result.info = dict(edited.info)
    return result


def custom_node_fix(name: str, repo: str) -> Fix:
    folder = repo.rsplit("/", 1)[-1]
    return Fix(
        [
            f"With ComfyUI-Manager: open Manager > Custom Nodes Manager, search for \"{name}\", press Install, then restart ComfyUI.",
            "Without it, run these in ComfyUI's custom_nodes folder (on the machine or pod ComfyUI runs on), then restart ComfyUI:",
        ],
        [f"git clone {repo}", f"pip install -r {folder}/requirements.txt"],
        [Fix.link(name, repo)],
    )

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
    can_animate = True
    can_decompose = True

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
            raise BackendNotReady(f"ComfyUI is missing {', '.join(missing)}. Update ComfyUI to 0.3.60 or newer for Qwen-Image-Edit.")
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

    def edit_requirements(self, selected: bool = False) -> list[dict]:
        """
        Everything the instruction edit mode needs, checked over ComfyUI's API, each with how to fix it.

        Each item is {"key", "label", "ok", "detail", "required", "fix": {"steps", "commands", "links"} or None}.
        required is True only when the mode is selected, so the report doesn't block face inpainting.
        """
        self._object_info.clear()
        update_fix = {
            "steps": ["Update ComfyUI to 0.3.60 or newer (ComfyUI Manager > Update ComfyUI, or git pull in the ComfyUI folder).", "Restart ComfyUI."],
            "commands": ["cd ComfyUI && git pull && pip install -r requirements.txt"],
            "links": [{"label": "ComfyUI releases", "url": "https://github.com/comfyanonymous/ComfyUI/releases"}],
        }
        missing_nodes = [node for node in EDIT_NODES if not self.object_info(node)]
        encoder = next((node for node in EDIT_ENCODERS if self.object_info(node)), None)
        if not encoder:
            missing_nodes.append(EDIT_ENCODERS[0])
        items = [
            {
                "key": "qwen_edit_nodes",
                "label": "Qwen-Image-Edit nodes",
                "ok": not missing_nodes,
                "detail": f"Missing: {', '.join(missing_nodes)}" if missing_nodes else f"Core nodes present ({encoder})",
                "required": selected,
                "fix": None if not missing_nodes else update_fix,
            }
        ]
        if not missing_nodes:
            has_type = "qwen_image" in self.options("CLIPLoader", "type")
            items.append(
                {
                    "key": "qwen_edit_clip_type",
                    "label": "CLIPLoader qwen_image type",
                    "ok": has_type,
                    "detail": "Available" if has_type else "This ComfyUI's CLIPLoader can't load the Qwen text encoder.",
                    "required": selected,
                    "fix": None if has_type else update_fix,
                }
            )

        lists = {
            "diffusion_model": lambda: self.options("UNETLoader", "unet_name"),
            "text_encoder": lambda: self.options("CLIPLoader", "clip_name"),
            "vae": lambda: self.options("VAELoader", "vae_name"),
            "lightning_lora": lambda: self.options("LoraLoaderModelOnly", "lora_name") or self.options("LoraLoader", "lora_name"),
        }
        labels = {
            "diffusion_model": "Qwen-Image-Edit-2511 model",
            "text_encoder": "Qwen2.5-VL text encoder",
            "vae": "Qwen-Image VAE",
            "lightning_lora": "Lightning 8-step LoRA (optional, 5x faster)",
        }
        for role, listing in lists.items():
            model = instruction_edit.MODEL_BY_ROLE[role]
            found = instruction_edit.find_model(role, listing())
            items.append(
                {
                    "key": f"qwen_edit_{role}",
                    "label": labels[role],
                    "ok": bool(found),
                    "detail": found or f"Not in ComfyUI/models/{model.folder}",
                    "required": selected and model.required,
                    "fix": None
                    if found
                    else {
                        "steps": [
                            f"Download {model.name} (~{model.size_gb:g} GB) into ComfyUI/models/{model.folder}/.",
                            "Or fetch every missing file at once with the AutoExpress helper, run where ComfyUI is installed.",
                            "Refresh ComfyUI (or restart it) so the loader lists the file.",
                        ],
                        "commands": [
                            f"wget -c -P ComfyUI/models/{model.folder} {model.urls[0]}",
                            "python -m autoexpress_core.instruction_edit download /path/to/ComfyUI",
                        ],
                        "links": [{"label": model.name, "url": model.urls[0].replace("/resolve/", "/blob/")}],
                    },
                }
            )
        has_face_mask = all(self.object_info(node) for node in FACE_MASK_NODES) and bool(self.options("UltralyticsDetectorProvider", "model_name"))
        items.append(
            {
                "key": "qwen_edit_face_paste",
                "label": "Face paste-back for photos (optional)",
                "ok": has_face_mask,
                "detail": "Impact Pack face detector found" if has_face_mask
                else "Without Impact Pack and a face detector, photo edits keep the whole re-rendered image.",
                "required": False,
                "fix": None if has_face_mask else {
                    "steps": [
                        "Install ComfyUI Impact Pack and ComfyUI Impact Subpack (ComfyUI Manager > Custom Nodes Manager).",
                        "Download face_yolov8m.pt into ComfyUI/models/ultralytics/bbox/.",
                        "Restart ComfyUI.",
                    ],
                    "commands": [f"wget -c -P ComfyUI/models/ultralytics/bbox {FACE_MODEL_URL}"],
                    "links": [{"label": "ComfyUI Impact Pack", "url": IMPACT_PACK}, {"label": "ComfyUI Impact Subpack", "url": IMPACT_SUBPACK}],
                },
            }
        )
        items.append(
            {
                "key": "qwen_edit_vram",
                "label": "GPU memory",
                "ok": True,
                "detail": instruction_edit.VRAM_NOTE,
                "required": False,
                "fix": None,
            }
        )
        return items


    def capabilities(self) -> list[Capability]:
        self._object_info.clear()
        self._get_json("/system_stats", timeout=10)
        items = [Capability("api", "ComfyUI API", True)]

        impact = bool(self.object_info("FaceDetailer"))
        items.append(
            Capability(
                "impact_pack", "ComfyUI Impact Pack (FaceDetailer)", impact,
                "Installed" if impact else "FaceDetailer node not found",
                fix=custom_node_fix("ComfyUI Impact Pack", IMPACT_PACK),
            )
        )
        subpack = bool(self.object_info("UltralyticsDetectorProvider"))
        items.append(
            Capability(
                "impact_subpack", "ComfyUI Impact Subpack (UltralyticsDetectorProvider)", subpack,
                "Installed" if subpack else "UltralyticsDetectorProvider node not found",
                fix=custom_node_fix("ComfyUI Impact Subpack", IMPACT_SUBPACK),
            )
        )
        if subpack:
            faces = [m for m in self.options("UltralyticsDetectorProvider", "model_name") if "face" in m.lower()]
            items.append(
                listed(
                    "Face detection model",
                    faces,
                    Fix(
                        [
                            "Download face_yolov8m.pt into ComfyUI's models/ultralytics/bbox folder, then re-check.",
                            "In ComfyUI's folder (on the machine or pod ComfyUI runs on):",
                        ],
                        [f"wget -P models/ultralytics/bbox {FACE_MODEL_URL}"],
                        [Fix.link("face_yolov8m.pt", FACE_MODEL_URL)],
                    ),
                    key="face_model",
                )
            )
        items.append(
            listed(
                "Checkpoints",
                self.models,
                Fix(["Put a Stable Diffusion checkpoint (.safetensors) in ComfyUI's models/checkpoints folder, then re-check."]),
            )
        )
        items.append(listed("LoRAs", self.loras, required=False))
        items.append(
            Capability(
                "lora_folder",
                "Automatic expression LoRA downloads",
                bool(self.lora_dir),
                f"LoRA folder {self.lora_dir} is on this machine" if self.lora_dir else
                "ComfyUI's LoRA folder isn't on this machine, so missing expression LoRAs have to be installed on ComfyUI",
                required=False,
                fix=Fix(
                    [
                        "Optional. AutoExpress lists any missing expression LoRA with its download link when you generate.",
                        "Put each one in ComfyUI's models/loras folder.",
                    ]
                ),
            )
        )
        try:
            import websocket  # noqa: F401

            live = True
        except ImportError:
            live = False
        items.append(
            Capability(
                "live_progress", "Live step progress", live,
                "Uses ComfyUI's websocket" if live else "websocket-client isn't installed where AutoExpress runs",
                required=False,
                fix=Fix(["Optional. Install it where AutoExpress runs, then restart AutoExpress:"], ["pip install websocket-client"]),
            )
        )
        # The instruction edit mode is optional at connect time; the pre-generation check marks it required.
        items.extend(self.edit_capabilities(selected=False))
        items.extend(self.animate_capabilities(selected=False))
        items.extend(self.decompose_capabilities(selected=False))
        return items

    def animate_files(self) -> dict[str, str | None]:
        """The Wan 2.2 file ComfyUI lists for each model role, or None where it's missing."""
        lists = {
            "high_noise": self.options("UNETLoader", "unet_name"),
            "low_noise": self.options("UNETLoader", "unet_name"),
            "text_encoder": self.options("CLIPLoader", "clip_name"),
            "vae": self.options("VAELoader", "vae_name"),
            "lightning_high": self.options("LoraLoaderModelOnly", "lora_name"),
            "lightning_low": self.options("LoraLoaderModelOnly", "lora_name"),
        }
        return {role: animation.find_model(role, choices) for role, choices in lists.items()}

    def ensure_animate_ready(self) -> None:
        """What animated sprites need: recent core nodes and the Wan 2.2 image to video files."""
        self._object_info.clear()
        missing = [node for node in ANIMATE_NODES if not self.object_info(node)]
        if missing:
            raise BackendNotReady(f"ComfyUI is missing {', '.join(missing)}. Update ComfyUI for Wan 2.2 animated sprites.")
        if "wan" not in self.options("CLIPLoader", "type"):
            raise BackendNotReady("This ComfyUI's CLIPLoader has no wan type. Update ComfyUI for Wan 2.2 animated sprites.")
        files = self.animate_files()
        missing_files = [
            f"models/{animation.MODEL_BY_ROLE[role].folder}/{animation.MODEL_BY_ROLE[role].name}"
            for role, found in files.items()
            if not found and animation.MODEL_BY_ROLE[role].required
        ]
        if missing_files:
            raise BackendNotReady(
                f"ComfyUI is missing the Wan 2.2 files {', '.join(missing_files)}. "
                "Run: python -m autoexpress_core.animation download <ComfyUI folder>. " + animation.VRAM_NOTE
            )

    def animate_capabilities(self, selected: bool = False) -> list[Capability]:
        """Readiness of animated sprites, one item for the nodes and one for the model files."""
        self._object_info.clear()
        missing_nodes = [node for node in ANIMATE_NODES if not self.object_info(node)]
        items = [
            Capability(
                "wan_nodes", "Wan 2.2 image to video nodes (animated sprites)", not missing_nodes,
                f"Missing: {', '.join(missing_nodes)}" if missing_nodes else "Core nodes present",
                required=selected,
                fix=Fix(
                    ["Update ComfyUI (ComfyUI Manager > Update ComfyUI, or git pull in the ComfyUI folder).", "Restart ComfyUI."],
                    ["cd ComfyUI && git pull && pip install -r requirements.txt"],
                ),
            )
        ]
        if not missing_nodes:
            files = self.animate_files()
            missing = [animation.MODEL_BY_ROLE[role] for role, found in files.items() if not found]
            needed = [model for model in missing if model.required]
            items.append(
                Capability(
                    "wan_models", "Wan 2.2 image to video models (animated sprites)", not needed,
                    "Missing: " + ", ".join(f"models/{m.folder}/{m.name}" for m in missing) if missing else "All files present",
                    required=selected,
                    fix=Fix(
                        [
                            "In the folder AutoExpress is installed in, on the machine or pod ComfyUI runs on, download the files, then re-check.",
                            animation.VRAM_NOTE,
                        ],
                        ["python -m autoexpress_core.animation download /path/to/ComfyUI"],
                        [Fix.link(m.name, m.urls[0]) for m in missing],
                    ),
                )
            )
        return items

    def ensure_decompose_ready(self) -> None:
        """What Live2D model kits need: the See-through nodes (their models download on first use)."""
        self._object_info.clear()
        missing = [node for node in SEETHROUGH_NODES if not self.object_info(node)]
        if missing:
            error = BackendNotReady(
                f"ComfyUI is missing the See-through nodes ({', '.join(missing)}). Install ComfyUI-See-through "
                f"({live2d_layers.SEETHROUGH_REPO}) and restart ComfyUI. " + live2d_layers.VRAM_NOTE
            )
            error.fix = custom_node_fix("ComfyUI-See-through", live2d_layers.SEETHROUGH_REPO)
            raise error

    def decompose_capabilities(self, selected: bool = False) -> list[Capability]:
        """Readiness of Live2D model kits (the See-through layer split)."""
        self._object_info.clear()
        missing = [node for node in SEETHROUGH_NODES if not self.object_info(node)]
        return [
            Capability(
                "seethrough_nodes", "See-through layer split (Live2D model kits)", not missing,
                f"Missing: {', '.join(missing)}" if missing else "Nodes present",
                required=selected,
                fix=Fix(
                    [
                        "Optional, for Live2D model kits. Install ComfyUI-See-through on the machine or pod ComfyUI runs on, then restart ComfyUI.",
                        live2d_layers.VRAM_NOTE,
                    ],
                    [f"cd ComfyUI/custom_nodes && git clone {live2d_layers.SEETHROUGH_REPO}", "pip install -r ComfyUI-See-through/requirements.txt"],
                    [Fix.link("ComfyUI-See-through", live2d_layers.SEETHROUGH_REPO)],
                ),
            )
        ]

    def _seethrough_model(self, node: str, hint: str, default: str, low_vram: bool) -> str:
        """A See-through loader's model: a copy in models/SeeThrough when ComfyUI lists one, else the Hugging Face repo."""
        choices = self.options(node, "model")
        fitting = [c for c in choices if hint in c.lower() and ("nf4" in c.lower()) == low_vram]
        local = [c for c in fitting if c.count("/") != 1 or c.startswith(("models", "."))]
        if local:
            return local[0]
        if not low_vram and default in choices:
            return default
        return fitting[0] if fitting else default

    def build_decompose_workflow(self, image_name: str, prefix: str, settings: "live2d_layers.SplitSettings") -> dict:
        """See-through: layers (LayerDiff 3D), depth (Marigold), left/right and hair splits, then the layers saved as PNGs."""
        quant = "nf4" if settings.low_vram else "none"
        workflow = {
            "load_image": {"class_type": "LoadImage", "inputs": {"image": image_name}},
            "layerdiff": {
                "class_type": "SeeThrough_LoadLayerDiffModel",
                "inputs": {
                    "model": self._seethrough_model("SeeThrough_LoadLayerDiffModel", "layerdiff", "layerdifforg/seethroughv0.0.2_layerdiff3d", settings.low_vram),
                    "quant_mode": quant,
                    "cache_tag_embeds": True,
                    "group_offload": False,
                    "auto_download": True,
                },
            },
            "depth_model": {
                "class_type": "SeeThrough_LoadDepthModel",
                "inputs": {
                    "model": self._seethrough_model("SeeThrough_LoadDepthModel", "marigold", "layerdifforg/seethroughv0.0.1_marigold", settings.low_vram),
                    "quant_mode": quant,
                    "cache_tag_embeds": True,
                    "group_offload": False,
                    "auto_download": True,
                },
            },
            "layers": {
                "class_type": "SeeThrough_GenerateLayers",
                "inputs": {
                    "image": ["load_image", 0],
                    "layerdiff_model": ["layerdiff", 0],
                    "seed": settings.seed,
                    "resolution": settings.resolution,
                    "num_inference_steps": settings.steps,
                },
            },
            "depth": {
                "class_type": "SeeThrough_GenerateDepth",
                "inputs": {"layers": ["layers", 0], "depth_model": ["depth_model", 0], "seed": settings.seed, "resolution_depth": min(settings.resolution, DEPTH_MAX)},
            },
            "post": {"class_type": "SeeThrough_PostProcess", "inputs": {"layers_depth": ["depth", 0], "tblr_split": True, "use_lama": True}},
            "save": {"class_type": "SeeThrough_SavePSD", "inputs": {"parts": ["post", 0], "filename_prefix": prefix}},
        }
        for node in workflow.values():
            node["inputs"] = self._with_defaults(node["class_type"], node["inputs"])
        return workflow

    def _with_defaults(self, node: str, inputs: dict) -> dict:
        """inputs without the ones this version of the node doesn't take, plus defaults for required ones it added."""
        spec = self.object_info(node).get("input", {})
        known = {**spec.get("required", {}), **spec.get("optional", {})}
        if not known:
            return inputs
        result = {key: value for key, value in inputs.items() if key in known}
        for key, value in spec.get("required", {}).items():
            if key not in result and isinstance(value, (list, tuple)) and len(value) > 1 and isinstance(value[1], dict) and "default" in value[1]:
                result[key] = value[1]["default"]
        return result

    def _output_file(self, filename: str, subfolder: str = "") -> bytes:
        response = self._request("GET", "/view", params={"filename": filename, "subfolder": subfolder, "type": "output"}, timeout=120)
        self._check(response, f"download of {filename}")
        return response.content

    # Upscale models for drawn art, best first (the setup script downloads the first).
    UPSCALE_MODELS = ("4x-AnimeSharp", "RealESRGAN_x4plus_anime_6B", "4x_foolhardy_Remacri", "RealESRGAN_x4plus", "4x-UltraSharp")

    def upscale_model(self) -> str | None:
        """The upscale model to use, or None when ComfyUI has none."""
        try:
            choices = self.options("UpscaleModelLoader", "model_name")
        except BackendError:
            return None
        for wanted in self.UPSCALE_MODELS:
            match = next((c for c in choices if wanted.lower() in c.lower()), None)
            if match:
                return match
        return choices[0] if choices else None

    def upscale(self, image: str) -> Image.Image | None:
        """A base64 picture upscaled with ComfyUI's upscale model (usually 4x), or None without one or on failure."""
        model = self.upscale_model()
        if model is None:
            return None
        self._interrupted.clear()
        self.last_error = None
        try:
            workflow = {
                "image": {"class_type": "LoadImage", "inputs": {"image": self.upload_image(image)}},
                "model": {"class_type": "UpscaleModelLoader", "inputs": {"model_name": model}},
                "upscale": {"class_type": "ImageUpscaleWithModel", "inputs": {"upscale_model": ["model", 0], "image": ["image", 0]}},
                "output": {"class_type": "PreviewImage", "inputs": {"images": ["upscale", 0]}},
            }
            self._prompt_id = self.queue_prompt(workflow)
            return self.fetch_image(self.wait_for(self._prompt_id)).convert("RGB")
        except BackendError as e:
            return self._fail(e, "upscale")
        except (KeyError, ValueError, TypeError, OSError) as e:
            return self._fail(BackendRejected(f"Unexpected response from ComfyUI: {e}"), "upscale")
        finally:
            self._prompt_id = None

    def pose_keypoints(self, image: str) -> list | None:
        """
        The body keypoints in a base64 picture from DWPose (comfyui_controlnet_aux's DWPreprocessor):
        OpenPose JSON's "people" list in the picture's pixels, or None without the node or on failure.
        """
        try:
            if not self.object_info("DWPreprocessor") or not self.object_info("SavePoseKpsAsJsonFile"):
                return None
        except BackendError:
            return None
        self._interrupted.clear()
        try:
            picture = b64_to_pil(image)
            # Saved to a file of its own: ComfyUI caches a repeated picture and then reports nothing
            # from the detector, but a new file name makes the save run again.
            prefix = f"autoexpress_pose_{uuid.uuid4().hex[:12]}"
            workflow = {
                "image": {"class_type": "LoadImage", "inputs": {"image": self.upload_image(image)}},
                "pose": {
                    "class_type": "DWPreprocessor",
                    "inputs": self._with_defaults(
                        "DWPreprocessor",
                        {"image": ["image", 0], "detect_hand": "disable", "detect_face": "disable", "detect_body": "enable", "resolution": 1024},
                    ),
                },
                "save": {"class_type": "SavePoseKpsAsJsonFile", "inputs": {"pose_kps": ["pose", 1], "filename_prefix": prefix}},
            }
            self._prompt_id = self.queue_prompt(workflow)
            self.wait_for(self._prompt_id)
            frames = json.loads(self._output_file(f"{prefix}_00001.json"))
            frame = frames[0] if isinstance(frames, list) and frames else frames
            if not isinstance(frame, dict):
                return None
            people = frame.get("people") or []
            # In the detector's own canvas: scale to the picture's pixels.
            width, height = frame.get("canvas_width") or picture.width, frame.get("canvas_height") or picture.height
            sx, sy = picture.width / width, picture.height / height
            for person in people:
                flat = person.get("pose_keypoints_2d") or []
                person["pose_keypoints_2d"] = [v * (sx if i % 3 == 0 else sy if i % 3 == 1 else 1) for i, v in enumerate(flat)]
            return people
        except BackendError as e:
            return self._fail(e, "pose detection")
        except (KeyError, ValueError, TypeError, OSError) as e:
            return self._fail(BackendRejected(f"Unexpected response from ComfyUI: {e}"), "pose detection")
        finally:
            self._prompt_id = None

    # SAM 3 (ComfyUI's own SAM3_Detect, with the SAM 3.1 checkpoint from Comfy-Org/sam3.1).
    SEGMENT_MODEL_HINT = "sam3"

    def segment_model(self) -> str | None:
        """The SAM 3 checkpoint ComfyUI has, or None (no SAM3_Detect node, or no checkpoint)."""
        try:
            if not self.object_info("SAM3_Detect"):
                return None
            return next((name for name in self.options("CheckpointLoaderSimple", "ckpt_name") if self.SEGMENT_MODEL_HINT in name.lower()), None)
        except BackendError:
            return None

    def segment(self, image: str, prompt: str, positive: list | None = None, negative: list | None = None, threshold: float = 0.4) -> Image.Image | None:
        """
        Where a base64 picture shows prompt (a short noun phrase, or several separated by commas),
        from SAM 3: a mask (mode L, the picture's size, 255 inside), or None without SAM 3 or on
        failure. positive / negative are point prompts ([(x, y), ...] in the picture's pixels).
        """
        checkpoint = self.segment_model()
        if checkpoint is None:
            return None
        self._interrupted.clear()
        try:
            picture = b64_to_pil(image)
            detect = {"model": ["sam", 0], "image": ["image", 0], "conditioning": ["text", 0], "threshold": threshold, "refine_iterations": 5, "individual_masks": False}
            if positive:
                detect["positive_coords"] = json.dumps([{"x": int(x), "y": int(y)} for x, y in positive])
            if negative:
                detect["negative_coords"] = json.dumps([{"x": int(x), "y": int(y)} for x, y in negative])
            workflow = {
                "image": {"class_type": "LoadImage", "inputs": {"image": self.upload_image(image)}},
                "sam": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
                "text": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["sam", 1], "text": prompt}},
                "detect": {"class_type": "SAM3_Detect", "inputs": detect},
                "as_image": {"class_type": "MaskToImage", "inputs": {"mask": ["detect", 0]}},
                "output": {"class_type": "SaveImage", "inputs": {"images": ["as_image", 0], "filename_prefix": f"autoexpress_mask_{uuid.uuid4().hex[:12]}"}},
            }
            self._prompt_id = self.queue_prompt(workflow)
            entry = self.wait_for(self._prompt_id)
            mask = self.fetch_image(entry).convert("L")
            return mask.resize(picture.size, Image.Resampling.BILINEAR) if mask.size != picture.size else mask
        except BackendError as e:
            return self._fail(e, "segmentation")
        except (KeyError, ValueError, TypeError, OSError) as e:
            return self._fail(BackendRejected(f"Unexpected response from ComfyUI: {e}"), "segmentation")
        finally:
            self._prompt_id = None

    def decompose_layers(self, image: str, settings: "live2d_layers.SplitSettings") -> tuple[list, tuple[int, int]] | None:
        """
        Split a base64 character picture into layers with See-through.

        Returns ([Part ...], canvas size) on See-through's square canvas, or None on failure (reason in last_error).
        """
        self._interrupted.clear()
        self.last_error = None
        self._progress = None
        stop_listening = None
        try:
            prefix = f"autoexpress_live2d_{uuid.uuid4().hex[:10]}"
            workflow = self.build_decompose_workflow(self.upload_image(image), prefix, settings)
            stop_listening = self._listen_for_progress()
            self._prompt_id = self.queue_prompt(workflow)
            self.wait_for(self._prompt_id)
            # The save node names its files <prefix>_<time>_<id>_*; its log holds the name of the layer list it wrote last.
            info_name = self._output_file(SEETHROUGH_INFO_LOG).decode("utf-8").strip()
            if not info_name.startswith(prefix):
                raise BackendRejected("Another See-through job finished at the same time; run the Live2D kit again.")
            info = json.loads(self._output_file(info_name))
            parts = []
            for entry in info.get("layers", []):
                layer = Image.open(io.BytesIO(self._output_file(entry["filename"])))
                layer.load()
                depth_map = None
                if entry.get("depth_filename"):
                    try:
                        depth_map = Image.open(io.BytesIO(self._output_file(entry["depth_filename"]))).convert("L")
                    except (BackendError, OSError):
                        depth_map = None  # only the head turn's parallax uses it
                parts.append(
                    live2d_layers.Part(
                        tag=entry["name"],
                        image=layer.convert("RGBA"),
                        left=int(entry.get("left", 0)),
                        top=int(entry.get("top", 0)),
                        depth=float(entry.get("depth_median", 1.0)),
                        depth_map=depth_map,
                    )
                )
            if not parts:
                raise BackendRejected("See-through found no layers in the picture.")
            return parts, (int(info.get("width", settings.resolution)), int(info.get("height", settings.resolution)))
        except BackendError as e:
            return self._fail(e, "layer split")
        except (KeyError, ValueError, TypeError, OSError) as e:
            return self._fail(BackendRejected(f"Unexpected response from ComfyUI's See-through nodes: {e}"), "layer split")
        finally:
            if stop_listening:
                stop_listening.set()
            self._prompt_id = None
            self._progress = None

    def edit_capabilities(self, selected: bool = False) -> list[Capability]:
        """edit_requirements() as Capability items for the readiness report."""
        return [
            Capability(
                item["key"], item["label"], item["ok"], item["detail"], item["required"],
                Fix(item["fix"]["steps"], item["fix"]["commands"], item["fix"]["links"]) if item["fix"] else None,
            )
            for item in self.edit_requirements(selected)
        ]

    def _install_dir(self) -> pathlib.Path | None:
        """ComfyUI's folder when it runs on this machine (from the command line it reports), else None."""
        try:
            argv = self._get_json("/system_stats", timeout=10).get("system", {}).get("argv") or []
        except (BackendError, ValueError, AttributeError, TypeError):
            return None
        root = pathlib.Path(argv[0]).parent if argv else None
        return root if root and (root / "custom_nodes").is_dir() else None

    @property
    def lora_dir(self) -> str | None:
        root = self._install_dir()
        folder = root / "models" / "loras" if root else None
        return str(folder) if folder and folder.is_dir() else None

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
        root = self._install_dir()
        return comfyui_sources([root / "custom_nodes"] if root else [])

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

    def build_edit_workflow(self, instruction: str, image_name: str, settings: instruction_edit.EditSettings, reference_name: str | None = None) -> dict:
        """
        A Qwen-Image-Edit workflow that applies one edit instruction to the uploaded image, plus a face mask output for paste-back.
        reference_name is a second uploaded image the instruction can refer to as picture 2 (a pose skeleton to follow).
        """
        unet = instruction_edit.find_model("diffusion_model", self.options("UNETLoader", "unet_name"), settings.model)
        text_encoder = instruction_edit.find_model("text_encoder", self.options("CLIPLoader", "clip_name"))
        vae_name = instruction_edit.find_model("vae", self.options("VAELoader", "vae_name"))
        if not (unet and text_encoder and vae_name):
            self.ensure_edit_ready()  # raises with the list of missing files
        lightning = None
        if settings.resolved_lightning():
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
        references = {}
        if reference_name and encoder == "TextEncodeQwenImageEditPlus":
            workflow["reference"] = self._node("LoadImage", {"image": reference_name})
            workflow["reference_scaled"] = self._node(
                "ImageScaleToTotalPixels", {"image": ["reference", 0], "upscale_method": "lanczos", "megapixels": settings.megapixels}
            )
            references = {"image2": ["reference_scaled", 0]}
        conditioning = {}
        for node_id, text in (("positive", instruction), ("negative", "")):
            workflow[node_id] = self._node(encoder, {"clip": ["clip", 0], "prompt": text, "vae": ["vae", 0], image_input: ["scaled", 0], **references})
            conditioning[node_id] = [node_id, 0]
        # 2511 was trained with its reference image at timestep zero; ComfyUI's own 2511 template sets this method.
        if "2511" in unet and "index_timestep_zero" in self.options(REFERENCE_METHOD_NODE, "reference_latents_method"):
            for node_id in ("positive", "negative"):
                workflow[f"{node_id}_reference"] = self._node(
                    REFERENCE_METHOD_NODE, {"conditioning": conditioning[node_id], "reference_latents_method": "index_timestep_zero"}
                )
                conditioning[node_id] = [f"{node_id}_reference", 0]

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
                "positive": conditioning["positive"],
                "negative": conditioning["negative"],
                "latent_image": ["latent", 0],
                "denoise": settings.resolved_denoise(),
            },
        )
        workflow["decode"] = self._node("VAEDecode", {"samples": ["sampler", 0], "vae": ["vae", 0]})
        workflow["output"] = {"class_type": "PreviewImage", "inputs": {"images": ["decode", 0]}}
        if settings.resolved_paste_face():
            if all(self.object_info(node) for node in FACE_MASK_NODES) and self.options("UltralyticsDetectorProvider", "model_name"):
                # The face box on the original image; instruction_edit() feathers it and pastes the edited face in.
                workflow["face_detector"] = self._node("UltralyticsDetectorProvider", {"model_name": self.detector_model(None)})
                workflow["face_segs"] = self._node(
                    "BboxDetectorSEGS",
                    {"bbox_detector": ["face_detector", 0], "image": ["image", 0], "threshold": 0.5, "dilation": 0, "crop_factor": 1.0, "drop_size": 10, "labels": "all"},
                )
                workflow["face_mask"] = self._node("SegsToCombinedMask", {"segs": ["face_segs", 0]})
                workflow["face_mask_image"] = self._node("MaskToImage", {"mask": ["face_mask", 0]})
                workflow[FACE_MASK_OUTPUT] = {"class_type": "PreviewImage", "inputs": {"images": ["face_mask_image", 0]}}
            else:
                log.warning("No Impact Pack face detector in ComfyUI, so the whole re-rendered photo is kept instead of only the face.")
        return workflow

    def build_animation_workflow(self, prompt: str, negative: str, image_name: str, size: tuple[int, int], settings: "animation.AnimationSettings") -> dict:
        """
        A Wan 2.2 image to video workflow (high noise then low noise model) that animates the uploaded still.

        With settings.loop the still is both the first and the last frame, so the clip loops.
        Every decoded frame comes back through one PreviewImage node.
        """
        files = self.animate_files()
        if not all(files[role] for role in ("high_noise", "low_noise", "text_encoder", "vae")):
            self.ensure_animate_ready()  # raises with the list of missing files
        # Full sampling by default: at the 4-step LoRAs' cfg 1 the negative prompt (talking, lip sync, ...) has no
        # effect, and smiling or upset faces then open and close the mouth as if talking.
        lightning = bool(settings.lightning)
        if lightning and not (files["lightning_high"] and files["lightning_low"]):
            log.warning("Wan 2.2 4-step LoRAs not found, sampling 20 steps instead.")
            lightning = False
        steps = settings.resolved_steps(lightning)
        switch = max(1, steps // 2)
        seed = settings.seed if settings.seed >= 0 else random.randint(0, 2**32 - 1)

        workflow = {}
        for stage in ("high", "low"):
            workflow[f"{stage}_unet"] = self._node("UNETLoader", {"unet_name": files[f"{stage}_noise"], "weight_dtype": "default"})
            model = [f"{stage}_unet", 0]
            if lightning:
                workflow[f"{stage}_lightning"] = self._node(
                    "LoraLoaderModelOnly", {"model": model, "lora_name": files[f"lightning_{stage}"], "strength_model": 1.0}
                )
                model = [f"{stage}_lightning", 0]
            workflow[f"{stage}_shift"] = self._node("ModelSamplingSD3", {"model": model, "shift": settings.shift})
        workflow["clip"] = self._node("CLIPLoader", {"clip_name": files["text_encoder"], "type": "wan", "device": "default"})
        workflow["vae"] = self._node("VAELoader", {"vae_name": files["vae"]})
        workflow["positive"] = self._node("CLIPTextEncode", {"clip": ["clip", 0], "text": prompt})
        workflow["negative"] = self._node("CLIPTextEncode", {"clip": ["clip", 0], "text": negative})
        workflow["image"] = self._node("LoadImage", {"image": image_name})
        width, height = size
        video_inputs = {
            "positive": ["positive", 0],
            "negative": ["negative", 0],
            "vae": ["vae", 0],
            "width": width,
            "height": height,
            "length": settings.frame_count,
            "batch_size": 1,
            "start_image": ["image", 0],
        }
        if settings.loop:
            video_inputs["end_image"] = ["image", 0]
        workflow["video"] = self._node("WanFirstLastFrameToVideo", video_inputs)
        cfg = settings.resolved_cfg(lightning)
        common = {
            "noise_seed": seed,
            "steps": steps,
            "cfg": cfg,
            "sampler_name": "euler",
            "scheduler": "simple",
            "positive": ["video", 0],
            "negative": ["video", 1],
        }
        workflow["sample_high"] = self._node(
            "KSamplerAdvanced",
            {**common, "model": ["high_shift", 0], "add_noise": "enable", "latent_image": ["video", 2], "start_at_step": 0, "end_at_step": switch, "return_with_leftover_noise": "enable"},
        )
        workflow["sample_low"] = self._node(
            "KSamplerAdvanced",
            {**common, "model": ["low_shift", 0], "add_noise": "disable", "latent_image": ["sample_high", 0], "start_at_step": switch, "end_at_step": 10000, "return_with_leftover_noise": "disable"},
        )
        workflow["decode"] = self._node("VAEDecode", {"samples": ["sample_low", 0], "vae": ["vae", 0]})
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

    def fetch_image(self, entry: dict, node: str = "output") -> Image.Image:
        images = entry.get("outputs", {}).get(node, {}).get("images", [])
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

    # A second picture (a pose skeleton) can go with an edit, with TextEncodeQwenImageEditPlus.
    takes_reference = True

    def instruction_edit(self, image: str, instruction: str, settings: instruction_edit.EditSettings, reference: str | None = None) -> Image.Image | None:
        """
        Apply one edit instruction to a base64 image with Qwen-Image-Edit; reference is an optional
        second base64 image the instruction calls picture 2.

        Returns the edited image at the input's size, or None on failure (the reason is in last_error).
        """
        self._interrupted.clear()
        self.last_error = None
        self._progress = None
        stop_listening = None
        try:
            if settings.seed < 0:
                settings = dataclasses.replace(settings, seed=random.randint(0, 2**32 - 1))
            workflow = self.build_edit_workflow(instruction, self.upload_image(image), settings, self.upload_image(reference) if reference else None)
            stop_listening = self._listen_for_progress()
            self._prompt_id = self.queue_prompt(workflow)
            entry = self.wait_for(self._prompt_id)
            result = self.fetch_image(entry)
            source = b64_to_pil(image)
            if (settings.keep_size or FACE_MASK_OUTPUT in workflow) and result.size != source.size:
                result = result.convert("RGB").resize(source.size, Image.LANCZOS)
            if FACE_MASK_OUTPUT in workflow:
                mask = self.fetch_image(entry, FACE_MASK_OUTPUT)
                result = paste_face(source, result, mask)
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
                "Denoising strength": f"{sampler['denoise']:g}",
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

    def fetch_images(self, entry: dict, node: str = "output") -> list[Image.Image]:
        """Every image a node produced (the frames of a clip), in order."""
        images = entry.get("outputs", {}).get(node, {}).get("images", [])
        if not images:
            raise BackendRejected("ComfyUI finished without any frames.")
        frames = []
        for image in images:
            response = self._request(
                "GET",
                "/view",
                params={"filename": image["filename"], "subfolder": image.get("subfolder", ""), "type": image.get("type", "temp")},
                timeout=120,
            )
            self._check(response, "frame download")
            frame = Image.open(io.BytesIO(response.content))
            frame.load()
            frames.append(frame)
        return frames

    def animate(self, image: str, prompt: str, negative: str, settings: "animation.AnimationSettings") -> list[Image.Image] | None:
        """
        Animate a base64 still with Wan 2.2 image to video.

        Returns the frames at the video size (first and last equal to the still when looping), or None on failure.
        """
        self._interrupted.clear()
        self.last_error = None
        self._progress = None
        stop_listening = None
        try:
            if settings.seed < 0:
                settings = dataclasses.replace(settings, seed=random.randint(0, 2**32 - 1))
            source = b64_to_pil(image)
            size = animation.video_size(*source.size, settings.resolution)
            workflow = self.build_animation_workflow(prompt, negative, self.upload_image(image), size, settings)
            stop_listening = self._listen_for_progress()
            self._prompt_id = self.queue_prompt(workflow)
            frames = self.fetch_images(self.wait_for(self._prompt_id))
            sampler = workflow["sample_high"]["inputs"]
            params = ", ".join(
                f"{key}: {value}"
                for key, value in {
                    "Steps": sampler["steps"],
                    "CFG scale": f"{sampler['cfg']:g}",
                    "Seed": sampler["noise_seed"],
                    "Size": f"{size[0]}x{size[1]}",
                    "Frames": len(frames),
                    "Model": workflow["high_unet"]["inputs"]["unet_name"],
                    "Version": "ComfyUI",
                }.items()
            )
            for frame in frames[:1]:
                frame.info["parameters"] = f"{prompt}\nNegative prompt: {negative}\n{params}"
            return frames
        except BackendError as e:
            return self._fail(e, "animation")
        except (KeyError, ValueError, TypeError) as e:
            return self._fail(BackendRejected(f"Unexpected response from ComfyUI: {e}"), "animation")
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
