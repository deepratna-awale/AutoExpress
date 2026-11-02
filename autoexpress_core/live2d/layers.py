"""
Turn a layer decomposition into the layer tree of a Live2D model's source PSD.

The layers come from See-through (single-image layer decomposition for anime characters,
https://github.com/shitagaki-lab/see-through), run as ComfyUI nodes. Its tags (front hair,
irides-l, handwear-r, ...) become the names and groups a Live2D Cubism Editor user expects:
one group per part (Face, Eye L, Mouth, Body, ...), every layer one art mesh, hidden areas
already painted in.

L and R are the character's own left and right (Eye L is on the right of the picture), the
way Live2D's standard parameters (ParamEyeLOpen ...) name them.

Extra art for blinking and talking comes from edited copies of the input (eyes closed,
mouth open): the pixels that changed around the eyes and mouth become hidden layers above
the open eyes and the closed mouth, ready to be switched on by ParamEyeLOpen / ParamMouthOpenY.

Only Pillow is needed.
"""

import dataclasses
import re

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from .psd import Group, Layer

# Tag -> (group, layer name, order inside the group: lower is drawn on top). Groups not
# listed in GROUP_ORDER keep their place from the depth of their layers.
_PARTS = {
    "front hair": ("Front hair", "Front hair", 0),
    "back hair": ("Back hair", "Back hair", 0),
    "hair": ("Back hair", "Hair", 0),
    "headwear": ("Headwear", "Headwear", 0),
    "eyewear": ("Face", "Eyewear", 0),
    "eyebrow": ("Face", "Eyebrows", 1),
    "nose": ("Face", "Nose", 5),
    "face": ("Face", "Face", 9),
    "ears": ("Ears", "Ears", 1),
    "earwear": ("Ears", "Earwear", 0),
    "neck": ("Body", "Neck", 0),
    "neckwear": ("Body", "Neckwear", 0),
    "topwear": ("Body", "Topwear", 0),
    "handwear": ("Body", "Arms", 0),
    "bottomwear": ("Body", "Bottomwear", 0),
    "legwear": ("Body", "Legwear", 0),
    "footwear": ("Body", "Footwear", 0),
    "tail": ("Tail", "Tail", 0),
    "wings": ("Wings", "Wings", 0),
    "objects": ("Objects", "Objects", 0),
    "eyes": ("Face", "Eyes", 2),
    "mouth": ("Mouth", "Mouth", 1),
}

# Per-side parts: tag -> (group template, layer template, order). {s} is L or R.
_SIDED = {
    "eyebrow": ("Face", "Eyebrow {s}", 1),
    "brow": ("Face", "Eyebrow {s}", 1),
    "eyelash": ("Eye {s}", "Eyelash {s}", 1),
    "irides": ("Eye {s}", "Iris {s}", 2),
    "eyewhite": ("Eye {s}", "Eye white {s}", 3),
    "eye": ("Eye {s}", "Eye {s}", 2),
    "ears": ("Ears", "Ear {s}", 1),
    "handwear": ("Body", "Arm {s}", 0),
}

_ALIASES = {"hairf": "front hair", "hairb": "back hair", "eyebg": "eyewhite", "iris": "irides", "brows": "eyebrow"}

# Face features always sit on the face, whatever their depth says.
_FACE_FEATURE_GROUPS = ("Eye L", "Eye R", "Mouth")

GROUP_ORDER_HINT = (
    "Front hair",
    "Headwear",
    "Face",
    "Eye L",
    "Eye R",
    "Mouth",
    "Ears",
    "Body",
    "Objects",
    "Tail",
    "Wings",
    "Back hair",
)

# What a model should have, and what it means when it's missing (for the kit report).
EXPECTED = {
    "Face": "No face layer: the picture may not show the character's face clearly from the front.",
    "Eye L": "The character's left eye wasn't separated: hair or an accessory may cover it, or the face is turned.",
    "Eye R": "The character's right eye wasn't separated: hair or an accessory may cover it, or the face is turned.",
    "Mouth": "No mouth layer: the mouth may be hidden or too small at this resolution.",
    "Front hair": "No front hair layer: fine for very short hair, otherwise hair sway won't have its own part.",
    "Body": "No body layers: a waist-up or full-body picture rigs much better than a face crop.",
}


