import io
import base64
from PIL import Image, PngImagePlugin
from .logger import setup_logging
import pathlib

log = setup_logging()


def raw_b64_img(input_image):
    # Convert the input image to base64 format (SD api accepts base64)
    with Image.open(input_image) as image:
        with io.BytesIO() as img_buffer:
            # Save the image to a bytes buffer
            image.save(
                img_buffer, format=input_image.suffix[1:]
            )  # suffix returns .png -> remove . to get only png

            # Encode the image to base64 and decode to a string in one step
            input_img_base64_str = base64.b64encode(img_buffer.getvalue()).decode(
                "utf-8"
            )
    # input_img_base64_str = Image.open(io.BytesIO(base64.b64decode(input_image.split(",", 1)[0])))
    return input_img_base64_str


def b64_img(image) -> str:
    return "data:image/png;base64," + raw_b64_img(image)


def is_image_valid(input_image_path, image_str):

    if not input_image_path and not image_str:
        log.error("Need atleast an image path/ base 64 string of image.")
        return False

    if not image_str:
        input_image_path = pathlib.Path(input_image_path)
        image_str = raw_b64_img(input_image_path)
        return image_str

    return image_str
