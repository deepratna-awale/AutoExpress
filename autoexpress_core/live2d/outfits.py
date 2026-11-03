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
    wear = " ".join((inner_wear or "").split())[:200] or "a matching lace lingerie set (lace bra and lace panties) in a colour that suits her outfit"
    return f"Dress her in {wear}, and nothing else. " + KEEP + _describe(description)


def mid_instruction(description: str = "", garment: str = "") -> str:
    """The Qwen edit that takes the outermost layer off (the coat, jacket, haori...; garment when known)."""
    named = f"her {garment}" if garment else "the coat, jacket, blazer, cardigan, cape, robe or haori"
    return (
        f"Take off only her outermost layer of clothing: {named} worn "
        "open over her other clothes. Keep every garment under it (top, dress, skirt, trousers, belt, legwear) exactly "
        "as it is, drawn complete where the outer layer covered it. If she wears no outer layer, change nothing. " + KEEP + _describe(description)
    )


def outer_half_instruction(description: str = "", garment: str = "") -> str:
    """The Qwen edit with the outermost layer slipped halfway off."""
    named = f"her {garment}" if garment else "the coat, jacket, blazer, cardigan or haori"
    return (
        f"Her outermost layer of clothing ({named}) has slipped halfway off: it hangs "
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
    wear = " ".join((inner_wear or "").split())[:120] or "her panties"
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
        .replace("clothing: her ", "clothing: his ")
        .replace("clothing (her ", "clothing (his ")
        .replace("her shoulders", "his shoulders")
        .replace("her elbows", "his elbows")
        .replace("Open her top", "Open his top")
        .replace("on her shoulders", "on his shoulders")
        .replace("Her skirt is lifted up at the front, or her", "His")
        .replace("her bra", "his chest")
        .replace("her panties", "his briefs")
        .replace("her other clothes", "his other clothes")
        .replace("her build", "his build")
        .replace("her outfit", "his outfit")
        .replace("a matching lace lingerie set (lace bra and lace panties)", "simple briefs")
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
    # The edit's white background shut in between an arm and the body (the hand touching the hip)
    # isn't reached from the picture's border: skin is never this white over a patch.
    r, g, b = rgb.split()
    white = ImageChops.darker(ImageChops.darker(r, g), b).point(lambda v: 255 if v > 245 else 0)
    alpha = ImageChops.subtract(alpha, white.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(7)))
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


def _like(image: Image.Image, layer: Image.Image, tolerance: int = 60) -> Image.Image:
    """Where image (RGB) is close to the median colour of layer (RGBA), mode L 0/255."""
    solid = layer.getchannel("A").point(lambda v: 255 if v > 128 else 0)
    if solid.getbbox() is None:
        return Image.new("L", image.size, 0)
    colour = tuple(int(v) for v in ImageStat.Stat(layer.convert("RGB"), solid).median)
    return layers._difference(image, Image.new("RGB", image.size, colour)).point(lambda v: 255 if v < tolerance else 0)


def _skirt_under(skirt: Image.Image, coat: Image.Image, more: Image.Image) -> Image.Image:
    """
    skirt (RGBA, canvas size) with what lies under coat (mode L) painted as plain cloth from the
    skirt's colours outside it; more (mode L) is skirt the coat hid that the split left bare.
    """
    import numpy as np

    from .puppet import _push_pull

    solid = np.asarray(skirt.getchannel("A")) > 128
    hidden = np.asarray(coat) > 128
    region = solid | (np.asarray(more) > 128)
    known = solid & ~hidden
    unknown = region & ~known
    if not unknown.any() or known.sum() < 100:
        return skirt
    rgb = np.asarray(skirt.convert("RGB")).astype(np.float32)
    # From the skirt's own cloth: not its drawn lines and deep shadows (dark blots), nor specks of
    # the coat's colour the split left in it (a pale smudge).
    luma = rgb.mean(axis=2)
    colour = np.median(rgb[known], axis=0)
    cloth = known & (luma >= np.median(luma[known]) - 30) & (np.abs(rgb - colour).max(axis=2) < 70)
    filled = _push_pull(rgb, cloth if cloth.sum() >= 100 else known)
    filled = np.asarray(Image.fromarray(filled.clip(0, 255).astype(np.uint8), "RGB").filter(ImageFilter.GaussianBlur(8))).astype(np.float32)
    # Feathered into the drawn skirt, so no seam shows where the plain cloth starts.
    soft = np.asarray(Image.fromarray((unknown * 255).astype(np.uint8), "L").filter(ImageFilter.GaussianBlur(6))).astype(np.float32) / 255.0
    soft = np.maximum(soft, unknown)[..., None]
    out = rgb * (1 - soft) + filled * soft
    alpha = np.asarray(skirt.getchannel("A")).copy()
    alpha[region] = 255
    result = Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")
    result.putalpha(Image.fromarray(alpha, "L"))
    return result


