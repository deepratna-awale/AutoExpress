from autoexpress_core import ExpressionGenerator, build_expression_payload, expression_loras
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
    model_family: str = None,
    use_expression_loras: bool = True,
    lora_dir: str = None,
    civitai_api_key: str = None,
    generator: ExpressionGenerator = None,
):
    for _ in iter_expressions(
        sd,
        output_path,
        settings,
        image_str=image_str,
        input_image_path=input_image_path,
        is_realistic=is_realistic,
        model_family=model_family,
        use_expression_loras=use_expression_loras,
        lora_dir=lora_dir,
        civitai_api_key=civitai_api_key,
        generator=generator,
    ):
        pass


def iter_expressions(
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
    generator: ExpressionGenerator = None,
    only: list[str] = None,
):
    """Same as generate_expressions, but yields (expression name, image) as each one is saved."""
    image_str = utils.is_image_valid(input_image_path, image_str)
    if not image_str:
        return

    settings = dict(settings or {})
    generator = generator or ExpressionGenerator(sd)
    family = model_family or "auto"

    lora_prompt = ""
    if use_expression_loras:
        lora_prompt = get_expression_lora_prompt(
            sd, settings.get("ad_checkpoint"), family, is_realistic, lora_dir, civitai_api_key
        )

    yield from generator.iter_generate(
        image_str,
        settings=settings,
        flavor=family,
        only=only,
        output_dir=output_path,
        lora_prompt=lora_prompt,
        is_realistic=is_realistic,
    )


def get_expression_lora_prompt(
    sd: a1111_client.A1111Client,
    checkpoint: str,
    family: str,
    is_realistic: bool = False,
    lora_dir: str = None,
    civitai_api_key: str = None,
) -> str:
    """Download the expression LoRAs for this checkpoint if we can, and return their prompt tags."""
    from autoexpress_core import resolve_flavor

    family = resolve_flavor(family, checkpoint, is_realistic)
    lora_dir = lora_dir or sd.lora_dir

    if not lora_dir:
        log.info(
            "WebUI LoRA folder isn't reachable from here, so only expression LoRAs "
            "already installed on the server will be used."
        )

    lora_prompt = expression_loras.expression_lora_prompt(
        checkpoint,
        family,
        lora_dir=lora_dir,
        api_key=civitai_api_key,
        # lora_stems: the <lora:name> form, also for WebUIs that list files with folders and extensions
        installed_names=lambda: getattr(sd, "lora_stems", None) or sd.loras or [],
        refresh=sd.refresh_loras,
        log=log.info,
    )
    log.info(f"Expression LoRAs: {lora_prompt or 'none installed'}")
    return lora_prompt


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

    json_payload = build_expression_payload(image_str, settings, template="empty_bg.json")
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
