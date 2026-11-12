"""
The undress chain: the picture, then one garment fewer per state, each state an edit of the one before.

The garment manifest (garments.py) gives the order. For each state the previous state is edited
with Qwen-Image-Edit so exactly one garment comes off, and the edit is then made consistent:

  align     the edit is moved and scaled to lie over the previous state, matched on what didn't change
            (Qwen hands its edits back a little zoomed and shifted)
  colour    a per-channel linear fit in Lab on the unchanged part takes out Qwen's colour drift
  pixel     the region R is the removed garment's mask (from the segmentation model, else what the
  lock      edit changed) grown 5 px, never the head or the hands, never outside the previous figure,
            plus the garment's cast shadow on what it covered. Outside R every pixel is copied from the
            previous state, so nothing else in the picture can change.
  skin      skin the edit reveals is colour-locked to the face's lit skin in Lab (CIEDE2000 under 3)
  lock

A garment's layer is then the pixels of the state before its removal inside its matte, the body
is the last state, and the layers stacked over the body give the picture back. A half state (the
jacket slipped off the shoulders, the shirt open, the skirt lifted) is drawn from the state in which
its garment is outermost, and only the garment's own pixels are kept, over the next state, so
nothing the chain didn't draw (an invented bra, stockings) can come in with it.

Images that show inner wear or less are named INTERNAL_ (see garments.derive) and never go in a
preview or contact sheet.

Only numpy and Pillow are needed; the edits and masks come from the WebUI.
"""

import dataclasses
from collections.abc import Callable

from PIL import Image, ImageDraw, ImageFilter

from .. import instruction_edit
from ..images import pil_to_b64
from . import garments as tags
from . import outfits

WHITE = 250  # brighter than this on every channel is the white background
GROW = 5  # how far R reaches past the garment's mask
FEATHER = 3  # px of soft edge inside R
SKIN_DE = 3.0  # the revealed skin is within this CIEDE2000 of the face's
HEAD_PROMPT = "head, hair, face"
HANDS_PROMPT = "hands"
FACE_PROMPT = "face"
FIGURE_PROMPT = "person"

KEEP = (
    "Keep everything else exactly the same: the same pose, the same face, hair, hands and fingers, the same lighting, "
    "line art and shading, the same framing and size, plain white background. Do not add any accessories, jewellery or pattern."
)


# Colour ------------------------------------------------------------------------------------------
def _np():
    import numpy as np

    return np


def to_lab(rgb):
    """sRGB (uint8, ... x 3) to CIE Lab (D65), float."""
    np = _np()
    c = np.asarray(rgb, dtype=np.float64) / 255.0
    c = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    m = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > (6 / 29) ** 3, np.cbrt(xyz), xyz / (3 * (6 / 29) ** 2) + 4 / 29)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def from_lab(lab):
    """CIE Lab back to sRGB uint8."""
    np = _np()
    lab = np.asarray(lab, dtype=np.float64)
    fy = (lab[..., 0] + 16) / 116
    f = np.stack([fy + lab[..., 1] / 500, fy, fy - lab[..., 2] / 200], -1)
    xyz = np.where(f > 6 / 29, f ** 3, 3 * (6 / 29) ** 2 * (f - 4 / 29)) * np.array([0.95047, 1.0, 1.08883])
    m = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560], [0.0556434, -0.2040259, 1.0572252]])
    c = np.clip(xyz @ m.T, 0, 1)
    c = np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1 / 2.4) - 0.055)
    return np.clip(np.rint(c * 255), 0, 255).astype(np.uint8)


