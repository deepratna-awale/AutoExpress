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
    # Made here, not by See-through: the hair colour painted under the bangs, and the swappable
    # clothing layers (outfits.py) under See-through's clothes.
    "hair underlay": ("Front hair", "Hair underlay", 5),
    "outer wear": ("Body", "Outer wear", 0),
    "outer wear half": ("Body", "Outer wear half", 0),
    "topwear half": ("Body", "Topwear half", 0),
    "bottomwear half": ("Body", "Bottomwear half", 0),
    "inner wear": ("Body", "Inner wear", 15),
    "inner top": ("Body", "Inner top", 14),
    "inner bottom": ("Body", "Inner bottom", 15),
    "nude body": ("Body", "Body", 20),
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


# Cleaning up the split -------------------------------------------------------------------
# See-through leaves soft, half-transparent alpha inside skin and clothing (a see-through neck
# with the collar showing behind it) and a faint veil around the front hair. Artists draw body
# parts fully opaque with only an anti-aliased edge, so the alpha is pushed to that.
SOLID_TAGS = ("face", "neck", "topwear", "bottomwear", "legwear", "footwear", "handwear", "neckwear", "ears", "headwear", "nude body", "inner wear")
HAIR_TAGS = ("front hair", "back hair", "hair")


def _alpha_ramp(low: int, high: int):
    span = max(1, high - low)
    return [0 if v <= low else 255 if v >= high else round((v - low) * 255 / span) for v in range(256)]


_SOLID_RAMP = _alpha_ramp(16, 110)
_HAIR_RAMP = _alpha_ramp(70, 170)


def defringe(image: Image.Image, radius: int = 6) -> Image.Image:
    """
    image with its half-transparent edge pixels coloured like the solid pixels next to them.

    The split's edge pixels carry the background they were cut from (a pale halo around dark hair).
    Their colour is replaced by the solid colour nearby (a normalised blur of the solid pixels).
    """
    from PIL import ImageMath

    image = image.convert("RGBA")
    alpha = image.getchannel("A")
    present = alpha.point(lambda v: 255 if v > 0 else 0)
    # The outer ring (within a few px of the outside) counts as edge too: once an edge has been made
    # opaque, or upscaled, its halo is solid and several pixels wide, but still pale next to what's inside.
    ring = ImageChops.subtract(present, present.filter(ImageFilter.MinFilter(2 * radius + 1)))
    solid = ImageChops.subtract(alpha.point(lambda v: 255 if v > 230 else 0), ring)
    if solid.getbbox() is None:
        return image
    weight = solid.filter(ImageFilter.BoxBlur(radius))
    channels = []
    for channel in image.convert("RGB").split():
        spread = ImageChops.multiply(channel, solid).filter(ImageFilter.BoxBlur(radius))
        channels.append(ImageMath.lambda_eval(lambda a: a["convert"](a["min"](a["s"] * 255 / (a["w"] + 0.001), 255), "L"), s=spread, w=weight) if hasattr(ImageMath, "lambda_eval")
                        else ImageMath.eval("convert(min(s * 255 / (w + 0.001), 255), 'L')", s=spread, w=weight))
    spread = Image.merge("RGB", channels)
    soft = alpha.point(lambda v: 255 if 0 < v <= 230 else 0)
    # On the ring only pixels clearly paler than what's inside are halo; darker ones are the outline.
    paler = ImageChops.subtract(image.convert("L"), spread.convert("L")).point(lambda v: 255 if v > 40 else 0)
    edge = ImageChops.multiply(ImageChops.lighter(soft, ImageChops.multiply(ring, paler)), weight.point(lambda v: 255 if v > 8 else 0))
    rgb = Image.composite(spread, image.convert("RGB"), edge)
    result = rgb.convert("RGBA")
    result.putalpha(alpha)
    return result


def solidify(image: Image.Image, ramp=_SOLID_RAMP) -> Image.Image:
    """image with its alpha pushed through ramp: the inside fully opaque, only the outer edge soft, without a halo."""
    image = defringe(image.convert("RGBA"))
    image.putalpha(image.getchannel("A").point(ramp))
    return image


