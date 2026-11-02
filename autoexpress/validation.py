"""Validation of what the browser sends, so bad input fails fast with a clear message."""

import base64
import binascii
import io
import pathlib
import re

from PIL import Image, UnidentifiedImageError

# field: (type, min, max)
NUMERIC_FIELDS = {
    "ad_steps": (int, 1, 150),
    "ad_cfg_scale": (float, 0.0, 30.0),
    "ad_denoising_strength": (float, 0.0, 1.0),
    "ad_clip_skip": (int, 1, 12),
    "ad_inpaint_width": (int, 64, 4096),
    "ad_inpaint_height": (int, 64, 4096),
    "seed": (int, -1, 2**63 - 1),
    "edit_steps": (int, 1, 100),
    "edit_cfg_scale": (float, 0.0, 20.0),
    "expression_intensity": (float, 0.0, 1.0),
}
TEXT_FIELDS = ("ad_prompt", "ad_negative_prompt", "ad_checkpoint", "ad_sampler", "ad_scheduler", "edit_instruction", "edit_model")
# field: allowed values
CHOICE_FIELDS = {"edit_style": ("illustration", "photo")}
METHODS = ("inpaint", "instruct")
MAX_TEXT = 10_000
MAX_LORAS = 20
# animation field: (type, min, max)
ANIMATION_NUMBERS = {"frames": (int, 17, 121), "fps": (int, 1, 60), "resolution": (int, 256, 1080), "steps": (int, 1, 60), "cfg": (float, 0.0, 15.0), "seed": (int, -1, 2**63 - 1)}
ANIMATION_FORMATS = ("webp", "apng", "gif")
IDLE_SOURCES = ("card", "web", "llm", "none")


class ValidationError(ValueError):
    """Bad request input. errors maps field name to message."""

    code = "invalid_request"

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))

    def to_dict(self) -> dict:
        return {"code": self.code, "message": str(self), "fields": self.errors}


def safe_dir_name(name: str | None, default: str = "New_Character") -> str:
    """
    A single folder name from user input: no path separators, no '..', no control
    characters. Unicode letters (e.g. Japanese character names) are kept.
    """
    name = (name or "").strip()
    name = name.rsplit(".", 1)[0] if re.search(r"\.[A-Za-z0-9]{1,4}$", name) else name
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", name)
    name = re.sub(r"\.{2,}", "_", name).strip(" ._")
    return name[:100] or default


def resolve_inside(root: pathlib.Path, *parts: str) -> pathlib.Path | None:
    """root/parts, or None when the result would escape root (path traversal)."""
    root = root.resolve()
    target = root.joinpath(*parts).resolve()
    return target if target == root or root in target.parents else None


