import base64
import io
import pathlib

from PIL import Image

DATA_URI_PREFIX = "data:image/png;base64,"


def pil_to_b64(image: Image.Image, data_uri: bool = True) -> str:
    """Encode a PIL image as a PNG base64 string."""
    with io.BytesIO() as img_buffer:
        image.save(img_buffer, format="PNG")
        encoded = base64.b64encode(img_buffer.getvalue()).decode("utf-8")
    return DATA_URI_PREFIX + encoded if data_uri else encoded


def b64_to_pil(b64_image_str: str) -> Image.Image:
    """Decode a raw or data URI base64 string into a PIL image."""
    if b64_image_str.startswith("data:"):
        b64_image_str = b64_image_str.split(",", 1)[1]
    return Image.open(io.BytesIO(base64.b64decode(b64_image_str)))


def file_to_b64(path, data_uri: bool = False) -> str:
    with Image.open(pathlib.Path(path)) as image:
        image.load()
        return pil_to_b64(image, data_uri=data_uri)