@dataclasses.dataclass
class Part:
    """One decomposed layer: tag as See-through names it, RGBA image, position on the canvas, depth (lower is nearer)."""

    tag: str
    image: Image.Image
    left: int = 0
    top: int = 0
    depth: float = 1.0


def parse_tag(tag: str) -> tuple[str, str | None]:
    """(base tag, side) for a See-through tag: "irides-l" -> ("irides", "L"), "eyer" -> ("eye", "R"), "browl" -> ("brow", "L")."""
    tag = tag.strip().lower().replace("_", " ")
    match = re.fullmatch(r"(.+?)[- ]([lr])", tag)
    if match:
        base, side = match.group(1), match.group(2).upper()
        return _ALIASES.get(base, base), side
    match = re.fullmatch(r"(eye|brow)([lr])", tag)
    if match:
        return match.group(1), match.group(2).upper()
    return _ALIASES.get(tag, tag), None


def classify(tag: str) -> tuple[str, str, int]:
    """(group, layer name, order inside the group) for a See-through tag. Unknown tags get their own group."""
    base, side = parse_tag(tag)
    if side and base in _SIDED:
        group, name, order = _SIDED[base]
        return group.format(s=side), name.format(s=side), order
    if base in _PARTS:
        return _PARTS[base]
    title = base.strip().capitalize() + (f" {side}" if side else "")
    return "Other", title, 0


def _clean_parts(parts: list[Part]) -> list[Part]:
    """Drop empty layers, and the whole-head layer when the head was split into its own parts."""
    parts = [part for part in parts if part.image.getchannel("A").getbbox()]
    tags = {parse_tag(part.tag)[0] for part in parts}
    if "face" in tags:
        parts = [part for part in parts if parse_tag(part.tag)[0] != "head"]
    return parts


@dataclasses.dataclass
class Overlay:
    """Extra art for a switched state (eyes closed, mouth open), placed in group above the layer it replaces."""

    group: str
    name: str
    image: Image.Image
    left: int
    top: int
    parameter: str


def build_tree(parts: list[Part], overlays: list[Overlay] | None = None) -> tuple[list, dict]:
    """
    The PSD layer tree (top to bottom) and a manifest of what went where.

    Groups are ordered by the nearest depth of their layers, with the eyes and mouth kept
    on the face; layers inside a group follow the part order (lashes over iris over eye white).
    """
    parts = _clean_parts(parts)
    grouped: dict[str, list[tuple[int, float, Layer, str]]] = {}
    for part in parts:
        group, name, order = classify(part.tag)
        grouped.setdefault(group, []).append((order, part.depth, Layer(name, part.image, part.left, part.top), part.tag))

    # Two layers can end up with one name (two "Other" tags); keep names unique for Cubism.
    seen: dict[str, int] = {}
    for entries in grouped.values():
        for _, _, layer, _ in entries:
            count = seen.get(layer.name, 0)
            seen[layer.name] = count + 1
            if count:
                layer.name = f"{layer.name} {count + 1}"

    overlays = overlays or []
    for overlay in overlays:
        grouped.setdefault(overlay.group, []).append(
            (-1, -1.0, Layer(overlay.name, overlay.image, overlay.left, overlay.top, visible=False), "")
        )

    def group_depth(name: str) -> float:
        depths = [depth for order, depth, _, _ in grouped[name] if order >= 0]
        if name in _FACE_FEATURE_GROUPS and "Face" in grouped:
            return group_depth("Face") - 0.0001 * (1 + _FACE_FEATURE_GROUPS.index(name))
        if not depths:
            return 0.0
        nearest = min(depths)
        if name == "Face" and "Front hair" in grouped:
            # The face sits behind the front hair whatever the depth estimate says.
            nearest = max(nearest, group_depth("Front hair") + 0.001)
        if name == "Back hair":
            nearest = max(nearest, max((d for g, e in grouped.items() if g != "Back hair" for _, d, _, _ in e), default=nearest) + 0.001)
        return nearest

    hint = {name: index for index, name in enumerate(GROUP_ORDER_HINT)}
    group_names = sorted(grouped, key=lambda name: (group_depth(name), hint.get(name, len(hint))))

    tree = []
    manifest = {"groups": []}
    for group_name in group_names:
        entries = sorted(grouped[group_name], key=lambda entry: (entry[0], entry[1]))
        layers = [layer for _, _, layer, _ in entries]
        tree.append(Group(group_name, layers))
        manifest["groups"].append(
            {
                "name": group_name,
                "layers": [
                    {
                        "name": layer.name,
                        "tag": tag,
                        "visible": layer.visible,
                        "box": [layer.left, layer.top, layer.left + layer.image.width, layer.top + layer.image.height],
                    }
                    for _, _, layer, tag in entries
                ],
            }
        )
    for overlay in overlays:
        manifest.setdefault("switches", []).append({"layer": overlay.name, "group": overlay.group, "parameter": overlay.parameter})
    manifest["missing"] = [{"part": part, "message": message} for part, message in EXPECTED.items() if part not in grouped]
    return tree, manifest