def decode_image(data: str, max_pixels: int) -> Image.Image:
    """Check a base64 / data URI image decodes, is a real image and is not huge."""
    if not isinstance(data, str) or not data.strip():
        raise ValidationError({"init_images": "An input image is required."})
    raw = data.split(",", 1)[1] if data.startswith("data:") else data
    try:
        blob = base64.b64decode(raw, validate=False)
        image = Image.open(io.BytesIO(blob))
        width, height = image.size
        if width * height > max_pixels:
            raise ValidationError({"init_images": f"Image is {width}x{height}, larger than the {max_pixels} pixel limit."})
        image.load()
    except (binascii.Error, UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise ValidationError({"init_images": f"Not a readable image: {e}"}) from e
    return image


def validate_generate(data, max_pixels: int) -> dict:
    """
    Check and normalise a /generate body.

    Returns:
        dict: image (base64 str), output_name, loras (list of (name, weight)),
              settings (payload overrides), expressions (list or None), wait (bool),
              method ("inpaint", "instruct" or None for the family's default),
              remove_background (bool), animation (dict of animation settings, or None for stills only).
              settings["pose"] is True when sprite poses were asked for.
    """
    if not isinstance(data, dict):
        raise ValidationError({"body": "Expected a JSON object."})

    errors: dict[str, str] = {}
    settings: dict = {}

    image = data.get("init_images")
    if isinstance(image, list):
        image = image[0] if image else None
    try:
        decode_image(image, max_pixels)
    except ValidationError as e:
        errors.update(e.errors)

    for key, (cast, low, high) in NUMERIC_FIELDS.items():
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            number = cast(float(value)) if cast is int else cast(value)
        except (TypeError, ValueError):
            errors[key] = f"must be a number, got {value!r}"
            continue
        if not low <= number <= high:
            errors[key] = f"must be between {low} and {high}"
            continue
        settings[key] = number

    for key in TEXT_FIELDS:
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            errors[key] = "must be text"
        elif len(value) > MAX_TEXT:
            errors[key] = f"is longer than {MAX_TEXT} characters"
        else:
            settings[key] = value

    loras = []
    raw_loras = data.get("loras") or []
    if not isinstance(raw_loras, list) or len(raw_loras) > MAX_LORAS:
        errors["loras"] = f"must be a list of at most {MAX_LORAS} items"
    else:
        for item in raw_loras:
            name = (item or {}).get("lora_name") if isinstance(item, dict) else None
            if not name or not isinstance(name, str) or re.search(r"[<>:]", name):
                errors["loras"] = f"invalid lora name {name!r}"
                break
            try:
                weight = float((item or {}).get("lora_strength", 1.0) or 1.0)
            except (TypeError, ValueError):
                errors["loras"] = f"invalid strength for {name!r}"
                break
            if not -5 <= weight <= 5:
                errors["loras"] = f"strength for {name!r} must be between -5 and 5"
                break
            loras.append((name.strip(), weight))

    expressions = data.get("expressions")
    if expressions is not None and (
        not isinstance(expressions, list) or not all(isinstance(e, str) for e in expressions)
    ):
        errors["expressions"] = "must be a list of expression names"

    for key, allowed in CHOICE_FIELDS.items():
        value = data.get(key)
        if value in (None, "", "auto"):
            continue
        if value not in allowed:
            errors[key] = f"must be one of {', '.join(allowed)}"
        else:
            settings[key] = value

    # None: the model family's default method, picked once the family is known.
    method = data.get("method") or None
    if method is not None and method not in METHODS:
        errors["method"] = f"must be one of {', '.join(METHODS)}"

    remove_background = data.get("remove_background", False)
    if not isinstance(remove_background, bool):
        errors["remove_background"] = "must be true or false"

    pose = data.get("pose", False)
    if not isinstance(pose, bool):
        errors["pose"] = "must be true or false"
    elif pose:
        settings["pose"] = True

    animate = data.get("animate", False)
    animation = None
    if not isinstance(animate, bool):
        errors["animate"] = "must be true or false"
    elif animate:
        try:
            animation = validate_animation(data.get("animation"))
        except ValidationError as e:
            errors.update(e.errors)

    if errors:
        raise ValidationError(errors)

    return {
        "animation": animation,
        "image": image,
        "output_name": safe_dir_name(data.get("output_dir")),
        "loras": loras,
        "settings": settings,
        "expressions": expressions or None,
        "wait": data.get("wait", True) is not False,
        "method": method,
        "remove_background": remove_background,
    }


def validate_animation(data) -> dict:
    """
    Check the "animation" object of /generate and /animate: frames, fps, resolution, steps, cfg, seed,
    formats (webp, apng, gif), idle_motion (text), idle_source (card, web, llm, none), extra (text), loop.
    """
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValidationError({"animation": "must be an object"})
    errors: dict[str, str] = {}
    result: dict = {}
    for key, (cast, low, high) in ANIMATION_NUMBERS.items():
        value = data.get(key)
        if value is None or value == "":
            continue
        try:
            number = cast(float(value)) if cast is int else cast(value)
        except (TypeError, ValueError):
            errors[f"animation.{key}"] = f"must be a number, got {value!r}"
            continue
        if not low <= number <= high:
            errors[f"animation.{key}"] = f"must be between {low} and {high}"
            continue
        result[key] = number
    formats = data.get("formats")
    if formats is not None:
        if isinstance(formats, str):
            formats = [formats]
        if not isinstance(formats, list) or not formats or not all(f in ANIMATION_FORMATS for f in formats):
            errors["animation.formats"] = f"must be a list of {', '.join(ANIMATION_FORMATS)}"
        else:
            result["formats"] = list(dict.fromkeys(formats))
    for key in ("idle_motion", "extra"):
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or len(value) > 2000:
            errors[f"animation.{key}"] = "must be text of at most 2000 characters"
        else:
            result[key] = value.strip()
    source = data.get("idle_source") or "card"
    if source not in IDLE_SOURCES:
        errors["animation.idle_source"] = f"must be one of {', '.join(IDLE_SOURCES)}"
    result["idle_source"] = source
    for key in ("loop", "lightning"):
        if key in data and data[key] is not None and not isinstance(data[key], bool):
            errors[f"animation.{key}"] = "must be true or false"
        elif key in data and data[key] is not None:
            result[key] = data[key]
    if errors:
        raise ValidationError(errors)
    return result


MAX_LIVE2D_IMAGES = 8
LIVE2D_VARIANTS = ("auto", "instruct", "inpaint", "none")


def validate_live2d(data, max_pixels: int) -> dict:
    """
    Check and normalise a /live2d body.

    Returns:
        dict: images (list of base64 str), name (folder-safe), output_name, settings (split, variant and
              face edit settings), character_lora (LoRA entry or None), wait (bool).
    """
    if not isinstance(data, dict):
        raise ValidationError({"body": "Expected a JSON object."})
    errors: dict[str, str] = {}
    images = data.get("images")
    if isinstance(images, str):
        images = [images]
    if not isinstance(images, list) or not images:
        errors["images"] = "Send at least one picture of the character."
        images = []
    elif len(images) > MAX_LIVE2D_IMAGES:
        errors["images"] = f"Send at most {MAX_LIVE2D_IMAGES} pictures."
    else:
        for index, image in enumerate(images):
            try:
                decode_image(image, max_pixels)
            except ValidationError as e:
                errors[f"images[{index}]"] = next(iter(e.errors.values()))

    raw = data.get("settings") or {}
    if not isinstance(raw, dict):
        errors["settings"] = "must be an object"
        raw = {}
    settings: dict = {}
    for key, (cast, low, high) in {"resolution": (int, 768, 2048), "steps": (int, 8, 60), "seed": (int, 0, 2**32 - 1), "base_index": (int, 0, MAX_LIVE2D_IMAGES - 1)}.items():
        if raw.get(key) in (None, ""):
            continue
        try:
            number = cast(float(raw[key]))
        except (TypeError, ValueError):
            errors[key] = f"must be a number, got {raw[key]!r}"
            continue
        if not low <= number <= high:
            errors[key] = f"must be between {low} and {high}"
        else:
            settings[key] = number
    variants = raw.get("variants", "auto")
    if variants not in LIVE2D_VARIANTS:
        errors["variants"] = f"must be one of {', '.join(LIVE2D_VARIANTS)}"
    settings["variants"] = variants
    settings["low_vram"] = bool(raw.get("low_vram", False))
    # Swappable clothing (autoexpress_core.live2d.outfits): only with an explicit adult confirmation.
    settings["outfit_layers"] = raw.get("outfit_layers") is True
    settings["adult_confirmed"] = raw.get("adult_confirmed") is True
    if "safe_mode" in raw:
        settings["safe_mode"] = raw.get("safe_mode") is not False
    if "clothing_slots" in raw:
        settings["clothing_slots"] = raw.get("clothing_slots") is not False
    if "use_prompt_data" in raw:
        settings["use_prompt_data"] = raw.get("use_prompt_data") is not False
    for key in ("character_description", "inner_wear", "outfit_prompt"):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, str) or len(value) > 2000:
            errors[key] = "must be text of at most 2000 characters"
        else:
            settings[key] = value
    if raw.get("remove_background") is not None:
        settings["remove_background"] = bool(raw["remove_background"])
    for key, (cast, low, high) in NUMERIC_FIELDS.items():
        if raw.get(key) in (None, "") or key == "seed":
            continue
        try:
            number = cast(float(raw[key])) if cast is int else cast(raw[key])
        except (TypeError, ValueError):
            errors[key] = f"must be a number, got {raw[key]!r}"
            continue
        if low <= number <= high:
            settings[key] = number
    for key in TEXT_FIELDS:
        value = raw.get(key)
        if isinstance(value, str) and len(value) <= MAX_TEXT:
            settings[key] = value

    lora = data.get("character_lora")
    if lora is not None:
        entry = lora.get("entry") if isinstance(lora, dict) else None
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            errors["character_lora"] = "must be {entry, installed_name} from /live2d/character-lora"
            lora = None
        else:
            installed = lora.get("installed_name")
            lora = {"entry": entry, "installed_name": installed if isinstance(installed, str) and installed else None}

    if errors:
        raise ValidationError(errors)
    return {
        "images": images,
        "name": safe_dir_name(data.get("name"), "character"),
        "output_name": safe_dir_name(data.get("output_dir"), "live2d"),
        "settings": settings,
        "character_lora": lora,
        "wait": data.get("wait", False) is True,
    }
