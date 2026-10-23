from . import utils, json_handler, expression_sets, expression_loras
from . import a1111_client
from loguru import logger as log

import io
import base64
import pathlib

from PIL import Image, PngImagePlugin

PAUSE_EXECUTION = False

def generate_expressions(
    sd: a1111_client.A1111Client,
    output_path: str,
    settings: dict,
    image_str: str = None,
    input_image_path: str = None,
    is_realistic: bool = False,
    model_family: str = None,
    use_expression_loras: bool = True,
    lora_dir: str = None,
    civitai_api_key: str = None,
):
    global PAUSE_EXECUTION
    image_str = utils.is_image_valid(input_image_path, image_str)

    output_path = pathlib.Path(output_path)
    pathlib.Path(output_path).mkdir(parents=True, exist_ok=True)

    settings = dict(settings or {})
    family = expression_sets.resolve_family(
        model_family, settings.get("ad_checkpoint"), is_realistic
    )
    expressions = expression_sets.load_family(family)["expressions"]
    base_prompt = settings.get("ad_prompt", "")
    if use_expression_loras:
        base_prompt = expression_sets.join_prompt(
            base_prompt,
            get_expression_lora_prompt(
                sd, settings.get("ad_checkpoint"), family, lora_dir, civitai_api_key
            ),
        )
    settings["ad_negative_prompt"] = expression_sets.build_negative(
        settings.get("ad_negative_prompt", ""), family
    )
    log.info(f"Using {family} expression prompts.")

    log.info(f"Output Directory: {output_path.absolute()}")

    for expression_name in expressions:
        if PAUSE_EXECUTION:
            sd.interrupt()
            PAUSE_EXECUTION = not PAUSE_EXECUTION
            log.info("Interrupted by user. Stopping..")
            return

        log.info(f"Generating image for {expression_name} expression.")

        default_request_body = json_handler.get_img2img_payload()

        settings["ad_prompt"] = expression_sets.build_prompt(
            base_prompt, expression_name, family
        )

        json_payload = json_handler.edit_payload_body(
            image_str, default_request_body, settings
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


def get_expression_lora_prompt(
    sd: a1111_client.A1111Client,
    checkpoint: str,
    family: str,
    lora_dir: str = None,
    civitai_api_key: str = None,
) -> str:
    """Download the expression LoRAs for this checkpoint if we can, and return their prompt tags."""
    architecture = expression_loras.guess_architecture(checkpoint, family)
    lora_dir = lora_dir or sd.lora_dir

    if lora_dir:
        ready, failures = expression_loras.ensure_loras(
            architecture, lora_dir, civitai_api_key, log=log.info
        )
        if ready:
            sd.refresh_loras()
        for failure in failures:
            log.warning(failure)
    else:
        log.info(
            "WebUI LoRA folder isn't reachable from here, so only expression LoRAs "
            "already installed on the server will be used."
        )

    lora_prompt = expression_loras.lora_prompt(architecture, installed_names=sd.loras or [])
    log.info(f"Expression LoRAs for {architecture}: {lora_prompt or 'none installed'}")
    return lora_prompt


def opaque(
    sd: a1111_client.A1111Client,
    input_image_path: str,
    image_str: str,
    output_path: str,
    settings: dict = None,
):
    gen_info = None

    image_str = utils.is_image_valid(input_image_path, image_str)

    output_path = pathlib.Path(output_path).absolute()
    pathlib.Path(output_path).mkdir(parents=True, exist_ok=True)

    default_request_body = json_handler.get_opaque_payload()

    json_payload = json_handler.edit_payload_body(
        image_str, default_request_body, settings, ""
    )

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
