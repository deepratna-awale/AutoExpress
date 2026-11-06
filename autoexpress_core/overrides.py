"""
Per-expression prompts and settings.

A character's set sometimes has one expression that comes out wrong. An override gives that one
expression its own prompt and settings (seed, denoising strength, intensity, steps ...) while the
rest of the set keeps the shared ones. Overrides are saved next to the sprites, in
<output folder>/autoexpress_overrides.json, so every later run for that character (the whole set or
a single retry) uses them again, and the file can be exported and imported.

The file looks like this:

    {
      "version": 1,
      "expressions": {
        "joy": {
          "prompt": "(laughing, closed eyes:1.1)",
          "settings": {"seed": 1234, "ad_denoising_strength": 0.6}
        }
      }
    }

"prompt" replaces the expression's own part of the prompt: the expression tags in face inpainting
(the character prompt, quality tags and expression LoRAs stay), or the whole edit instruction in
the instruction edit mode. Leave it empty to keep the default wording.
"""

import json
import pathlib

FILE_NAME = "autoexpress_overrides.json"
VERSION = 1
MAX_PROMPT = 10_000

# setting: (type, min, max). The same ranges the /generate route accepts.
NUMBERS = {
    "seed": (int, -1, 2**63 - 1),
    "ad_steps": (int, 1, 150),
    "ad_cfg_scale": (float, 0.0, 30.0),
    "ad_denoising_strength": (float, 0.0, 1.0),
    "expression_intensity": (float, 0.0, 1.0),
    "edit_steps": (int, 1, 100),
    "edit_cfg_scale": (float, 0.0, 20.0),
}
TEXTS = ("ad_negative_prompt", "ad_sampler", "ad_scheduler")
SETTINGS = (*NUMBERS, *TEXTS)


class OverrideError(ValueError):
    """Bad override data. errors maps a field ("joy.settings.seed") to a message."""

    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__("; ".join(f"{k}: {v}" for k, v in errors.items()))


def normalize(data) -> dict[str, dict]:
    """
    Check and clean overrides: {expression: {"prompt": str, "settings": {...}}}.

    Accepts the whole file ({"expressions": {...}}) or just the mapping. Expression names are
    lower-cased, unknown settings are refused, empty entries are dropped.
    """
    if isinstance(data, dict) and isinstance(data.get("expressions"), dict):
        data = data["expressions"]
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise OverrideError({"overrides": "must be an object of expression name to prompt and settings"})

    errors: dict[str, str] = {}
    result: dict[str, dict] = {}
    for raw_name, entry in data.items():
        name = str(raw_name).strip().lower()
        if not name:
            continue
        if not isinstance(entry, dict):
            errors[name] = "must be an object with prompt and settings"
            continue
        clean: dict = {}
        prompt = entry.get("prompt")
        if prompt not in (None, ""):
            if not isinstance(prompt, str):
                errors[f"{name}.prompt"] = "must be text"
            elif len(prompt) > MAX_PROMPT:
                errors[f"{name}.prompt"] = f"is longer than {MAX_PROMPT} characters"
            elif prompt.strip():
                clean["prompt"] = prompt.strip()
        settings = entry.get("settings") or {}
        if not isinstance(settings, dict):
            errors[f"{name}.settings"] = "must be an object"
            settings = {}
        clean_settings = {}
        for key, value in settings.items():
            field = f"{name}.settings.{key}"
            if value is None or value == "":
                continue
            if key in NUMBERS:
                cast, low, high = NUMBERS[key]
                try:
                    number = cast(float(value)) if cast is int else cast(value)
                except (TypeError, ValueError):
                    errors[field] = f"must be a number, got {value!r}"
                    continue
                if not low <= number <= high:
                    errors[field] = f"must be between {low} and {high}"
                    continue
                clean_settings[key] = number
            elif key in TEXTS:
                if not isinstance(value, str) or len(value) > MAX_PROMPT:
                    errors[field] = "must be text"
                    continue
                clean_settings[key] = value
            else:
                errors[field] = f"unknown setting, use one of: {', '.join(SETTINGS)}"
        if clean_settings:
            clean["settings"] = clean_settings
        if clean:
            result[name] = clean
    if errors:
        raise OverrideError(errors)
    return result


def path_for(folder: str | pathlib.Path) -> pathlib.Path:
    return pathlib.Path(folder) / FILE_NAME


def load(folder: str | pathlib.Path) -> dict[str, dict]:
    """The overrides saved in a character's output folder, {} when there are none (or the file is unreadable)."""
    path = path_for(folder)
    if not path.is_file():
        return {}
    try:
        return normalize(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def save(folder: str | pathlib.Path, overrides: dict[str, dict]) -> pathlib.Path:
    """Write the overrides to the folder (removing the file when there are none). Returns its path."""
    path = path_for(folder)
    overrides = normalize(overrides)
    if not overrides:
        path.unlink(missing_ok=True)
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document(overrides), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def document(overrides: dict[str, dict]) -> dict:
    """The file's contents for these overrides, also what an export downloads."""
    return {"version": VERSION, "expressions": dict(sorted(overrides.items()))}


def merge(saved: dict[str, dict], new: dict[str, dict]) -> dict[str, dict]:
    """Saved overrides with new ones on top; a new entry replaces the saved one for that expression."""
    return {**saved, **new}


def apply(settings: dict, override: dict | None) -> dict:
    """The shared settings with one expression's settings on top."""
    if not override or not override.get("settings"):
        return dict(settings)
    return {**settings, **override["settings"]}
