"""
Which pictures make a good Live2D model, and a quick check of the ones a user sends.

The layer splitter sees one picture, so that picture decides most of the result. check_image()
looks at what can be told without a model: size, a plain or transparent background, the
character filling the frame and not cut off at the sides, one character only. The kit report
(see kit.py) adds what the split itself found (both eyes, a mouth, front hair ...).

Only Pillow is needed.
"""

import dataclasses

from PIL import Image, ImageFilter, ImageStat

MIN_SIDE = 768
GOOD_SIDE = 1280

ADVICE = {
    "title": "Pictures that make a good Live2D model",
    "best": [
        "One character, facing the viewer (front view or a slight three-quarter turn), with a calm, neutral face and the mouth closed.",
        "Waist up or full body, so the body, arms and hair get their own parts. A face crop only gives a head.",
        "At least 1280 pixels on the short side, sharp, no heavy blur, glow or film grain.",
        "A plain or transparent background, nothing in front of the character (no text, hands, props or other characters overlapping).",
        "Arms a little away from the body and the hands visible, hair not covering the eyes.",
        "The whole character inside the frame: nothing cut off at the top or sides.",
    ],
    "extras": [
        "The same picture with the eyes closed and with the mouth open: AutoExpress makes these itself, but drawn versions are better.",
        "A turnaround or sprite sheet (front, three-quarter, side) helps whoever rigs the model, and lets AutoExpress pick the best front view.",
        "The character's name (or a character card): AutoExpress looks for a character LoRA on Civitai so edits stay on model.",
    ],
    "avoid": [
        "Dynamic action poses, strong perspective or foreshortening, the character lying down or seen from above or below.",
        "Busy scenes, crowds, or several characters in one picture.",
        "Sketches and very loose line art: the split works best on finished, cleanly shaded art.",
    ],
}


@dataclasses.dataclass
class Check:
    id: str
    ok: bool
    message: str
    level: str = "warning"  # "warning" or "error" when not ok

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def _border_pixels(image: Image.Image, width: int) -> list[Image.Image]:
    w, h = image.size
    return [
        image.crop((0, 0, w, width)),
        image.crop((0, h - width, w, h)),
        image.crop((0, 0, width, h)),
        image.crop((w - width, 0, w, h)),
    ]


def has_transparency(image: Image.Image) -> bool:
    if image.mode not in ("RGBA", "LA", "PA") and "transparency" not in image.info:
        return False
    alpha = image.convert("RGBA").getchannel("A")
    return alpha.getextrema()[0] < 250


