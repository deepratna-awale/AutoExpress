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
}
TEXT_FIELDS = ("ad_prompt", "ad_negative_prompt", "ad_checkpoint", "ad_sampler", "ad_scheduler", "edit_instruction", "edit_model", "edit_style")
METHODS = ("inpaint", "instruct")
MAX_TEXT = 10_000
MAX_LORAS = 20


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
              method ("inpaint" or "instruct").
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

    method = data.get("method") or "inpaint"
    if method not in METHODS:
        errors["method"] = f"must be one of {', '.join(METHODS)}"

    if errors:
        raise ValidationError(errors)

    return {
        "image": image,
        "output_name": safe_dir_name(data.get("output_dir")),
        "loras": loras,
        "settings": settings,
        "expressions": expressions or None,
        "wait": data.get("wait", True) is not False,
        "method": method,
    }
