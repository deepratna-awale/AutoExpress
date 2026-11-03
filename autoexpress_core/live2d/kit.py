"""
Live2D model kits: from character pictures to a layered, Live2D-ready model source.

build_kit() runs the whole pipeline on a backend that can split layers (ComfyUI with the
See-through nodes):

1. Check the pictures (guidance.check_image) and pick the best one.
2. Remove a busy background (rembg, when installed).
3. Make the art a rig needs and the picture doesn't show: the eyes closed and the mouth open.
   With a character LoRA installed on the WebUI, face inpainting with the LoRA keeps the
   character on model; otherwise Qwen-Image-Edit does it (ComfyUI), else plain face inpainting.
   With swappable clothing on (adult, drawn characters only, see outfits.py), also the body
   under the clothes and the body in inner wear.
4. Split the character into up to 23 layers with hidden areas painted in (See-through), at up to
   2048 px (small pictures are upscaled first), then make skin, clothes and hair opaque and paint
   the hair colour under the bangs.
5. Write the kit:
     <name>.psd                 Cubism-ready: one group per part, L/R named, blink and mouth art hidden
     <name>_seethrough.psd      the same layers flat, named the way See-through names them, for
                                tools that rig See-through output directly (StretchyStudio, Anime2.5DRig)
     layers/*.png               every layer on its own, at its place on the canvas
     preview.png, sheet.png     the reassembled character, and every layer side by side
     runtime/                   expressions/ and motions/ for the 28 emotions plus
                                sillytavern_settings.json, to copy into the model folder after rigging
     manifest.json              layers, switches, checks, what's missing
     README.txt                 how to rig it in Live2D Cubism Editor and use it in SillyTavern
   and zips the folder.

Only Pillow is needed here; rembg is used when installed.
"""

import dataclasses
import json
import os
import pathlib
import shutil
import zipfile
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter

from .. import instruction_edit
from ..images import pil_to_b64
from ..payload import build_expression_payload
from . import DECOMPOSE, guidance, layers, model_files, outfits, prompt_data, psd, puppet, skeleton

MAX_SIDE = 2048
EYES_CLOSED = "eyes_closed"
MOUTH_OPEN = "mouth_open"
# Drawn pieces for the strongest emotions (the rig bends the rest).
ANGRY_BROWS = "angry_brows"
GRIN = "grin"
TEARS = "teary_eyes"
EXPRESSION_ART = (ANGRY_BROWS, GRIN, TEARS)

KEEP = "Keep everything else exactly the same: face shape, eyebrows, hair, outfit, pose, colors, line art, art style, background and framing."
INSTRUCTIONS = {
    EYES_CLOSED: "Close both eyes gently, like a calm blink: relaxed closed eyelids drawn as soft curved lash lines, no other change to the face. " + KEEP,
    MOUTH_OPEN: "Open the mouth a little, as if saying \"ah\": a small relaxed open mouth showing a bit of the inside, no other change to the face. " + KEEP,
    ANGRY_BROWS: "Make the eyebrows furious: sharply furrowed and slanted, the inner ends pulled hard down towards the nose in a fierce scowl. "
    "Keep the eyes open and looking the same way, and the mouth unchanged. " + KEEP.replace("eyebrows, ", ""),
    GRIN: "Give the character a wide, beaming grin: the corners of the mouth pulled up high and the lips parted just enough to show the upper teeth. "
    "The jaw doesn't drop: the chin and the outline of the face stay exactly where they are. Keep the eyes, eyebrows and everything else unchanged. " + KEEP,
    TEARS: "Make the eyes teary: glistening, watery eyes with tears welling up along the lower lids and a tear running down each cheek. "
    "Keep the eyes open, and the eyebrows and mouth unchanged. " + KEEP,
}
PROMPTS = {
    EYES_CLOSED: "closed eyes, calm expression, closed mouth",
    MOUTH_OPEN: "open mouth, :o, neutral expression, eyes open",
    ANGRY_BROWS: "v-shaped eyebrows, furrowed brow, angry, eyes open, closed mouth",
    GRIN: "grin, wide smile, upper teeth, parted lips, happy, eyes open",
    TEARS: "tears, teary eyes, streaming tears, eyes open, closed mouth",
}

AUTO, INPAINT, INSTRUCT = "auto", instruction_edit.INPAINT, instruction_edit.INSTRUCT


@dataclasses.dataclass
class KitResult:
    folder: pathlib.Path
    zip_path: pathlib.Path
    manifest: dict
    puppet_zip: pathlib.Path | None = None


class KitCancelled(Exception):
    pass


def prepare_picture(
    image: Image.Image,
    remove_background: bool | None = None,
    log: Callable[[str], None] = lambda _: None,
    backend=None,
    min_side: int = 0,
) -> Image.Image:
    """
    The picture as See-through and the edits should see it: at most MAX_SIDE px, the character on white.

    remove_background None removes it only when it's busy (and rembg is installed). A picture whose
    long side is under min_side is upscaled to it first, with the backend's upscale model when it
    has one (backend.upscale), else with Lanczos, so the layers come out at the split's resolution.
    """
    image = image.copy()
    image.load()
    if min_side and max(image.size) < min_side:
        target = min(MAX_SIDE, min_side)
        upscaled = None
        upscale = getattr(backend, "upscale", None) if backend is not None else None
        if upscale:
            log(f"Upscaling the picture from {max(image.size)} px to {target} px with an upscale model.")
            upscaled = upscale(pil_to_b64(image.convert("RGB")))
        scale = target / max(image.size)
        size = (round(image.width * scale), round(image.height * scale))
        if upscaled is None:
            log(f"Upscaling the picture from {max(image.size)} px to {target} px.")
            upscaled = image.resize(size, Image.Resampling.LANCZOS)
        elif upscaled.size != size:
            upscaled = upscaled.resize(size, Image.Resampling.LANCZOS)
        if image.mode == "RGBA" and upscaled.mode != "RGBA":
            alpha = image.getchannel("A").resize(size, Image.Resampling.LANCZOS)
            upscaled = upscaled.convert("RGBA")
            upscaled.putalpha(alpha)
        image = upscaled
    if max(image.size) > MAX_SIDE:
        scale = MAX_SIDE / max(image.size)
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    transparent = guidance.has_transparency(image)
    if not transparent:
        busy = guidance.background_plainness(image) < 0.7
        if remove_background or (remove_background is None and busy):
            from .. import background

            if background.available():
                model = os.environ.get(background.MODEL_ENV, "").strip() or background.LIVE2D_MODEL
                log(f"Removing the background ({model}).")
                try:
                    image = background.remove_background(image, model)
                except Exception as error:  # noqa: BLE001 - a model that can't load: the lighter one
                    log(f"{model} failed ({error}); using {background.ILLUSTRATION_MODEL}.")
                    image = background.remove_background(image, background.ILLUSTRATION_MODEL)
                transparent = True
            else:
                log("The background is busy and rembg isn't installed, so it stays. A plain background splits better.")
    if transparent:
        flat = Image.new("RGB", image.size, (255, 255, 255))
        flat.paste(image.convert("RGBA"), mask=image.convert("RGBA").getchannel("A"))
        return flat
    return image.convert("RGB")


