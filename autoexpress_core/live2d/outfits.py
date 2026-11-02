"""
Swappable clothing for puppets: the body, the inner wear and the outer clothes as separate layers.

Live2D artists who want outfits that can be changed draw the full body under the clothes and
every garment on its own layer, then switch them with expressions. A single picture only shows
the outer clothes, so the two hidden layers are drawn with Qwen-Image-Edit:

1. the character with the clothes taken off (the body layer), and
2. that body with plain inner wear on (bra and briefs, or whatever the user describes),

and cut out where they belong on the split's canvas. See-through's own clothing layers stay the
outer layer. The puppet then stacks body < inner wear < outer clothes, each with a switch
(ParamClothesInner, ParamClothesOuter) and outfit expressions (outfit_full, outfit_inner, outfit_nude).

The body and inner layers show nudity, so they are only made when all of this holds:
  * the user turned them on and confirmed the character is an adult,
  * the picture is a drawing (anime, cartoon, game art), never a photo of a real person,
  * nothing in the character's name or description reads as a child.
Otherwise the kit is built as before, with the clothes as one layer.

Only Pillow is needed.
"""

import re

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from . import layers

INNER, NUDE = "inner_wear", "nude_body"
# The extra edits for the clothing slots (Koikatsu style: every garment on, half off, or off).
MID = "no_outer_wear"  # the picture without the coat, jacket or other outermost layer
OUTER_HALF = "outer_wear_half"  # the coat slipped halfway off the shoulders
TOP_HALF = "top_half"  # the shirt or top opened at the front (from MID)
BOTTOM_HALF = "bottom_half"  # the skirt lifted, or the trousers pulled down a little (from MID)

# Words that read as a child or a young teenager. A character described with any of them gets no
# body or inner wear layers, whatever else the settings say.
MINOR_TERMS = (
    "child", "children", "kid", "kids", "toddler", "baby", "infant", "minor", "underage", "under age",
    "preteen", "pre-teen", "tween", "young girl", "young boy", "little girl", "little boy", "schoolgirl",
    "schoolboy", "school girl", "school boy", "elementary", "middle school", "middle schooler",
    "junior high", "grade school", "loli", "lolicon", "shota", "shotacon", "toddlercon", "jailbait",
    "petite child", "childlike", "child-like", "kindergarten", "daughter", "son", "teen", "teenager",
    "teenage", "adolescent", "pubescent", "prepubescent", "juvenile", "youngster",
)
_YEARS = re.compile(r"\b(1[0-7]|[1-9])\s*(?:-|\s)?(?:years?|yrs?|y/?o)\b(?:\s*old)?", re.IGNORECASE)
_AGE = re.compile(r"\bage[d:]?\s*(1[0-7]|[1-9])\b", re.IGNORECASE)

KEEP = (
    "Keep the face, expression, hair, pose, body proportions, camera framing, line art, colours, "
    "art style and background exactly the same."
)


