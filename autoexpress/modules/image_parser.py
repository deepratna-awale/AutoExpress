# Read Image Data using sd_parsers
from sd_parsers import ParserManager
from sd_parsers.data import Generators
from loguru import logger as log
import re

def get_lora_from_prompt(prompt):
    # Regular expression pattern to find text and strength
    pattern = r"<lora:(.*?):(.*?)>"

    # Find all matches
    matches = re.findall(pattern, prompt)

    log.info(matches)
    return matches


def get_parsed_data(image_path):
    parser_manager = ParserManager()
    parsed_data = parser_manager.parse(image_path)
    if not parsed_data:  # return if no metadata found in image
        return None
    return parsed_data


def generate_parameters(image_path):
    parsed_data = get_parsed_data(image_path)

    # get first sampler (there may be more than one (i.e., in upscaled comfy images)
    sampler = next(iter(parsed_data.samplers), None)
    if sampler is None:  # return if no samplers found in image
        return None

    prompt = parsed_data.full_prompt
    if prompt:
        lora = get_lora_from_prompt(prompt)

    width, height = "", ""
    if parsed_data.generator == Generators.AUTOMATIC1111:
        try:
            # almost every SD image generator uses a different way to store image sizes
            width, height = parsed_data.metadata["Size"].split("x")
        except Exception:
            pass

    params = {
        "checkpoint": sampler.model.name if sampler.model else None,
        "sampler": sampler.name,
        "lora": parsed_data.metadata.get("lora", None) or parsed_data.metadata.get("lora_name", None),
        "scheduler": sampler.parameters.get("scheduler", None),
        "clip_skip": "2",
        "seed": sampler.parameters.get("seed", None),
        "steps": sampler.parameters.get("steps", None),
        "inpaint_width": width,
        "inpaint_height": height,
        "cfg_scale": sampler.parameters.get("cfg_scale", None),
        "denoising_strength": "0.5",
        "prompt": parsed_data.full_prompt,
        "negative_prompt": parsed_data.full_negative_prompt,
    }
    return params

def generate_uncleaned_params(image_path): 
    return str(get_parsed_data(image_path))


def main():

    image_path = r"D:\Workspace\AutoExpress\uploads\ComfyUI_00011_.png"
    params = generate_parameters(image_path)
    parsed_data = get_parsed_data(image_path)
    log.info(params)
    print(parsed_data)

if __name__ == "__main__":
    main()