def variant_method(backend, method: str = AUTO, lora_installed: bool = False) -> str | None:
    """How to make the eyes-closed and mouth-open art on this backend, or None when it can't."""
    methods = getattr(backend, "edit_methods", ())
    if method in (INPAINT, INSTRUCT):
        return method if method in methods else None
    if lora_installed and INPAINT in methods:
        return INPAINT
    if INSTRUCT in methods:
        return INSTRUCT
    return INPAINT if INPAINT in methods else None


def make_variant(backend, picture: Image.Image, which: str, method: str, settings: dict, lora_prompt: str = "") -> Image.Image | None:
    """The picture with the eyes closed or the mouth open, the same size, or None when the backend failed."""
    b64 = pil_to_b64(picture)
    if method == INSTRUCT:
        edit = instruction_edit.EditSettings.from_settings(settings)
        edit = dataclasses.replace(edit, keep_size=True, photo=False, intensity=1.0)
        result = backend.instruction_edit(b64, INSTRUCTIONS[which], edit)
    else:
        face = dict(settings)
        face["ad_prompt"] = ", ".join(part for part in (settings.get("ad_prompt", ""), lora_prompt, PROMPTS[which]) if part)
        face.setdefault("ad_denoising_strength", 0.45)
        result = backend.img2img(build_expression_payload(b64, face))
    if result is None:
        return None
    return result.convert("RGB").resize(picture.size, Image.Resampling.LANCZOS) if result.size != picture.size else result.convert("RGB")


def make_outfit_edits(backend, picture: Image.Image, settings: dict, log, check_cancel, progress) -> tuple[dict, list[str]]:
    """The nude and inner wear edits of picture ({outfits.NUDE: ..., outfits.INNER: ...}, as many as worked) and notes."""
    notes: list[str] = []
    edits: dict[str, Image.Image] = {}
    if INSTRUCT not in getattr(backend, "edit_methods", ()):
        notes.append("Swappable clothing needs Qwen-Image-Edit on ComfyUI; the clothes stay one layer.")
        return edits, notes
    description = settings.get("character_description", "")
    if settings.get("outfit_from_prompt"):
        description = (description + f". Her outfit: {settings['outfit_from_prompt']}").strip(". ")
    edit = instruction_edit.EditSettings.from_settings(settings)
    edit = dataclasses.replace(edit, keep_size=True, photo=False, intensity=1.0)
    check_cancel()
    progress("drawing the body layer", 0.3)
    log("Drawing the body under the clothes (Qwen-Image-Edit).")
    nude = backend.instruction_edit(pil_to_b64(picture), outfits.adapt(outfits.nude_instruction(description), description), edit)
    if nude is None:
        notes.append(f"Couldn't draw the body layer: {getattr(backend, 'last_error', None) or 'the WebUI failed'}. The clothes stay one layer.")
        return edits, notes
    nude = nude.convert("RGB").resize(picture.size, Image.Resampling.LANCZOS) if nude.size != picture.size else nude.convert("RGB")
    edits[outfits.NUDE] = nude
    check_cancel()
    progress("drawing the inner wear", 0.35)
    log("Drawing the inner wear (Qwen-Image-Edit).")
    inner = backend.instruction_edit(
        pil_to_b64(nude), outfits.adapt(outfits.inner_instruction(settings.get("inner_wear", ""), description), description), edit
    )
    if inner is None:
        notes.append(f"Couldn't draw the inner wear: {getattr(backend, 'last_error', None) or 'the WebUI failed'}. The puppet has the body and the outer clothes only.")
    else:
        edits[outfits.INNER] = inner.convert("RGB").resize(picture.size, Image.Resampling.LANCZOS) if inner.size != picture.size else inner.convert("RGB")
    return edits, notes


def upscale_sheet(backend, images: list[Image.Image], pad: int = 12) -> list[Image.Image] | None:
    """
    images (RGBA) upscaled with the WebUI's upscale model in one go (packed into one sheet), or
    None when it has none. The colour is upscaled by the model, the transparency smoothly.
    """
    if not images or not hasattr(backend, "upscale"):
        return None
    columns = max(1, round(len(images) ** 0.5))
    rows = [images[i:i + columns] for i in range(0, len(images), columns)]
    width = max(sum(im.width + pad for im in row) for row in rows) + pad
    height = sum(max(im.height for im in row) + pad for row in rows) + pad
    sheet = Image.new("RGB", (width, height), (128, 128, 128))
    places = []
    y = pad
    for row in rows:
        x = pad
        for image in row:
            # Transparent pixels take the colour around them, so no grey bleeds into the edges.
            rgba = image.convert("RGBA")
            spread = rgba.copy()
            for _ in range(4):
                spread = Image.alpha_composite(spread.filter(ImageFilter.GaussianBlur(3)), rgba)
            flat = Image.alpha_composite(Image.new("RGBA", rgba.size, (128, 128, 128, 255)), spread).convert("RGB")
            sheet.paste(flat, (x, y))
            places.append((x, y, image))
            x += image.width + pad
        y += max(im.height for im in row) + pad
    big = backend.upscale(pil_to_b64(sheet))
    if big is None:
        return None
    factor = big.width / sheet.width
    result = []
    for x, y, image in places:
        box = (round(x * factor), round(y * factor), round((x + image.width) * factor), round((y + image.height) * factor))
        colour = big.crop(box).convert("RGBA")
        colour.putalpha(image.getchannel("A").resize(colour.size, Image.Resampling.LANCZOS))
        result.append(colour)
    return result


