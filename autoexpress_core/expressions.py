import json
import pathlib
from functools import lru_cache

RESOURCES = pathlib.Path(__file__).parent / "resources"

# Prompt flavours. Anime uses booru style tags, the others use natural language
# descriptions that work better with CLIP/T5 style text encoders.
FLAVORS = {
    "anime": "expressions.json",
    "realistic": "clip_expressions.json",
    "illustrious": "illu_expressions.json",
}
DEFAULT_FLAVOR = "anime"


@lru_cache(maxsize=None)
def _load(flavor: str) -> tuple[tuple[str, str], ...]:
    if flavor not in FLAVORS:
        raise ValueError(f"Unknown expression flavor '{flavor}'. Choose from: {', '.join(FLAVORS)}")
    with open(RESOURCES / FLAVORS[flavor], "r", encoding="utf-8") as exp_file:
        return tuple(json.load(exp_file).items())


def get_expressions(flavor: str = DEFAULT_FLAVOR, only: list[str] | None = None) -> dict[str, str]:
    """
    Get the expression name to prompt mapping for a flavor.

    Args:
        flavor (str): One of FLAVORS.
        only (list[str] | None): Optional subset of expression names to keep, in file order.

    Returns:
        dict[str, str]: Expression name mapped to its prompt.
    """
    expressions = dict(_load(flavor))
    if only:
        wanted = {name.strip().lower() for name in only if name and name.strip()}
        expressions = {name: tags for name, tags in expressions.items() if name in wanted}
    return expressions


def expression_names(flavor: str = DEFAULT_FLAVOR) -> list[str]:
    return [name for name, _ in _load(flavor)]


def join_prompt(base_prompt: str | None, expression_prompt: str | None) -> str:
    """Append an expression prompt to a base prompt, separated by a comma."""
    parts = [
        part.strip().rstrip(",").strip()
        for part in (base_prompt or "", expression_prompt or "")
    ]
    return ", ".join(part for part in parts if part)
