import requests
import io
import base64
from PIL import Image, PngImagePlugin
from .logger import setup_logging
import pathlib


# Setup logging as per logger.py configuration
log = setup_logging()

use_https = False
if use_https:
    protocol = "https://"
else:
    protocol = "http://"

ip = "127.0.0.1"
port = "7860"

url = f"{protocol}{ip}:{port}"

img2img_api_path = "/sdapi/v1/img2img"
samplers_api_path = "/sdapi/v1/samplers"
models_api_path = "/sdapi/v1/sd-models"
loras_api_path = "/sdapi/v1/loras"
extensions_api_path = "/sdapi/v1/extensions"
interrupt_api_path = "/sdapi/v1/interrupt"
image_info_api_path = "/sdapi/v1/png-info"


def interrupt():
    response = requests.post(
        url=f"{url}{interrupt_api_path}",
        headers={"Content-Type": "application/json"},
    )

    if response.status_code != 200:
        log.error(f"Request failed with code: {response.status_code} {response.json()}")
        return False
    
    r = response.json()
    log.error(f"Interrupted by user.{r.text}" )
    return True

def get_extensions():
    response = requests.get(
        url=f"{url}{extensions_api_path}",
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
    log.debug(f"Found following extensions: {extensions}")
    
    if ext in extensions:
        log.info(f"Found {ext} extension.")

        if extensions[ext] == True:
            log.info(f"{ext} extension is enabled.")
            return True

        else:
            log.warning(f"Please enable the {ext} extension if you want to use it.")
            return False

    log.error(f"Could not find {ext} extension")
    return False


def get_loras():
    loras = None
    response = requests.get(
        url=f"{url}{loras_api_path}",
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
        url=f"{url}{samplers_api_path}",
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
        url=f"{url}{models_api_path}",
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


def img2img_api(json_payload):
    
    response = requests.post(
        url=f"{url}{img2img_api_path}",
        data=json_payload,
        headers={"Content-Type": "application/json"},
    )

    if response.status_code == 200:
        return response
    
    log.error(f"Request failed with code: {response.status_code} {response.json()}")
    return False


def get_image_info(b64_image):
    png_payload = "data:image/png;base64," + b64_image
    
    response = requests.post(
        url=f"{url}{image_info_api_path}", 
        json=png_payload,
        headers={"Content-Type": "application/json"}
        )
    
    if response.status_code == 200:
        return response

    log.error(f"Request failed with code: {response.status_code} {response.json()}")
    return False

def main():
    import utils
    file_path = r"D:\Workspace\AI\stable-diffusion-webui\outputs\txt2img-images\2024-04-15\00018-4139222450.png"
    file_path = pathlib.Path(file_path)
    image_str = utils.raw_b64_img(file_path)

    json_body = {
        "prompt": "",
        "negative_prompt": "",
        "styles": [""],
        "seed": -1,
        "subseed": -1,
        "subseed_strength": 0,
        "seed_resize_from_h": -1,
        "seed_resize_from_w": -1,
        "sampler_name": "Euler",
        "scheduler": "Automatic",
        "batch_size": 1,
        "n_iter": 1,
        "steps": 50,
        "cfg_scale": 7,
        "width": 512,
        "height": 768,
        "restore_faces": False,
        "tiling": True,
        "do_not_save_samples": False,
        "do_not_save_grid": False,
        "eta": 0,
        "denoising_strength": 0.75,
        "s_min_uncond": 0,
        "s_churn": 0,
        "s_tmax": 0,
        "s_tmin": 0,
        "s_noise": 0,
        "override_settings": {},
        "override_settings_restore_afterwards": True,
        "refiner_checkpoint": "",
        "refiner_switch_at": 0,
        "disable_extra_networks": False,
        "firstpass_image": "",
        "comments": {},
        "init_images": [""],
        "resize_mode": 0,
        "image_cfg_scale": 7,
        "mask": "string",
        "mask_blur_x": 4,
        "mask_blur_y": 4,
        "mask_blur": 0,
        "mask_round": True,
        "inpainting_fill": 0,
        "inpaint_full_res": True,
        "inpaint_full_res_padding": 0,
        "inpainting_mask_invert": 0,
        "initial_noise_multiplier": 0,
        "latent_mask": "string",
        "force_task_id": "string",
        "sampler_index": "Euler",
        "include_init_images": False,
        "script_name": "",
        "script_args": [],
        "send_images": True,
        "save_images": False,
        "alwayson_scripts": {},
        "infotext": "string",
    }

    png_payload = "data:image/png;base64," + image_str
    json_body["init_images"][0] = png_payload

    response = img2img_api(json_body)
    log(response.json()['detail'][0]['msg'])
    log(response.json()["detail"][0]["type"])
    if response == 200:
        r = response.json()
        for i in r['images']:
            image = Image.open(io.BytesIO(base64.b64decode(i.split(",",1)[0])))

            info_response  = get_image_info(i)
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_text("parameters", info_response.json().get("info"))
            image.save("Output/output.png", pnginfo=pnginfo)


if __name__ == "__main__":
    main()
    
