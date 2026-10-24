"""
ComfyUI nodes for AutoExpress.

ComfyUI has no ADetailer, so the face inpainting is done by Impact Pack's
FaceDetailer. These nodes provide the AutoExpress specific parts around it:

    AutoExpress Expression LoRAs   -> model / clip   -> FaceDetailer
                                   -> trigger        -> AutoExpress Expression Prompts
    AutoExpress Expression Prompts -> prompts (list) -> FaceDetailer "wildcard" input
                                   -> negative       -> CLIP Text Encode -> FaceDetailer negative
                                   -> names (list)   -> AutoExpress Save Expressions / Sprite Sheet

Because the prompts output is a list, ComfyUI runs FaceDetailer once per
expression on its own, no loop nodes needed.

The instruction edit mode skips FaceDetailer and has Qwen-Image-Edit-2511
rewrite the expression from a sentence (about 24 GB of VRAM, see
autoexpress_core.instruction_edit):

    AutoExpress Edit Instructions -> instructions (list) -> TextEncodeQwenImageEditPlus prompt
                                  -> names (list)        -> AutoExpress Save Expressions / Sprite Sheet

example_workflows/ has both graphs ready to load.
"""

import os

import numpy as np
import torch
from PIL import Image

import folder_paths

import comfy.sd
import comfy.utils

from ..autoexpress_core import (
    AUTO,
    DEFAULT_FLAVOR,
    FLAVORS,
    civitai_key,
    expression_loras,
    expression_names,
    expression_sets,
    instruction_edit,
    make_sprite_sheet,
    resolve_flavor,
)
from ..autoexpress_core import intensity as expression_intensity
from ..autoexpress_core.log import log

CATEGORY = "AutoExpress"


def tensor_to_pil(image: torch.Tensor) -> list[Image.Image]:
    """ComfyUI IMAGE ([B, H, W, C] floats in 0..1) to PIL images."""
    if image.dim() == 3:
        image = image.unsqueeze(0)
    arrays = (image.cpu().numpy() * 255.0).clip(0, 255).astype(np.uint8)
    return [Image.fromarray(array) for array in arrays]


def pil_to_tensor(image: Image.Image) -> torch.Tensor:
    array = np.asarray(image.convert("RGB")).astype(np.float32) / 255.0
    return torch.from_numpy(array).unsqueeze(0)


def parse_selection(selection: str) -> list[str] | None:
    """'all' or empty means every expression, otherwise a comma separated list of names."""
    names = [name.strip().lower() for name in (selection or "").split(",") if name.strip()]
    return None if not names or names == ["all"] else names


def checkpoint_choices() -> list[str]:
    return [""] + folder_paths.get_filename_list("checkpoints")


# ComfyUI's model config classes (comfy.supported_models) for each base.
_CONFIG_ARCHITECTURE = {"SD15": "sd15", "SD20": "sd2", "SDXL": "sdxl", "Flux": "flux"}


def model_base_architecture(model) -> str | None:
    """The base architecture of a loaded MODEL, from its config or else its weights."""
    base_model = getattr(model, "model", None)
    config = getattr(base_model, "model_config", None)
    for cls in type(config).__mro__ if config is not None else ():
        if cls.__name__ in _CONFIG_ARCHITECTURE:
            return _CONFIG_ARCHITECTURE[cls.__name__]
    try:
        state = base_model.state_dict()
    except Exception:
        return None
    return expression_loras.base_architecture(
        (key, tuple(getattr(tensor, "shape", ()) or ()) or None) for key, tensor in state.items()
    )


def safe_folder_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (name or "").strip())
    return keep.strip() or "New_Character"


PROMPT_STYLE_TOOLTIP = "Model family the prompts are written for. 'auto' picks it from ckpt_name."


def intensity_input():
    """Optional expression intensity slider; -1 means the model family's calibrated default."""
    return ("FLOAT", {
        "default": -1.0,
        "min": -1.0,
        "max": 1.0,
        "step": 0.05,
        "display": "slider",
        "tooltip": "How strong the expression is, 0 (barely) to 1 (exaggerated). -1 uses the model family's default: "
        "0.5 for anime and furry models, much lower for realistic ones, where strong expressions look uncanny.",
    })