def solidify_parts(parts: list[Part]) -> list[Part]:
    """Skin, clothing and hair made opaque (see SOLID_TAGS); eyes, mouth and lines keep their alpha."""
    result = []
    for part in parts:
        base = parse_tag(part.tag)[0]
        if base in SOLID_TAGS:
            part = dataclasses.replace(part, image=solidify(part.image))
        elif base in HAIR_TAGS:
            part = dataclasses.replace(part, image=solidify(part.image, _HAIR_RAMP))
        result.append(part)
    return result


CLOTHING_TAGS = ("topwear", "bottomwear", "legwear", "footwear", "handwear", "neckwear", "headwear")
_UNDER_TAGS = ("neck", "face")
_SWITCH_TAGS = ("hair underlay", "nude body", "inner wear")


def _on_canvas(part: Part, size, channel: str | None = None) -> Image.Image:
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.paste(part.image.convert("RGBA"), (part.left, part.top))
    return canvas.getchannel(channel) if channel else canvas


def _difference(layer: Image.Image, picture: Image.Image) -> Image.Image:
    """The largest channel difference between layer and picture, per pixel (mode L)."""
    r, g, b = ImageChops.difference(layer.convert("RGB"), picture.convert("RGB")).split()
    return ImageChops.lighter(ImageChops.lighter(r, g), b)


def _mismatch(layer: Image.Image, picture: Image.Image, threshold: int) -> Image.Image:
    """Where layer's colour differs from picture's by more than threshold (mode L, 0/255), specks dropped."""
    diff = ImageChops.difference(layer.convert("RGB"), picture.convert("RGB"))
    r, g, b = diff.split()
    worst = ImageChops.lighter(ImageChops.lighter(r, g), b)
    mask = worst.point(lambda v: 255 if v > threshold else 0)
    return mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))


def match_picture(parts: list[Part], picture: Image.Image, threshold: int = 48) -> list[Part]:
    """
    Make the layers agree with the picture they were split from (picture: RGB on the split's canvas).

    1. Clothing drawn over the neck or face where the picture shows the neck or face (the back of a
       collar, which See-through often leaves in the top layer, looking like the collar seen through
       a see-through neck) is cut out of the clothing.
    2. Wherever a layer is the one on top and its colour is far from the picture's (grey patches in
       the back hair, smudges in the inpainting), it takes the picture's colour, so the puppet at
       rest looks like the picture.
    """
    size = picture.size
    picture = picture.convert("RGB")
    parts = list(parts)
    # 1. Clothing over the neck and face.
    unders = [p for p in parts if parse_tag(p.tag)[0] in _UNDER_TAGS]
    for index, part in enumerate(parts):
        if parse_tag(part.tag)[0] not in CLOTHING_TAGS or not unders:
            continue
        layer = _on_canvas(part, size)
        solid = layer.getchannel("A").point(lambda v: 255 if v > 200 else 0)
        # Cut where the neck or face matches the picture clearly better than the clothing does: the
        # back of a collar is often only a slightly different shade, so this is relative, not a threshold.
        clothing_off = _difference(layer, picture)
        cut = Image.new("L", size, 0)
        for under in unders:
            other = _on_canvas(under, size)
            other_solid = other.getchannel("A").point(lambda v: 255 if v > 200 else 0)
            under_off = _difference(other, picture)
            better = ImageChops.subtract(clothing_off, under_off).point(lambda v: 255 if v > 16 else 0)
            close = under_off.point(lambda v: 255 if v < 24 else 0)
            cut = ImageChops.lighter(cut, ImageChops.multiply(ImageChops.multiply(solid, other_solid), ImageChops.multiply(better, close)))
        cut = cut.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
        cut = cut.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))
        if cut.getbbox() is None:
            continue
        alpha = ImageChops.subtract(layer.getchannel("A"), cut.filter(ImageFilter.GaussianBlur(1)))
        layer.putalpha(alpha)
        box = alpha.getbbox()
        if box:
            parts[index] = dataclasses.replace(part, image=layer.crop(box), left=box[0], top=box[1])
    # 2. Visible colour from the picture (the character only: not the picture's background).
    tree, _ = build_tree(parts)
    by_image = {id(p.image): i for i, p in enumerate(parts)}
    background = picture.getpixel((0, 0))
    subject = ImageChops.difference(picture, Image.new("RGB", size, background)).convert("L").point(lambda v: 255 if v > 20 else 0)
    outline_clear = subject.filter(ImageFilter.MinFilter(13))
    covered = Image.new("L", size, 0)
    for group in tree:
        for layer in group.children:
            index = by_image.get(id(layer.image))
            if index is None or not layer.visible:
                continue
            part = parts[index]
            canvas = _on_canvas(part, size)
            solid = canvas.getchannel("A").point(lambda v: 255 if v > 230 else 0)
            visible = ImageChops.subtract(solid, covered)
            covered = ImageChops.lighter(covered, solid)
            if parse_tag(part.tag)[0] in _SWITCH_TAGS:
                continue
            if parse_tag(part.tag)[0] in HAIR_TAGS:
                canvas = _even_hidden_hair(canvas, solid, visible)
            # Stay off the layer's own edge and the character's outline, where the picture's pixels are
            # mixed with its background (they would paint a pale halo onto the layer).
            inside = ImageChops.multiply(solid.filter(ImageFilter.MinFilter(5)), outline_clear)
            fix = ImageChops.multiply(ImageChops.multiply(visible, inside), ImageChops.multiply(subject, _mismatch(canvas, picture, threshold)))
            fixed = canvas
            if fix.getbbox() is not None:
                fixed = Image.composite(Image.merge("RGBA", (*picture.split(), canvas.getchannel("A"))), canvas, fix.filter(ImageFilter.GaussianBlur(1.5)))
            parts[index] = dataclasses.replace(part, image=fixed.crop((part.left, part.top, part.left + part.image.width, part.top + part.image.height)))
    return parts