def _row_span(mask: Image.Image) -> Image.Image:
    """mask (mode L) filled in each row from its leftmost to its rightmost pixel."""
    import numpy as np

    on = np.asarray(mask) > 127
    out = np.zeros_like(on)
    rows = np.flatnonzero(on.any(axis=1))
    if rows.size:
        first = on[rows].argmax(axis=1)
        last = on.shape[1] - 1 - on[rows][:, ::-1].argmax(axis=1)
        columns = np.arange(on.shape[1])
        out[rows] = (columns >= first[:, None]) & (columns <= last[:, None])
    return Image.fromarray((out * 255).astype(np.uint8), "L")


def _coat_shadow(skirt: Image.Image, coat: Image.Image, size) -> Image.Image:
    """
    The coat's shadow drawn on the skirt (mode L): skirt that shows just below and beside the coat
    and is clearly darker than the same column of skirt further from the coat. It belongs to the
    coat: with the coat off the skirt there is lit cloth. The skirt's own shading (its sides run
    dark all the way down) and thin drawn lines (the waistband's) stay with the skirt.
    """
    import numpy as np

    solid = np.asarray(skirt.getchannel("A")) > 128
    covered = np.asarray(coat) > 128
    shows = solid & ~covered
    if shows.sum() < 100 or not covered.any():
        return Image.new("L", size, 0)
    width, height = size
    scale = 4
    reach = max(3, (height // 30) // scale * 2 + 1)
    small = coat.resize((max(1, width // scale), max(1, height // scale)), Image.Resampling.NEAREST)
    near = np.asarray(small.filter(ImageFilter.MaxFilter(min(reach, 31))).resize(size, Image.Resampling.NEAREST)) > 128
    luma = np.asarray(skirt.convert("L")).astype(np.float32)
    lit = float(np.median(luma[shows]))
    span = min(reach, 31) * scale
    band = np.zeros_like(shows)
    for x in np.flatnonzero((shows & near).any(axis=0)):
        column = shows[:, x] & near[:, x]
        # The same column just past the coat's reach: what the cloth looks like without its shadow.
        last = int(np.flatnonzero(column)[-1])
        below = shows[last + 1 : last + 1 + span, x]
        reference = float(np.median(luma[last + 1 : last + 1 + span, x][below])) if below.sum() >= span // 4 else lit
        band[:, x] = column & (luma[:, x] < min(reference, lit) - 20)
    mask = Image.fromarray((band * 255).astype(np.uint8), "L")
    return mask.filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.MinFilter(3))


def slot_parts(
    parts: list,
    size,
    picture: Image.Image,
    edits: dict,
    nude: Image.Image | None = None,
    inner: Image.Image | None = None,
    outer: Image.Image | None = None,
) -> list:
    """
    The split's clothing rearranged into slots, the way Koikatsu dresses a character: the outermost
    layer (coat, jacket, haori) on its own layer apart from the top under it, and a half-off art
    for the coat (slipped off the shoulders), the top (opened at the front) and the bottom (skirt
    lifted), each cut from its drawn edit (MID, OUTER_HALF, TOP_HALF, BOTTOM_HALF; canvas size,
    RGBA). A half-off state is drawn, not faded: cloth that slips or opens changes its shape.

    picture is the original on the canvas; nude and inner the body and inner wear edits there, when
    made (the opened top and lifted skirt need what they uncover, so they come only with inner).
    outer (mode L, canvas size), when given, is a segmentation model's mask of the coat, which
    then sets its outline instead of comparing the picture with the coat-off edit. Returns the new
    list of parts (the split's, changed, plus the new layers).
    """
    body_tags = ("topwear", "bottomwear", "legwear", "footwear", "handwear", "neckwear")
    clothed = layers._alpha_union(parts, size, body_tags + ("neck",)).point(lambda v: 255 if v > 64 else 0)
    if clothed.getbbox() is None:
        return parts
    body_depths = [p.depth for p in parts if layers.classify(p.tag)[0] == "Body"]
    top_depth = min(body_depths, default=0.5)
    waist = waist_line(parts, size)
    face = layers._alpha_union(parts, size, ("face",)).getbbox()
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
        if outer is not None and outer.getbbox() is not None:
            # A segmentation model's mask of the coat (SAM 3): its own outline, exactly.
            # Grown by the coat's outline where the coat-off edit differs: the mask stops inside the
            # drawn line, which then stayed on the shirt and skirt as a pale or coat-coloured rim.
            sam = outer.point(lambda v: 255 if v > 127 else 0)
            rim = ImageChops.multiply(ImageChops.subtract(sam.filter(ImageFilter.MaxFilter(9)), sam), _changed(picture, mid))
            coat = ImageChops.multiply(ImageChops.lighter(sam, rim), clothed.filter(ImageFilter.MaxFilter(5)))
        else:
            coat = ImageChops.multiply(_changed(picture, mid), clothed)
            coat = _drop_small(coat, 0.004)
            # Closed and grown a little: the test misses the coat's edges and seams, which then
            # stayed behind in the top as coat-coloured patches with the coat off.
            coat = ImageChops.multiply(coat.filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.MinFilter(5)), clothed)
        if waist is not None:
            # A coat covers the shoulders and chest: what the edit changed only further down (a shoe
            # or a stocking redrawn a little differently) stays with its own garment.
            coat = layers.keep_touching(coat, (0, 0, size[0], waist))
        if 0.04 < _share(coat, clothed) < 0.85:
            skirt_part = next((p for p in result if layers.parse_tag(p.tag)[0] == "bottomwear"), None)
            shadow = _coat_shadow(layers._on_canvas(skirt_part, size), coat, size) if skirt_part is not None else Image.new("L", size, 0)
            # The coat's shadow on the skirt comes off with the coat.
            extra.append(_part("outer wear", _layer(picture, ImageChops.lighter(coat, shadow)), top_depth - 0.02))
            # Under the coat: the mid edit's clothes (its skin is the body layer's job when there is one).
            # A white shirt and pale skin differ by little, so the test is fine and the holes it
            # still leaves inside the cloth are closed (they showed the inner wear through the top).
            if under_base is None:
                under = coat
            else:
                close = max(5, ((face[2] - face[0]) // 10 if face else 15) // 2 * 2 + 1)
                cloth = _changed(mid, under_base, 18).filter(ImageFilter.MaxFilter(close)).filter(ImageFilter.MinFilter(close))
                under = ImageChops.multiply(coat, cloth)
            # Never the edit's white background: a shirt's sleeve is narrower than the coat's, and the
            # white beside it would hang round the arm as a pale halo once the coat is off.
            under = ImageChops.multiply(under, _key_from_white(mid).point(lambda v: 255 if v > 128 else 0))
            skirt_shape = layers._alpha_union(result, size, ("bottomwear",)).point(lambda v: 255 if v > 128 else 0)
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
            top_piece = under
            if has_bottom:
                # The top reaches a little past the waist where the edit shows no skirt there (a
                # shirt's hem the coat hid), so no gap opens between top and skirt with the coat off.
                bottom = next(p for p in result if layers.parse_tag(p.tag)[0] == "bottomwear")
                skirt_like = _like(mid, layers._on_canvas(bottom, size))
                hem = below(below(under, waist + max(4, size[1] // 60), True), waist, False)
                top_piece = ImageChops.lighter(below(under, waist, True), ImageChops.subtract(hem, skirt_like))
                # Arms hang below the waist: the shirt's sleeves down there, beside the skirt, are
                # the top's too (left out, the arms showed bare skin from the elbow down).
                beside = ImageChops.subtract(below(under, waist, False), skirt_shape.filter(ImageFilter.MaxFilter(9)))
                top_piece = ImageChops.lighter(top_piece, ImageChops.subtract(beside, skirt_like))
            for tag, piece in (("topwear", top_piece), ("bottomwear", below(under, waist, False) if has_bottom else None)):
                if piece is None or piece.getbbox() is None:
                    continue
                current = next((p for p in result if layers.parse_tag(p.tag)[0] == tag), None)
                if tag == "bottomwear" and current is not None:
                    # Under the coat's hem the skirt is plain cloth spread from its own visible
                    # colours: the edit redraws the skirt with a waistband and seams the drawing
                    # doesn't have, and the split's paint there is flat or carries the coat's shadow
                    # (that shadow stays in the coat layer and comes off with it).
                    result[result.index(current)] = _part(tag, _skirt_under(layers._on_canvas(current, size), ImageChops.lighter(coat, shadow), ImageChops.lighter(ImageChops.multiply(piece, skirt_shape), ImageChops.multiply(piece, _like(mid, layers._on_canvas(current, size))))), current.depth)
                    continue
                fill = _layer(mid, piece)
                if current is None:
                    extra.append(_part(tag, fill, top_depth))
                    continue
                canvas = layers._on_canvas(current, size)
                canvas.alpha_composite(fill)
                result[result.index(current)] = _part(tag, canvas, current.depth)
            half = edits.get(OUTER_HALF)
            if half is not None:
                # The slipped coat hangs beside the body too, in the gap between an arm and the
                # hips: the reach spans each row of the clothes from side to side.
                reach = _row_span(clothed).filter(ImageFilter.MaxFilter(31))
                slipped = ImageChops.multiply(ImageChops.multiply(_changed(half, mid), _key_from_white(half).point(lambda v: 255 if v > 128 else 0)), reach)
                # The edit often bares the shoulders under the slipped coat too: that skin isn't
                # coat. It is told by the body edit's skin at the same place (a pale coat can be
                # skin-coloured overall, so a single skin colour would take the coat too).
                if nude is not None:
                    bare = layers._difference(half, nude.convert("RGB")).point(lambda v: 255 if v < 24 else 0)
                    slipped = ImageChops.subtract(slipped, bare.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.MaxFilter(5)))
                slipped = _drop_small(slipped, 0.004)
                extra.append(_part("outer wear half", _layer(half, slipped), top_depth - 0.019))

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
