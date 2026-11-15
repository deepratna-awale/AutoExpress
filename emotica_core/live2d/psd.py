"""
A small layered PSD writer: RGBA pixel layers, nested groups and hidden layers.

It writes what Live2D Cubism Editor, Photoshop, Krita, Clip Studio Paint and psd-tools read:
8-bit RGB with transparency, one layer record per layer (cropped to its pixels), groups as
section dividers, Unicode layer names, and a flattened composite. Channels are stored
uncompressed, which every reader supports; zip the file to ship it (it compresses well).

Only Pillow is needed.
"""

import dataclasses
import os
import io
import struct
from typing import BinaryIO, Union

from PIL import Image

BLEND_NORMAL = b"norm"
# Layer record flags
_FLAG_HIDDEN = 0x02
_FLAG_PIXEL_DATA_IRRELEVANT = 0x18  # bits 3 and 4: set on group and divider records
# lsct section types
_OPEN_FOLDER = 1
_CLOSED_FOLDER = 2
_SECTION_DIVIDER = 3
_DIVIDER_NAME = "</Layer group>"


@dataclasses.dataclass
class Layer:
    """A pixel layer: an RGBA image placed at (left, top) on the canvas."""

    name: str
    image: Image.Image
    left: int = 0
    top: int = 0
    visible: bool = True
    opacity: int = 255


@dataclasses.dataclass
class Group:
    """A layer group (a Cubism "part"). children are listed top to bottom, like a layers panel."""

    name: str
    children: list = dataclasses.field(default_factory=list)
    visible: bool = True
    opened: bool = True
    opacity: int = 255


Node = Union[Layer, Group]


def _pascal_name(name: str) -> bytes:
    raw = name.encode("latin-1", "replace")[:255]
    data = bytes([len(raw)]) + raw
    return data + b"\0" * (-len(data) % 4)


def _block(key: bytes, payload: bytes) -> bytes:
    payload += b"\0" * (-len(payload) % 2)
    return b"8BIM" + key + struct.pack(">I", len(payload)) + payload