def _even_hidden_hair(canvas: Image.Image, solid: Image.Image, visible: Image.Image) -> Image.Image:
    """
    Hair the picture hides (behind the face and clothes) that the split painted in pale grey gets the
    hair's own colour, so it doesn't flash grey when the front moves aside.
    """
    seen = ImageChops.multiply(visible, solid)
    if ImageStat.Stat(seen).sum[0] < 255 * 200:
        seen = solid
    rgb = canvas.convert("RGB")
    grey = rgb.convert("L")
    level = ImageStat.Stat(grey, seen).median[0]
    colour = _median_colour(rgb, seen)
    hidden = ImageChops.subtract(solid, visible.filter(ImageFilter.MaxFilter(5)))
    pale = ImageChops.multiply(hidden, grey.point(lambda v: 255 if v > level + 45 else 0))
    pale = pale.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.GaussianBlur(2))
    if pale.getbbox() is None:
        return canvas
    flat = Image.new("RGBA", canvas.size, colour + (255,))
    flat.putalpha(canvas.getchannel("A"))
    return Image.composite(flat, canvas, pale)


def _median_colour(image: Image.Image, mask: Image.Image) -> tuple[int, int, int]:
    stat = ImageStat.Stat(image.convert("RGB"), mask)
    return tuple(int(v) for v in stat.median) if stat.count[0] else (60, 50, 50)


