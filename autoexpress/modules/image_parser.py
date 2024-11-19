# Read Image Data using sd_parsers
from sd_parsers import ParserManager
from sd_parsers.data import Generators
from loguru import logger as log
import re
from PIL import Image

def get_lora_from_prompt(prompt):
    # Regular expression pattern to find text and strength
    pattern = r"<lora:(.*?):(.*?)>"

    # Find all matches
    matches = re.findall(pattern, prompt)

    log.info(matches)
    return matches

def get_size_from_image_metadata(image_path):
    width, height = 0, 0
    try:
        with Image.open(image_path) as img:
            width, height = img.size
    except Exception:
        pass

    return width, height


def get_parsed_data(image_path):
    parser_manager = ParserManager(two_pass=True, normalize_parameters=True)
    parsed_data = parser_manager.parse(image_path)
    if not parsed_data:  # return if no metadata found in image
        return None
    return parsed_data


def generate_cleaned_parameters(image_path):
    """
    Parse an image file and return a dictionary of parameters.

    Parameters:
    image_path (str): Path to the image file.

    Returns:
    dict: A dictionary of parameters in the following format:
        {
            "ad_checkpoint": str,
            "ad_sampler": str,
            "loras": str,
            "ad_scheduler": str,
            "ad_clip_skip": str,
            "seed": str,
            "ad_steps": str,
            "width": int,
            "height": int,
            "ad_cfg_scale": str,
            "ad_denoising_strength": str,
            "prompt": str,
            "negative_prompt": str,
        }
    If no parameters are found in the image, returns None.
    """
    parsed_data = get_parsed_data(image_path)
    if not parsed_data:
        return None
    # get first sampler (there may be more than one (i.e., in upscaled comfy images)
    sampler = next(iter(parsed_data.samplers), None)
    prompt = parsed_data.full_prompt

    width = parsed_data.metadata.get("width", None)
    height = parsed_data.metadata.get("height", None)

    if not width or not height:
        width, height = get_size_from_image_metadata(image_path)

    log.info(f"Image Width: {width} | Image Height: {height}")

    if parsed_data.generator == Generators.AUTOMATIC1111:
        loras = parsed_data.metadata.get("lora", None)
    elif parsed_data.generator == Generators.COMFYUI:
        loras = parsed_data.metadata.get("lora_name", None)
    if not loras:
        if prompt:
            loras = get_lora_from_prompt(prompt)
            if loras:
                lora_dict_list = []
                for lora in loras:
                    lora_dict_list.append(
                        {
                            "lora_name": lora[0],
                            "lora_strength": lora[1],
                        }
                    )
                loras = lora_dict_list

    if sampler is not None:  # return if no samplers found in image
        params = {
            "ad_checkpoint": sampler.model.name if sampler.model else None,
            "ad_sampler": sampler.name or "Euler a",
            "loras": loras,
            "ad_scheduler": sampler.parameters.get("scheduler", "Automatic"),
            "ad_clip_skip": 2,
            "seed": sampler.parameters.get("seed", -1),
            "ad_steps": sampler.parameters.get("steps", 24),
            "width": width,
            "height": height,
            "ad_cfg_scale": sampler.parameters.get("cfg_scale", 7),
            "ad_denoising_strength": 0.4,
            "ad_prompt": parsed_data.full_prompt,
            "ad_negative_prompt": parsed_data.full_negative_prompt,
        }

    return params

def generate_uncleaned_params(image_path): 
    return str(get_parsed_data(image_path))


def main():

    image_path = r"D:\Workspace\AutoExpress\uploads\ComfyUI_00011_.png"
    params = generate_cleaned_parameters(image_path)
    parsed_data = get_parsed_data(image_path)
    log.info(params)
    print(parsed_data)

if __name__ == "__main__":
    main()
