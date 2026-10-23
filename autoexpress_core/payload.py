import copy
import json
import pathlib
from functools import lru_cache

from .expressions import join_prompt
from .log import log

RESOURCES = pathlib.Path(__file__).parent / "resources"

SAME_CHECKPOINT = "Use same checkpoint"


@lru_cache(maxsize=None)
def _read(name: str) -> str:
    with open(RESOURCES / name, "r", encoding="utf-8") as payload_file:
        return payload_file.read()


def load_payload(name: str = "payload.json") -> dict:
    """Return a fresh copy of one of the bundled A1111 request bodies."""
    return json.loads(_read(name))


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
                for value in data.values()
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


def apply_settings(payload: dict, settings: dict | None) -> dict:
    """Write every setting into the payload wherever its key appears."""
    if not settings:
        return payload

    for key, value in settings.items():
        update_nested_key(payload, key, value)

    # Since A1111 1.9 the seed is also passed through the built-in "Seed" script,
    # whose args override the top level value, so keep both in sync.
    if "seed" in settings:
        seed_script = payload.get("alwayson_scripts", {}).get("Seed")
        if seed_script and seed_script.get("args"):
            seed_script["args"][0] = settings["seed"]

    if not find_nested_key(payload, "ad_checkpoint"):
        update_nested_key(payload, "ad_checkpoint", SAME_CHECKPOINT)

    return payload


def build_expression_payload(
    b64_image_str: str,
    settings: dict | None = None,
    expression_prompt: str | None = None,
    template: str | dict = "payload.json",
) -> dict:
    """
    Build an img2img request body that inpaints one expression on the face with ADetailer.

    Args:
        b64_image_str (str): Base64 encoded input image (raw or data URI).
        settings (dict | None): Values to write into the payload, e.g. ad_prompt, ad_steps, seed.
        expression_prompt (str | None): Expression prompt appended to ad_prompt.
        template (str | dict): Bundled payload file name, or a payload dict, to start from.

    Returns:
        dict: The request body, ready for /sdapi/v1/img2img.
    """
    payload = load_payload(template) if isinstance(template, str) else copy.deepcopy(template)
    payload = apply_settings(payload, copy.deepcopy(settings))

    if expression_prompt is not None:
        base_prompt = find_nested_key(payload, "ad_prompt")
        update_nested_key(payload, "ad_prompt", join_prompt(base_prompt, expression_prompt))

    payload["init_images"] = [b64_image_str]

    log.debug(f"Built payload with ad_prompt: {find_nested_key(payload, 'ad_prompt')}")
    return payload
