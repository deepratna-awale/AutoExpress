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

    font = ImageFont.load_default()
    label_h = 0
    if labels:
        label_h = max(16, tile_h // 16)
        try:
            font = ImageFont.load_default(size=label_h - 4)
        except TypeError:  # Pillow < 10.1 has a single fixed size default font
            pass

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
            text = labels[index].title()
            text_w = draw.textlength(text, font=font)
            draw.text((x + (tile_w - text_w) / 2, y + tile_h + 1), text, fill="white", font=font)

    return sheet
