import math

from PIL import Image, ImageDraw, ImageFont

BACKGROUND = (51, 51, 51)


def make_sprite_sheet(
    images: list[Image.Image],
    labels: list[str] | None = None,
    columns: int = 7,
    background: tuple[int, int, int] = BACKGROUND,
) -> Image.Image:
    """
    Tile images into one sheet, optionally with a label under each tile.

    Args:
        images (list[Image.Image]): Images to tile. All tiles take the size of the first image.
        labels (list[str] | None): Optional caption per image.
        columns (int): Tiles per row.
        background (tuple[int, int, int]): Sheet background color.

    Returns:
        Image.Image: The sprite sheet.
    """
    if not images:
        raise ValueError("Need at least one image to build a sprite sheet.")

    columns = max(1, min(columns, len(images)))
    rows = math.ceil(len(images) / columns)
    tile_w, tile_h = images[0].size

    label_h = max(16, tile_h // 16) if labels else 0
    font = _label_font(label_h - 4) if labels else None

    sheet = Image.new("RGB", (columns * tile_w, rows * (tile_h + label_h)), background)
    draw = ImageDraw.Draw(sheet)

    for index, image in enumerate(images):
        col, row = index % columns, index // columns
        x, y = col * tile_w, row * (tile_h + label_h)
        tile = image.convert("RGB")
        if tile.size != (tile_w, tile_h):
            tile = tile.resize((tile_w, tile_h))
        sheet.paste(tile, (x, y))

        if labels and index < len(labels):
            _draw_label(sheet, draw, labels[index].title(), font, x, y + tile_h, tile_w, label_h)

    return sheet


def _label_font(size: int):
    """A font of roughly `size` pixels, or None when only Pillow's fixed bitmap font exists."""
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 has a single fixed size default font
        pass
    for name in ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return None


def _draw_label(sheet, draw, text, font, x, y, width, height):
    if font is not None:
        text_w = draw.textlength(text, font=font)
        draw.text((x + (width - text_w) / 2, y + 1), text, fill="white", font=font)
        return

    # Scale the small bitmap font up so labels stay readable on large tiles.
    small_font = ImageFont.load_default()
    left, top, right, bottom = small_font.getbbox(text)
    small = Image.new("L", (max(1, right - left), max(1, bottom - top)), 0)
    ImageDraw.Draw(small).text((-left, -top), text, fill=255, font=small_font)
    scale = max(1, (height - 4) // small.height)
    big = small.resize((small.width * scale, small.height * scale), Image.NEAREST)
    sheet.paste((255, 255, 255), (x + (width - big.width) // 2, y + 2), big)
