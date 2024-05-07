import json
import requests
import io
import base64
from PIL import Image, PngImagePlugin
from modules import logger
import pathlib
from termcolor import colored


# Setup logging as per logger.py configuration
logger.setup_logging()
log = logger.logging.getLogger(__name__)

url = "http://127.0.0.1:7860/"
img2img_api = "sdapi/v1/img2img"
samplers_api = "sdapi/v1/samplers"
models_api = "sdapi/v1/sd-models"
loras_api = "sdapi/v1/loras"
extensions_api = "sdapi/v1/extensions"

def get_extensions():
    response = requests.get(
        url=f"{url}{extensions_api}",
        headers={"Content-Type": "application/json"},
    )

    if response.status_code == 200:
        r = response.json()
        extensions = dict()
        for extension in r:
            name = extension["name"]
            extensions[name] = extension["enabled"]
    else:
        log.error(f"Request failed with code: {response.status_code} {response.json()}")

    return extensions

def is_extension(ext="adetailer"):
    extensions = get_extensions()
    print(extensions)
    if ext in extensions:
        log.info(f"Found {ext} extension.")
        if extensions[ext] == True:
            log.info(f"{ext} extension is enabled.")
            return True
        else:
            log.warning(f"Please enable the {ext} extension if you want to use it.")
            return False

    else:
        log.error(f"Could not find {ext} extension")

def get_expression_list():
    with open(r"src\resources\expressions.json", "r") as exp_file:
        expressions = json.load(exp_file)
    return [*expressions]


def get_loras():
    loras = None
    response = requests.get(
        url=f"{url}{loras_api}",
        headers={"Content-Type": "application/json"},
    )

    if response.status_code == 200:
        r = response.json()
        loras = []
        for lora in r:
            loras.append(lora["name"])
    else:
        log.error(f"Request failed with code: {response.status_code} {response.json()}")

    return loras


def get_samplers():
    samplers = None
    response = requests.get(
        url=f"{url}{samplers_api}",
        headers={"Content-Type": "application/json"},
    )

    if response.status_code == 200:
        r = response.json()
        samplers = []
        for sampler in r:
            samplers.append(sampler["name"])
    else:
        log.error(f"Request failed with code: {response.status_code} {response.json()}")

    return samplers


def get_models():
    models = None
    response = requests.get(
        url=f"{url}{models_api}",
        headers={"Content-Type": "application/json"},
    )

    if response.status_code == 200:
        r = response.json()
        models = []
        for model in r:
            models.append(model["model_name"])
    else:
        log.error(f"Request failed with code: {response.status_code} {response.json()}")

    return models


def make_base_prompts(
    settings: dict, quality_prompt: str = None, negative_quality_prompt: str = None
):
    prompt = ""
    negative_prompt = ""

    if not quality_prompt:
        quality_prompt = str(
            "masterpiece, best quality, high quality, highres, ultra-detailed,"
        )
    if not negative_quality_prompt:
        negative_quality_prompt = str(
            "worst quality, low quality, normal quality,easynegative,"
        )

    if settings.get("use_quality"):
        settings.pop("use_quality")

        if settings.get("prompt"):
            prompt = ",".join(settings.get("prompt"))
            prompt = quality_prompt + prompt

        else:
            prompt = quality_prompt

    if settings.get("use_negative_quality"):
        settings.pop("use_negative_quality")
        if settings.get("negative_prompt"):
            negative_prompt = ",".join(settings.get("negative_prompt"))
            negative_prompt = str(negative_quality_prompt + negative_prompt)

        else:
            negative_prompt = negative_quality_prompt

    return (prompt, negative_prompt)


def edit_payload_body(b64_image_str: str, payload, settings=None, expression_tags=None):
    if settings:
        for key, value in settings.items():
            payload[key] = value

    payload["init_images"][0] = b64_image_str
    if expression_tags:
        payload["prompt"] += str("," + expression_tags)


    json_payload = json.dumps(payload, indent=4)
    return json_payload


def get_b64_str(input_image):
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


