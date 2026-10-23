import hashlib
import json
import struct

import pytest

from autoexpress_core import expression_loras


@pytest.mark.parametrize(
    "checkpoint, family, expected",
    [
        ("ponyDiffusionV6XL", "danbooru", "pony"),
        ("waiNSFWIllustrious_v110", None, "illustrious"),
        ("noobaiXLNAIXL_vPred10Version", None, "illustrious"),
        ("flux1-dev-fp8", None, "flux"),
        ("sd3.5_large", "natural_language", "flux"),
        ("juggernautXL_v9", "sdxl_base", "sdxl"),
        ("animagine-xl-3.1", "danbooru", "sdxl"),
        ("realisticVisionV60B1_v51VAE", "sdxl_base", "sd15"),
        ("fluffyrock-e621-v2", "e621", "sd15"),
        ("", None, "sdxl"),
    ],
)
def test_guess_architecture(checkpoint, family, expected):
    assert expression_loras.guess_architecture(checkpoint, family) == expected


@pytest.mark.parametrize("architecture", expression_loras.architectures())
def test_entries_are_complete(architecture):
    entries = expression_loras.loras_for(architecture)
    assert entries
    for entry in entries:
        assert entry["name"].startswith("AutoExpress-")
        assert entry["civitai_version_id"]
        assert len(entry["sha256"]) == 64
        assert 0 < entry["weight"] <= 1


def test_lora_prompt_uses_installed_names_only():
    assert expression_loras.lora_prompt("pony", installed_names=[]) == ""
    assert expression_loras.lora_prompt(
        "pony", installed_names=["AutoExpress-expressions-pony"]
    ) == "<lora:AutoExpress-expressions-pony:0.6>, cinematic expression style"
    # A copy the user already has under Civitai's original file name counts too.
    assert expression_loras.lora_prompt(
        "pony", installed_names=["cinematic expression style pony v1.1"]
    ).startswith("<lora:cinematic expression style pony v1.1:0.6>")


def _fake_entry(tmp_path, monkeypatch, content, sha256):
    source = tmp_path / "source.safetensors"
    source.write_bytes(content)
    entry = {
        "name": "AutoExpress-test",
        "civitai_version_id": 1,
        "sha256": sha256,
        "weight": 0.5,
        "trigger": "",
        "mirror_url": source.as_uri(),
    }
    monkeypatch.setattr(expression_loras, "loras_for", lambda arch: [dict(entry)])
    # Keep the test offline: only the mirror is tried.
    monkeypatch.setattr(expression_loras, "CIVITAI_DOWNLOAD_URL", source.as_uri() + "?{version_id}")
    return entry


def test_ensure_loras_downloads_and_verifies(tmp_path, monkeypatch):
    content = b"fake lora"
    _fake_entry(tmp_path, monkeypatch, content, hashlib.sha256(content).hexdigest().upper())
    lora_dir = tmp_path / "Lora"

    ready, failures = expression_loras.ensure_loras("sdxl", lora_dir)

    assert failures == []
    assert (lora_dir / "AutoExpress-test.safetensors").read_bytes() == content
    assert expression_loras.lora_prompt("sdxl", lora_dir=lora_dir) == "<lora:AutoExpress-test:0.5>"


def test_ensure_loras_rejects_bad_hash(tmp_path, monkeypatch):
    _fake_entry(tmp_path, monkeypatch, b"tampered", "0" * 64)
    lora_dir = tmp_path / "Lora"

    ready, failures = expression_loras.ensure_loras("sdxl", lora_dir)

    assert ready == []
    assert "sha256 mismatch" in failures[0]
    assert not any(lora_dir.iterdir())


def test_apply_expression_weights_drops_lora_for_listed_expression():
    prompt = "1girl, <lora:AutoExpress-expressions-illustrious:0.6>, cinematic expression style, <lora:AutoExpress-face-enhancer-illustrious:0.5>"
    assert expression_loras.apply_expression_weights(prompt, "anger") == (
        "1girl, <lora:AutoExpress-face-enhancer-illustrious:0.5>"
    )
    assert expression_loras.apply_expression_weights(prompt, "joy") == prompt


