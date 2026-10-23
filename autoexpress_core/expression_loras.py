"""Expression LoRAs per base architecture.

resources/expression_loras.json lists, for each architecture (pony,
illustrious, sdxl, sd15, flux), the LoRAs that help faces show emotion. This
module picks the right ones for a checkpoint, downloads any that are missing
into a LoRA folder, and builds the <lora:...> tags for the prompt.

Only the standard library is used, and paths resolve relative to this file,
so the module can move into a shared core package unchanged.
"""

import hashlib
import json
import os
import pathlib
import re
import shutil
import urllib.request
from functools import lru_cache

LORAS_FILE = pathlib.Path(__file__).resolve().parent / "resources" / "expression_loras.json"

CIVITAI_DOWNLOAD_URL = "https://civitai.com/api/download/models/{version_id}"
CIVITAI_KEY_ENV = "CIVITAI_API_KEY"
LORA_EXTENSION = ".safetensors"

# The prompt family already says which architecture these are.
_FAMILY_ARCHITECTURE = {
    "pony": "pony",
    "illustrious": "illustrious",
    "natural_language": "flux",
}

_SD15_PATTERN = r"sd[-_ ]?1\.?5|v1-5|\b15\b|fluffyrock|anything-?v[345]|counterfeit|meina|orangemix|abyss|realisticvision|dreamshaper_?8"


@lru_cache(maxsize=None)
def _load():
    with open(LORAS_FILE, "r", encoding="utf-8") as loras_file:
        data = json.load(loras_file)
    return {arch: items for arch, items in data.items() if not arch.startswith("_")}


def architectures():
    return sorted(_load())


def guess_architecture(checkpoint_name, family_id=None):
    """Pick the LoRA architecture for a checkpoint, using the prompt family as a hint."""
    name = (checkpoint_name or "").lower()

    if re.search(r"pony|pdxl|autismmix", name):
        return "pony"
    if re.search(r"illustrious|illu|noob|\bwai", name):
        return "illustrious"
    if re.search(r"flux", name):
        return "flux"
    if family_id in _FAMILY_ARCHITECTURE:
        return _FAMILY_ARCHITECTURE[family_id]
    if re.search(_SD15_PATTERN, name) and "xl" not in name:
        return "sd15"
    return "sdxl"


def loras_for(architecture):
    """Return copies of the LoRA entries for an architecture ([] if none)."""
    return [dict(entry) for entry in _load().get(architecture, [])]


def lora_path(entry, lora_dir):
    return pathlib.Path(lora_dir) / f"{entry['name']}{LORA_EXTENSION}"


def _installed_name(entry, lora_dir=None, installed_names=None):
    """The name the WebUI knows this LoRA by, or None if it isn't installed."""
    candidates = [entry["name"], pathlib.Path(entry.get("original_file") or "").stem]
    candidates = [c for c in candidates if c]

    if installed_names is not None:
        known = set(installed_names)
        return next((c for c in candidates if c in known), None)

    if lora_dir:
        for candidate in candidates:
            if (pathlib.Path(lora_dir) / f"{candidate}{LORA_EXTENSION}").is_file():
                return candidate
    return None


def _download_urls(entry, api_key=None):
    if entry.get("mirror_url"):
        yield entry["mirror_url"], {}
    url = CIVITAI_DOWNLOAD_URL.format(version_id=entry["civitai_version_id"])
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    yield url, headers


def download_lora(entry, lora_dir, api_key=None, timeout=60):
    """Download one LoRA into lora_dir, checking its sha256. Returns the file path."""
    api_key = api_key or os.environ.get(CIVITAI_KEY_ENV)
    target = lora_path(entry, lora_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")

    errors = []
    for url, headers in _download_urls(entry, api_key):
        request = urllib.request.Request(url, headers={"User-Agent": "AutoExpress", **headers})
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response, open(partial, "wb") as out:
                while chunk := response.read(1 << 20):
                    digest.update(chunk)
                    out.write(chunk)
        except Exception as error:  # try the next source
            errors.append(f"{url}: {error}")
            partial.unlink(missing_ok=True)
            continue

        expected = (entry.get("sha256") or "").lower()
        if expected and digest.hexdigest() != expected:
            partial.unlink(missing_ok=True)
            errors.append(f"{url}: sha256 mismatch")
            continue

        shutil.move(str(partial), str(target))
        return target

    hint = "" if api_key else f" Civitai needs an API key for downloads; set {CIVITAI_KEY_ENV}."
    raise RuntimeError(f"Could not download {entry['name']}: {'; '.join(errors)}.{hint}")


def ensure_loras(architecture, lora_dir, api_key=None, log=None):
    """Download any missing LoRAs for an architecture. Returns (entries, failures)."""
    ready, failures = [], []
    for entry in loras_for(architecture):
        if _installed_name(entry, lora_dir=lora_dir):
            ready.append(entry)
            continue
        if log:
            log(f"Downloading expression LoRA {entry['name']} ({entry.get('size_mb', '?')} MB)")
        try:
            download_lora(entry, lora_dir, api_key)
            ready.append(entry)
        except RuntimeError as error:
            failures.append(str(error))
            if log:
                log(str(error))
    return ready, failures


def lora_prompt(architecture, lora_dir=None, installed_names=None):
    """<lora:name:weight> tags plus trigger words for the installed LoRAs."""
    parts = []
    for entry in loras_for(architecture):
        name = _installed_name(entry, lora_dir=lora_dir, installed_names=installed_names)
        if not name:
            continue
        parts.append(f"<lora:{name}:{entry['weight']}>")
        if entry.get("trigger"):
            parts.append(entry["trigger"])
    return ", ".join(parts)


def expression_lora_prompt(
    checkpoint_name,
    family_id=None,
    lora_dir=None,
    api_key=None,
    download=True,
    installed_names=None,
    refresh=None,
    log=None,
):
    """
    Everything a host needs in one call: pick the LoRAs for a checkpoint, fetch the
    missing ones when the LoRA folder is reachable, and return their prompt tags.

    installed_names may be a list or a callable returning one (the host's LoRA list,
    read after the refresh). refresh is called after a download so the host rescans.
    """
    architecture = guess_architecture(checkpoint_name, family_id)

    if lora_dir and download:
        ready, failures = ensure_loras(architecture, lora_dir, api_key, log=log)
        if ready and refresh:
            refresh()
        for failure in failures:
            if log:
                log(failure)

    if callable(installed_names):
        installed_names = installed_names()
    return lora_prompt(architecture, lora_dir=lora_dir, installed_names=installed_names)
