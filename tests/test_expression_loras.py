import hashlib

import pytest

from autoexpress.modules import expression_loras


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
