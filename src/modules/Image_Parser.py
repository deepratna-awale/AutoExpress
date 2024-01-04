# Read Image Data using sd_parsers
from sd_parsers import ParserManager


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


def get_metadata(parsed_data):
    meta = parsed_data.parameters.get("parameters").split("\n")[-1].split(",")
    meta = [data for data in meta if ":" in data]
    for key_value in meta:
        key_value.strip()
        key, value = key_value.split(":", 1)
        meta_data[key.lower().strip()] = value.strip()
        # print(key, ":",value)

    return meta_data


def get_seed(meta_data: dict):
    return meta_data.get("seed")


def get_cfg_scale(meta_data: dict):
    return meta_data.get("cfg scale")


def get_size(meta_data: dict):
    width, height = meta_data.get("size").split("x")
    width, height = int(width), int(height)
    return (width, height)


def get_width(meta_data: dict):
    width = get_size(meta_data)[0]
    return width


def get_height(meta_data: dict):
    height = get_size(meta_data)[1]
    return height


def get_model(meta_data: dict):
    return meta_data.get("model")


def get_model_hash(meta_data: dict):
    return meta_data.get("model hash")


if __name__ == "__main__":
    image_path = r"Output\fix_bg.png"
    meta_data = dict()
    parser_manager = ParserManager()
    parsed_data = parser_manager.parse(image_path)
    meta_data = get_metadata(parsed_data)
    model = get_model(meta_data)
    seed = get_seed(meta_data)

    print(seed)
