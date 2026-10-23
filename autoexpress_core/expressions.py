"""
Expression prompts, one set per model family (see expression_sets).

FLAVORS lists the choices a UI can offer: "auto" plus every family id.
The old flavor names still work: "anime" maps to danbooru, "realistic" to sdxl_base.
"""

from . import expression_sets
from .expression_sets import AUTO, join_prompt

LEGACY_FLAVORS = {
    "anime": "danbooru",
    "realistic": expression_sets.DEFAULT_REALISTIC_FAMILY,
}

FLAVORS = [AUTO] + [family["id"] for family in expression_sets.list_families()]
DEFAULT_FLAVOR = AUTO


def resolve_flavor(flavor: str | None = AUTO, checkpoint_name: str | None = None, is_realistic: bool = False) -> str:
    """Turn a UI choice ("auto", a family id or a legacy flavor) into a family id."""
    flavor = LEGACY_FLAVORS.get(flavor, flavor)
    return expression_sets.resolve_family(flavor, checkpoint_name, is_realistic)


def get_expressions(flavor: str = AUTO, only: list[str] | None = None, checkpoint_name: str | None = None) -> dict[str, str]:
    """
    Get the expression name to prompt mapping for a flavor.

    Args:
        flavor (str): "auto", a family id or a legacy flavor name.
        only (list[str] | None): Optional subset of expression names to keep, in file order.
        checkpoint_name (str | None): Used to pick the family when flavor is "auto".

    Returns:
        dict[str, str]: Expression name mapped to its prompt.
    """
    try:
        family = resolve_flavor(flavor, checkpoint_name)
    except KeyError as error:
        raise ValueError(f"Unknown expression flavor '{flavor}'. Choose from: {', '.join(FLAVORS)}") from error

    expressions = expression_sets.load_family(family)["expressions"]
    if only:
        wanted = {name.strip().lower() for name in only if name and name.strip()}
        expressions = {name: tags for name, tags in expressions.items() if name in wanted}
    return expressions


def expression_names(flavor: str = AUTO) -> list[str]:
    return list(get_expressions(flavor))


__all__ = [
    "AUTO",
    "FLAVORS",
    "DEFAULT_FLAVOR",
    "LEGACY_FLAVORS",
    "resolve_flavor",
    "get_expressions",
    "expression_names",
    "join_prompt",
]