def hair_underlay(parts: list[Part], size) -> Part | None:
    """
    The hair colour painted under the bangs, from the hairline down to the brows (a Part, or None).

    The front hair sways, and without this the forehead skin (or nothing) shows where a strand
    was. Artists paint that area in a darker hair colour; this takes the front hair's own shape
    above the brows, filled with its darker tones, so a swaying strand uncovers hair. It stays
    with the head and doesn't sway. Below the brows nothing is added: strands moving over the
    eyes should show the eyes.
    """
    hair = _alpha_union(parts, size, ("front hair",))
    box = hair.getbbox()
    if box is None:
        return None
    face = _alpha_union(parts, size, ("face",)).getbbox()
    brows = _alpha_union(parts, size, ("eyebrow", "brow")).getbbox()
    eyes = _alpha_union(parts, size, ("eyewhite", "irides", "eyelash", "eye", "eyes")).getbbox()
    if brows:
        limit = brows[1] + (brows[3] - brows[1]) * 0.5
    elif eyes:
        limit = eyes[1] - (eyes[3] - eyes[1]) * 0.4
    elif face:
        limit = face[1] + (face[3] - face[1]) * 0.35
    else:
        return None
    fade = max(4, (face[3] - face[1]) * 0.06 if face else 12)
    solid = hair.point(lambda v: 255 if v > 128 else 0)
    # A little wider than the hair so its anti-aliased edge never shows skin either.
    grow = max(3, (box[2] - box[0]) // 150) * 2 + 1
    shape = solid.filter(ImageFilter.MaxFilter(grow))
    # Only over the head: not the strands hanging down past the face.
    if face:
        reach = (face[2] - face[0]) * 0.12
        region = Image.new("L", size, 0)
        ImageDraw.Draw(region).rectangle((face[0] - reach, 0, face[2] + reach, size[1]), fill=255)
        shape = ImageChops.multiply(shape, region)
    gradient = Image.new("L", (1, size[1]), 0)
    gradient.putdata([255 if y < limit - fade else 0 if y > limit else round(255 * (limit - y) / fade) for y in range(size[1])])
    shape = ImageChops.multiply(shape, gradient.resize(size))
    if shape.getbbox() is None:
        return None
    # The darker half of the hair's colours: the shade under the bangs.
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    for part in parts:
        if parse_tag(part.tag)[0] == "front hair":
            canvas.alpha_composite(part.image.convert("RGBA"), (part.left, part.top))
    rgb = canvas.convert("RGB")
    grey = rgb.convert("L")
    median = _median_colour(rgb, solid)
    dark_mask = ImageChops.multiply(solid, grey.point(lambda v, m=sum(median) / 3: 255 if v <= m else 0))
    colour = _median_colour(rgb, dark_mask if dark_mask.getbbox() else solid)
    colour = tuple(round(c * 0.85) for c in colour)
    # Blur the hair itself under it so it keeps a little of the strands' shading.
    art = Image.new("RGBA", size, colour + (0,))
    texture = Image.blend(Image.new("RGB", size, colour), rgb.filter(ImageFilter.GaussianBlur(6)), 0.35)
    art.paste(texture, (0, 0))
    art.putalpha(shape)
    crop = shape.getbbox()
    return Part("hair underlay", art.crop(crop), crop[0], crop[1], depth=min((p.depth for p in parts if parse_tag(p.tag)[0] == "front hair"), default=0.0) + 0.0005)


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
            # Closed eyes stay close around the eye: changes further out are hair or face the edit
            # redrew, and would show as a patch over them.
            width, height = local[2] - local[0], local[3] - local[1]
            near = Image.new("L", mask.size, 0)
            reach = (int(local[0] - width * 0.18), int(local[1] - height * 0.45), int(local[2] + width * 0.18), int(local[3] + height * 0.45))
            near.paste(ellipse_mask((max(1, reach[2] - reach[0]), max(1, reach[3] - reach[1]))), reach[:2])
            mask = ImageChops.multiply(mask, near)
    if mask.getbbox() is None:
        return None
    edited = edited.convert("RGBA").resize(base.size) if edited.size != base.size else edited.convert("RGBA")
    art = edited.crop(box)
    if fill:
        art = clean_eyelid(art, base.convert("RGBA").crop(box), mask, local if core is not None else None)
        # A feathered edge, so the lid melts into the face instead of sitting on it as a patch.
        mask = ImageChops.multiply(mask, mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.6)).point(lambda v: min(255, v * 2)))
    alpha = ImageChops.multiply(art.getchannel("A"), mask)
    art.putalpha(alpha)
    bbox = alpha.getbbox()
    if bbox is None:
        return None
    return Overlay(group, name, art.crop(bbox), box[0] + bbox[0], box[1] + bbox[1], parameter)