def subject_mask(image: Image.Image) -> Image.Image:
    """The character's silhouette (mode L): from transparency, else from the difference to the border colour."""
    if has_transparency(image):
        return image.convert("RGBA").getchannel("A").point(lambda v: 255 if v > 32 else 0)
    rgb = image.convert("RGB")
    border = _border_pixels(rgb, max(2, min(rgb.size) // 100))
    means = [ImageStat.Stat(part).median for part in border]
    background = tuple(sorted(channel)[len(channel) // 2] for channel in zip(*means))
    flat = Image.new("RGB", rgb.size, background)
    from PIL import ImageChops

    diff = ImageChops.difference(rgb, flat).convert("L")
    return diff.point(lambda v: 255 if v > 24 else 0).filter(ImageFilter.MedianFilter(5))


def background_plainness(image: Image.Image) -> float:
    """0 (busy) to 1 (flat): how even the picture's border is. Transparent pictures count as plain."""
    if has_transparency(image):
        return 1.0
    rgb = image.convert("RGB")
    border = _border_pixels(rgb, max(2, min(rgb.size) // 50))
    # The character often reaches the bottom edge (a waist-up picture), so judge by the second busiest side.
    spreads = sorted(max(ImageStat.Stat(part).stddev) for part in border)
    spread = spreads[-2]
    return max(0.0, min(1.0, 1 - spread / 48))


def _components(mask: Image.Image, limit: int = 8) -> list[int]:
    """Sizes of the biggest separate blobs in a small copy of mask (for counting characters)."""
    small = mask.resize((max(1, mask.width // 8), max(1, mask.height // 8)), Image.Resampling.BILINEAR).point(lambda v: 255 if v > 96 else 0)
    width, height = small.size
    pixels = small.load()
    seen = bytearray(width * height)
    sizes = []
    for y in range(height):
        for x in range(width):
            if pixels[x, y] and not seen[y * width + x]:
                stack, size = [(x, y)], 0
                seen[y * width + x] = 1
                while stack:
                    cx, cy = stack.pop()
                    size += 1
                    for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                        if 0 <= nx < width and 0 <= ny < height and pixels[nx, ny] and not seen[ny * width + nx]:
                            seen[ny * width + nx] = 1
                            stack.append((nx, ny))
                sizes.append(size)
    return sorted(sizes, reverse=True)[:limit]


def check_image(image: Image.Image) -> dict:
    """
    Checks of one picture for a Live2D model, and a score to pick the best of several.

    Returns {"score": 0..100, "checks": [Check...], "size": [w, h], "subject_box": [l, t, r, b] | None}.
    """
    image.load()
    width, height = image.size
    checks: list[Check] = []
    short = min(width, height)
    if short < MIN_SIDE:
        checks.append(Check("resolution", False, f"{width}x{height} is small: at least {GOOD_SIDE} px on the short side gives clean layers.", "error"))
    elif short < GOOD_SIDE:
        checks.append(Check("resolution", False, f"{width}x{height} works, but {GOOD_SIDE} px or more on the short side gives cleaner layers."))
    else:
        checks.append(Check("resolution", True, f"{width}x{height}: big enough."))

    plain = background_plainness(image)
    if has_transparency(image):
        checks.append(Check("background", True, "Transparent background."))
    elif plain >= 0.7:
        checks.append(Check("background", True, "Plain background."))
    else:
        checks.append(Check("background", False, "Busy background: a plain or transparent one splits more cleanly. AutoExpress removes it first when it can."))

    mask = subject_mask(image)
    box = mask.getbbox()
    subject_box = list(box) if box else None
    coverage = 0.0
    if box is None:
        checks.append(Check("subject", False, "Couldn't find the character in the picture.", "error"))
    else:
        coverage = (box[2] - box[0]) * (box[3] - box[1]) / float(width * height)
        if coverage < 0.15:
            checks.append(Check("subject", False, "The character is small in the frame: crop closer or use a bigger picture."))
        else:
            checks.append(Check("subject", True, "The character fills the frame well."))
        margin = max(2, short // 200)
        cut = [side for side, touching in (("top", box[1] <= margin), ("left", box[0] <= margin), ("right", box[2] >= width - margin)) if touching]
        if cut and (plain >= 0.7 or has_transparency(image)):
            checks.append(Check("cropped", False, f"The character touches the {' and '.join(cut)} edge: anything cut off there won't be in the model."))
        aspect = (box[3] - box[1]) / max(1, box[2] - box[0])
        if aspect < 0.8:
            checks.append(Check("framing", False, "The character is wider than tall: a lying down, wide or action pose rigs poorly. A standing pose works best."))
        if plain >= 0.7 or has_transparency(image):
            blobs = _components(mask)
            if len(blobs) > 1 and blobs[1] > 0.35 * blobs[0]:
                checks.append(Check("characters", False, "There seem to be several characters or separate figures: use a picture of one character."))

    score = 100.0
    for check in checks:
        if not check.ok:
            score -= 40 if check.level == "error" else 15
    score += min(10, coverage * 10)
    score += min(10, short / GOOD_SIDE * 5)
    return {"score": round(max(0.0, min(100.0, score)), 1), "checks": [check.to_dict() for check in checks], "size": [width, height], "subject_box": subject_box}


def rank_images(images: list[Image.Image]) -> list[tuple[int, dict]]:
    """(index, report) for each picture, best first."""
    reports = [(index, check_image(image)) for index, image in enumerate(images)]
    return sorted(reports, key=lambda item: item[1]["score"], reverse=True)