def test_build_prompt_applies_expression_weights():
    from autoexpress_core import expression_sets

    base = "<lora:AutoExpress-expressions-illustrious:0.6>, cinematic expression style"
    assert "AutoExpress-expressions-illustrious" not in expression_sets.build_prompt(base, "anger", "illustrious")
    assert "AutoExpress-expressions-illustrious:0.6" in expression_sets.build_prompt(base, "joy", "illustrious")


def _safetensors(path, shapes):
    header = json.dumps({key: {"dtype": "F16", "shape": shape, "data_offsets": [0, 0]} for key, shape in shapes.items()})
    path.write_bytes(struct.pack("<Q", len(header)) + header.encode())
    return path


SD15_KEYS = {
    "model.diffusion_model.input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight": [320, 768],
    "cond_stage_model.transformer.text_model.embeddings.position_ids": [1, 77],
}
SDXL_KEYS = {
    "model.diffusion_model.input_blocks.4.1.transformer_blocks.0.attn2.to_k.weight": [640, 2048],
    "conditioner.embedders.1.model.ln_final.weight": [1280],
}
FLUX_KEYS = {"double_blocks.0.img_attn.qkv.weight": [9216, 3072]}


@pytest.mark.parametrize(
    "tensors, expected",
    [
        (SD15_KEYS, "sd15"),
        (SDXL_KEYS, "sdxl"),
        (FLUX_KEYS, "flux"),
        ({"model.diffusion_model.middle_block.1.transformer_blocks.0.attn2.to_k.weight": [1280, 1024]}, "sd2"),
        ({"diffusion_model.label_emb.0.0.weight": None}, "sdxl"),
        ({"cond_stage_model.transformer.text_model.final_layer_norm.weight": None}, "sd15"),
        ({"first_stage_model.decoder.conv_in.weight": [512, 4, 3, 3]}, None),
    ],
)
def test_base_architecture(tensors, expected):
    assert expression_loras.base_architecture(tensors.items()) == expected


@pytest.mark.parametrize(
    "checkpoint, family, base, expected",
    [
        # Names that match nothing used to fall back to SDXL.
        ("AAM_Anylora_AnimeMix", "danbooru", "sd15", "sd15"),
        ("AAM_Anylora_AnimeMix", "danbooru", None, "sdxl"),
        # The base wins over a misleading name or family.
        ("ponyDiffusionV6XL", "pony", "sd15", "sd15"),
        ("someMix", "natural_language", "sdxl", "sdxl"),
        ("someMix", "illustrious", "sdxl", "illustrious"),
        ("waiNSFWIllustrious_v110", None, "sdxl", "illustrious"),
        ("ponyDiffusionV6XL", None, "sdxl", "pony"),
        ("unnamed", None, "flux", "flux"),
        # SD 2.x has no LoRAs of its own, so the name decides.
        ("realisticVisionV60B1", None, "sd2", "sd15"),
    ],
)
def test_guess_architecture_with_base(checkpoint, family, base, expected):
    assert expression_loras.guess_architecture(checkpoint, family, base) == expected


def test_checkpoint_base_architecture_reads_header(tmp_path):
    assert expression_loras.checkpoint_base_architecture(_safetensors(tmp_path / "AAM_Anylora_AnimeMix.safetensors", SD15_KEYS)) == "sd15"
    assert expression_loras.checkpoint_base_architecture(_safetensors(tmp_path / "mix.safetensors", SDXL_KEYS)) == "sdxl"
    (tmp_path / "broken.safetensors").write_bytes(b"\x01")
    assert expression_loras.checkpoint_base_architecture(tmp_path / "broken.safetensors") is None
    assert expression_loras.checkpoint_base_architecture(tmp_path / "missing.safetensors") is None
    assert expression_loras.checkpoint_base_architecture(tmp_path / "old.ckpt") is None
    assert expression_loras.checkpoint_base_architecture(None) is None