def _unicode_name(name: str) -> bytes:
    encoded = name.encode("utf-16-be")
    return _block(b"luni", struct.pack(">I", len(encoded) // 2) + encoded)


def _section(kind: int) -> bytes:
    payload = struct.pack(">I", kind)
    if kind != _SECTION_DIVIDER:
        payload += b"8BIM" + BLEND_NORMAL
    return _block(b"lsct", payload)


@dataclasses.dataclass
class _Record:
    name: str
    rect: tuple[int, int, int, int]  # top, left, bottom, right
    channels: list[tuple[int, bytes]]  # (channel id, raw plane)
    flags: int
    opacity: int
    extra: bytes


def _crop(layer: Layer, size: tuple[int, int]) -> tuple[Image.Image | None, tuple[int, int, int, int]]:
    """The layer cut to its visible pixels and to the canvas, and its rect (top, left, bottom, right)."""
    image = layer.image.convert("RGBA")
    width, height = size
    # Clip to the canvas first.
    left, top = layer.left, layer.top
    box = (max(0, -left), max(0, -top), min(image.width, width - left), min(image.height, height - top))
    if box[2] <= box[0] or box[3] <= box[1]:
        return None, (0, 0, 0, 0)
    image = image.crop(box)
    left, top = left + box[0], top + box[1]
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        return None, (0, 0, 0, 0)
    image = image.crop(bbox)
    left, top = left + bbox[0], top + bbox[1]
    return image, (top, left, top + image.height, left + image.width)


def _pixel_record(layer: Layer, size: tuple[int, int]) -> _Record:
    image, rect = _crop(layer, size)
    if image is None:
        channels = [(cid, b"") for cid in (-1, 0, 1, 2)]
    else:
        r, g, b, a = image.split()
        channels = [(-1, a.tobytes()), (0, r.tobytes()), (1, g.tobytes()), (2, b.tobytes())]
    flags = 0 if layer.visible else _FLAG_HIDDEN
    return _Record(layer.name, rect, channels, flags, layer.opacity, _unicode_name(layer.name))


def _group_records(group: Group, size: tuple[int, int]) -> list[_Record]:
    """Records for a group, bottom first: divider, children (bottom to top), then the folder record."""
    empty = [(cid, b"") for cid in (-1, 0, 1, 2)]
    records = [
        _Record(_DIVIDER_NAME, (0, 0, 0, 0), empty, _FLAG_PIXEL_DATA_IRRELEVANT, 255, _unicode_name(_DIVIDER_NAME) + _section(_SECTION_DIVIDER))
    ]
    for child in reversed(group.children):
        records.extend(_records(child, size))
    flags = _FLAG_PIXEL_DATA_IRRELEVANT | (0 if group.visible else _FLAG_HIDDEN)
    kind = _OPEN_FOLDER if group.opened else _CLOSED_FOLDER
    records.append(_Record(group.name, (0, 0, 0, 0), empty, flags, group.opacity, _unicode_name(group.name) + _section(kind)))
    return records


def _records(node: Node, size: tuple[int, int]) -> list[_Record]:
    if isinstance(node, Group):
        return _group_records(node, size)
    return [_pixel_record(node, size)]


def flatten(nodes: list[Node], size: tuple[int, int]) -> Image.Image:
    """The visible layers composited over transparency (nodes listed top to bottom)."""
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))

    def paint(items: list[Node], visible: bool) -> None:
        for node in reversed(items):
            if isinstance(node, Group):
                paint(node.children, visible and node.visible)
            elif visible and node.visible:
                image = node.image.convert("RGBA")
                if node.opacity < 255:
                    alpha = image.getchannel("A").point(lambda v: v * node.opacity // 255)
                    image.putalpha(alpha)
                layer = Image.new("RGBA", size, (0, 0, 0, 0))
                layer.paste(image, (node.left, node.top))
                canvas.alpha_composite(layer)

    paint(nodes, True)
    return canvas


def write_psd(target: Union[str, BinaryIO, os.PathLike], nodes: list[Node], size: tuple[int, int], composite: Image.Image | None = None) -> None:
    """
    Write a layered PSD.

    Args:
        target: A path or a binary file object.
        nodes: Top-level layers and groups, listed top to bottom (the order a layers panel shows).
        size: Canvas (width, height).
        composite: The flattened image saved for readers that don't read layers. Default: the visible layers.
    """
    width, height = size
    records = []
    for node in reversed(nodes):
        records.extend(_records(node, size))

    layer_info = io.BytesIO()
    # A negative count says the composite's first extra channel is its transparency.
    layer_info.write(struct.pack(">h", -len(records)))
    for record in records:
        layer_info.write(struct.pack(">4i", *record.rect))
        layer_info.write(struct.pack(">H", len(record.channels)))
        for channel_id, plane in record.channels:
            layer_info.write(struct.pack(">hI", channel_id, len(plane) + 2))
        layer_info.write(b"8BIM" + BLEND_NORMAL)
        layer_info.write(struct.pack(">BBBB", record.opacity, 0, record.flags, 0))
        extra = struct.pack(">I", 0) + struct.pack(">I", 0) + _pascal_name(record.name) + record.extra
        layer_info.write(struct.pack(">I", len(extra)) + extra)
    for record in records:
        for _, plane in record.channels:
            layer_info.write(struct.pack(">H", 0) + plane)
    info = layer_info.getvalue()
    info += b"\0" * (-len(info) % 4)

    layer_section = struct.pack(">I", len(info)) + info + struct.pack(">I", 0)  # no global layer mask

    if composite is None:
        composite = flatten(nodes, size)
    composite = composite.convert("RGBA").resize(size) if composite.size != size else composite.convert("RGBA")

    def write(handle: BinaryIO) -> None:
        handle.write(b"8BPS" + struct.pack(">H", 1) + b"\0" * 6)
        handle.write(struct.pack(">HIIHH", 4, height, width, 8, 3))
        handle.write(struct.pack(">I", 0))  # color mode data
        handle.write(struct.pack(">I", 0))  # image resources
        handle.write(struct.pack(">I", len(layer_section)) + layer_section)
        handle.write(struct.pack(">H", 0))  # raw composite
        for band in composite.split():
            handle.write(band.tobytes())

    if hasattr(target, "write"):
        write(target)
    else:
        with open(target, "wb") as handle:
            write(handle)
