"""
Host-agnostic core of AutoExpress.

Everything a front end needs to turn one character image into a set of
expression images lives here: the expression prompt sets per model family,
the expression LoRAs, the ADetailer img2img payload, the instruction edit
mode (Qwen-Image-Edit), the generation loop and
sprite sheet helpers. Each WebUI
integration (standalone Flask app, A1111/Forge/SD.Next extension, ComfyUI
nodes, InvokeAI nodes) only adds its own UI and, where needed, a backend.

Only relative imports are used inside this package so it can be imported both
as a top level package and as a sub package of the repository (ComfyUI loads
the repository root as a package).
"""

from . import civitai_key, expression_loras, expression_sets, instruction_edit
from .expressions import (
    AUTO,
    FLAVORS,
    DEFAULT_FLAVOR,
    resolve_flavor,
    get_expressions,
    expression_names,
    join_prompt,
)
from .payload import build_expression_payload, load_payload
from .generator import ExpressionGenerator, Backend
from .grid import make_sprite_sheet
from . import images

__version__ = "2.1.1"

__all__ = [
    "civitai_key",
    "expression_loras",
    "expression_sets",
    "instruction_edit",
    "AUTO",
    "resolve_flavor",
    "FLAVORS",
    "DEFAULT_FLAVOR",
    "get_expressions",
    "expression_names",
    "join_prompt",
    "build_expression_payload",
    "load_payload",
    "ExpressionGenerator",
    "Backend",
    "make_sprite_sheet",
    "images",
]
