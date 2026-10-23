from autoexpress_core import ExpressionGenerator, build_expression_payload
from autoexpress_core.images import b64_to_pil
from . import utils
from . import a1111_client
from loguru import logger as log

import pathlib


def generate_expressions(
    sd: a1111_client.A1111Client,
    output_path: str,
    settings: dict,
    image_str: str = None,
    input_image_path: str = None,
    is_realistic: bool = False,
    generator: ExpressionGenerator = None,
):
    image_str = utils.is_image_valid(input_image_path, image_str)
    if not image_str:
        return

    if is_realistic:
        log.info("Using clip prompts since realistic is set to true.")

    generator = generator or ExpressionGenerator(sd)
    generator.generate(
        image_str,
        settings=settings,
        flavor="realistic" if is_realistic else "anime",
        output_dir=output_path,
    )


def opaque(
    sd: a1111_client.A1111Client,
    input_image_path: str,
    image_str: str,
    output_path: str,
    settings: dict = None,
):
    image_str = utils.is_image_valid(input_image_path, image_str)

    output_path = pathlib.Path(output_path).absolute()
    output_path.mkdir(parents=True, exist_ok=True)

    json_payload = build_expression_payload(
        image_str, settings, template="empty_bg.json"
    )
    output_image_path = pathlib.Path(output_path, "temp.png")

    response = sd.img2img_api(json_payload)

    if not response:
        return

    r = response.json()
    gen_info = r["info"]

    b64_to_pil(r["images"][0]).save(output_image_path)

    log.info(f"Picture generated with info: {gen_info}")
    log.info(
        f"Enforced an opaque background on image. Temp file at {output_image_path.absolute()}"
    )

    return (output_image_path, gen_info)
