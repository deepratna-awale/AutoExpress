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
import pathlib
import shutil
import zipfile
from typing import Callable

from PIL import Image, ImageDraw

from .. import instruction_edit
from ..images import pil_to_b64
from ..payload import build_expression_payload
from . import DECOMPOSE, guidance, layers, model_files, outfits, psd, puppet

MAX_SIDE = 2048
EYES_CLOSED = "eyes_closed"
MOUTH_OPEN = "mouth_open"

KEEP = "Keep everything else exactly the same: face shape, eyebrows, hair, outfit, pose, colors, line art, art style, background and framing."
INSTRUCTIONS = {
    EYES_CLOSED: "Close both eyes gently, like a calm blink: relaxed closed eyelids drawn as soft curved lash lines, no other change to the face. " + KEEP,
    MOUTH_OPEN: "Open the mouth a little, as if saying \"ah\": a small relaxed open mouth showing a bit of the inside, no other change to the face. " + KEEP,
}
PROMPTS = {
    EYES_CLOSED: "closed eyes, calm expression, closed mouth",
    MOUTH_OPEN: "open mouth, :o, neutral expression, eyes open",
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
                log("Removing the background.")
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
      swappable clothing outfit_layers, adult_confirmed, character_description, inner_wear (outfits.py).
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
    split = layers.SplitSettings.from_settings(settings)
    picture = prepare_picture(images[base_index], settings.get("remove_background"), log, backend, split.resolution)
    picture.save(folder / "input.png")
    check_cancel()

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
    notes = []
    if method:
        for index, which in enumerate((EYES_CLOSED, MOUTH_OPEN)):
            check_cancel()
            progress(f"drawing {which.replace('_', ' ')}", 0.05 + 0.15 * index)
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
        for which, image in outfit_edits.items():
            image.save(folder / f"{which}.png")

    # 4. Split.
    check_cancel()
    progress("splitting layers", 0.4)
    log(f"Splitting the character into layers with See-through at {split.resolution} px. This takes a few minutes.")
    result = backend.decompose_layers(pil_to_b64(picture), split)
    if result is None:
        raise backend.last_error or RuntimeError("The layer split failed.")
    parts, canvas_size = result
    check_cancel()
    parts = layers.solidify_parts(parts)
    box = layers.square_placement(picture.size, canvas_size[0])
    base_canvas = to_canvas(picture, box, canvas_size)
    parts = layers.match_picture(parts, Image.alpha_composite(Image.new("RGBA", canvas_size, (255, 255, 255, 255)), base_canvas).convert("RGB"))
    underlay = layers.hair_underlay(parts, canvas_size)

    # 5. Extra art, crop to the picture, write.
    progress("writing the kit", 0.9)
    overlays = layers.edit_overlays(
        parts,
        base_canvas,
        to_canvas(variants[EYES_CLOSED], box, canvas_size) if EYES_CLOSED in variants else None,
        to_canvas(variants[MOUTH_OPEN], box, canvas_size) if MOUTH_OPEN in variants else None,
    )
    extra = outfits.outfit_parts(
        parts,
        canvas_size,
        to_canvas(outfit_edits[outfits.NUDE], box, canvas_size) if outfits.NUDE in outfit_edits else None,
        to_canvas(outfit_edits[outfits.INNER], box, canvas_size) if outfits.INNER in outfit_edits else None,
    )
    outfit_state["made"] = [part.tag for part in extra]
    if outfit_edits and not extra:
        notes.append("The body edit couldn't be cut out to a layer; the clothes stay one layer.")
    parts = parts + extra + ([underlay] if underlay else [])
    for which, wanted in ((EYES_CLOSED, "closed"), (MOUTH_OPEN, "Mouth open")):
        if which in variants and not any(wanted in overlay.name for overlay in overlays):
            notes.append(f"The {which.replace('_', ' ')} edit didn't change the {'eyes' if which == EYES_CLOSED else 'mouth'} enough to make a layer from it.")
    parts = layers.crop_parts(parts, box)
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
    composite.save(folder / "preview.png")
    sheet_parts = parts + [layers.Part(o.name, o.image, o.left, o.top) for o in overlays]
    contact_sheet(sheet_parts).save(folder / "sheet.jpg", quality=90)

    runtime = folder / "runtime"
    written = model_files.write_model_files(runtime)
    (runtime / model_files.SETTINGS_FILE).write_text(
        json.dumps(model_files.sillytavern_settings(motions=set(written["Motions"])), indent=2) + "\n", encoding="utf-8"
    )

    puppet.build_puppet(tree, manifest, size, folder / "puppet" / name, name, parts)

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