def de2000(lab1, lab2) -> float:
    """CIEDE2000 colour difference between two Lab colours."""
    np = _np()
    L1, a1, b1 = (float(v) for v in lab1)
    L2, a2, b2 = (float(v) for v in lab2)
    c1, c2 = np.hypot(a1, b1), np.hypot(a2, b2)
    cm = (c1 + c2) / 2
    g = 0.5 * (1 - np.sqrt(cm ** 7 / (cm ** 7 + 25.0 ** 7)))
    a1p, a2p = a1 * (1 + g), a2 * (1 + g)
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dL, dC = L2 - L1, c2p - c1p
    dh = 0.0 if c1p * c2p == 0 else (h2p - h1p if abs(h2p - h1p) <= 180 else h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360)
    dH = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2))
    Lm, cmp_ = (L1 + L2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        hm = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hm = (h1p + h2p) / 2
    else:
        hm = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    t = 1 - 0.17 * np.cos(np.radians(hm - 30)) + 0.24 * np.cos(np.radians(2 * hm)) + 0.32 * np.cos(np.radians(3 * hm + 6)) - 0.20 * np.cos(np.radians(4 * hm - 63))
    sl = 1 + 0.015 * (Lm - 50) ** 2 / np.sqrt(20 + (Lm - 50) ** 2)
    sc, sh = 1 + 0.045 * cmp_, 1 + 0.015 * cmp_ * t
    rt = -2 * np.sqrt(cmp_ ** 7 / (cmp_ ** 7 + 25.0 ** 7)) * np.sin(np.radians(60 * np.exp(-(((hm - 275) / 25) ** 2))))
    return float(np.sqrt((dL / sl) ** 2 + (dC / sc) ** 2 + (dH / sh) ** 2 + rt * (dC / sc) * (dH / sh)))


# Masks -------------------------------------------------------------------------------------------
def grow(mask, radius: int):
    """mask (numpy bool) grown by radius px (a 3x3 step at a time)."""
    np = _np()
    m = np.asarray(mask, bool).copy()
    for _ in range(max(0, int(radius))):
        n = m.copy()
        n[1:] |= m[:-1]
        n[:-1] |= m[1:]
        n[:, 1:] |= m[:, :-1]
        n[:, :-1] |= m[:, 1:]
        m = n
    return m


def shrink(mask, radius: int):
    return ~grow(~_np().asarray(mask, bool), radius)


def fill_holes(mask):
    """mask with every hole that doesn't reach the border filled."""
    np = _np()
    m = np.asarray(mask, bool)
    padded = np.pad(m, 1).astype(np.uint8) * 255
    image = Image.fromarray(padded).copy()  # a copy: an image over a numpy buffer doesn't take the fill
    ImageDraw.floodfill(image, (0, 0), 128)
    outside = np.asarray(image)[1:-1, 1:-1] == 128
    return ~outside


def silhouette(rgb):
    """Where the figure is in a picture on white (holes filled, so white cloth inside it counts)."""
    np = _np()
    return fill_holes(grow(np.asarray(rgb).min(-1) < WHITE, 1))


def feather(region, px: int = FEATHER):
    """1 well inside region, a ramp to 0 at its edge, exactly 0 outside."""
    np = _np()
    weight = np.zeros(np.asarray(region).shape, np.float32)
    inside = np.asarray(region, bool)
    for _ in range(px + 1):
        weight += inside
        inside = shrink(inside, 1)
    return weight / float(px + 1)


def as_mask(image: Image.Image | None, size, threshold: int = 127):
    """A mask image (mode L) as numpy bool at size, or None."""
    np = _np()
    if image is None:
        return None
    image = image.convert("L")
    if image.size != size:
        image = image.resize(size, Image.Resampling.BILINEAR)
    return np.asarray(image) > threshold


def rgb_array(image: Image.Image):
    np = _np()
    rgba = image.convert("RGBA")
    flat = Image.new("RGB", rgba.size, (255, 255, 255))
    flat.paste(rgba, mask=rgba.getchannel("A"))
    return np.asarray(flat).copy()


# Alignment and locks ---------------------------------------------------------------------------------
def _shifted(image: Image.Image, scale: float, dx: float, dy: float, centre) -> Image.Image:
    cx, cy = centre
    return image.transform(image.size, Image.AFFINE, (scale, 0, cx - cx * scale + dx, 0, scale, cy - cy * scale + dy), resample=Image.BICUBIC, fillcolor=(255, 255, 255))


def align(prev, edit, still, reach: int = 24):
    """
    edit moved and scaled to lie over prev, matched on still (where nothing should change): the
    shift and zoom with the smallest mean difference there, found coarse to fine. Returns (aligned,
    (scale, dx, dy), residual before, residual after).
    """
    np = _np()
    prev, edit, still = np.asarray(prev), np.asarray(edit), np.asarray(still, bool)
    h, w = still.shape
    full_before = float(np.abs(edit.astype(np.float32) - prev.astype(np.float32)).mean(-1)[still].mean()) if still.any() else 0.0
    if still.sum() < 100:
        return edit.copy(), (1.0, 0.0, 0.0), full_before, full_before
    edit_image = Image.fromarray(edit).convert("RGB")
    still_image = Image.fromarray((still * 255).astype(np.uint8))

    def level(factor):
        size = (max(1, round(w / factor)), max(1, round(h / factor)))
        a = np.asarray(Image.fromarray(prev).convert("L").resize(size, Image.Resampling.BOX), np.float32)
        keep = np.asarray(still_image.resize(size, Image.Resampling.BOX)) > 200
        if keep.sum() < 20:
            keep = np.asarray(still_image.resize(size, Image.Resampling.BOX)) > 0
        image = edit_image.resize(size, Image.Resampling.BOX) if factor > 1 else edit_image
        centre = (size[0] / 2, size[1] / 2)

        def score(scale, dx, dy):
            moved = np.asarray(_shifted(image, scale, dx, dy, centre).convert("L"), np.float32)
            return float(np.abs(moved - a)[keep].mean())

        return score

    factors = [f for f in (16, 8, 4, 2) if max(h, w) / f >= 48] + [1]
    scale, dx, dy = 1.0, 0.0, 0.0
    for index, factor in enumerate(factors):
        score = level(factor)
        if index == 0:
            r = max(1, int(np.ceil(reach / factor)))
            scales, shifts = (0.97, 0.98, 0.99, 1.0, 1.01, 1.02, 1.03), range(-r, r + 1)
        else:
            scales, shifts = (scale - 0.005, scale, scale + 0.005), (-1, 0, 1)
            dx, dy = dx * factors[index - 1] / factor, dy * factors[index - 1] / factor
        best = (score(scale, dx, dy), scale, dx, dy)
        base_x, base_y = (0.0, 0.0) if index == 0 else (dx, dy)
        for s in scales:
            for oy in shifts:
                for ox in shifts:
                    value = score(s, base_x + ox, base_y + oy)
                    if value < best[0] - 1e-6:
                        best = (value, s, base_x + ox, base_y + oy)
        _, scale, dx, dy = best
    moved = np.asarray(_shifted(edit_image, scale, dx, dy, (w / 2, h / 2)))
    after = float(np.abs(moved.astype(np.float32) - prev.astype(np.float32)).mean(-1)[still].mean())
    if after >= full_before:
        return edit.copy(), (1.0, 0.0, 0.0), full_before, full_before
    return moved.copy(), (float(scale), float(dx), float(dy)), full_before, after


def colour_lock(prev, edit, still):
    """The edit's colours fitted to prev (a per-channel linear map in Lab, gain within 0.9..1.1) on the unchanged part."""
    np = _np()
    sel = np.asarray(still, bool) & (np.asarray(prev).min(-1) < WHITE)
    if sel.sum() < 100:
        return np.asarray(edit).copy()
    a, b = to_lab(edit), to_lab(prev)
    out = a.copy()
    for c in range(3):
        x, y = a[..., c][sel], b[..., c][sel]
        gain = float(np.clip(np.polyfit(x, y, 1)[0], 0.9, 1.1)) if np.ptp(x) > 1e-3 else 1.0
        out[..., c] = a[..., c] * gain + float(np.median(y - gain * x))
    result = from_lab(out)
    white = np.asarray(edit).min(-1) >= WHITE
    result[white] = np.asarray(edit)[white]  # the background stays white
    return result


def snap_white(edit, region):
    """Qwen's background is off-white: near-white grey pixels inside region become pure white."""
    np = _np()
    e = np.asarray(edit).copy()
    lo, hi = e.min(-1), e.max(-1)
    e[np.asarray(region, bool) & (lo >= 234) & ((hi - lo) <= 10)] = 255
    return e


def shadow_release(prev, edit, mask, protect=None, reach: int = 40, lighter: float = 14):
    """
    The removed garment's cast shadow on what it covered: pixels near the mask (not protected, not
    background) that the aligned edit makes clearly lighter at the same hue. They join R, so no ghost
    of the garment stays behind.
    """
    np = _np()
    mask = np.asarray(mask, bool)
    near = grow(mask, reach) & ~grow(mask, 4) & (np.asarray(prev).min(-1) < WHITE)
    if protect is not None:
        near &= ~np.asarray(protect, bool)
    lp, le = to_lab(prev), to_lab(edit)
    released = near & ((le[..., 0] - lp[..., 0]) > lighter) & (np.abs(le[..., 1:] - lp[..., 1:]).max(-1) < 12)
    return grow(shrink(released, 1), 1)


def removal_region(mask, protect=None, figure=None, grow_px: int = GROW):
    """R: the garment's mask grown, never protected pixels, at most 2 px outside the previous figure."""
    np = _np()
    region = grow(mask, grow_px)
    if protect is not None:
        region &= ~np.asarray(protect, bool)
    if figure is not None:
        region &= grow(figure, 2)
    return region


def pixel_lock(prev, edit, region, px: int = FEATHER):
    """
    The edit inside region (with a soft edge where both look alike), the previous state everywhere
    else, exactly: no pixel outside region differs from prev. Where the edit clearly differs
    (another garment's edge, the background where the removed garment's outline was) it wins
    outright, so no ghost line survives the feather.
    """
    np = _np()
    prev, edit, region = np.asarray(prev), np.asarray(edit), np.asarray(region, bool)
    weight = feather(region, px)
    distance = np.sqrt(((to_lab(prev) - to_lab(edit)) ** 2).sum(-1))
    weight = np.maximum(weight, (region & (distance > 18)).astype(np.float32))
    out = prev.astype(np.float32) * (1 - weight[..., None]) + edit.astype(np.float32) * weight[..., None]
    out = np.rint(out).astype(np.uint8)
    out[~region] = prev[~region]
    return out


def changed_outside(prev, locked, region) -> int:
    """Pixels outside region that differ from prev (the pixel lock makes this 0)."""
    np = _np()
    return int(((np.abs(np.asarray(locked).astype(int) - np.asarray(prev).astype(int)).max(-1) > 0) & ~np.asarray(region, bool)).sum())


def lit(lab, mask, q: float = 55):
    """The lit part of mask: pixels above its q-th percentile of lightness."""
    np = _np()
    if mask.sum() < 50:
        return mask
    return mask & (lab[..., 0] >= np.percentile(lab[..., 0][mask], q))


def face_skin(picture, face_mask):
    """The face's lit skin colour (median Lab), or None."""
    np = _np()
    if face_mask is None or face_mask.sum() < 50:
        return None
    lab = to_lab(picture)
    skin = face_mask & (np.asarray(picture).min(-1) < WHITE) & (lab[..., 0] > 45)
    if skin.sum() < 50:
        return None
    return np.median(lab[lit(lab, skin)], 0)


def skin_pixels(image, region, reference):
    """Skin inside region: close to the reference skin's hue, not white cloth, not dark lines."""
    np = _np()
    lab = to_lab(image)
    return (
        np.asarray(region, bool)
        & (np.asarray(image).min(-1) < WHITE)
        & (np.abs(lab[..., 1] - reference[1]) < 14)
        & (np.abs(lab[..., 2] - reference[2]) < 16)
        & (lab[..., 0] > reference[0] - 40)
    )


def skin_error(image, region, reference) -> float | None:
    """CIEDE2000 between the lit skin inside region and reference, or None without skin there."""
    np = _np()
    skin = skin_pixels(image, region, reference)
    if skin.sum() < 200:
        return None
    lab = to_lab(image)
    return de2000(np.median(lab[lit(lab, skin)], 0), reference)


def skin_lock(image, region, reference, strength: float = 1.0):
    """
    The skin inside region coloured to meet the reference (the face): a gain on L and an offset on a
    and b, so the shading survives. Nothing outside region changes.
    """
    np = _np()
    image = np.asarray(image)
    skin = skin_pixels(image, region, reference)
    if skin.sum() < 200:
        return image.copy()
    lab = to_lab(image)
    median = np.median(lab[lit(lab, skin)], 0)
    gain = float(np.clip(reference[0] / max(median[0], 1), 0.85, 1.2))
    new = lab.copy()
    new[..., 0] = lab[..., 0] * gain
    new[..., 1] = lab[..., 1] + (reference[1] - median[1])
    new[..., 2] = lab[..., 2] + (reference[2] - median[2])
    blur = np.asarray(Image.fromarray((skin * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255
    weight = (np.minimum(blur, 1.0) * strength * np.asarray(region, bool))[..., None]
    out = from_lab(lab * (1 - weight) + new * weight)
    out[~np.asarray(region, bool)] = image[~np.asarray(region, bool)]
    return out


# Layers -------------------------------------------------------------------------------------------------
def rgba(rgb, alpha) -> Image.Image:
    np = _np()
    return Image.fromarray(np.dstack([np.asarray(rgb), np.asarray(alpha).astype(np.uint8)]), "RGBA")


def soft_alpha(mask, grow_px: int = 1):
    """A matte with a 1 px soft edge."""
    np = _np()
    m = grow(mask, grow_px)
    return np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(0.8)))


def garment_layer(before, mask, after=None, figure=None) -> Image.Image:
    """
    A garment's layer: the pixels of the state before its removal inside its matte, plus every pixel
    of the figure the removal changed (its cast shadow, released in the next state).
    """
    np = _np()
    before = np.asarray(before)
    matte = np.asarray(mask, bool)
    if after is not None:
        changed = np.abs(np.asarray(after).astype(int) - before.astype(int)).max(-1) > 0
        matte = matte | (changed & (figure if figure is not None else silhouette(before)))
        matte = fill_holes(shrink(grow(matte, 1), 1))
    return rgba(before, soft_alpha(matte))


def half_garment(edit, next_state, garment, region, threshold: int = 25):
    """
    The garment's own pixels in a half-state edit: inside region, where the garment is (garment, in
    the edit) and either the edit differs from the next state or the pixel is well inside the
    garment. What the garment no longer covers comes from the next chain state.
    """
    np = _np()
    garment = np.asarray(garment, bool) & np.asarray(region, bool)
    changed = np.abs(np.asarray(edit).astype(int) - np.asarray(next_state).astype(int)).max(-1) > threshold
    return (garment & changed) | shrink(garment, 3)


def compose(base, layers_rgba) -> "object":
    """Layers (RGBA images, bottom first) over base (RGB array), as an RGB array."""
    np = _np()
    out = np.asarray(base).astype(np.float32).copy()
    for layer in layers_rgba:
        a = np.asarray(layer.convert("RGBA")).astype(np.float32)
        alpha = a[..., 3:4] / 255
        out = out * (1 - alpha) + a[..., :3] * alpha
    return np.rint(out).astype(np.uint8)


def stack_error(stack, picture, ignore=None, tolerance: int = 24) -> int:
    """Pixels of the figure where the layer stack is off from the picture by more than tolerance."""
    np = _np()
    bad = (np.abs(np.asarray(stack).astype(int) - np.asarray(picture).astype(int)).max(-1) > tolerance) & (np.asarray(picture).min(-1) < WHITE)
    if ignore is not None:
        bad &= ~np.asarray(ignore, bool)
    return int(bad.sum())


# Instructions ---------------------------------------------------------------------------------------------
def remove_instruction(garment: dict, under: list[dict], reveals_skin: bool, description: str = "") -> str:
    """The Qwen edit that takes exactly one garment off."""
    words = tags.garment_words(garment)
    text = f"Remove the {words} completely, every part of it."
    if under:
        text += " Under it she wears " + ", ".join(tags.garment_words(g) for g in under) + ", which stay exactly as they are, drawn complete where it covered them."
    if reveals_skin:
        text += " Where it covered her body her skin is bare, the same skin tone as her face, with the same soft shading and outlines."
    text += " Every other garment stays exactly as it is. " + KEEP
    if description:
        text += f" The character: {' '.join(description.split())[:300]}."
    return outfits.adapt(text, description)


def half_instruction(garment: dict, description: str = "") -> str:
    """The Qwen edit that draws a garment half worn."""
    text = f"Her {tags.garment_words(garment)} is now {garment.get('half_state') or tags.default_half_state(garment)}. It stays on her; change nothing else. " + KEEP
    if description:
        text += f" The character: {' '.join(description.split())[:300]}."
    return outfits.adapt(text, description)


# The chain -------------------------------------------------------------------------------------------------
@dataclasses.dataclass
class Chain:
    """The states (numpy RGB, by state name), the masks and regions per step, layers, metrics, notes."""

    states: dict
    order: list
    masks: dict
    regions: dict
    halves: dict
    metrics: dict
    notes: list
    figures: dict


def _segment(backend, image, prompt: str, size):
    segment = getattr(backend, "segment", None)
    if segment is None or not prompt:
        return None
    for _ in range(2):
        found = segment(pil_to_b64(Image.fromarray(image)), prompt)
        if found is not None:
            mask = as_mask(found, size)
            return mask if mask is not None and mask.any() else None
    return None


def _edit(backend, image, instruction: str, settings) -> "object | None":
    np = _np()
    result = backend.instruction_edit(pil_to_b64(Image.fromarray(image)), instruction, settings)
    if result is None:
        return None
    result = result.convert("RGB")
    if result.size != (image.shape[1], image.shape[0]):
        result = result.resize((image.shape[1], image.shape[0]), Image.Resampling.LANCZOS)
    return np.asarray(result).copy()


def lock_step(prev, raw, mask_hint, protect, figure, face_ref, reveals_skin: bool, segment=None):
    """
    One state from a raw edit of prev: aligned, colour-locked, pixel-locked to R and skin-locked.
    mask_hint: the garment's mask on prev (None: what the aligned edit changed near the figure).
    Returns (state, mask, R, metrics).
    """
    np = _np()
    if mask_hint is not None:
        still = grow(figure, 20) & ~grow(mask_hint, GROW + 12)
    else:
        still = grow(figure, 20)
    if protect is not None:
        still |= protect
    aligned, warp, before, after = align(prev, raw, still)
    mask = mask_hint
    if mask is None:
        changed = np.abs(aligned.astype(int) - prev.astype(int)).max(-1) > 40
        mask = fill_holes(grow(shrink(changed, 1), 2)) & figure
        still = grow(figure, 20) & ~grow(mask, GROW + 12)
    aligned = colour_lock(prev, aligned, still)
    region = removal_region(mask, protect, figure)
    released = shadow_release(prev, aligned, mask, protect)
    region |= released
    if protect is not None:
        region &= ~protect
    aligned = snap_white(aligned, region)
    locked = pixel_lock(prev, aligned, region)
    metrics = {"warp": [round(float(v), 3) for v in warp], "residual_before": round(before, 2), "residual_after": round(after, 2), "R_px": int(region.sum()), "shadow_release_px": int(released.sum())}
    if reveals_skin and face_ref is not None:
        metrics["skin_dE00_before"] = _round(skin_error(locked, region, face_ref))
        locked = skin_lock(locked, region, face_ref)
        metrics["skin_dE00"] = _round(skin_error(locked, region, face_ref))
    metrics["changed_outside_R"] = changed_outside(prev, locked, region)
    return locked, mask, region, metrics


def _round(value):
    return None if value is None else round(float(value), 2)


def run_chain(
    backend,
    picture: Image.Image,
    manifest: dict,
    settings: dict | None = None,
    log: Callable[[str], None] = lambda _: None,
    check_cancel: Callable[[], None] = lambda: None,
    progress: Callable[[str, float], None] = lambda step, fraction: None,
    span: tuple[float, float] = (0.05, 0.35),
) -> Chain:
    """
    Run the undress chain on picture (the source pose, on white) for the manifest's states and half
    states. Steps that fail end the chain there (a note says so); what was made is kept.
    """
    np = _np()
    settings = dict(settings or {})
    edit = dataclasses.replace(instruction_edit.EditSettings.from_settings(settings), keep_size=True, photo=False, intensity=1.0)
    description = settings.get("character_description", "")
    s0 = rgb_array(picture)
    size = picture.size
    by_id = tags.garment_by_id(manifest)
    head = _segment(backend, s0, HEAD_PROMPT, size)
    hands = _segment(backend, s0, HANDS_PROMPT, size)
    protect = None
    if head is not None or hands is not None:
        protect = np.zeros(s0.shape[:2], bool)
        if head is not None:
            protect |= shrink(fill_holes(head), 1)
        if hands is not None:
            protect |= shrink(hands, 3)
    face = _segment(backend, s0, FACE_PROMPT, size)
    face_ref = face_skin(s0, face)
    notes = []
    if face_ref is None:
        notes.append("No face found to match the revealed skin to; the skin keeps the edit's colour.")
    if protect is None:
        notes.append("No segmentation model: the head and hands are kept by the pixel lock only where no garment was changed.")
    states = {manifest["states"][0]["name"]: s0}
    figures = {manifest["states"][0]["name"]: silhouette(s0)}
    masks, regions, metrics, halves = {}, {}, {}, {}
    order = [manifest["states"][0]["name"]]
    steps = manifest["states"][1:]
    total = max(1, len(steps) + len(manifest.get("half_states", [])))
    done = 0
    prev_name = order[0]
    for state in steps:
        check_cancel()
        garment = by_id[state["removed"]]
        progress(f"taking off the {tags.garment_words(garment)}", span[0] + (span[1] - span[0]) * done / total)
        log(f"Undress chain: {state['name']} (Qwen-Image-Edit, then aligned and pixel-locked).")
        prev = states[prev_name]
        under = [by_id[g] for g in state.get("shows", []) if g in by_id]
        raw = _edit(backend, prev, remove_instruction(garment, under, bool(state.get("reveals_skin_regions")), description), edit)
        if raw is None:
            notes.append(f"Couldn't take off the {tags.garment_words(garment)}: {getattr(backend, 'last_error', None) or 'the WebUI failed'}. The chain stops at {prev_name}.")
            break
        hint = _segment(backend, prev, tags.garment_words(garment), size)
        locked, mask, region, step = lock_step(prev, raw, hint, protect, figures[prev_name], face_ref, bool(state.get("reveals_skin_regions")))
        step["mask"] = "segmentation" if hint is not None else "changed pixels"
        states[state["name"]], masks[state["name"]], regions[state["name"]], metrics[state["name"]] = locked, mask, region, step
        figures[state["name"]] = (figures[prev_name] & ~region) | (silhouette(locked) & region)
        order.append(state["name"])
        prev_name = state["name"]
        done += 1
    for half in manifest.get("half_states", []):
        if half["from"] not in states or half["over"] not in states:
            continue
        check_cancel()
        garment = by_id[half["garment"]]
        progress(f"drawing the {tags.garment_words(garment)} half off", span[0] + (span[1] - span[0]) * done / total)
        source, nxt = states[half["from"]], states[half["over"]]
        raw = _edit(backend, source, half_instruction(garment, description), edit)
        done += 1
        if raw is None:
            notes.append(f"Couldn't draw the {tags.garment_words(garment)} half off; it only switches on or off.")
            continue
        figure = figures[half["from"]]
        aligned, _, _, _ = align(source, raw, grow(figure, 20) & ~grow(masks[half["over"]], 60) if half["over"] in masks else grow(figure, 20))
        aligned = colour_lock(source, aligned, figure & ~grow(masks.get(half["over"], np.zeros_like(figure)), 60))
        found = _segment(backend, aligned, tags.garment_words(garment), size)
        if found is None:
            found = np.abs(aligned.astype(int) - nxt.astype(int)).max(-1) > 25
            found = fill_holes(grow(shrink(found, 1), 1)) & (aligned.min(-1) < WHITE)
        region = grow(found, 2)
        if protect is not None:
            region &= ~protect
        piece = half_garment(aligned, nxt, found, region)
        halves[half["name"]] = rgba(aligned, soft_alpha(piece, 0))
        metrics[half["name"]] = {"over": half["over"], "px": int(piece.sum())}
    return Chain(states, order, masks, regions, halves, metrics, notes, figures)


# From the chain to kit layers --------------------------------------------------------------------------------
# Garment slot -> the kit's layer tag (layers._PARTS), so the puppet's clothing switches follow it.
SLOT_TAGS = {
    "outerwear": "outer wear", "top": "topwear", "dress": "topwear", "waist": "bottomwear", "bottom": "bottomwear",
    "legwear": "legwear", "footwear": "footwear", "gloves": "handwear", "inner_top": "inner top", "inner_bottom": "inner bottom",
}
HALF_TAGS = {"outerwear": "outer wear half", "top": "topwear half", "dress": "topwear half", "bottom": "bottomwear half"}
BODY_TAG = "nude body"
# Depth (lower is nearer) for the chain's layers: the outermost garment nearest.
SLOT_DEPTH = {"outerwear": 0.55, "waist": 0.56, "top": 0.58, "dress": 0.58, "gloves": 0.57, "bottom": 0.6, "footwear": 0.61, "legwear": 0.62, "inner_top": 0.64, "inner_bottom": 0.65}


@dataclasses.dataclass
class ChainLayer:
    tag: str
    image: Image.Image  # RGBA, the picture's size
    depth: float
    internal: bool
    name: str  # the file stem (INTERNAL_ in front when it shows inner wear or less)


def chain_layers(chain: Chain, manifest: dict) -> list[ChainLayer]:
    """The chain's layers: one per removed garment, the half states, and the body (the last state)."""
    by_id = tags.garment_by_id(manifest)
    info = {s["name"]: s for s in manifest["states"]}
    result = []
    for before, after in zip(chain.order, chain.order[1:]):
        state = info[after]
        garment = by_id[state["removed"]]
        tag = SLOT_TAGS.get(garment["slot"])
        if tag is None:
            continue
        internal = info[before]["internal"] or info[before]["shows_inner_wear"] or garment["slot"] in tags.UNDERWEAR_SLOTS
        image = garment_layer(chain.states[before], chain.masks[after], chain.states[after], chain.figures[before])
        result.append(ChainLayer(tag, image, SLOT_DEPTH.get(garment["slot"], 0.6), bool(internal), tags.internal_name(f"layer_{garment['id']}", bool(internal))))
    for half in manifest.get("half_states", []):
        image = chain.halves.get(half["name"])
        tag = HALF_TAGS.get(half["slot"])
        if image is None or tag is None:
            continue
        result.append(ChainLayer(tag, image, SLOT_DEPTH.get(half["slot"], 0.6) - 0.005, bool(half["internal"]), tags.internal_name(f"half_{half['garment']}", bool(half["internal"]))))
    last = chain.order[-1]
    if len(chain.order) > 1:
        base = rgba(chain.states[last], soft_alpha(chain.figures[last], 0))
        internal = bool(info[last]["internal"] or info[last]["shows_inner_wear"])
        result.append(ChainLayer(BODY_TAG, base, 0.7, internal, tags.internal_name("layer_body", internal)))
    return result


def check_stack(chain: Chain, layers_list: list[ChainLayer], protect=None) -> int:
    """How many figure pixels the garment layers over the body miss the picture by (see stack_error)."""
    np = _np()
    body = [layer for layer in layers_list if layer.tag == BODY_TAG]
    garments_only = [layer for layer in layers_list if layer.tag != BODY_TAG and not layer.tag.endswith(" half")]
    base = np.full(chain.states[chain.order[0]].shape, 255, np.uint8)
    stack = compose(base, [b.image for b in body] + [g.image for g in sorted(garments_only, key=lambda g: -g.depth)])
    return stack_error(stack, chain.states[chain.order[0]], protect)