def node_intensity(value, family: str | None = None, photo: bool = False) -> float:
    """The intensity a node runs at: its slider, else the family's default, else the drawn/photo default."""
    if value is not None and value >= 0:
        return expression_intensity.resolve(value)
    if family:
        return expression_sets.family_defaults(family)["intensity"]
    return expression_intensity.resolve(None, realistic=photo)


class AutoExpressExpressionPrompts:
    """Every AutoExpress expression as a prompt list, prefixed with the character prompt."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_style": (FLAVORS, {"default": DEFAULT_FLAVOR, "tooltip": PROMPT_STYLE_TOOLTIP}),
                "base_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Character prompt placed before every expression prompt.",
                }),
                "base_negative": ("STRING", {"multiline": True, "default": ""}),
                "expressions": ("STRING", {
                    "default": "all",
                    "tooltip": "'all', or a comma separated list such as: joy, anger, surprise",
                }),
            },
            "optional": {
                "ckpt_name": (checkpoint_choices(), {"tooltip": "Only used to pick the prompt style when it is 'auto'."}),
                "lora_trigger": ("STRING", {"forceInput": True, "tooltip": "Trigger words from AutoExpress Expression LoRAs."}),
                "intensity": intensity_input(),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "STRING", "INT")
    RETURN_NAMES = ("prompts", "names", "negative", "count")
    OUTPUT_IS_LIST = (True, True, False, False)
    OUTPUT_TOOLTIPS = (
        "One prompt per expression. Connect to FaceDetailer's wildcard input.",
        "Expression names, in the same order as the prompts.",
        "Negative prompt with the family's negative tags added.",
        "Number of expressions.",
    )
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = "Builds the AutoExpress expression prompts. Downstream nodes run once per expression."

    def build(self, prompt_style, base_prompt, base_negative, expressions, ckpt_name="", lora_trigger="", intensity=-1.0):
        family = resolve_flavor(prompt_style, ckpt_name)
        intensity = node_intensity(intensity, family)
        all_names = expression_sets.load_family(family)["expressions"]
        wanted = parse_selection(expressions)
        names = [name for name in all_names if wanted is None or name in wanted]
        if not names:
            raise ValueError(f"No expressions matched '{expressions}'. Valid names: {', '.join(all_names)}")

        base = expression_sets.join_prompt(base_prompt, lora_trigger)
        prompts = [expression_sets.build_prompt(base, name, family, intensity=intensity) for name in names]
        negative = expression_sets.build_negative(base_negative, family)
        log.info(f"AutoExpress: {len(names)} {family} expression prompts at intensity {intensity:g}.")
        return (prompts, names, negative, len(names))


class AutoExpressExpressionPrompt:
    """A single AutoExpress expression prompt."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt_style": (FLAVORS, {"default": DEFAULT_FLAVOR, "tooltip": PROMPT_STYLE_TOOLTIP}),
                "expression": (expression_names(), {"default": "joy"}),
                "base_prompt": ("STRING", {"multiline": True, "default": ""}),
            },
            "optional": {
                "ckpt_name": (checkpoint_choices(),),
            },
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "name")
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, prompt_style, expression, base_prompt, ckpt_name=""):
        family = resolve_flavor(prompt_style, ckpt_name)
        return (expression_sets.build_prompt(base_prompt, expression, family), expression)


