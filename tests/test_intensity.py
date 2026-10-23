"""Expression intensity: the slider's mappings and the per-family defaults."""

import pytest

from autoexpress_core import ExpressionGenerator, expression_sets
from autoexpress_core import intensity as expression_intensity
from autoexpress_core.payload import find_nested_key


def test_resolve_clamps_and_defaults():
    assert expression_intensity.resolve(None) == 0.5
    assert expression_intensity.resolve(None, realistic=True) == 0.25
    assert expression_intensity.resolve("auto") == 0.5
    assert expression_intensity.resolve(2) == 1.0 and expression_intensity.resolve("-3") == 0.0


def test_half_is_the_classic_strength():
    assert expression_intensity.prompt_weight(0.5) == 1.0
    assert expression_intensity.lora_scale(0.5) == 1.0
    assert expression_intensity.denoise_scale(0.5) == 1.0
    assert expression_intensity.edit_tier(0.5) == "normal"
    assert expression_intensity.lora_scale(0) == 0.0 and expression_intensity.prompt_weight(1) == 1.4


def test_weight_expression_for_tags_and_sentences():
    assert expression_intensity.weight_expression("smile, :d", 0.5) == "smile, :d"
    assert expression_intensity.weight_expression("smile, :d", 0.25) == "(smile, :d:0.8)"
    assert expression_intensity.weight_expression("They smile.", 0.1, natural_language=True).endswith("slight and subtle.")
    assert "(" not in expression_intensity.weight_expression("They smile.", 0.9, natural_language=True)


def test_scale_lora_tags():
    tags = "<lora:expr:0.6>, cinematic expression style"
    assert expression_intensity.scale_lora_tags(tags, 0.5) == "<lora:expr:0.6>, cinematic expression style"
    assert expression_intensity.scale_lora_tags(tags, 1.0) == "<lora:expr:0.9>, cinematic expression style"
    assert expression_intensity.scale_lora_tags(tags, 0.0) == "cinematic expression style"


def test_families_carry_calibrated_defaults():
    families = {f["id"]: f for f in expression_sets.list_families()}
    assert families["danbooru"]["defaults"] == {"method": "inpaint", "intensity": 0.5, "edit_style": "illustration"}
    realistic = families["sdxl_base"]["defaults"]
    assert realistic["intensity"] < 0.3 and realistic["edit_style"] == "photo"
    for family in families.values():
        assert 0 <= family["defaults"]["intensity"] <= 1 and family["defaults"]["method"] in ("inpaint", "instruct")


def test_generator_tones_down_realistic_families(face_image, fake_backend):
    generator = ExpressionGenerator(fake_backend)
    generator.generate(face_image, settings={"ad_denoising_strength": 0.5}, flavor="sdxl_base", only=["joy"],
                       lora_prompt="<lora:expr:0.6>")
    prompt = find_nested_key(fake_backend.payloads[0], "ad_prompt")
    joy = expression_sets.load_family("sdxl_base")["expressions"]["joy"]
    assert f"({joy}:0.76)" in prompt  # 0.2 -> weight 0.76
    assert "<lora:expr:0.24>" in prompt  # 0.6 * 0.4
    assert find_nested_key(fake_backend.payloads[0], "ad_denoising_strength") == pytest.approx(0.41)


def test_generator_explicit_intensity_wins(face_image, fake_backend):
    ExpressionGenerator(fake_backend).generate(
        face_image, settings={"expression_intensity": 0.5}, flavor="sdxl_base", only=["joy"]
    )
    payload = fake_backend.payloads[0]
    joy = expression_sets.load_family("sdxl_base")["expressions"]["joy"]
    assert find_nested_key(payload, "ad_prompt").endswith(joy)
    assert "expression_intensity" not in str(payload)