def read_clothing(image: Image.Image, settings: dict, log) -> dict:
    """
    The clothing named in the picture's prompt data (PNG metadata), filled into settings where the
    user left them empty: the inner wear, and the outfit as context for the edits. The whole prompt
    goes to the clothing check too. Returns what was found, for the manifest.
    """
    found: dict = {}
    if settings.get("use_prompt_data", True) is False:
        return found
    prompt = prompt_data.prompt_of(image)
    if not prompt:
        return found
    settings["prompt_data"] = prompt[:2000]
    outer, inner = prompt_data.clothing(prompt)
    if outer:
        found["outfit"] = outer
        settings.setdefault("outfit_from_prompt", outer)
    if inner:
        found["inner_wear"] = inner
        if not (settings.get("inner_wear") or "").strip():
            settings["inner_wear"] = inner
    if found:
        log("From the picture's prompt: " + "; ".join(f"{k.replace('_', ' ')} {v}" for k, v in found.items()) + ".")
    return found


def change_outfit(backend, picture: Image.Image, settings: dict, name: str, log) -> tuple[Image.Image | None, str]:
    """
    The picture with the character in the outfit the user typed (settings outfit_prompt), drawn with
    Qwen-Image-Edit before the split so every layer has it. An outfit that asks for nudity or
    underwear needs what the body layer needs (outfits.check). Returns (picture or None, note).
    """
    outfit = " ".join(str(settings.get("outfit_prompt") or "").split())
    if INSTRUCT not in getattr(backend, "edit_methods", ()):
        return None, "Changing the outfit needs Qwen-Image-Edit on ComfyUI; the picture keeps its clothes."
    if outfits.revealing(outfit):
        allowed, reason = outfits.check({**settings, "outfit_layers": True}, picture, name)
        if not allowed:
            return None, f"The outfit wasn't changed: {reason}"
    elif outfits.blocked_terms(outfit):
        return None, "The outfit wasn't changed: it reads as a child's."
    description = settings.get("character_description", "")
    edit = dataclasses.replace(instruction_edit.EditSettings.from_settings(settings), keep_size=True, photo=False, intensity=1.0)
    log(f"Dressing the character in {outfit} (Qwen-Image-Edit).")
    changed = backend.instruction_edit(pil_to_b64(picture), outfits.adapt(outfits.outfit_instruction(outfit, description), description), edit)
    if changed is None:
        return None, f"Couldn't change the outfit: {getattr(backend, 'last_error', None) or 'the WebUI failed'}. The picture keeps its clothes."
    changed = changed.convert("RGB")
    if changed.size != picture.size:
        changed = changed.resize(picture.size, Image.Resampling.LANCZOS)
    return changed, ""


NEUTRAL_POSE = (
    "Redraw this exact character standing in a neutral A-pose, seen straight from the front, full body from the top of the "
    "head to the feet: standing straight and relaxed, arms straight (not bent at the elbow) and held a little away from the sides with open "
    "relaxed hands and a clear gap between each arm and the body, legs straight and parallel about hip-width apart with a "
    "gap between them all the way down, knees facing forward straight above the ankles (not touching, not bent, not turned "
    "inward), feet flat and pointing forward. Keep the same face, expression, hair, outfit, accessories, "
    "body proportions, colours, line art and art style. Plain white background, the whole character in frame with a little "
    "margin, nothing else in the picture."
)
# The most an arm may bend at the elbow in the A-pose (degrees): a sleeve drawn bent there won't
# line up with the same arm drawn straight in the other clothing edits.
ELBOW_BEND = 18.0
# Portrait shape for the A-pose (width / height): room for the arms and the feet.
NEUTRAL_ASPECT = 0.62
# Asked again when the redraw kept the feet together or crossed (a model's walk often survives it).
FEET_APART = (
    " Her feet are planted apart, about shoulder-width, with a clear gap of background between her legs from the knees "
    "all the way down to the feet; the legs and ankles do not cross or touch."
)
# The narrowest gap between the feet (share of the figure's height) that reads as standing apart.
FEET_GAP = 0.04
ARMS_OUT = (
    " Her arms are angled out from her sides at about thirty degrees, like a mannequin's A-pose, with a wide gap of white "
    "background between each arm (sleeve included) and her body and clothes all the way from the armpit to the hand; "
    "the sleeves do not touch the jacket, the waist or the hips."
)
NEUTRAL_TRIES = 3
POSE_GUIDE = (
    "Picture 2 is an OpenPose stick-figure skeleton. Make the character from picture 1 stand in exactly that skeleton's "
    "pose, limb for limb: the same angle of each arm out from the body, the same straight legs and the same distance "
    "between the feet; draw no skeleton, lines or dots. "
)


def feet_gap(picture: Image.Image) -> float:
    """
    How far apart the feet stand in a full-body picture on white: the widest gap of background
    between them across the bottom of the figure (ankles and feet), as a share of the figure's
    height. Near 0 when the legs touch or cross there.
    """
    import numpy as np

    rgb = np.asarray(picture.convert("RGB")).astype(np.int16)
    figure = rgb.min(axis=2) < 230
    rows = np.nonzero(figure.any(axis=1))[0]
    if len(rows) < 20:
        return 0.0
    top, height = rows[0], rows[-1] - rows[0]
    gaps = []
    for share in (0.86, 0.89, 0.92, 0.95):
        xs = np.nonzero(figure[int(top + share * height)])[0]
        gaps.append(float(np.diff(xs).max()) / height if len(xs) > 1 else 0.0)
    return min(gaps)


# The share of the rows from the armpits to the waist that must show background between each arm
# and the body: a sleeve that touches the body there can't be told from the coat it lies against.
ARMS_APART = 0.6