def clean_eyelid(art: Image.Image, base: Image.Image, mask: Image.Image, core: tuple | None = None) -> Image.Image:
    """
    A closed eye from an edit, cleaned up: the lashes (the dark lines) stay as drawn, everything
    else becomes the picture's own skin colour around the eye with only the edit's soft shading,
    so the lid never shows a grey or off-colour patch, hair the edit redrew, or bits of the open eye.
    """
    solid = mask.point(lambda v: 255 if v > 32 else 0)
    ring = ImageChops.subtract(solid.filter(ImageFilter.MaxFilter(11)), solid.filter(ImageFilter.MaxFilter(3)))
    base_rgb = base.convert("RGB")
    if ring.getbbox() is None:
        return art
    # The skin: the lighter half of the ring (the ring can catch lashes, brows and hair too).
    grey = base_rgb.convert("L")
    level = ImageStat.Stat(grey, ring).median[0]
    light = ImageChops.multiply(ring, grey.point(lambda v: 255 if v >= level else 0))
    skin = ImageStat.Stat(base_rgb, light if light.getbbox() else ring).median
    skin_level = max(1.0, 0.299 * skin[0] + 0.587 * skin[1] + 0.114 * skin[2])
    art_rgb = art.convert("RGB")
    art_grey = art_rgb.convert("L")
    art_level = max(1.0, ImageStat.Stat(art_grey, solid).median[0])
    # Lashes: much darker than the skin. Kept with a soft edge.
    lash = art_grey.point(lambda v: 255 if v < skin_level * 0.55 else 0 if v > skin_level * 0.75 else int((skin_level * 0.75 - v) / (skin_level * 0.2) * 255))
    lash = lash.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    if core is not None:
        # Lashes lie across the eye: dark strands above or below it are redrawn hair or brow.
        width, height = core[2] - core[0], core[3] - core[1]
        band = Image.new("L", art.size, 0)
        band.paste(255, (int(core[0] - width * 0.04), int(core[1] - height * 0.1), int(core[2] + width * 0.04), int(core[3] + height * 0.25)))
        lash = ImageChops.multiply(lash, band.filter(ImageFilter.GaussianBlur(2)))
    # Skin with the edit's shading (a lid crease, a soft shadow), but none of its colour cast.
    shade = art_grey.point(lambda v: int(255 * max(0.9, min(1.04, v / art_level)) / 1.04))
    flat = Image.new("RGB", art.size, tuple(int(c) for c in skin))
    shaded = ImageChops.multiply(flat, Image.merge("RGB", (shade, shade, shade))).point(lambda v: min(255, int(v * 1.04)))
    cleaned = Image.composite(art_rgb, shaded, lash)
    result = cleaned.convert("RGBA")
    result.putalpha(art.getchannel("A"))
    return result


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


_SPECK_TAGS = (
    "topwear", "bottomwear", "legwear", "footwear", "handwear", "neckwear", "neck", "nude body", "inner wear", "inner top", "inner bottom",
    "outer wear", "outer wear half", "topwear half", "bottomwear half",
)


