"""
ComfyUI nodes for AutoExpress.

ComfyUI has no ADetailer, so the face inpainting is done by Impact Pack's
FaceDetailer. These nodes provide the AutoExpress specific parts around it:

    AutoExpress Expression Prompts -> prompts (list) -> FaceDetailer "wildcard" input
                                   -> names (list)   -> AutoExpress Save Expressions / Sprite Sheet

Because the prompts output is a list, ComfyUI runs FaceDetailer once per
expression on its own, no loop nodes needed.
"""

import os

import numpy as np
import torch
from PIL import Image

import folder_paths

from ..autoexpress_core import (
    DEFAULT_FLAVOR,
    FLAVORS,
    expression_names,
    get_expressions,
    join_prompt,
    make_sprite_sheet,
)

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


def safe_folder_name(name: str) -> str:
    keep = "".join(c if c.isalnum() or c in "-_ " else "_" for c in (name or "").strip())
    return keep.strip() or "New_Character"


class AutoExpressExpressionPrompts:
    """Every AutoExpress expression as a prompt list, prefixed with the character prompt."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "flavor": (list(FLAVORS), {"default": DEFAULT_FLAVOR}),
                "base_prompt": ("STRING", {
                    "multiline": True,
                    "default": "",
                    "tooltip": "Character prompt placed before every expression prompt.",
                }),
                "expressions": ("STRING", {
                    "default": "all",
                    "tooltip": "'all', or a comma separated list such as: joy, anger, surprise",
                }),
            }
        }

    RETURN_TYPES = ("STRING", "STRING", "INT")
    RETURN_NAMES = ("prompts", "names", "count")
    OUTPUT_IS_LIST = (True, True, False)
    OUTPUT_TOOLTIPS = (
        "One prompt per expression. Connect to FaceDetailer's wildcard input.",
        "Expression names, in the same order as the prompts.",
        "Number of expressions.",
    )
    FUNCTION = "build"
    CATEGORY = CATEGORY
    DESCRIPTION = "Builds the AutoExpress expression prompts. Downstream nodes run once per expression."

    def build(self, flavor, base_prompt, expressions):
        selected = get_expressions(flavor, parse_selection(expressions))
        if not selected:
            raise ValueError(f"No expressions matched '{expressions}'. Valid names: {', '.join(expression_names(flavor))}")
        names = list(selected)
        prompts = [join_prompt(base_prompt, tags) for tags in selected.values()]
        return (prompts, names, len(names))


class AutoExpressExpressionPrompt:
    """A single AutoExpress expression prompt."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "flavor": (list(FLAVORS), {"default": DEFAULT_FLAVOR}),
                "expression": (expression_names(), {"default": "joy"}),
                "base_prompt": ("STRING", {"multiline": True, "default": ""}),
            }
        }

    RETURN_TYPES = ("STRING", "STRING")
    RETURN_NAMES = ("prompt", "name")
    FUNCTION = "build"
    CATEGORY = CATEGORY

    def build(self, flavor, expression, base_prompt):
        tags = get_expressions(flavor)[expression]
        return (join_prompt(base_prompt, tags), expression)


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
    "AutoExpressSaveExpressions": AutoExpressSaveExpressions,
    "AutoExpressSpriteSheet": AutoExpressSpriteSheet,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "AutoExpressExpressionPrompts": "AutoExpress Expression Prompts",
    "AutoExpressExpressionPrompt": "AutoExpress Expression Prompt",
    "AutoExpressSaveExpressions": "AutoExpress Save Expressions",
    "AutoExpressSpriteSheet": "AutoExpress Sprite Sheet",
}
