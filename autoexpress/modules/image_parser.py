# Read Image Data using sd_parsers
from sdparsers import ParserManager
from .logger import setup_logging


# Setup logging as per logger.py configuration
log = setup_logging()

def get_parsed_data(file_path):
    parser_manager = ParserManager()
    parsed_data = parser_manager.parse(file_path)
    if parsed_data:
        return parsed_data
    return None


def get_prompt(parsed_data):
    for prompt in parsed_data.prompts:
        return prompt.value


def get_negative_prompt(parsed_data):
    for prompt in parsed_data.negative_prompts:
        return prompt.value


def list_to_dict(lst):
    result_dict = {}
    for item in lst:
        # Split the string into key and value parts
        key, value = item.split(":", 1)
        # Trim any leading/trailing whitespace and add to dictionary
        result_dict[key.strip().lower()] = value.strip()
    return result_dict


def get_metadata(parsed_data):
    parameters = None
    metadata = None
    if not parsed_data:
        return "No parsed data found"

    parameters = parsed_data.parameters
    if not parameters:
        return "No parameters found in parsed data."

    parameters = parsed_data.parameters.get("parameters")
    metadata = parameters.split("\n")[-1].split(", ")
    metadata = list_to_dict(metadata)
    meta_dict = {
        key.strip().replace(" ", "_"): value for key, value in metadata.items()
    }
    return meta_dict


def get_seed(meta_data):
    if not meta_data:
        return -1
    return meta_data.get("seed")

def get_sampler(meta_data):
    if not meta_data:
        return None
    return meta_data.get("sampler")

def get_cfg_scale(meta_data: dict):
    if not meta_data:
        log.info("No metadata to extract cfg scale, defaulting to 7")
        return 7
    cfg_scale = meta_data.get("cfg scale")
    if not cfg_scale:
        return 7
    return meta_data.get("cfg scale")


def get_size(meta_data: dict):
    if not meta_data:
        log.info("No metadata found, defaulting to default portrait size 512x768")
        return (512, 768)
    width, height = meta_data.get("size").split("x")
    return (width, height)


def get_width(meta_data: dict):
    width = get_size(meta_data)[0]
    return width


def get_height(meta_data: dict):
    height = get_size(meta_data)[1]
    return height


def get_model(meta_data: dict):
    if not meta_data:
        log.info("No metadata found, cannot detect model. Setting to None")
        return None
    return meta_data.get("model")


def get_model_hash(meta_data: dict):
    if not meta_data:
        log.info("No metadata found, cannot detect model hash. Setting to None")
        return None
    return meta_data.get("model hash")


def get_lora(meta_data: dict):
    if not meta_data:
        log.info("No metadata found, cannot detect lora. Setting to None")
        return None
    return meta_data.get("lora")


def main():


    image_path = r"D:\Workspace\AI\stable-diffusion-webui\outputs\txt2img-images\2023-11-30\00005-856227872.png"

    parser_manager = ParserManager()
    parsed_data = parser_manager.parse(image_path)
    metadata = get_metadata(parsed_data)

    log.info("Acquired Metadata.")
    log(metadata)

if __name__ == "__main__":

    main()