class AutoExpressEditInstructions:
    """Every AutoExpress expression as an edit instruction for Qwen-Image-Edit."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "expressions": ("STRING", {
                    "default": "all",
                    "tooltip": "'all', or a comma separated list such as: joy, anger, surprise",
                }),
                "style": (list(instruction_edit.STYLES), {
                    "default": instruction_edit.ILLUSTRATION,
                    "tooltip": "illustration keeps the art style; photo keeps a realistic photo from turning into a cartoon.",
                }),
                "intensity": intensity_input(),
                "extra_instruction": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Added to every instruction, e.g. 'Keep the glasses on.'",
                }),
            },
        }

    RETURN_TYPES = ("STRING", "STRING", "INT", "FLOAT")
    RETURN_NAMES = ("instructions", "names", "count", "denoise")
    OUTPUT_IS_LIST = (True, True, False, True)
    OUTPUT_TOOLTIPS = (
        "One edit instruction per expression. Connect to TextEncodeQwenImageEditPlus's prompt.",
        "Expression names, in the same order as the instructions.",
        "Number of expressions.",
        "KSampler denoise per expression for the intensity: lower keeps more of the original face.",
    )
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = (
        "Edit instructions for Qwen-Image-Edit-2511 (or 2509): stronger expressions than face inpainting, "
        "no face detector or LoRA. " + instruction_edit.VRAM_NOTE
    )

    def build(self, expressions, style=instruction_edit.ILLUSTRATION, intensity=-1.0, extra_instruction=""):
        intensity = node_intensity(intensity, photo=style == instruction_edit.PHOTO)
        all_names = instruction_edit.instruction_names()
        wanted = parse_selection(expressions)
        names = [name for name in all_names if wanted is None or name in wanted]
        if not names:
            raise ValueError(f"No expressions matched '{expressions}'. Valid names: {', '.join(all_names)}")
        photo = style == instruction_edit.PHOTO
        values = [instruction_edit.expression_intensity_for(name, intensity, style) for name in names]
        instructions = [instruction_edit.build_instruction(name, extra_instruction, style, value) for name, value in zip(names, values)]
        denoise = [expression_intensity.edit_denoise(value, photo) for value in values]
        log.info(f"AutoExpress: {len(names)} {style} edit instructions at intensity {intensity:g}.")
        return (instructions, names, len(names), denoise)


class AutoExpressExpressionLoras:
    """Applies the expression LoRAs that match the checkpoint, downloading them from Civitai when missing."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ("MODEL",),
                "clip": ("CLIP",),
                "ckpt_name": (checkpoint_choices(), {"tooltip": "The checkpoint you loaded. Its name tells Pony and Illustrious apart from plain SDXL; the base (SD 1.5, SDXL, Flux) is read from the model."}),
                "prompt_style": (FLAVORS, {"default": DEFAULT_FLAVOR, "tooltip": PROMPT_STYLE_TOOLTIP}),
                "architecture": ([AUTO] + expression_loras.architectures(), {"default": AUTO}),
                "download_missing": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "intensity": intensity_input(),
                "civitai_api_key": ("STRING", {
                    "default": "",
                    "tooltip": "Needed by Civitai for downloads. Leave empty to reuse the key from ComfyUI LoRA Manager or the CIVITAI_API_KEY / CIVITAI_API_TOKEN environment variable.",
                }),
            },
        }

    RETURN_TYPES = ("MODEL", "CLIP", "STRING")
    RETURN_NAMES = ("model", "clip", "lora_trigger")
    OUTPUT_TOOLTIPS = (
        "Model with the expression LoRAs applied.",
        "CLIP with the expression LoRAs applied.",
        "Trigger words. Connect to AutoExpress Expression Prompts.",
    )
    FUNCTION = "apply"
    CATEGORY = CATEGORY

    def apply(self, model, clip, ckpt_name, prompt_style, architecture, download_missing, civitai_api_key="", intensity=-1.0):
        family = resolve_flavor(prompt_style, ckpt_name)
        scale = expression_intensity.lora_scale(node_intensity(intensity, family))
        if architecture == AUTO:
            base = model_base_architecture(model)
            architecture = expression_loras.guess_architecture(ckpt_name, family, base)
            log.info(f"AutoExpress: {ckpt_name or 'model'} is {base or 'of unknown base'}, using {architecture} expression LoRAs.")

        lora_dir = folder_paths.get_folder_paths("loras")[0]
        if download_missing:
            api_key, key_source = civitai_key.find_civitai_key(
                explicit=civitai_api_key,
                host_sources=civitai_key.comfyui_sources(folder_paths.get_folder_paths("custom_nodes")),
            )
            if key_source:
                log.info(f"AutoExpress: using the Civitai API key from {key_source}")
            expression_loras.ensure_loras(architecture, lora_dir, api_key, log=log.info)

        triggers = []
        for entry in expression_loras.loras_for(architecture):
            path = self._find(entry)
            if path is None:
                log.warning(f"AutoExpress: expression LoRA {entry['name']} is not installed, skipping.")
                continue
            weight = round(entry["weight"] * scale, 3)
            if weight == 0:
                continue
            lora = comfy.utils.load_torch_file(path, safe_load=True)
            model, clip = comfy.sd.load_lora_for_models(model, clip, lora, weight, weight)
            if entry.get("trigger"):
                triggers.append(entry["trigger"])
            log.info(f"AutoExpress: applied {entry['name']} at {weight:g} ({architecture}).")

        return (model, clip, ", ".join(triggers))

    @staticmethod
    def _find(entry) -> str | None:
        names = [entry["name"], os.path.splitext(entry.get("original_file") or "")[0]]
        for name in filter(None, names):
            path = folder_paths.get_full_path("loras", name + expression_loras.LORA_EXTENSION)
            if path:
                return path
        return None


