from . import utils, json_handler
from . import a1111_api as sd
from loguru import logger as log

import io
import base64
import pathlib

from PIL import Image, PngImagePlugin

def generate_expressions(
    output_path: str,
    settings: dict,
    image_str: str = None,
    input_image_path: str = None,
    is_realistic: bool = False
):

    image_str = utils.is_image_valid(input_image_path, image_str)

    output_path = pathlib.Path(output_path)
    pathlib.Path(output_path).mkdir(parents=True, exist_ok=True)
    
    if is_realistic:
        log.info("Using clip prompts since realistic is set to true.")
        expressions = json_handler.get_clip_expression_list()
    else:
        expressions = json_handler.get_expression_list()

    log.info(f"Output Directory: {output_path.absolute()}")

    for expression_name, tags in expressions.items():
        log.info(
            f"Generating image for {expression_name} expression."
        )

        default_request_body = json_handler.get_img2img_payload()

        json_payload = json_handler.edit_payload_body(
            image_str, default_request_body, settings, tags
        )

        output_image_path = pathlib.Path(output_path, expression_name + ".png")

        response = sd.img2img_api(json_payload)

        if not response:
            return
        
        r = response.json()
        image = Image.open(io.BytesIO(base64.b64decode(r["images"][0])))
        image.save(output_image_path)
        log.info("Done.")

    log.info(f"Generated all Expressions in {output_path.absolute()}")


def opaque(input_image_path, image_str, output_path, settings=None):
    gen_info = None

    image_str = utils.is_image_valid(input_image_path, image_str)

    output_path = pathlib.Path(output_path).absolute()
    pathlib.Path(output_path).mkdir(parents=True, exist_ok=True)

    default_request_body = json_handler.get_opaque_payload()

    json_payload = json_handler.edit_payload_body(image_str, default_request_body, settings, "")

    output_image_path = pathlib.Path(output_path, "temp" + ".png")

    response = sd.img2img_api(json_payload)
    
    if not response:
        return
    
    r = response.json()

    img_str = r["images"][0]
    gen_info = r["info"]

    image = Image.open(io.BytesIO(base64.b64decode(img_str)))
    image.save(output_image_path)

    log.info(f"Picture generated with info: {gen_info}")
    log.info(f"Image Saved")

    log.info(
            f"Enforced an opaque background on image. Temp file at {output_image_path.absolute()}"
    )

    return (output_image_path, gen_info)
