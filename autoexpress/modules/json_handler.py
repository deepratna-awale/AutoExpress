# Thin wrappers kept for the standalone app; the logic lives in autoexpress_core.
import json

from autoexpress_core import get_expressions, load_payload, build_expression_payload
from autoexpress_core.payload import update_nested_key, find_nested_key


def get_opaque_payload():
    return load_payload("empty_bg.json")


def get_expression_list():
    return get_expressions("anime")


def get_clip_expression_list():
    return get_expressions("realistic")


def get_img2img_payload():
    return load_payload("payload.json")


def edit_payload_body(b64_image_str: str, payload, settings=None, expression_tags=None):
    payload = build_expression_payload(
        b64_image_str, settings, expression_tags or None, template=payload
    )
    return json.dumps(payload, indent=4)


__all__ = [
    "get_opaque_payload",
    "get_expression_list",
    "get_clip_expression_list",
    "get_img2img_payload",
    "edit_payload_body",
    "update_nested_key",
    "find_nested_key",
]
