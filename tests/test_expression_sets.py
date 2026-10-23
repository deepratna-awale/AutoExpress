import pytest

from autoexpress.modules import expression_sets


FAMILIES = [f["id"] for f in expression_sets.list_families()]


def test_all_families_cover_the_same_expressions():
    reference = set(expression_sets.load_family("danbooru")["expressions"])
    assert len(reference) == 28
    for family_id in FAMILIES:
        assert set(expression_sets.load_family(family_id)["expressions"]) == reference


@pytest.mark.parametrize("family_id", FAMILIES)
def test_family_has_required_fields(family_id):
    family = expression_sets.load_family(family_id)
    for key in ("name", "description", "models", "quality_tags", "negative"):
        assert key in family
    assert all(prompt.strip() for prompt in family["expressions"].values())


@pytest.mark.parametrize(
    "checkpoint, expected",
    [
        ("ponyDiffusionV6XL_v6StartWithThisOne.safetensors", "pony"),
        ("autismmixSDXL_autismmixPony.safetensors", "pony"),
        ("waiNSFWIllustrious_v110.safetensors", "illustrious"),
        ("noobaiXLNAIXL_vPred10Version.safetensors", "illustrious"),
        ("flux1-dev-fp8.safetensors", "natural_language"),
        ("sd3.5_large.safetensors", "natural_language"),
        ("fluffyrock-e621-v2.safetensors", "e621"),
        ("animagine-xl-3.1.safetensors", "danbooru"),
        ("juggernautXL_v9.safetensors", "danbooru"),
        ("", "danbooru"),
    ],
)
def test_guess_family(checkpoint, expected):
    assert expression_sets.guess_family(checkpoint) == expected


def test_guess_family_realistic_fallback():
    assert expression_sets.guess_family("juggernautXL_v9", is_realistic=True) == "sdxl_base"


def test_resolve_family():
    assert expression_sets.resolve_family("pony") == "pony"
    assert expression_sets.resolve_family("auto", "flux1-dev") == "natural_language"
    with pytest.raises(KeyError):
        expression_sets.resolve_family("not-a-family")
    with pytest.raises(KeyError):
        expression_sets.load_family("../payload")


def test_build_prompt_adds_missing_quality_tags_once():
    prompt = expression_sets.build_prompt("score_9, 1girl, solo,", "joy", "pony")
    assert prompt.count("score_9") == 1
    assert prompt.startswith("score_8_up, score_7_up, score_9, 1girl, solo, happy")


def test_build_negative_does_not_duplicate():
    negative = expression_sets.build_negative("score_4, blurry", "pony")
    assert negative == "score_4, blurry, score_5, score_6"


def test_join_prompt_skips_blanks():
    assert expression_sets.join_prompt("a,", "", None, " b ") == "a, b"