class AutoExpressSaveExpressions:
    """Saves each image as <output>/autoexpress/<character>/<expression>.png."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "names": ("STRING", {"forceInput": True}),
                "character_name": ("STRING", {"default": "New_Character"}),
            }
        }

    INPUT_IS_LIST = True
    RETURN_TYPES = ()
    OUTPUT_NODE = True
    FUNCTION = "save"
    CATEGORY = CATEGORY

    def save(self, images, names, character_name):
        character = safe_folder_name(character_name[0])
        subfolder = os.path.join("autoexpress", character)
        output_dir = os.path.join(folder_paths.get_output_directory(), subfolder)
        os.makedirs(output_dir, exist_ok=True)

        pil_images = [pil for batch in images for pil in tensor_to_pil(batch)]
        results = []
        for index, image in enumerate(pil_images):
            name = names[index] if index < len(names) else f"expression_{index:02d}"
            filename = f"{safe_folder_name(name)}.png"
            image.save(os.path.join(output_dir, filename))
            results.append({"filename": filename, "subfolder": subfolder, "type": "output"})

        return {"ui": {"images": results}}


class AutoExpressSpriteSheet:
    """Tiles the expression images into one labelled sheet."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "columns": ("INT", {"default": 7, "min": 1, "max": 64}),
                "show_labels": ("BOOLEAN", {"default": True}),
            },
            "optional": {
                "names": ("STRING", {"forceInput": True}),
            },
        }

    INPUT_IS_LIST = True
    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("sprite_sheet",)
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, images, columns, show_labels, names=None):
        pil_images = [pil for batch in images for pil in tensor_to_pil(batch)]
        labels = list(names) if names and show_labels[0] else None
        sheet = make_sprite_sheet(pil_images, labels, columns=columns[0])
        return (pil_to_tensor(sheet),)


NODE_CLASS_MAPPINGS = {
    "AutoExpressExpressionPrompts": AutoExpressExpressionPrompts,
    "AutoExpressExpressionPrompt": AutoExpressExpressionPrompt,
    "AutoExpressExpressionLoras": AutoExpressExpressionLoras,
    "AutoExpressEditInstructions": AutoExpressEditInstructions,
    "AutoExpressSaveExpressions": AutoExpressSaveExpressions,
    "AutoExpressSpriteSheet": AutoExpressSpriteSheet,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AutoExpressExpressionPrompts": "AutoExpress Expression Prompts",
    "AutoExpressExpressionPrompt": "AutoExpress Expression Prompt",
    "AutoExpressExpressionLoras": "AutoExpress Expression LoRAs",
    "AutoExpressEditInstructions": "AutoExpress Edit Instructions",
    "AutoExpressSaveExpressions": "AutoExpress Save Expressions",
    "AutoExpressSpriteSheet": "AutoExpress Sprite Sheet",
}