def blocked_terms(*texts: str) -> list[str]:
    """The child-coded words and ages found in texts (empty when none)."""
    text = " ".join(t for t in texts if t).lower()
    found = [term for term in MINOR_TERMS if re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", text)]
    found += [m.group(0) for m in _YEARS.finditer(text)]
    found += [m.group(0) for m in _AGE.finditer(text)]
    return found


def drawing_score(image: Image.Image) -> float:
    """
    How much the picture looks drawn (0..1); above 0.5 it is a drawing.

    Two things tell a drawing from a photo (or a photoreal render): drawings are calm, most of the
    character is flat colour or a smooth gradient with no grain (photos have sensor noise and skin
    texture everywhere), and they have ink lines, thin strokes much darker than what's around them.
    A very flat picture is a drawing even with few lines; otherwise it needs both.
    """
    small = image.convert("RGB")
    small.thumbnail((512, 512))
    grey = small.convert("L")
    background = small.getpixel((0, 0))
    distance = ImageChops.difference(small, Image.new("RGB", small.size, background)).convert("L")
    subject = distance.point(lambda v: 255 if v > 24 else 0)
    total = ImageStat.Stat(subject).sum[0] / 255
    if total < 50:
        return 0.0
    residual = ImageChops.difference(grey, grey.filter(ImageFilter.MedianFilter(3)))
    calm = ImageStat.Stat(ImageChops.multiply(subject, residual.point(lambda v: 255 if v <= 1 else 0))).sum[0] / 255 / total
    ink = ImageChops.subtract(grey.filter(ImageFilter.MedianFilter(7)), grey).point(lambda v: 255 if v > 45 else 0)
    lines = ImageStat.Stat(ImageChops.multiply(subject, ink)).sum[0] / 255 / total
    if calm >= 0.85:
        return round(calm, 3)
    return round(calm, 3) if lines >= 0.012 else round(min(calm, 0.45) * 0.5, 3)


def check(settings: dict, picture: Image.Image, name: str = "", safe_mode: bool | None = None) -> tuple[bool, str]:
    """
    (allowed, why not) for the body and inner wear layers. See the module docstring.

    safe_mode (default on, or settings["safe_mode"]) runs the drawing check on the picture. Off,
    for drawings the check wrongly reads as photos, the picture is taken as the drawing the user
    confirmed it is. The adult confirmation and the child check always run.
    """
    if safe_mode is None:
        safe_mode = settings.get("safe_mode", True) is not False
    if not settings.get("outfit_layers"):
        return False, "Swappable clothing is off."
    if not settings.get("adult_confirmed"):
        return False, "Swappable clothing needs you to confirm the character is an adult."
    if settings.get("is_realistic") or settings.get("photo"):
        return False, "Swappable clothing is only made for drawn characters, never for photos."
    score = drawing_score(picture) if safe_mode else 1.0
    if score < 0.5:
        return False, f"The picture looks like a photo (drawing score {score:.2f}), so no body or inner wear layers were made. They are only made for drawn characters."
    found = blocked_terms(
        name,
        settings.get("character_description", ""),
        settings.get("inner_wear", ""),
        settings.get("outfit_prompt", ""),
        settings.get("prompt_data", ""),
    )
    if found:
        return False, "The character's name or description reads as a child (" + ", ".join(sorted(set(found))[:5]) + "), so no body or inner wear layers were made."
    return True, ""


def _describe(description: str) -> str:
    description = " ".join((description or "").split())[:400]
    return f" The character: {description}." if description else ""


REVEALING = re.compile(
    r"(?<![a-z])(nude|naked|topless|bottomless|nothing|undressed|unclothed|lingerie|underwear|bra|bras|panties|panty|thong|"
    r"g-string|bikini|micro bikini|see-through|sheer|transparent|nipples?|pasties|body paint)(?![a-z])",
    re.IGNORECASE,
)


def revealing(text: str) -> bool:
    """Whether an outfit asks for nudity or underwear (then it needs the same check as the body layer)."""
    return bool(REVEALING.search(text or ""))


def outfit_instruction(outfit: str, description: str = "") -> str:
    """The Qwen edit that dresses the character in the outfit the user asked for, before the split."""
    outfit = " ".join((outfit or "").split())[:300]
    return f"Change her clothes to {outfit}. Keep any accessories that still fit. " + KEEP + _describe(description)


def nude_instruction(description: str = "") -> str:
    """The Qwen edit that takes the clothes off (the body layer)."""
    return (
        "Remove all of the clothing, underwear, socks and shoes so she is fully nude, showing the adult woman's natural "
        "body under the clothes with anatomy that fits her build, drawn in the same style and shading as the picture. "
        "Keep hair accessories and the hairstyle. " + KEEP + _describe(description)
    )


def inner_instruction(inner_wear: str = "", description: str = "") -> str:
    """The Qwen edit that puts inner wear on the body layer."""
    wear = " ".join((inner_wear or "").split())[:200] or "a simple matching bra and briefs in a colour that suits her outfit"
    return f"Dress her in {wear}, and nothing else. " + KEEP + _describe(description)


def mid_instruction(description: str = "") -> str:
    """The Qwen edit that takes the outermost layer off (the coat, jacket, haori...)."""
    return (
        "Take off only her outermost layer of clothing: the coat, jacket, blazer, cardigan, cape, robe or haori worn "
        "open over her other clothes. Keep every garment under it (top, dress, skirt, trousers, belt, legwear) exactly "
        "as it is, drawn complete where the outer layer covered it. If she wears no outer layer, change nothing. " + KEEP + _describe(description)
    )


def outer_half_instruction(description: str = "") -> str:
    """The Qwen edit with the outermost layer slipped halfway off."""
    return (
        "Her outermost layer of clothing (the coat, jacket, blazer, cardigan or haori) has slipped halfway off: it hangs "
        "down off both shoulders to her elbows, showing her shoulders and the clothes under it. Change nothing else. " + KEEP + _describe(description)
    )


def top_half_instruction(inner_wear: str = "", description: str = "") -> str:
    """The Qwen edit with the top opened at the front (from the picture without the outer layer)."""
    wear = " ".join((inner_wear or "").split())[:120] or "her bra"
    return (
        f"Open her top at the front: unbuttoned or loosened and pulled open, showing {wear} underneath. "
        "The top stays on her shoulders. Change nothing else. " + KEEP + _describe(description)
    )


def bottom_half_instruction(inner_wear: str = "", description: str = "") -> str:
    """The Qwen edit with the skirt lifted, or the trousers pulled down a little."""
    wear = " ".join((inner_wear or "").split())[:120] or "her briefs"
    return (
        f"Her skirt is lifted up at the front, or her shorts or trousers pulled down a little, showing {wear}. "
        "Change nothing else. " + KEEP + _describe(description)
    )


def male_words(description: str) -> bool:
    return bool(re.search(r"\b(he|him|his|man|male|boy|guy|husband|father|king|prince)\b", (description or "").lower()))


def adapt(instruction: str, description: str) -> str:
    """The instructions are written for a woman; switch the words for a male character."""
    if not male_words(description):
        return instruction
    return (
        instruction.replace("adult woman's", "adult man's")
        .replace("so she is", "so he is")
        .replace("Dress her", "Dress him")
        .replace("Change her clothes", "Change his clothes")
        .replace("only her outermost", "only his outermost")
        .replace("Her outermost", "His outermost")
        .replace("her shoulders", "his shoulders")
        .replace("her elbows", "his elbows")
        .replace("Open her top", "Open his top")
        .replace("on her shoulders", "on his shoulders")
        .replace("Her skirt is lifted up at the front, or her", "His")
        .replace("her other clothes", "his other clothes")
        .replace("her bra", "his chest")
        .replace("her build", "his build")
        .replace("her outfit", "his outfit")
        .replace("a simple matching bra and briefs", "simple briefs")
    )


# Cutting the layers out ------------------------------------------------------------------------
def _key_from_white(image: Image.Image) -> Image.Image:
    """
    Alpha (mode L) of a character drawn on white: everything but the white background around it.

    The background is the near-white area connected to the picture's border (flood filled), not
    every light pixel, so pale skin inside the character's outline stays.
    """
    rgb = image.convert("RGB")
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, (255, 255, 255)))
    r, g, b = diff.split()
    distance = ImageChops.lighter(ImageChops.lighter(r, g), b)
    scale = max(1, max(rgb.size) // 1024)
    small = distance.resize((rgb.width // scale, rgb.height // scale), Image.Resampling.BILINEAR)
    light = small.point(lambda v: 255 if v < 14 else 0)
    width, height = light.size
    seeds = [(x, y) for x in range(0, width, 8) for y in (0, height - 1)] + [(x, y) for y in range(0, height, 8) for x in (0, width - 1)]
    for seed in seeds:
        if light.getpixel(seed) == 255:
            ImageDraw.floodfill(light, seed, 128)
    background = light.point(lambda v: 255 if v == 128 else 0).resize(rgb.size, Image.Resampling.BILINEAR)
    alpha = background.point(lambda v: 255 - v)
    # A soft edge where the character meets the background.
    edge = distance.point(lambda v: 0 if v < 8 else 255 if v > 40 else (v - 8) * 255 // 32)
    near_background = background.filter(ImageFilter.MaxFilter(3))
    return ImageChops.lighter(ImageChops.subtract(alpha, near_background), ImageChops.multiply(edge, ImageChops.multiply(alpha, near_background)))


def _colour_distance(image: Image.Image, colour) -> Image.Image:
    return ImageChops.difference(image.convert("RGB"), Image.new("RGB", image.size, tuple(colour))).convert("L")


def body_layer(nude: Image.Image, parts: list, size) -> Image.Image | None:
    """
    The body layer (RGBA, canvas size) from the nude edit, already placed on the split's canvas.

    Kept: inside the clothed character's body (the clothes, arms and neck layers, since the body is
    under the clothes), below the chin, and not where the edit drew hair.
    """
    body_tags = ("neck", "topwear", "bottomwear", "legwear", "footwear", "handwear", "neckwear")
    clothed = layers._alpha_union(parts, size, body_tags)
    box = clothed.getbbox()
    if box is None:
        return None
    face = layers._alpha_union(parts, size, ("face",)).getbbox()
    # Only a hair wider than the clothed body: the edit never puts the limbs exactly where they were,
    # and a body sticking out past the clothes would show around them in the full outfit.
    region = clothed.point(lambda v: 255 if v > 64 else 0).filter(ImageFilter.MaxFilter(3))
    alpha = ImageChops.multiply(_key_from_white(nude), region)
    if face:
        # Only under the face: an arm raised beside the head stays.
        chin = face[3] - (face[3] - face[1]) * 0.12
        reach = (face[2] - face[0]) * 0.15
        cut = Image.new("L", size, 255)
        cut.paste(0, (max(0, int(face[0] - reach)), 0, min(size[0], int(face[2] + reach)), max(0, int(chin))))
        alpha = ImageChops.multiply(alpha, cut)
    # Hair the edit kept over the body belongs to the hair layers: drop pixels of the hair's colour
    # that aren't also close to the skin's.
    rgb = nude.convert("RGB")
    hair = layers._alpha_union(parts, size, ("front hair", "back hair", "hair")).point(lambda v: 255 if v > 128 else 0)
    skin = layers._alpha_union(parts, size, ("face", "neck")).point(lambda v: 255 if v > 200 else 0)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    for part in parts:
        canvas.alpha_composite(part.image.convert("RGBA"), (part.left, part.top))
    if hair.getbbox() and skin.getbbox():
        hair_colour = ImageStat.Stat(canvas.convert("RGB"), hair).median
        skin_colour = ImageStat.Stat(canvas.convert("RGB"), skin).median
        near_hair = _colour_distance(rgb, hair_colour).point(lambda v: 255 if v < 36 else 0)
        far_skin = _colour_distance(rgb, skin_colour).point(lambda v: 255 if v > 70 else 0)
        drop = ImageChops.multiply(near_hair, far_skin).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(5))
        alpha = ImageChops.subtract(alpha, drop)
    alpha = alpha.filter(ImageFilter.MedianFilter(3))
    if alpha.getbbox() is None:
        return None
    layer = nude.convert("RGBA")
    layer.putalpha(alpha)
    return layers.solidify(layer)


def inner_layer(inner: Image.Image, nude: Image.Image, body: Image.Image, threshold: int = 36) -> Image.Image | None:
    """
    The inner wear layer (RGBA, canvas size): where the inner wear edit differs from the nude edit,
    inside the body layer. Small specks (the two edits never match pixel for pixel) are dropped.
    """
    diff = ImageChops.difference(inner.convert("RGB"), nude.convert("RGB")).convert("L")
    mask = diff.point(lambda v: 255 if v >= threshold else 0)
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    mask = mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))
    region = body.getchannel("A").filter(ImageFilter.MaxFilter(5))
    mask = ImageChops.multiply(mask, region)
    mask = _drop_small(mask, 0.002)
    if mask.getbbox() is None:
        return None
    layer = inner.convert("RGBA")
    layer.putalpha(mask.filter(ImageFilter.GaussianBlur(0.8)))
    return layers.solidify(layer)


def _drop_small(mask: Image.Image, share: float) -> Image.Image:
    """mask without the connected pieces smaller than share of its box (flood fill, Pillow only)."""
    box = mask.getbbox()
    if box is None:
        return mask
    small = mask.point(lambda v: 255 if v > 127 else 0)
    width, height = small.size
    scale = max(1, max(width, height) // 512)
    work = small.resize((width // scale, height // scale), Image.Resampling.NEAREST)
    pixels = work.load()
    w, h = work.size
    minimum = share * w * h
    keep = Image.new("L", work.size, 0)
    out = keep.load()
    seen = bytearray(w * h)
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
                if len(piece) >= minimum:
                    for px, py in piece:
                        out[px, py] = 255
    keep = keep.resize(small.size, Image.Resampling.NEAREST).filter(ImageFilter.MaxFilter(3))
    return ImageChops.multiply(mask, keep)


def outfit_parts(parts: list, size, nude: Image.Image | None, inner: Image.Image | None) -> list:
    """The body and inner wear Parts for the split (both edits on its canvas), as many as could be made."""
    if nude is None:
        return []
    body = body_layer(nude, parts, size)
    if body is None:
        return []
    depth = max((p.depth for p in parts if layers.classify(p.tag)[0] == "Body"), default=1.0)
    result = []
    box = body.getchannel("A").getbbox()
    result.append(layers.Part("nude body", body.crop(box), box[0], box[1], depth))
    if inner is not None:
        wear = inner_layer(inner, nude, body)
        if wear is not None:
            for tag, piece in split_inner(wear, parts, size):
                box = piece.getchannel("A").getbbox()
                result.append(layers.Part(tag, piece.crop(box), box[0], box[1], depth))
    return result


def waist_line(parts: list, size) -> int | None:
    """
    Where the top half of the clothes meets the bottom half (canvas y): the top of the skirt or
    trousers, else the bottom of the top; None for a picture with neither (a dress, or no split).
    """
    bottom = layers._alpha_union(parts, size, ("bottomwear",)).point(lambda v: 255 if v > 128 else 0).getbbox()
    top = layers._alpha_union(parts, size, ("topwear",)).point(lambda v: 255 if v > 128 else 0).getbbox()
    if bottom and top and bottom[1] > top[1]:
        return bottom[1]
    if top and not bottom:
        return top[3]
    return None


def split_inner(wear: Image.Image, parts: list, size) -> list[tuple[str, Image.Image]]:
    """
    The inner wear as its pieces, so each can come off on its own: [("inner top", bra), ("inner
    bottom", briefs)] split at the waist, or [("inner wear", all of it)] when it can't be split
    (no waist line, or one side is only specks, as with a one-piece).
    """
    waist = waist_line(parts, size)
    alpha = wear.getchannel("A")
    box = alpha.getbbox()
    if waist is None or box is None or not box[1] < waist < box[3]:
        return [("inner wear", wear)]
    # Cut through the gap between the pieces (bare midriff) nearest the waist; a one-piece has no gap.
    height = box[3] - box[1]
    rows = alpha.crop((0, box[1], size[0], box[3])).point(lambda v: 255 if v > 64 else 0).resize((1, height), Image.Resampling.BOX)
    widths = [rows.getpixel((0, y)) for y in range(height)]
    low, high = max(0, waist - box[1] - int(height * 0.25)), min(height, waist - box[1] + int(height * 0.15))
    if high <= low:
        return [("inner wear", wear)]
    gap = min(range(low, high), key=lambda y: (widths[y], abs(y + box[1] - waist)))
    # A one-piece crosses every row there; specks the edits left (they never match pixel for
    # pixel) can cross the gap of a two-piece, so the gap only has to be much narrower than the wear.
    if widths[gap] > max(2, 0.2 * max(widths)):
        return [("inner wear", wear)]
    waist = box[1] + gap
    pieces = []
    for tag, region in (("inner top", (0, 0, size[0], waist)), ("inner bottom", (0, waist, size[0], size[1]))):
        mask = Image.new("L", size, 0)
        mask.paste(255, region)
        piece = wear.copy()
        piece.putalpha(ImageChops.multiply(alpha, mask))
        kept = ImageStat.Stat(piece.getchannel("A")).sum[0]
        pieces.append((tag, piece, kept))
    total = sum(kept for _, _, kept in pieces) or 1
    if min(kept for _, _, kept in pieces) / total < 0.08:
        return [("inner wear", wear)]
    return [(tag, piece) for tag, piece, _ in pieces]


# Clothing slots ------------------------------------------------------------------------------
def _changed(a: Image.Image, b: Image.Image, threshold: int = 40) -> Image.Image:
    """Where two pictures of the same character differ (mode L), without the specks of an edit's drift."""
    diff = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    r, g, bl = diff.split()
    mask = ImageChops.lighter(ImageChops.lighter(r, g), bl).point(lambda v: 255 if v >= threshold else 0)
    mask = mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(3))
    return mask.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))


def _layer(colours: Image.Image, alpha: Image.Image) -> Image.Image | None:
    if alpha.getbbox() is None:
        return None
    layer = colours.convert("RGBA")
    if colours.mode == "RGBA":
        alpha = ImageChops.multiply(alpha, colours.getchannel("A"))
    layer.putalpha(alpha.filter(ImageFilter.GaussianBlur(0.7)))
    return layers.solidify(layer)


def _part(tag: str, image: Image.Image | None, depth: float):
    if image is None:
        return None
    box = image.getchannel("A").getbbox()
    return layers.Part(tag, image.crop(box), box[0], box[1], depth) if box else None


def _share(mask: Image.Image, of: Image.Image) -> float:
    total = ImageStat.Stat(of).sum[0]
    return ImageStat.Stat(mask).sum[0] / total if total else 0.0


def slot_parts(parts: list, size, picture: Image.Image, edits: dict, nude: Image.Image | None = None, inner: Image.Image | None = None) -> list:
    """
    The split's clothing rearranged into slots, the way Koikatsu dresses a character: the outermost
    layer (coat, jacket, haori) on its own layer apart from the top under it, and a half-off art
    for the coat (slipped off the shoulders), the top (opened at the front) and the bottom (skirt
    lifted), each from its edit (MID, OUTER_HALF, TOP_HALF, BOTTOM_HALF; canvas size, RGBA).

    picture is the original on the canvas; nude and inner the body and inner wear edits there, when
    made (the half-off arts need what they uncover, so they come only with the inner wear).
    Returns the new list of parts (the split's, changed, plus the new layers).
    """
    body_tags = ("topwear", "bottomwear", "legwear", "footwear", "handwear", "neckwear")
    clothed = layers._alpha_union(parts, size, body_tags + ("neck",)).point(lambda v: 255 if v > 64 else 0)
    if clothed.getbbox() is None:
        return parts
    body_depths = [p.depth for p in parts if layers.classify(p.tag)[0] == "Body"]
    top_depth = min(body_depths, default=0.5)
    waist = waist_line(parts, size)
    result = list(parts)
    extra = []
    under_base = nude if nude is not None else None

    def below(mask: Image.Image, y: int | None, upper: bool) -> Image.Image:
        if y is None:
            return mask if upper else Image.new("L", size, 0)
        cut = Image.new("L", size, 0)
        cut.paste(255, (0, 0, size[0], y) if upper else (0, y, size[0], size[1]))
        return ImageChops.multiply(mask, cut)

    mid = edits.get(MID)
    if mid is not None:
        coat = ImageChops.multiply(_changed(picture, mid), clothed)
        coat = _drop_small(coat, 0.004)
        if 0.04 < _share(coat, clothed) < 0.85:
            extra.append(_part("outer wear", _layer(picture, coat), top_depth - 0.02))
            # Under the coat: the mid edit's clothes (its skin is the body layer's job when there is one).
            under = coat if under_base is None else ImageChops.multiply(coat, _changed(mid, under_base, 36))
            changed = []
            for part in result:
                if layers.parse_tag(part.tag)[0] not in body_tags:
                    changed.append(part)
                    continue
                canvas = layers._on_canvas(part, size)
                canvas.putalpha(ImageChops.subtract(canvas.getchannel("A"), coat))
                kept = _part(part.tag, canvas if canvas.getchannel("A").getbbox() else None, part.depth)
                if kept:
                    changed.append(kept)
            result = changed
            has_bottom = any(layers.parse_tag(p.tag)[0] == "bottomwear" for p in result)
            for tag, piece in (("topwear", below(under, waist, True) if has_bottom else under), ("bottomwear", below(under, waist, False) if has_bottom else None)):
                if piece is None or piece.getbbox() is None:
                    continue
                fill = _layer(mid, piece)
                current = next((p for p in result if layers.parse_tag(p.tag)[0] == tag), None)
                if current is None:
                    extra.append(_part(tag, fill, top_depth))
                    continue
                canvas = layers._on_canvas(current, size)
                canvas.alpha_composite(fill)
                result[result.index(current)] = _part(tag, canvas, current.depth)
            half = edits.get(OUTER_HALF)
            if half is not None:
                reach = clothed.filter(ImageFilter.MaxFilter(31))
                slipped = ImageChops.multiply(ImageChops.multiply(_changed(half, mid), _key_from_white(half).point(lambda v: 255 if v > 128 else 0)), reach)
                extra.append(_part("outer wear half", _layer(half, _drop_small(slipped, 0.004)), top_depth - 0.019))

    if inner is not None:
        for key, tag in ((TOP_HALF, "topwear"), (BOTTOM_HALF, "bottomwear")):
            half = edits.get(key)
            garment = next((p for p in result if layers.parse_tag(p.tag)[0] == tag), None)
            if half is None or garment is None:
                continue
            region = layers._on_canvas(garment, size, "A").point(lambda v: 255 if v > 64 else 0).filter(ImageFilter.MaxFilter(41 if tag == "bottomwear" else 15))
            # Where the half-off art is clothing: different from the inner wear edit under it.
            cloth = ImageChops.multiply(ImageChops.multiply(_changed(half, inner), region), _key_from_white(half).point(lambda v: 255 if v > 128 else 0))
            extra.append(_part(f"{tag} half", _layer(half, _drop_small(cloth, 0.004)), garment.depth - 0.001))
    return result + [p for p in extra if p is not None]
