"""Expression prompt sets per model family.

Each family lives in resources/expressions/<family>.json with:
    name, description, models, quality_tags, negative, expressions

Only the standard library is used, and paths resolve relative to this file,
so the module can move into a shared core package unchanged.
"""

import json
import pathlib
import re
from functools import lru_cache

EXPRESSIONS_DIR = pathlib.Path(__file__).resolve().parent / "resources" / "expressions"

AUTO = "auto"
DEFAULT_FAMILY = "danbooru"
DEFAULT_REALISTIC_FAMILY = "sdxl_base"

# Checked in order, first match wins. Pony comes before e621 because Pony
# merges often carry furry names too.
_FAMILY_PATTERNS = [
    ("pony", r"pony|pdxl|autismmix|score_?9"),
    ("illustrious", r"illustrious|illu|noob|\bwai|obsession"),
    ("natural_language", r"flux|sd3|sd_3|sd-3|stable.?diffusion.?3|hidream|chroma|auraflow|lumina|qwen|kolors|hunyuan"),
    ("e621", r"e621|furry|fluffy|fluffusion|yiff|bb95|indigo"),
    ("danbooru", r"anime|animagine|anything|counterfeit|meina|orangemix|abyss|\bnai\b"),
]


def list_families():
    """Return [{"id", "name", "description", "models"}] for every family file."""
    families = []
    for family_id in sorted(_family_files()):
        data = load_family(family_id)
        families.append(
            {
                "id": family_id,
                "name": data["name"],
                "description": data["description"],
                "models": data["models"],
            }
        )
    return families


def _family_files():
    return {path.stem: path for path in EXPRESSIONS_DIR.glob("*.json")}


@lru_cache(maxsize=None)
def _load(family_id):
    # Look the id up among the files on disk instead of building a path from
    # it, so a request can't point the loader outside the expressions folder.
    path = _family_files().get(family_id)
    if path is None:
        raise KeyError(f"Unknown expression family: {family_id}")
    with open(path, "r", encoding="utf-8") as family_file:
        return json.load(family_file)


def load_family(family_id):
    """Return a copy of the family data so callers can't mutate the cache."""
    return json.loads(json.dumps(_load(family_id)))


def guess_family(checkpoint_name, is_realistic=False):
    """Pick a family from a checkpoint name, falling back on the realistic flag."""
    name = (checkpoint_name or "").lower()
    for family_id, pattern in _FAMILY_PATTERNS:
        if re.search(pattern, name):
            return family_id
    return DEFAULT_REALISTIC_FAMILY if is_realistic else DEFAULT_FAMILY


def resolve_family(family_id=None, checkpoint_name=None, is_realistic=False):
    """Turn a user choice (a family id, "auto" or None) into a real family id."""
    if family_id and family_id != AUTO:
        _load(family_id)
        return family_id
    return guess_family(checkpoint_name, is_realistic)


def join_prompt(*parts):
    """Join prompt fragments with ", ", skipping blanks and stray commas."""
    cleaned = [str(p).strip().strip(",").strip() for p in parts if p]
    return ", ".join(p for p in cleaned if p)


def _missing_tags(prompt, tags):
    present = {t.strip().lower() for t in (prompt or "").split(",")}
    tags = [t.strip() for t in (tags or "").split(",")]
    return [t for t in tags if t and t.lower() not in present]


def build_prompt(base_prompt, expression, family_id, add_quality_tags=True):
    """Base prompt plus the family's quality tags (if absent) plus the expression."""
    family = _load(family_id)
    quality = _missing_tags(base_prompt, family["quality_tags"]) if add_quality_tags else []
    return join_prompt(", ".join(quality), base_prompt, family["expressions"][expression])


def build_negative(base_negative, family_id):
    """Base negative plus any of the family's negative tags not already there."""
    family = _load(family_id)
    return join_prompt(base_negative, ", ".join(_missing_tags(base_negative, family["negative"])))