# Extra art from edited copies ----------------------------------------------------------
def changed_region(base: Image.Image, edited: Image.Image, box: tuple[int, int, int, int], threshold: int = 28, grow: int = 3) -> Image.Image | None:
    """
    An alpha mask (mode L, size of box) of where edited differs from base inside box, or None if nothing did.

    Small specks are dropped and the mask is closed and feathered, so the new art blends into the face.
    """
    base_crop = base.convert("RGB").crop(box)
    edited_crop = edited.convert("RGB").resize(base.size).crop(box) if edited.size != base.size else edited.convert("RGB").crop(box)
    diff = ImageChops.difference(base_crop, edited_crop).convert("L")
    mask = diff.point(lambda value: 255 if value >= threshold else 0)
    # Open (drop specks), then close and grow (fill the shape), then feather.
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    size = 2 * grow + 1
    mask = mask.filter(ImageFilter.MaxFilter(size)).filter(ImageFilter.MaxFilter(size)).filter(ImageFilter.MinFilter(size))
    if mask.getbbox() is None:
        return None
    # Ignore changes that cover almost the whole box: the edit moved everything, not just the feature.
    histogram = mask.histogram()
    if histogram[255] > 0.85 * mask.width * mask.height:
        return None
    return mask.filter(ImageFilter.GaussianBlur(1.2))


