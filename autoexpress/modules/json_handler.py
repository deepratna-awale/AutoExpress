import json
from loguru import logger as log
import pathlib

def get_opaque_payload():
    with open(pathlib.Path("autoexpress/resources/empty_bg.json"), "r") as payload_file:
        return json.load(payload_file)

def get_expression_list():
    with open(pathlib.Path("autoexpress/resources/expressions.json"), "r") as exp_file:
        return json.load(exp_file)


def get_clip_expression_list():
    with open(pathlib.Path("autoexpress/resources/clip_expressions.json"), "r") as exp_file:
        return json.load(exp_file)


def get_img2img_payload():
    with open(pathlib.Path("autoexpress/resources/payload.json"), "r") as payload_file:
        return json.load(payload_file)

def update_nested_key(data, key_to_update, new_value):
    if isinstance(data, dict):
        for key, value in data.items():
            if key == key_to_update:
                data[key] = new_value
            update_nested_key(value, key_to_update, new_value)
    elif isinstance(data, list):
        for item in data:
            update_nested_key(item, key_to_update, new_value)


def find_nested_key(data, target_key):
    """Recursively search for a key in a nested structure (dictionary or list) and return its value."""
    if isinstance(data, dict):
        if target_key in data:
            return data[target_key]
        return next(
            (
                result
                for key, value in data.items()
                if (result := find_nested_key(value, target_key)) is not None
            ),
            None,
        )

    elif isinstance(data, list):
        return next(
            (
                result
                for item in data
                if isinstance(item, (dict, list))
                and (result := find_nested_key(item, target_key)) is not None
            ),
            None,
        )
    return None


def edit_payload_body(b64_image_str: str, payload, settings=None, expression_tags=None):

    if settings:
        for key, value in settings.items():
            update_nested_key(payload, key, value)

    prompt = find_nested_key(payload, "ad_prompt")
    
    if prompt:
        if prompt[-1] not in [","]:
            update_nested_key(payload, "ad_prompt", prompt + ", ")

    if expression_tags:
        update_nested_key(
            payload,
            "ad_prompt",
            prompt + str(expression_tags),
        )

    # payload["prompt"] = payload["alwayson_scripts"]["ADetailer"]["args"][2]["ad_prompt"]
    # payload["negative_prompt"] = payload["alwayson_scripts"]["ADetailer"]["args"][2][
    #     "ad_negative_prompt"
    # ]

    log.debug(f"{payload}")

    payload["init_images"][0] = b64_image_str

    json_payload = json.dumps(payload, indent=4)

    return json_payload


if __name__ == "__main__":
    expression = get_expression_list()
    print(expression.keys())