def generate_expressions(
    output_path: str,
    settings: dict,
    image_str: str = None,
    input_image_path: str = None
):
    
    if not input_image_path and not image_str:
        log.error("Need atleast an image path/ base 64 string.")
        return
    
    if not image_str:
        input_image_path = pathlib.Path(input_image_path)
        b64_image_str = get_b64_str(input_image_path)
    else:
        b64_image_str = image_str

    output_path = pathlib.Path(output_path)
    pathlib.Path(output_path).mkdir(parents=True, exist_ok=True)

    settings["prompt"], settings["negative_prompt"] = make_base_prompts(settings)

    with open(r"src\resources\payload.json", "r") as payload_file:
        default_request_body = json.load(payload_file)

    with open(r"src\resources\expressions.json", "r") as exp_file:
        expressions = json.load(exp_file)

    log.info(f"Output Directory: {output_path.absolute()}")

    for expression_name, tags in expressions.items():
        log.info(
            f"Generating image for {colored(expression_name, 'green')} expression."
        )

        json_payload = edit_payload_body(
            b64_image_str, default_request_body, settings, tags
        )

        output_image_path = pathlib.Path(output_path, expression_name + ".png")

        response = requests.post(
            url=f"{url}{img2img_api}",
            data=json_payload,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            r = response.json()
            image = Image.open(io.BytesIO(base64.b64decode(r["images"][0])))
            image.save(output_image_path)
            log.info(colored("Done.", "green"))

        else:
            log.error(f"Error Code: {response.status_code} {response.json()}")

    log.info(colored(f"Generated all Expressions in {output_path.absolute()}", "green"))
    # fpath = colored(str(input_image_path.absolute()), "yellow")
    # log.info(f"Removing temp file {fpath}")
    # input_image_path.unlink()


def opaque(input_image_path, output_path, settings=None):
    gen_info = None
    input_image_path = pathlib.Path(input_image_path)
    b64_image_str = get_b64_str(input_image_path)

    output_path = pathlib.Path(output_path).absolute()

    pathlib.Path(output_path).mkdir(parents=True, exist_ok=True)

    with open(r"src\resources\empty_bg.json", "r") as payload_file:
        default_request_body = json.load(payload_file)

    json_payload = edit_payload_body(b64_image_str, default_request_body, settings, "")

    output_image_path = pathlib.Path(output_path, "temp" + ".png")

    response = requests.post(
        url=f"{url}{img2img_api}",
        data=json_payload,
        headers={"Content-Type": "application/json"},
    )

    if response.status_code == 200:
        r = response.json()

        img_str = r["images"][0]
        info = r["info"]

        image = Image.open(io.BytesIO(base64.b64decode(img_str)))
        image.save(output_image_path)

        log.info(f"Image Saved")

        info = info.replace("true", "False")
        info = info.replace("false", "False")
        info = info.replace("null", "None")

        gen_info = eval(info)

    else:
        log.error(f"Error Code: {response.status_code} {response.json()}")

    log.info(
        colored(
            f"Enforced an opaque background on image. Temp file at {output_image_path.absolute()}",
            "yellow",
        )
    )

    return (output_image_path, gen_info)


def main():

    input_image = r"D:\Workspace\AI\stable-diffusion-webui\outputs\txt2img-images\2024-04-15\00032-4139222450.png"

    output_dir = r"Output"
    char_name = r"Hina"

    output_path = pathlib.Path(output_dir, char_name)

    image_path, settings = opaque(input_image, output_path=output_path)

    log.info(settings)

    settings.update({"use_quality": True})
    settings.update({"use_negative_quality": True})
    settings.update({"ad_denoising_strength": 0.35})
    settings.update({"seed": 4139222450})
    settings.update(
        {
            "prompt": [
                "(white eyes:1.2)",
                "byakugan",
            ]
        }
    )
    settings.update(
        {
            "negative_prompt": [
                "3d",
                "headband",
            ]
        }
    )

    generate_expressions(image_path, output_path=output_path, settings=settings)


if __name__ == "__main__":
    main()
    # ext = is_extension("adetailer")
