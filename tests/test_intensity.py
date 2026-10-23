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
    assert families["danbooru"]["defaults"] == {
        "method": "inpaint", "intensity": 0.5, "edit_style": "illustration", "expression_loras": True,
    }
    # RunPod photo tests: inpainting barely moves a real face, the edit at 0.2 looks natural.
    assert families["sdxl_base"]["defaults"] == {
        "method": "instruct", "intensity": 0.2, "edit_style": "photo", "expression_loras": False,
    }
    assert families["natural_language"]["defaults"]["method"] == "instruct"
    for family in families.values():
        assert 0 <= family["defaults"]["intensity"] <= 1 and family["defaults"]["method"] in ("inpaint", "instruct")


def test_generator_tones_down_realistic_families(face_image, fake_backend):
    generator = ExpressionGenerator(fake_backend)
    generator.generate(face_image, settings={"ad_denoising_strength": 0.5}, flavor="sdxl_base", only=["joy"],
                       lora_prompt="<lora:expr:0.6>")
    prompt = find_nested_key(fake_backend.payloads[0], "ad_prompt")
    joy = expression_sets.load_family("sdxl_base")["expressions"]["joy"]
    # 0.2 -> weight 0.76, with the family's own (tag:1.4) weights removed so they don't cancel it
    assert f"({expression_intensity.strip_weights(joy)}:0.76)" in prompt and ":1.4" not in prompt
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


def test_strip_weights_keeps_escaped_parentheses():
    assert expression_intensity.strip_weights("(angry:1.4), ((frown)), \\(smile\\)") == "angry, frown, \\(smile\\)"


def test_photo_offsets_per_expression():
    from autoexpress_core import instruction_edit

    assert instruction_edit.expression_intensity_for("anger", 0.2, "photo") == pytest.approx(0.1)
    assert instruction_edit.expression_intensity_for("joy", 0.2, "photo") == 0.2
    assert instruction_edit.expression_intensity_for("anger", 0.2, "illustration") == 0.2
    surprise = instruction_edit.build_instruction("surprise", style="photo", intensity=0.1)
    assert "eyes their normal size, eyebrows slightly raised, lips slightly parted" in surprise
    assert "pale" not in expression_sets.load_family("sdxl_base")["expressions"]["fear"]
