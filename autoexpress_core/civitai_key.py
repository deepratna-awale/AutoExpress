"""
Finds a Civitai API key the user has already set up somewhere, so AutoExpress
does not have to ask for one.

Order of precedence:
    1. an explicit key (typed into AutoExpress or its own settings)
    2. a key stored by a Civitai extension or node of the host WebUI
    3. the environment (CIVITAI_API_KEY, CIVITAI_API_TOKEN, CIVITAI_TOKEN)

Only the standard library is used. The key itself is never logged, only
where it came from.
"""

import json
import os
import pathlib
import sys

ENV_VARS = ("CIVITAI_API_KEY", "CIVITAI_API_TOKEN", "CIVITAI_TOKEN")

# Settings keys used by Civitai extensions for A1111 / Forge (stored in the
# WebUI's shared.opts / config.json).
WEBUI_OPTION_KEYS = (
    ("Civitai Browser+", "custom_api_key"),
    ("Civitai Helper", "ch_civiai_api_key"),  # sic, that is the extension's own spelling
)

LORA_MANAGER_APP = "ComfyUI-LoRA-Manager"
LORA_MANAGER_DIR_ENV = "LORA_MANAGER_SETTINGS_DIR"


def _clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _read_json(path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as json_file:
            data = json.load(json_file)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def webui_option_sources(options: dict | None) -> list[tuple[str, str | None]]:
    """Keys from A1111/Forge Civitai extensions, given shared.opts.data or a parsed config.json."""
    options = options or {}
    return [(name, _clean(options.get(key))) for name, key in WEBUI_OPTION_KEYS]


def webui_config_sources(config_path) -> list[tuple[str, str | None]]:
    """Same as webui_option_sources, read from a WebUI's config.json (for a WebUI on this machine)."""
    return webui_option_sources(_read_json(config_path))


def _user_config_dir(app_name: str) -> pathlib.Path:
    """platformdirs.user_config_dir without the dependency."""
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or pathlib.Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = pathlib.Path.home() / "Library" / "Application Support"
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or pathlib.Path.home() / ".config"
    return pathlib.Path(base) / app_name


def comfyui_sources(custom_nodes_dirs=()) -> list[tuple[str, str | None]]:
    """Keys stored by ComfyUI nodes, currently ComfyUI LoRA Manager's settings.json."""
    candidates = []
    if os.environ.get(LORA_MANAGER_DIR_ENV):
        candidates.append(pathlib.Path(os.environ[LORA_MANAGER_DIR_ENV]) / "settings.json")
    candidates.append(_user_config_dir(LORA_MANAGER_APP) / "settings.json")
    for custom_nodes in custom_nodes_dirs or ():
        for folder in ("ComfyUI-Lora-Manager", "comfyui-lora-manager", "ComfyUI-LoRA-Manager"):
            candidates.append(pathlib.Path(custom_nodes) / folder / "settings.json")

    sources = []
    for path in candidates:
        if path.is_file():
            sources.append(("ComfyUI LoRA Manager", _clean(_read_json(path).get("civitai_api_key"))))
    return sources


def env_sources() -> list[tuple[str, str | None]]:
    return [(f"${name}", _clean(os.environ.get(name))) for name in ENV_VARS]


def find_civitai_key(explicit=None, host_sources=()) -> tuple[str | None, str | None]:
    """
    Pick the Civitai API key to use.

    Args:
        explicit: Key(s) typed into AutoExpress itself, a string or a list in priority order.
        host_sources: (source name, key) pairs from the host, e.g. webui_option_sources(...).

    Returns:
        tuple: (key, where it came from), or (None, None) when there is no key anywhere.
    """
    explicit = [explicit] if isinstance(explicit, str) or explicit is None else list(explicit)
    sources = [("AutoExpress", _clean(key)) for key in explicit]
    sources += list(host_sources or ())
    sources += env_sources()

    for name, key in sources:
        if key:
            return key, name
    return None, None