def overlay_from_edit(
    base: Image.Image,
    edited: Image.Image,
    box: tuple[int, int, int, int],
    group: str,
    name: str,
    parameter: str,
    threshold: int = 28,
    allowed: Image.Image | None = None,
    core: tuple[int, int, int, int] | None = None,
    fill: bool = False,
) -> Overlay | None:
    """
    The changed pixels of edited inside box as a hidden layer, or None when the edit changed nothing there.

    allowed (mode L, canvas size) limits it to where the new art may go: the face, not the front hair,
    which an edit often redraws a little differently and which sits above the eyes anyway.
    core (canvas coordinates) is the feature itself: the change is kept to an ellipse around the box,
    and only the pieces of it that reach the core are kept, so stray redrawn strands and outlines
    elsewhere in the box are dropped. fill also covers the whole core (closed eyes have to hide the
    open eye completely, even where the edit's skin happens to match), and evens the edit's colours
    out to the picture's around it.
    """
    box = clamp_box(box, base.size)
    if box[2] - box[0] < 4 or box[3] - box[1] < 4:
        return None
    mask = changed_region(base, edited, box, threshold)
    if mask is None:
        return None
    if allowed is not None:
        mask = ImageChops.multiply(mask, allowed.crop(box))
    if core is not None:
        mask = ImageChops.multiply(mask, ellipse_mask((box[2] - box[0], box[3] - box[1])))
        local = (core[0] - box[0], core[1] - box[1], core[2] - box[0], core[3] - box[1])
        mask = keep_touching(mask, local)
        if fill:
            inner = Image.new("L", mask.size, 0)
            inner.paste(ellipse_mask((max(1, local[2] - local[0]), max(1, local[3] - local[1]))), (local[0], local[1]))
            if allowed is not None:
                inner = ImageChops.multiply(inner, allowed.crop(box))
            mask = ImageChops.lighter(mask, inner)
    if mask.getbbox() is None:
        return None
    edited = edited.convert("RGBA").resize(base.size) if edited.size != base.size else edited.convert("RGBA")
    art = edited.crop(box)
    if fill:
        art = match_colours(art, base.convert("RGBA").crop(box), mask)
    alpha = ImageChops.multiply(art.getchannel("A"), mask)
    art.putalpha(alpha)
    bbox = alpha.getbbox()
    if bbox is None:
        return None
    return Overlay(group, name, art.crop(bbox), box[0] + bbox[0], box[1] + bbox[1], parameter)


def match_colours(art: Image.Image, base: Image.Image, mask: Image.Image) -> Image.Image:
    """art with its colours scaled to base's, judged on a ring just outside mask where both show the same skin."""
    solid = mask.point(lambda v: 255 if v > 32 else 0)
    ring = ImageChops.subtract(solid.filter(ImageFilter.MaxFilter(9)), solid)
    if ring.getbbox() is None:
        return art
    art_mean = ImageStat.Stat(art.convert("RGB"), ring).mean
    base_mean = ImageStat.Stat(base.convert("RGB"), ring).mean
    gains = [max(0.8, min(1.25, b / a)) if a > 1 else 1.0 for a, b in zip(art_mean, base_mean)]
    channels = [channel.point(lambda v, g=gain: min(255, int(v * g))) for channel, gain in zip(art.split()[:3], gains)]
    return Image.merge("RGBA", (*channels, art.getchannel("A")))


def ellipse_mask(size: tuple[int, int]) -> Image.Image:
    """A soft-edged ellipse filling size (mode L)."""
    width, height = size
    mask = Image.new("L", size, 0)
    inset = max(1, min(width, height) // 20)
    ImageDraw.Draw(mask).ellipse((inset, inset, width - 1 - inset, height - 1 - inset), fill=255)
    return mask.filter(ImageFilter.GaussianBlur(max(1, inset)))


def keep_touching(mask: Image.Image, core: tuple[int, int, int, int], level: int = 64) -> Image.Image:
    """mask with only the connected pieces that reach into the core box (all in mask's coordinates)."""
    width, height = mask.size
    pixels = mask.load()
    left, top = max(0, int(core[0])), max(0, int(core[1]))
    right, bottom = min(width, int(core[2])), min(height, int(core[3]))
    keep = bytearray(width * height)
    stack = [(x, y) for y in range(top, bottom) for x in range(left, right) if pixels[x, y] > level]
    for x, y in stack:
        keep[y * width + x] = 1
    while stack:
        x, y = stack.pop()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < width and 0 <= ny < height and not keep[ny * width + nx] and pixels[nx, ny] > level:
                keep[ny * width + nx] = 1
                stack.append((nx, ny))
    region = Image.frombytes("L", mask.size, bytes(keep)).point(lambda v: 255 if v else 0)
    # Keep the feathered edge around the kept pieces.
    return ImageChops.multiply(mask, region.filter(ImageFilter.MaxFilter(3)))


def clamp_box(box, size) -> tuple[int, int, int, int]:
    left, top, right, bottom = (int(round(v)) for v in box)
    return max(0, left), max(0, top), min(size[0], right), min(size[1], bottom)


def grow_box(box, factor_x: float, factor_y: float, size) -> tuple[int, int, int, int]:
    left, top, right, bottom = box
    width, height = right - left, bottom - top
    dx, dy = width * factor_x, height * factor_y
    return clamp_box((left - dx, top - dy, right + dx, bottom + dy), size)


def union_box(boxes) -> tuple[int, int, int, int] | None:
    boxes = [box for box in boxes if box]
    if not boxes:
        return None
    return min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)