def drop_specks(parts: list[Part], share: float = 0.01) -> list[Part]:
    """
    The clothing and body layers without their stray specks and slivers: pieces that aren't joined
    to the rest of the layer and are smaller than share of its biggest piece (bits of a neighbouring
    garment the split or an edit left, which show as floating scraps when a layer is switched off).
    """
    result = []
    for part in parts:
        if parse_tag(part.tag)[0] not in _SPECK_TAGS:
            result.append(part)
            continue
        alpha = part.image.getchannel("A")
        solid = alpha.point(lambda v: 255 if v > 40 else 0)
        width, height = solid.size
        scale = max(1, max(width, height) // 400)
        small = solid.resize((max(1, width // scale), max(1, height // scale)), Image.Resampling.NEAREST)
        pixels = small.load()
        w, h = small.size
        seen = bytearray(w * h)
        pieces = []
        for y in range(h):
            for x in range(w):
                if pixels[x, y] and not seen[y * w + x]:
                    stack = [(x, y)]
                    seen[y * w + x] = 1
                    piece = []
                    while stack:
                        cx, cy = stack.pop()
                        piece.append((cx, cy))
                        for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                            if 0 <= nx < w and 0 <= ny < h and pixels[nx, ny] and not seen[ny * w + nx]:
                                seen[ny * w + nx] = 1
                                stack.append((nx, ny))
                    pieces.append(piece)
        if len(pieces) <= 1:
            result.append(part)
            continue
        biggest = max(len(p) for p in pieces)
        drop = Image.new("L", small.size, 0)
        drawn = drop.load()
        for piece in pieces:
            if len(piece) < biggest * share:
                for px, py in piece:
                    drawn[px, py] = 255
        if drop.getbbox() is None:
            result.append(part)
            continue
        drop = drop.resize((width, height), Image.Resampling.NEAREST).filter(ImageFilter.MaxFilter(5))
        image = part.image.convert("RGBA")
        image.putalpha(ImageChops.subtract(alpha, drop))
        box = image.getchannel("A").getbbox()
        if box:
            result.append(dataclasses.replace(part, image=image.crop(box), left=part.left + box[0], top=part.top + box[1]))
    return result


def settle_lash_strays(parts: list[Part], size) -> list[Part]:
    """
    Move what a lash layer has away from its eye (hair strands, the outer corner's shadow,
    See-through often puts them there) onto the face layer, so a blink only hides the eye itself
    and never leaves a hole where those were.
    """
    face = next((p for p in parts if parse_tag(p.tag)[0] == "face"), None)
    if face is None:
        return parts
    eyes: dict[str, list] = {}
    for part in parts:
        base, side = parse_tag(part.tag)
        if base in ("irides", "eyewhite") and side:
            eyes.setdefault(side, []).append(part_box(part))
    face_canvas = _on_canvas(face, size)
    changed = False
    result = []
    for part in parts:
        base, side = parse_tag(part.tag)
        box = union_box([b for b in eyes.get(side, []) if b]) if base == "eyelash" and side else None
        if box is None:
            result.append(part)
            continue
        width, height = box[2] - box[0], box[3] - box[1]
        reach = (int(box[0] - width * 0.15), int(box[1] - height * 0.6), int(box[2] + width * 0.15), int(box[3] + height * 0.4))
        near = Image.new("L", size, 0)
        near.paste(ellipse_mask((max(1, reach[2] - reach[0]), max(1, reach[3] - reach[1]))), reach[:2])
        lash = _on_canvas(part, size)
        alpha = lash.getchannel("A")
        keep = ImageChops.multiply(alpha, near)
        away = ImageChops.subtract(alpha, near)
        if ImageStat.Stat(away).sum[0] / 255 < 4:
            result.append(part)
            continue
        stray = lash.copy()
        stray.putalpha(away)
        face_canvas.alpha_composite(stray)
        lash.putalpha(keep)
        bbox = keep.getbbox()
        changed = True
        if bbox:
            result.append(dataclasses.replace(part, image=lash.crop(bbox), left=bbox[0], top=bbox[1]))
    bbox = face_canvas.getchannel("A").getbbox()
    settled = dataclasses.replace(face, image=face_canvas.crop(bbox), left=bbox[0], top=bbox[1]) if changed else face
    # The ears sit above the face but under the eyes: where the lashes covered an ear, what's there
    # is See-through's guess, which would show through a blink, so the ear gives way there.
    covered = Image.new("L", size, 0)
    for part in parts:
        base, side = parse_tag(part.tag)
        if base == "eyelash" and side:
            covered = ImageChops.lighter(covered, _on_canvas(part, size, "A"))
    final = []
    for part in result:
        if part is face:
            final.append(settled)
        elif parse_tag(part.tag)[0] in ("ears", "ear"):
            ear = _on_canvas(part, size)
            ear.putalpha(ImageChops.subtract(ear.getchannel("A"), covered))
            box = ear.getchannel("A").getbbox()
            if box:
                final.append(dataclasses.replace(part, image=ear.crop(box), left=box[0], top=box[1]))
        else:
            final.append(part)
    return final


def trim_neck(parts: list[Part], size, overlap: int = 6) -> list[Part]:
    """
    Take the chin and lips out of the neck layer. See-through often draws the lower face into the
    neck too; the neck sits above the face, so that copy shows as a second jaw line across the face
    and stays behind when the head turns. The neck keeps a few pixels under the face's edge so no
    gap opens at the jaw.
    """
    face = _alpha_union(parts, size, ("face",)).point(lambda v: 255 if v > 128 else 0)
    if face.getbbox() is None:
        return parts
    inside = face.filter(ImageFilter.MinFilter(2 * overlap + 1))
    result = []
    for part in parts:
        if parse_tag(part.tag)[0] != "neck":
            result.append(part)
            continue
        neck = _on_canvas(part, size)
        neck.putalpha(ImageChops.subtract(neck.getchannel("A"), inside))
        box = neck.getchannel("A").getbbox()
        if box:
            result.append(dataclasses.replace(part, image=neck.crop(box), left=box[0], top=box[1]))
    return result


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


def best_shift(base: Image.Image, edited: Image.Image, box, reach: int = 12) -> tuple[int, int]:
    """
    How far (dx, dy) the edit is drawn from the picture around box: Qwen redraws the whole picture
    and often moves it by a few pixels, so a piece cut at the same place would sit off the face.
    """
    import numpy as np

    box = clamp_box(box, base.size)
    a = np.asarray(base.convert("L").crop(box), dtype=np.float32)
    wide = clamp_box((box[0] - reach, box[1] - reach, box[2] + reach, box[3] + reach), edited.size)
    b = np.asarray(edited.convert("L").crop(wide), dtype=np.float32)
    ox, oy = box[0] - wide[0], box[1] - wide[1]
    h, w = a.shape
    best, shift = None, (0, 0)
    for dy in range(-oy, b.shape[0] - h - oy + 1):
        for dx in range(-ox, b.shape[1] - w - ox + 1):
            window = b[oy + dy:oy + dy + h, ox + dx:ox + dx + w]
            # The median difference: the changed feature itself doesn't pull the match off.
            score = float(np.median(np.abs(window - a))) + 0.02 * (abs(dx) + abs(dy))
            if best is None or score < best:
                best, shift = score, (dx, dy)
    return shift


def expression_piece(
    base: Image.Image,
    edited: Image.Image,
    region,
    skin: Image.Image,
    group: str,
    name: str,
    parameter: str,
    core=None,
    threshold: int = 22,
) -> Overlay | None:
    """
    A drawn piece for a strong emotion (angry brows, a grin, teary eyes) cut from an edit: the edit is
    lined up with the picture first, then what it changed inside a soft ellipse over region is kept,
    on the face's skin only, with the feature itself (core) covered completely, so the old one never
    shows through. The edge is feathered, so the piece melts into the face.
    """
    size = base.size
    region = clamp_box(tuple(int(round(v)) for v in region), size)
    width, height = region[2] - region[0], region[3] - region[1]
    if width < 6 or height < 6:
        return None
    edited = edited.convert("RGBA")
    if edited.size != size:
        edited = edited.resize(size)
    dx, dy = best_shift(base, edited, grow_box(region, 0.6, 0.6, size))
    if dx or dy:
        edited = edited.transform(size, Image.AFFINE, (1, 0, dx, 0, 1, dy), resample=Image.BILINEAR)
    diff = ImageChops.difference(base.convert("RGB").crop(region), edited.convert("RGB").crop(region)).convert("L")
    grow = max(3, (width // 24) * 2 + 1)
    mask = diff.point(lambda v: 255 if v >= threshold else 0).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    mask = mask.filter(ImageFilter.MaxFilter(grow)).filter(ImageFilter.MaxFilter(grow)).filter(ImageFilter.MinFilter(grow))
    if mask.getbbox() is None:
        return None  # the edit didn't change anything here
    if core is not None:
        local = (core[0] - region[0], core[1] - region[1], core[2] - region[0], core[3] - region[1])
        cw, ch = max(1, local[2] - local[0]), max(1, local[3] - local[1])
        inner = Image.new("L", mask.size, 0)
        reach = (int(local[0] - cw * 0.1), int(local[1] - ch * 0.15))
        inner.paste(ellipse_mask((int(cw * 1.2) + 1, int(ch * 1.3) + 1)), reach)
        mask = ImageChops.lighter(mask, inner)
    if mask.getbbox() is None:
        return None
    # Kept inside a soft ellipse over the region, on the skin.
    oval = Image.new("L", mask.size, 0)
    ImageDraw.Draw(oval).ellipse((width * 0.06, height * 0.06, width * 0.94, height * 0.94), fill=255)
    oval = oval.filter(ImageFilter.GaussianBlur(max(1.5, min(width, height) * 0.06)))
    mask = ImageChops.multiply(mask.filter(ImageFilter.GaussianBlur(max(1.2, grow / 3))), oval)
    mask = ImageChops.multiply(mask, skin.crop(region).filter(ImageFilter.GaussianBlur(1.2)))
    art = edited.crop(region)
    alpha = ImageChops.multiply(art.getchannel("A"), mask)
    art.putalpha(alpha)
    bbox = alpha.point(lambda v: 255 if v > 8 else 0).getbbox()
    if bbox is None:
        return None
    return Overlay(group, name, art.crop(bbox), region[0] + bbox[0], region[1] + bbox[1], parameter)


def edit_overlays(
    parts: list[Part],
    base: Image.Image,
    eyes_closed: Image.Image | None = None,
    mouth_open: Image.Image | None = None,
    angry_brows: Image.Image | None = None,
    grin: Image.Image | None = None,
    tears: Image.Image | None = None,
) -> list[Overlay]:
    """
    Hidden layers from the edited copies (all on the decomposition's canvas): blinking and talking,
    and drawn pieces for the strongest emotions, past what bending the rig can do: angry brows
    ("Brow L angry", ParamBrowAngry), a wide grin ("Mouth grin", ParamMouthGrin) and teary eyes
    ("Eye L tears", ParamTear).
    """
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
    face = _alpha_union(parts, base.size, ("face",))
    face_box = face.getbbox()
    if face_box is None or (angry_brows is None and grin is None and tears is None):
        return overlays
    face_w, face_h = face_box[2] - face_box[0], face_box[3] - face_box[1]
    # The pieces go on the face's skin, kept off its outline (edits redraw the jaw a little differently).
    margin = max(3, face_w // 40) * 2 + 1
    skin = face.point(lambda v: 255 if v > 200 else 0).filter(ImageFilter.MinFilter(margin))
    if angry_brows is not None:
        for side in ("L", "R"):
            brow = union_box([part_box(p) for p in parts if parse_tag(p.tag) in (("eyebrow", side), ("brow", side))])
            eye = cores.get(f"Eye {side}")
            if brow is None:
                continue
            # The brow and the upper lid under it (a scowl pulls the brow down onto the eye).
            near = union_box([brow, eye]) if eye else brow
            width = near[2] - near[0]
            bottom = eye[1] + (eye[3] - eye[1]) * 0.4 if eye else brow[3] + face_h * 0.03
            region = (near[0] - width * 0.15, brow[1] - max((brow[3] - brow[1]) * 0.6, face_h * 0.05), near[2] + width * 0.15, bottom)
            overlay = expression_piece(base, angry_brows, region, skin, "Face", f"Brow {side} angry", "ParamBrowAngry")
            if overlay:
                overlays.append(overlay)
    if grin is not None and "Mouth" in cores:
        mouth = cores["Mouth"]
        mx, my = (mouth[0] + mouth[2]) / 2, (mouth[1] + mouth[3]) / 2
        nose = union_box([part_box(p) for p in parts if parse_tag(p.tag)[0] == "nose"])
        top = nose[3] + face_h * 0.01 if nose and nose[3] < my else my - face_h * 0.12
        region = (mx - face_w * 0.3, top, mx + face_w * 0.3, min(face_box[3] - face_h * 0.02, my + face_h * 0.2))
        overlay = expression_piece(base, grin, region, skin, "Mouth", "Mouth grin", "ParamMouthGrin", core=mouth)
        if overlay:
            overlays.append(overlay)
    if tears is not None:
        eyes = _alpha_union(parts, base.size, ("eyewhite", "irides", "eyelash", "eye"))
        for group in ("Eye L", "Eye R"):
            if group not in cores:
                continue
            eye = cores[group]
            width, height = eye[2] - eye[0], eye[3] - eye[1]
            # The eye and the cheek under it, where the tears run.
            region = (eye[0] - width * 0.3, eye[1] - height * 0.35, eye[2] + width * 0.3, min(face_box[3] - face_h * 0.04, eye[3] + height * 2.4))
            overlay = expression_piece(base, tears, region, ImageChops.lighter(skin, eyes), group, f"{group} tears", "ParamTear", core=eye)
            if overlay:
                overlays.append(overlay)
    return overlays


def crop_parts(parts: list[Part], box: tuple[int, int, int, int]) -> list[Part]:
    """Move every part onto a smaller canvas whose top left corner is at box."""
    return [dataclasses.replace(part, left=part.left - box[0], top=part.top - box[1]) for part in parts]


# Layer split settings --------------------------------------------------------------
SEETHROUGH_REPO = "https://github.com/jtydhr88/ComfyUI-See-through"
VRAM_NOTE = (
    "See-through needs about 12-16 GB of VRAM at 1280 px and 20-24 GB at 2048 px (8 GB at 1280 px with the 4-bit models). "
    "A rented GPU (RunPod etc.) works the same as a local one; its models (about 10 GB) download on first use."
)


@dataclasses.dataclass(frozen=True)
class SplitSettings:
    # The square size See-through works at (the picture is padded to a square). 768-2048. The
    # layers become the puppet's textures, so the default is the highest.
    resolution: int = 2048
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
