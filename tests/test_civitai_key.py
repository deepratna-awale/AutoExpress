import json

import pytest

from autoexpress_core import civitai_key


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    for name in civitai_key.ENV_VARS + (civitai_key.LORA_MANAGER_DIR_ENV,):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "xdg"))
    monkeypatch.setattr(civitai_key.pathlib.Path, "home", lambda: tmp_path / "home")


def test_explicit_beats_host_beats_env(monkeypatch):
    monkeypatch.setenv("CIVITAI_API_TOKEN", "from-env")
    host = civitai_key.webui_option_sources({"custom_api_key": "from-browser-plus"})

    assert civitai_key.find_civitai_key(["", "typed"], host) == ("typed", "AutoExpress")
    assert civitai_key.find_civitai_key([None, " "], host) == ("from-browser-plus", "Civitai Browser+")
    assert civitai_key.find_civitai_key(None, []) == ("from-env", "$CIVITAI_API_TOKEN")


def test_no_key_anywhere():
    assert civitai_key.find_civitai_key() == (None, None)


def test_civitai_helper_option_and_config_file(tmp_path):
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"ch_civiai_api_key": "helper-key"}))
    assert civitai_key.find_civitai_key(None, civitai_key.webui_config_sources(config)) == (
        "helper-key",
        "Civitai Helper",
    )
    assert civitai_key.webui_config_sources(tmp_path / "missing.json") == [
        ("Civitai Browser+", None),
        ("Civitai Helper", None),
    ]


def test_lora_manager_settings(monkeypatch, tmp_path):
    custom_nodes = tmp_path / "custom_nodes"
    (custom_nodes / "ComfyUI-Lora-Manager").mkdir(parents=True)
    (custom_nodes / "ComfyUI-Lora-Manager" / "settings.json").write_text(json.dumps({"civitai_api_key": "lm-key"}))
    assert civitai_key.find_civitai_key(None, civitai_key.comfyui_sources([custom_nodes])) == (
        "lm-key",
        "ComfyUI LoRA Manager",
    )

    pinned = tmp_path / "pinned"
    pinned.mkdir()
    (pinned / "settings.json").write_text(json.dumps({"civitai_api_key": "pinned-key"}))
    monkeypatch.setenv(civitai_key.LORA_MANAGER_DIR_ENV, str(pinned))
    assert civitai_key.find_civitai_key(None, civitai_key.comfyui_sources([custom_nodes]))[0] == "pinned-key"