def part_box(part: Part) -> tuple[int, int, int, int] | None:
    bbox = part.image.getchannel("A").getbbox()
    if bbox is None:
        return None
    return part.left + bbox[0], part.top + bbox[1], part.left + bbox[2], part.top + bbox[3]


def feature_cores(parts: list[Part]) -> dict[str, tuple[int, int, int, int]]:
    """The box of each eye's own layers (lash, iris, eye white) and of the mouth."""
    boxes: dict[str, list] = {"Eye L": [], "Eye R": [], "Mouth": [], "Eyes": []}
    for part in parts:
        base, side = parse_tag(part.tag)
        if base in ("eyelash", "irides", "eyewhite", "eye") and side:
            boxes[f"Eye {side}"].append(part_box(part))
        elif base in ("eyes",):
            boxes["Eyes"].append(part_box(part))
        elif base == "mouth":
            boxes["Mouth"].append(part_box(part))
    unions = {name: union_box(items) for name, items in boxes.items()}
    return {name: union for name, union in unions.items() if union is not None}


def feature_boxes(parts: list[Part], size) -> dict[str, tuple[int, int, int, int]]:
    """Where to look for blink and mouth changes: around each eye (with its brow and lashes) and around the mouth."""
    found = {}
    for name, union in feature_cores(parts).items():
        if name == "Mouth":
            # An open mouth reaches well above and below a closed one, which is often a thin line.
            width, height = union[2] - union[0], union[3] - union[1]
            found[name] = grow_box(union, 0.8, max(1.2, 0.9 * width / max(1, height)), size)
        else:
            found[name] = grow_box(union, 0.35, 0.45, size)
    return found


_FACE_TAGS = ("face", "eyewhite", "irides", "eyelash", "eyebrow", "brow", "eye", "eyes", "mouth", "nose")


def _alpha_union(parts: list[Part], size, tags) -> Image.Image:
    union = Image.new("L", size, 0)
    for part in parts:
        if parse_tag(part.tag)[0] in tags:
            alpha = Image.new("L", size, 0)
            alpha.paste(part.image.getchannel("A"), (part.left, part.top))
            union = ImageChops.lighter(union, alpha)
    return union


def face_area(parts: list[Part], size) -> Image.Image | None:
    """Where blink and mouth art may go (mode L): the face and its features, minus the front hair. None without a face layer."""
    face = _alpha_union(parts, size, _FACE_TAGS)
    if face.getbbox() is None:
        return None
    face = face.point(lambda v: 255 if v > 24 else 0).filter(ImageFilter.MaxFilter(5))
    hair = _alpha_union(parts, size, ("front hair",)).point(lambda v: 255 if v > 96 else 0)
    return ImageChops.subtract(face, hair).filter(ImageFilter.GaussianBlur(1))


def eye_area(parts: list[Part], size, allowed: Image.Image | None) -> Image.Image | None:
    """Where closed eyes may go: the face area minus the eyebrows, which don't move when the eyes close."""
    if allowed is None:
        return None
    brows = _alpha_union(parts, size, ("eyebrow", "brow"))
    if brows.getbbox() is None:
        return allowed
    brows = brows.point(lambda v: 255 if v > 48 else 0).filter(ImageFilter.MaxFilter(5))
    return ImageChops.subtract(allowed, brows)