def arms_apart(picture: Image.Image) -> float:
    """
    How clearly the arms hang apart from the body in a full-body picture on white: the share of the
    rows from the armpits to the waist (0.24 to 0.42 of the figure's height) with background between
    the body and the arm on both sides. Near 0 when the arms lie against the body.
    """
    import numpy as np

    rgb = np.asarray(picture.convert("RGB")).astype(np.int16)
    figure = rgb.min(axis=2) < 230
    rows = np.nonzero(figure.any(axis=1))[0]
    if len(rows) < 20:
        return 0.0
    top, height = rows[0], rows[-1] - rows[0]
    least = max(2, round(0.004 * height))
    band = range(int(top + 0.24 * height), int(top + 0.42 * height))
    apart = 0
    for y in band:
        xs = np.nonzero(figure[y])[0]
        if len(xs) < 2:
            continue
        steps = np.diff(xs)
        gaps = steps[steps > least]
        apart += len(gaps) >= 2
    return apart / max(1, len(band))


def neutral_pose(backend, picture: Image.Image, settings: dict, log) -> tuple[Image.Image | None, str]:
    """
    The character redrawn in the neutral A-pose, full body on white (Qwen-Image-Edit), so every limb
    is apart from the body and the puppet can be posed from it. The picture is first set on a
    portrait canvas with room for the whole body. Returns (picture or None, note).
    """
    if INSTRUCT not in getattr(backend, "edit_methods", ()):
        return None, "The neutral pose needs Qwen-Image-Edit on ComfyUI; the puppet keeps the picture's pose."
    image = picture.convert("RGBA")
    height = max(image.height, round(image.width / NEUTRAL_ASPECT))
    width = max(image.width, round(height * NEUTRAL_ASPECT))
    canvas = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    canvas.alpha_composite(image, ((width - image.width) // 2, (height - image.height) // 2))
    description = settings.get("character_description", "")
    edit = dataclasses.replace(instruction_edit.EditSettings.from_settings(settings), keep_size=True, photo=False, intensity=1.0)
    log("Redrawing the character in a neutral A-pose, full body (Qwen-Image-Edit).")
    best, best_score = None, (-1, -1.0)  # (checks passed, how near each came)
    feet_together = arms_close = False
    guide = pil_to_b64(skeleton.pose_picture(skeleton.a_pose_points(canvas.size), canvas.size)) if getattr(backend, "takes_reference", False) else None
    detect = getattr(backend, "pose_keypoints", None) if guide is not None else None
    for _ in range(NEUTRAL_TRIES):
        # The legs are straightened first, so the 2.5D rig only turns them a little from there; the
        # arms hang clear of the body, so each sleeve is cut whole from the coat it hangs beside.
        instruction = NEUTRAL_POSE + (FEET_APART if feet_together else "") + (ARMS_OUT if arms_close else "")
        if guide is not None:
            # A stick figure in the A-pose to follow (Qwen-Image-Edit takes it as picture 2): words
            # alone leave a blazer's sleeves lying against its sides.
            instruction = POSE_GUIDE + instruction
            posed = backend.instruction_edit(pil_to_b64(canvas.convert("RGB")), outfits.adapt(instruction, description) + outfits._describe(description), edit, reference=guide)
        else:
            posed = backend.instruction_edit(pil_to_b64(canvas.convert("RGB")), outfits.adapt(instruction, description) + outfits._describe(description), edit)
        if posed is None:
            break
        posed = posed.convert("RGB")
        if posed.size != canvas.size:
            posed = posed.resize(canvas.size, Image.Resampling.LANCZOS)
        gap, apart = feet_gap(posed), arms_apart(posed)
        feet_ok, arms_ok = gap >= FEET_GAP, apart >= ARMS_APART
        # The elbows, where a pose detector can find them: Qwen likes to bend a blazer's sleeves.
        bend = skeleton.elbow_bend(skeleton.keypoint_points(detect(pil_to_b64(posed)))) if detect is not None else 0.0
        elbows_ok = bend <= ELBOW_BEND
        score = (feet_ok + arms_ok + elbows_ok, min(gap / FEET_GAP, 1.0) + min(apart / ARMS_APART, 1.0) + min(ELBOW_BEND / max(bend, 1.0), 1.0))
        if score > best_score:
            best, best_score = posed, score
        if feet_ok and arms_ok and elbows_ok:
            break
        if feet_ok and arms_ok:
            log(f"The redraw bent an arm {bend:.0f} degrees at the elbow; asking again.")
            continue
        feet_together |= not feet_ok
        arms_close |= not arms_ok
        log(f"The redraw kept the {'feet together' if not feet_ok else 'arms against the body'}{' and the arms against the body' if not (feet_ok or arms_ok) else ''}; asking again.")
    if best is None:
        return None, f"Couldn't redraw the neutral pose: {getattr(backend, 'last_error', None) or 'the WebUI failed'}. The puppet keeps the picture's pose."
    return best, ""


SLOT_EDITS = (outfits.MID, outfits.OUTER_HALF, outfits.TOP_HALF, outfits.BOTTOM_HALF)


SLEEVE_MAP = "sleeve_map"
# What a segmentation model (SAM 3) is asked to find for the coat; its mask sets the coat's outline.
OUTER_PROMPT = "jacket, coat, blazer, cardigan"
OUTER_FILE = "outer_mask.png"


def outer_mask(backend, picture: Image.Image) -> Image.Image | None:
    """The coat in picture (RGBA) from the backend's segmentation model (SAM 3), mode L, or None."""
    segment = getattr(backend, "segment", None)
    if segment is None:
        return None
    on_white = Image.new("RGB", picture.size, (255, 255, 255))
    rgba = picture.convert("RGBA")
    on_white.paste(rgba, mask=rgba.getchannel("A"))
    b64 = pil_to_b64(on_white)
    mask = next((m for m in (segment(b64, OUTER_PROMPT) for _ in range(SEGMENT_TRIES)) if m is not None), None)
    if mask is None or mask.getbbox() is None:
        return None
    return mask


SLEEVE_PROMPTS = ("right sleeve of jacket", "left sleeve of jacket")
SEGMENT_TRIES = 3


def has_segmentation(backend) -> bool:
    """Whether the backend has a segmentation model (SAM 3) to find the coat and its sleeves."""
    find = getattr(backend, "segment_model", None)
    return bool(find and find())


def sam_sleeve_map(backend, picture: Image.Image, outer: Image.Image) -> Image.Image | None:
    """
    The sleeve map (see skeleton.sleeve_map_masks) from the segmentation model: each sleeve of the
    coat found by name (SAM 3 cuts a whole sleeve from "right sleeve of jacket"; a point on the arm
    instead makes it take that half of the jacket), the rest of the coat cyan. None when it finds no
    sleeve.
    """
    import numpy as np

    on_white = Image.new("RGB", picture.size, (255, 255, 255))
    rgba = picture.convert("RGBA")
    on_white.paste(rgba, mask=rgba.getchannel("A"))
    b64 = pil_to_b64(on_white)
    sleeves = np.zeros((picture.height, picture.width), bool)
    for prompt in SLEEVE_PROMPTS:
        # A remote ComfyUI drops the odd request; a map with one sleeve missing tears that arm.
        mask = next((m for m in (backend.segment(b64, prompt) for _ in range(SEGMENT_TRIES)) if m is not None), None)
        if mask is None:
            return None
        sleeves |= np.asarray(mask.convert("L")) > 127
    if sleeves.sum() < 0.002 * sleeves.size:
        return None
    coat = (np.asarray(outer.convert("L")) > 127) | sleeves
    out = np.full((picture.height, picture.width, 3), 255, np.uint8)
    out[coat & ~sleeves] = (0, 255, 255)
    out[sleeves] = (255, 0, 255)
    return Image.fromarray(out, "RGB")


def sleeves_on_coat(sleeve_map: Image.Image, outer: Image.Image) -> Image.Image:
    """
    sleeve_map (Qwen's paint) trimmed to the coat's outline from the segmentation model, with the
    rest of the coat painted cyan: the sleeves end exactly at the coat's edge, and the coat's body is
    known too (see skeleton.sleeve_map_masks).
    """
    import numpy as np

    rgb = np.asarray(sleeve_map.convert("RGB")).astype(np.int16)
    painted = (rgb[..., 0] > 180) & (rgb[..., 2] > 180) & (rgb[..., 1] < 110)
    coat = np.asarray(outer.convert("L").resize(sleeve_map.size, Image.Resampling.BILINEAR)) > 127
    grown = np.asarray(Image.fromarray((coat * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(5))) > 0
    sleeves = painted & grown
    out = np.full(rgb.shape, 255, np.uint8)
    out[coat & ~sleeves] = (0, 255, 255)
    out[sleeves] = (255, 0, 255)
    return Image.fromarray(out, "RGB")
# Qwen paints a garment's sleeves well on their own (asked for the sleeves and the rest of the
# jacket in two colours, it paints the whole jacket one colour and the skirt the other).
SLEEVE_MAP_INSTRUCTION = (
    "Paint only the two sleeves of her outermost garment (the jacket, coat, blazer or cardigan worn over everything else) "
    "flat solid pure magenta (#FF00FF), each whole from the shoulder seam down to the cuff, with no shading or lines. "
    "Leave the front of that garment, the lapels, her shirt, skirt, hands, face, hair, legs and the white background "
    "exactly as they are. If she wears no such outer garment, change nothing at all."
)


def make_slot_edits(backend, picture: Image.Image, settings: dict, made: dict, log, check_cancel, progress) -> tuple[dict, list[str]]:
    """
    The edits for the clothing slots: the picture without its outermost layer and with it slipped
    halfway off (any character), and, when the inner wear was made (so the clothing check passed),
    the top opened and the skirt lifted. Half off is drawn: cloth that slips or opens changes its
    shape, which fading part of the garment out can't show. Also the sleeve map (SLEEVE_MAP): the
    outer garment's sleeves painted flat, which says where each sleeve is cut from the garment.
    Returns ({key: picture}, notes).
    """
    description = settings.get("character_description", "")
    if settings.get("outfit_from_prompt"):
        description = (description + f". Her outfit: {settings['outfit_from_prompt']}").strip(". ")
    edit = dataclasses.replace(instruction_edit.EditSettings.from_settings(settings), keep_size=True, photo=False, intensity=1.0)
    inner_wear = settings.get("inner_wear", "")
    edits: dict[str, Image.Image] = {}
    notes: list[str] = []

    def run(key, source, instruction, label, fraction):
        check_cancel()
        progress(label, fraction)
        log(f"Drawing {label} (Qwen-Image-Edit).")
        result = backend.instruction_edit(pil_to_b64(source), outfits.adapt(instruction, description), edit)
        if result is None:
            notes.append(f"Couldn't draw {label}: {getattr(backend, 'last_error', None) or 'the WebUI failed'}.")
            return None
        result = result.convert("RGB")
        if result.size != picture.size:
            result = result.resize(picture.size, Image.Resampling.LANCZOS)
        edits[key] = result
        return result

    mid = run(outfits.MID, picture, outfits.mid_instruction(description), "the outfit without its outer layer", 0.36)
    if mid is not None:
        run(outfits.OUTER_HALF, picture, outfits.outer_half_instruction(description), "the outer layer half off", 0.37)
        if not has_segmentation(backend):
            # Without a segmentation model Qwen paints the sleeves for the map.
            run(SLEEVE_MAP, picture, SLEEVE_MAP_INSTRUCTION, "the sleeve map", 0.375)
    if outfits.INNER in made:
        base = mid if mid is not None else picture
        run(outfits.TOP_HALF, base, outfits.top_half_instruction(inner_wear, description), "the top opened", 0.38)
        run(outfits.BOTTOM_HALF, base, outfits.bottom_half_instruction(inner_wear, description), "the skirt lifted", 0.39)
    return edits, notes


def to_canvas(picture: Image.Image, box: tuple[int, int, int, int], size: tuple[int, int]) -> Image.Image:
    """picture scaled into box on a transparent canvas of size (See-through's square canvas)."""
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    scaled = picture.convert("RGBA").resize((box[2] - box[0], box[3] - box[1]), Image.Resampling.LANCZOS)
    canvas.paste(scaled, box[:2])
    return canvas


def contact_sheet(parts: list[layers.Part], tile: int = 256, columns: int = 6) -> Image.Image:
    """Every layer on a checkerboard, labelled, for a quick look."""
    rows = max(1, -(-len(parts) // columns))
    label = 22
    sheet = Image.new("RGB", (columns * tile, rows * (tile + label)), (245, 245, 245))
    checker = Image.new("RGB", (tile, tile), (255, 255, 255))
    draw_checker = ImageDraw.Draw(checker)
    for y in range(0, tile, 16):
        for x in range(0, tile, 16):
            if (x // 16 + y // 16) % 2:
                draw_checker.rectangle((x, y, x + 15, y + 15), fill=(225, 225, 225))
    draw = ImageDraw.Draw(sheet)
    for index, part in enumerate(parts):
        x, y = index % columns * tile, index // columns * (tile + label)
        cell = checker.copy()
        image = part.image.convert("RGBA")
        bbox = image.getchannel("A").getbbox()
        if bbox:
            image = image.crop(bbox)
            image.thumbnail((tile - 8, tile - 8))
            cell.paste(image, ((tile - image.width) // 2, (tile - image.height) // 2), image)
        sheet.paste(cell, (x, y))
        draw.text((x + 4, y + tile + 4), part.tag[:34], fill=(30, 30, 30))
    return sheet


README = """AutoExpress Live2D model kit: {name}
==========================================

Play it now (no Cubism Editor)
------------------------------
puppet/{name}/ is a ready-to-play puppet made from these layers: blinking, breathing, head turns,
hair sway, the 28 expressions and their motions. In SillyTavern, with the AutoExpress extension and
the Live2D extension both installed:
1. Copy puppet/{name} into SillyTavern's data/<user>/assets/live2d (or the character's live2d folder).
2. In the Live2D extension, pick "{name}.puppet.model.json" for the character. The emotions are
   already mapped. {name}_puppet.zip next to the kit holds the same folder.
To try it in a browser, serve puppet/{name} with any web server and open preview.html.

What's here
-----------
{name}.psd             The character split into Live2D parts, ready to import into Live2D Cubism Editor.
                       One group per part (Front hair, Face, Eye L, Eye R, Mouth, Body, Back hair ...),
                       hidden areas painted in. L and R are the character's own left and right.
                       Hidden layers: {switches}
{name}_seethrough.psd  The same layers, flat and named the way See-through names them. Tools that rig
                       See-through output automatically take it as is: StretchyStudio
                       (https://editor.stretchy.studio) and Anime2.5DRig.
layers/                Every layer as a PNG, at its place on the canvas.
preview.png            The layers put back together. sheet.png shows every layer on its own.
runtime/               Expressions and motions for the 28 SillyTavern emotions, and the settings file
                       the SillyTavern Live2D extension reads.
puppet/                The ready-to-play puppet (see above).
manifest.json          What went where, and the checks of the picture.

Make the Live2D model (Live2D Cubism Editor)
---------------------------------------------
1. File > Open: {name}.psd. Every layer becomes an art mesh, every group a part.
2. Use Modeling > Automatic mesh generation, then add deformers and parameters. Use Live2D's standard
   parameter ids (ParamAngleX/Y/Z, ParamEyeLOpen, ParamEyeROpen, ParamEyeLSmile, ParamBrowLY,
   ParamBrowLAngle, ParamMouthForm, ParamMouthOpenY, ParamCheek, ParamBodyAngleX, ParamBreath ...):
   the expressions in runtime/ drive those. Cubism's "Automatic generation of facial motion" and its
   templates speed this up.
3. Blink and talk: key the hidden "Eye L closed" / "Eye R closed" layers to 1 opacity at ParamEyeLOpen /
   ParamEyeROpen = 0, and "Mouth open" to ParamMouthOpenY = 1 (0 at the other end).
4. File > Export For Runtime > Export as moc3 file. You get a folder with <model>.model3.json.

Use it in SillyTavern (Live2D extension)
----------------------------------------
5. Copy everything in runtime/ into that exported folder, then add the emotions to the model with:
       python -m autoexpress_core.live2d attach <exported model folder>
   It registers the 28 expressions and motions in the .model3.json (keeping a .bak copy) and rewrites
   sillytavern_settings.json for the parameters your model actually has.
6. Put the folder in SillyTavern's data/<user>/assets/live2d (or the character's live2d folder), pick it
   for the character in the Live2D extension, and each emotion the classifier detects plays its
   expression and a short reaction; the idle motion breathes in between.
"""


def build_kit(
    backend,
    images: list[Image.Image],
    output_dir,
    name: str = "character",
    settings: dict | None = None,
    character_lora: dict | None = None,
    log: Callable[[str], None] = lambda _: None,
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[str, float], None] = lambda step, fraction: None,
) -> KitResult:
    """
    Build a Live2D model kit from one or more pictures of a character.

    settings: base_index (which picture, default the best), remove_background (None = only busy ones),
      variants ("auto", "inpaint", "instruct" or "none"), split settings (resolution, steps, seed,
      low_vram), the usual face inpainting / instruction edit settings (ad_*, edit_*), and for
      swappable clothing outfit_layers, adult_confirmed, character_description, inner_wear (outfits.py),
      outfit_prompt (dress the character in this before the split) and use_prompt_data (default on:
      read the clothing from the picture's prompt metadata, see prompt_data.py).
    character_lora: {"entry": LoRA entry, "installed_name": name on the WebUI} from character_lora, or None.
    """
    settings = dict(settings or {})
    if not images:
        raise ValueError("No pictures.")
    ready, message = backend.check_ready(DECOMPOSE)
    if not ready:
        raise backend.last_error or RuntimeError(message)

    output_dir = pathlib.Path(output_dir)
    folder = output_dir / name
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)

    def check_cancel():
        if cancelled():
            raise KitCancelled()

    # 1. Pick the picture.
    progress("checking pictures", 0.02)
    reports = guidance.rank_images(images)
    base_index = settings.get("base_index")
    if not isinstance(base_index, int) or not 0 <= base_index < len(images):
        base_index = reports[0][0]
    report = next(r for i, r in reports if i == base_index)
    log(f"Using picture {base_index + 1} of {len(images)} (score {report['score']}).")

    # 2. Prepare it.
    clothing_info = read_clothing(images[base_index], settings, log)
    original = images[base_index]
    notes = []
    if (settings.get("outfit_prompt") or "").strip():
        # Before the background removal and upscaling, so the new outfit gets both.
        check_cancel()
        progress("changing the outfit", 0.03)
        changed, note = change_outfit(backend, original, settings, name, log)
        if changed is not None:
            original = changed
            clothing_info["outfit_changed"] = True
            settings["outfit_from_prompt"] = " ".join(settings["outfit_prompt"].split())[:300]
        if note:
            notes.append(note)
    posed = False
    if settings.get("neutral_pose", True) is not False:
        # Every edit after this one, and the split, see the character in the A-pose.
        check_cancel()
        progress("redrawing the neutral pose", 0.04)
        redrawn, note = neutral_pose(backend, original, settings, log)
        if redrawn is not None:
            original = redrawn
            posed = True
            redrawn.save(folder / "neutral_pose.png")
        if note:
            notes.append(note)
    split = layers.SplitSettings.from_settings(settings)
    # The redrawn picture is always cut out: a clean edge around the whole character.
    picture = prepare_picture(original, True if posed else settings.get("remove_background"), log, backend, split.resolution)
    picture.save(folder / "input.png")
    check_cancel()
    # The joints from a pose detector (DWPose) where the WebUI has one, in the picture's pixels: the
    # puppet's skeleton sits on the drawn limbs.
    people = None
    detect = getattr(backend, "pose_keypoints", None)
    if posed and detect is not None:
        progress("finding the joints", 0.045)
        people = detect(pil_to_b64(picture))

    # 3. Eyes closed / mouth open.
    lora_installed = bool(character_lora and character_lora.get("installed_name"))
    requested = settings.get("variants", AUTO)
    method = None if requested == "none" else variant_method(backend, requested, lora_installed)
    lora_prompt = ""
    if character_lora and character_lora.get("entry"):
        from .character_lora import lora_tag

        if lora_installed:
            lora_prompt = lora_tag(character_lora["entry"], character_lora["installed_name"])
    variants: dict[str, Image.Image] = {}
    if method:
        wanted = (EYES_CLOSED, MOUTH_OPEN) + (EXPRESSION_ART if settings.get("expression_art", True) is not False else ())
        for index, which in enumerate(wanted):
            check_cancel()
            progress(f"drawing {which.replace('_', ' ')}", 0.05 + 0.25 * index / len(wanted))
            log(f"Drawing the character with {which.replace('_', ' ')} ({'face inpainting' if method == INPAINT else 'Qwen-Image-Edit'}).")
            result = make_variant(backend, picture, which, method, settings, lora_prompt if method == INPAINT else "")
            if result is None:
                error = getattr(backend, "last_error", None)
                notes.append(f"Couldn't draw {which.replace('_', ' ')}: {error or 'the WebUI failed'}. The kit has no {which.replace('_', ' ')} layer.")
                log(notes[-1])
                continue
            result.save(folder / f"{which}.png")
            variants[which] = result
    else:
        notes.append("No eyes-closed or mouth-open art was made (turned off, or the WebUI can't edit pictures).")

    # Swappable clothing: the body under the clothes and in inner wear.
    outfit_edits: dict[str, Image.Image] = {}
    outfit_state = {"requested": bool(settings.get("outfit_layers")), "made": []}
    if settings.get("outfit_layers"):
        allowed, reason = outfits.check(settings, picture, name)
        if allowed:
            outfit_edits, outfit_notes = make_outfit_edits(backend, picture, settings, log, check_cancel, progress)
            notes.extend(outfit_notes)
        else:
            notes.append(reason)
            outfit_state["refused"] = reason
    if settings.get("clothing_slots", True) is not False and INSTRUCT in getattr(backend, "edit_methods", ()):
        slot_edits, slot_notes = make_slot_edits(backend, picture, settings, outfit_edits, log, check_cancel, progress)
        outfit_edits.update(slot_edits)
        notes.extend(slot_notes)
    for which, image in outfit_edits.items():
        image.save(folder / f"{which}.png")
    # The coat's outline and its sleeves from a segmentation model (SAM 3) where the WebUI has one.
    outer = sam_map = None
    if outfits.MID in outfit_edits:
        check_cancel()
        progress("finding the coat", 0.395)
        outer = outer_mask(backend, picture)
        if outer is not None:
            outer.save(folder / OUTER_FILE)
            progress("finding the sleeves", 0.397)
            sam_map = sam_sleeve_map(backend, picture, outer)
            if sam_map is not None:
                sam_map.save(folder / f"{SLEEVE_MAP}.png")
                outfit_edits[SLEEVE_MAP] = sam_map

    # 4. Split.
    check_cancel()
    progress("splitting layers", 0.4)
    log(f"Splitting the character into layers with See-through at {split.resolution} px. This takes a few minutes.")
    result = backend.decompose_layers(pil_to_b64(picture), split)
    if result is None:
        raise backend.last_error or RuntimeError("The layer split failed.")
    parts, canvas_size = result
    check_cancel()
    # See-through's depth of every layer, hidden parts too: the puppet's turns get real parallax.
    depth_maps = layers.depth_canvases(parts, canvas_size)
    parts = layers.solidify_parts(parts)
    box = layers.square_placement(picture.size, canvas_size[0])
    base_canvas = to_canvas(picture, box, canvas_size)
    parts = layers.match_picture(parts, Image.alpha_composite(Image.new("RGBA", canvas_size, (255, 255, 255, 255)), base_canvas).convert("RGB"), subject=base_canvas.getchannel("A"))
    parts = layers.settle_lash_strays(parts, canvas_size)
    parts = layers.trim_neck(parts, canvas_size)
    underlay = layers.hair_underlay(parts, canvas_size)

    # 5. Extra art, crop to the picture, write.
    progress("writing the kit", 0.9)
    # Qwen hands its edits back a little zoomed and shifted: line each one up with the picture first.
    face_box = layers._alpha_union(parts, canvas_size, ("face",)).getbbox()
    variants = {which: layers.align_edit(base_canvas, to_canvas(image, box, canvas_size), face_box) for which, image in variants.items()}
    # The segmentation model's masks are of the picture itself (not an edit): they go on the canvas as they are.
    exact = outfit_edits.pop(SLEEVE_MAP, None) if sam_map is not None else None
    outfit_edits = {which: layers.align_edit(base_canvas, to_canvas(image, box, canvas_size), face_box) for which, image in outfit_edits.items()}
    sleeve_map = outfit_edits.pop(SLEEVE_MAP, None)
    outer_canvas = to_canvas(outer.convert("RGB"), box, canvas_size).convert("L") if outer is not None else None
    if exact is not None:
        sleeve_map = to_canvas(exact, box, canvas_size).convert("RGB")
    elif sleeve_map is not None and outer_canvas is not None:
        sleeve_map = sleeves_on_coat(sleeve_map, outer_canvas)
    overlays = layers.edit_overlays(
        parts,
        base_canvas,
        variants.get(EYES_CLOSED),
        variants.get(MOUTH_OPEN),
        *(variants.get(which) for which in EXPRESSION_ART),
    )
    extra = outfits.outfit_parts(
        parts,
        canvas_size,
        outfit_edits[outfits.NUDE] if outfits.NUDE in outfit_edits else None,
        outfit_edits[outfits.INNER] if outfits.INNER in outfit_edits else None,
    )
    outfit_state["made"] = [part.tag for part in extra]
    if outfit_edits and not extra:
        notes.append("The body edit couldn't be cut out to a layer; the clothes stay one layer.")
    slot_edits = {key: image for key, image in outfit_edits.items() if key in SLOT_EDITS}
    if slot_edits:
        white = Image.alpha_composite(Image.new("RGBA", canvas_size, (255, 255, 255, 255)), base_canvas)
        made = {p.tag for p in extra}
        parts = outfits.slot_parts(
            parts,
            canvas_size,
            white,
            slot_edits,
            nude=outfit_edits[outfits.NUDE] if "nude body" in made else None,
            inner=outfit_edits[outfits.INNER] if made & {"inner wear", "inner top", "inner bottom"} else None,
            outer=outer_canvas,
        )
        outfit_state["slots"] = sorted({p.tag for p in parts} & {"outer wear", "outer wear half", "topwear half", "bottomwear half"})
    parts = layers.drop_specks(parts + extra) + ([underlay] if underlay else [])
    for which, wanted in ((EYES_CLOSED, "closed"), (MOUTH_OPEN, "Mouth open")):
        if which in variants and not any(wanted in overlay.name for overlay in overlays):
            notes.append(f"The {which.replace('_', ' ')} edit didn't change the {'eyes' if which == EYES_CLOSED else 'mouth'} enough to make a layer from it.")
    parts = layers.crop_parts(parts, box)
    depth_maps = {tag: depth.crop(box) for tag, depth in depth_maps.items()}
    if sleeve_map is not None:
        sleeve_map = sleeve_map.convert("RGB").crop(box)
        if skeleton.sleeve_map_masks(sleeve_map) is None:
            sleeve_map = None  # no outer garment painted: the sleeves are cut along the drawing's lines
        else:
            sleeve_map.save(folder / puppet.SLEEVE_FILE)
    overlays = [dataclasses.replace(o, left=o.left - box[0], top=o.top - box[1]) for o in overlays]
    size = (box[2] - box[0], box[3] - box[1])

    tree, manifest = layers.build_tree(parts, overlays)
    composite = psd.flatten(tree, size)
    psd.write_psd(folder / f"{name}.psd", tree, size, composite)
    flat_nodes = [psd.Layer(part.tag, part.image, part.left, part.top) for part in sorted(parts, key=lambda p: p.depth)]
    psd.write_psd(folder / f"{name}_seethrough.psd", flat_nodes, size, composite)

    (folder / "layers").mkdir()
    for group in tree:
        for layer in group.children:
            canvas = Image.new("RGBA", size, (0, 0, 0, 0))
            canvas.paste(layer.image.convert("RGBA"), (layer.left, layer.top))
            safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in f"{group.name} - {layer.name}")
            canvas.save(folder / "layers" / f"{safe}.png")
    if depth_maps:
        puppet.save_depth(folder / "depth", depth_maps)
    composite.save(folder / "preview.png")
    sheet_parts = parts + [layers.Part(o.name, o.image, o.left, o.top) for o in overlays]
    contact_sheet(sheet_parts).save(folder / "sheet.jpg", quality=90)

    runtime = folder / "runtime"
    written = model_files.write_model_files(runtime)
    (runtime / model_files.SETTINGS_FILE).write_text(
        json.dumps(model_files.sillytavern_settings(motions=set(written["Motions"])), indent=2) + "\n", encoding="utf-8"
    )

    # The joints in the kit's pixels: the skeleton sits on the drawn limbs instead of anime proportions.
    if people:
        sx, sy = size[0] / picture.width, size[1] / picture.height
        for person in people:
            flat = person.get("pose_keypoints_2d") or []
            person["pose_keypoints_2d"] = [round(v * (sx if i % 3 == 0 else sy if i % 3 == 1 else 1), 2) for i, v in enumerate(flat)]
        (folder / puppet.POSE_FILE).write_text(json.dumps({"people": people}, indent=1) + "\n", encoding="utf-8")
    puppet.build_puppet(
        tree,
        manifest,
        size,
        folder / "puppet" / name,
        name,
        parts,
        enhance=lambda images: upscale_sheet(backend, images),
        neutral_pose=posed,
        depth_maps=depth_maps,
        people=people,
        sleeve_map=sleeve_map,
    )

    switches = ", ".join(o.name for o in overlays) or "none"
    (folder / "README.txt").write_text(README.format(name=name, switches=switches), encoding="utf-8")
    manifest.update(
        {
            "name": name,
            "canvas": list(size),
            "picture": {"index": base_index, "report": report, "all": [{"index": i, "score": r["score"]} for i, r in reports]},
            "variants": {"method": method, "made": sorted(variants)},
            "character_lora": (character_lora or {}).get("entry"),
            "split": dataclasses.asdict(split),
            "outfits": outfit_state,
            "neutral_pose": posed,
            "clothing": clothing_info,
            "notes": notes,
        }
    )
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    zip_path = output_dir / f"{name}_live2d_kit.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                archive.write(path, f"{name}/{path.relative_to(folder)}")
    puppet_zip = output_dir / f"{name}_puppet.zip"
    with zipfile.ZipFile(puppet_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((folder / "puppet").rglob("*")):
            if path.is_file():
                archive.write(path, str(path.relative_to(folder / "puppet")))
    progress("done", 1.0)
    log(f"Live2D kit ready: {zip_path}")
    return KitResult(folder, zip_path, manifest, puppet_zip)