def mouth_area(parts: list[Part], size, allowed: Image.Image | None) -> Image.Image | None:
    """Where an open mouth may go: inside the face, kept clear of its outline (which edits tend to redraw)."""
    if allowed is None:
        return None
    face = _alpha_union(parts, size, ("face",))
    box = face.getbbox()
    if box is None:
        return allowed
    margin = max(3, (box[2] - box[0]) // 40) * 2 + 1
    inner = face.point(lambda v: 255 if v > 200 else 0).filter(ImageFilter.MinFilter(margin))
    return ImageChops.multiply(allowed, inner.filter(ImageFilter.GaussianBlur(1)))


def edit_overlays(parts: list[Part], base: Image.Image, eyes_closed: Image.Image | None = None, mouth_open: Image.Image | None = None) -> list[Overlay]:
    """Hidden layers for blinking and talking from the edited copies (both on the decomposition's canvas)."""
    boxes = feature_boxes(parts, base.size)
    cores = feature_cores(parts)
    allowed = face_area(parts, base.size)
    eyes_allowed = eye_area(parts, base.size, allowed)
    overlays = []
    if eyes_closed is not None:
        eye_groups = [name for name in ("Eye L", "Eye R") if name in boxes]
        if not eye_groups and "Eyes" in boxes:
            eye_groups = ["Eyes"]
        for group in eye_groups:
            side = group.split(" ")[1] if " " in group else ""
            parameter = f"ParamEye{side}Open" if side else "ParamEyeLOpen, ParamEyeROpen"
            name = f"Eye {side} closed".replace("  ", " ") if side else "Eyes closed"
            overlay = overlay_from_edit(base, eyes_closed, boxes[group], group if side else "Face", name, parameter, allowed=eyes_allowed, core=cores[group], fill=True)
            if overlay:
                overlays.append(overlay)
    if mouth_open is not None and "Mouth" in boxes:
        overlay = overlay_from_edit(base, mouth_open, boxes["Mouth"], "Mouth", "Mouth open", "ParamMouthOpenY", allowed=mouth_area(parts, base.size, allowed), core=cores["Mouth"])
        if overlay:
            overlays.append(overlay)
    return overlays


def crop_parts(parts: list[Part], box: tuple[int, int, int, int]) -> list[Part]:
    """Move every part onto a smaller canvas whose top left corner is at box."""
    return [dataclasses.replace(part, left=part.left - box[0], top=part.top - box[1]) for part in parts]


# Layer split settings --------------------------------------------------------------
SEETHROUGH_REPO = "https://github.com/jtydhr88/ComfyUI-See-through"
VRAM_NOTE = (
    "See-through needs about 12-16 GB of VRAM at 1280 px (8 GB with the 4-bit models). "
    "A rented GPU (RunPod etc.) works the same as a local one; its models (about 10 GB) download on first use."
)


@dataclasses.dataclass(frozen=True)
class SplitSettings:
    # The square size See-through works at (the picture is padded to a square). 1024-2048.
    resolution: int = 1280
    steps: int = 30
    seed: int = 42
    # 4-bit models for 8-12 GB GPUs (needs bitsandbytes on the ComfyUI side).
    low_vram: bool = False

    @classmethod
    def from_settings(cls, settings: dict | None) -> "SplitSettings":
        settings = settings or {}

        def number(key, cast, low, high):
            try:
                value = cast(settings.get(key, getattr(cls, key)))
            except (TypeError, ValueError):
                value = getattr(cls, key)
            return max(low, min(high, value))

        resolution = number("resolution", int, 768, 2048) // 64 * 64
        return cls(
            resolution=resolution,
            steps=number("steps", int, 8, 60),
            seed=number("seed", int, 0, 2**32 - 1),
            low_vram=bool(settings.get("low_vram", False)),
        )


def square_placement(size: tuple[int, int], resolution: int) -> tuple[int, int, int, int]:
    """Where a picture of size lands on See-through's square canvas (centre padded, then scaled): left, top, right, bottom."""
    width, height = size
    side = max(width, height)
    scale = resolution / side
    left = (side - width) // 2 * scale
    top = (side - height) // 2 * scale
    return clamp_box((left, top, left + width * scale, top + height * scale), (resolution, resolution))
