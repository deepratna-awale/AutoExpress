"""
Find a character LoRA on Civitai, so edits of the character (eyes closed, mouth open) stay on model.

search() asks Civitai's public model search for LoRAs named after the character and picks the
version that fits the checkpoint's architecture (Illustrious, Pony, SDXL, SD 1.5, Flux). The
result is an entry in the same shape as resources/expression_loras.json, so the usual LoRA
download (expression_loras.download_lora) and manual install message work for it.

Only the standard library is used (urllib).
"""

import json
import re
import urllib.parse
import urllib.request

SEARCH_URL = "https://civitai.com/api/v1/models"

# Civitai base model names that work with each AutoExpress LoRA architecture, best first.
COMPATIBLE = {
    "illustrious": ("Illustrious", "NoobAI", "SDXL 1.0"),
    "pony": ("Pony", "SDXL 1.0"),
    "sdxl": ("SDXL 1.0", "Illustrious", "NoobAI", "Pony", "SDXL 0.9"),
    "sd15": ("SD 1.5",),
    "flux": ("Flux.1 D", "Flux.1 S"),
}
DEFAULT_WEIGHT = 0.8


def _words(text: str) -> list[str]:
    return [word for word in re.split(r"[^a-z0-9]+", (text or "").lower()) if word]


def name_score(query: str, title: str) -> float:
    """How well a model's title names the character: 1 when every word of the name is in it."""
    wanted = _words(query)
    if not wanted:
        return 0.0
    have = set(_words(title))
    hits = sum(1 for word in wanted if word in have)
    return hits / len(wanted)


def _version_for(model: dict, architecture: str | None) -> tuple[dict | None, int]:
    """The model version for the architecture and its rank (0 best); any version with rank 9 when nothing fits."""
    versions = model.get("modelVersions") or []
    if not versions:
        return None, 99
    preferred = COMPATIBLE.get(architecture or "", ())
    best, rank = None, 99
    for version in versions:
        base = version.get("baseModel") or ""
        if base in preferred and preferred.index(base) < rank:
            best, rank = version, preferred.index(base)
    if best is None and not preferred:
        return versions[0], 9
    return best, rank


def _primary_file(version: dict) -> dict | None:
    files = [item for item in version.get("files") or [] if (item.get("name") or "").lower().endswith(".safetensors")]
    return next((item for item in files if item.get("primary")), files[0] if files else None)


def to_entry(model: dict, version: dict) -> dict | None:
    """A LoRA entry (see resources/expression_loras.json) for a Civitai model version."""
    file = _primary_file(version)
    if file is None:
        return None
    stem = re.sub(r"\.safetensors$", "", file["name"], flags=re.IGNORECASE)
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("_") or f"character_{version['id']}"
    words = [word.strip() for word in version.get("trainedWords") or [] if word and word.strip()]
    return {
        "name": safe,
        "title": model.get("name") or safe,
        "civitai_model_id": model["id"],
        "civitai_version_id": version["id"],
        "base_model": version.get("baseModel"),
        "sha256": ((file.get("hashes") or {}).get("SHA256") or "").lower(),
        "size_mb": round((file.get("sizeKB") or 0) / 1024, 1),
        "original_file": file["name"],
        "trigger": ", ".join(words[:3]),
        "weight": DEFAULT_WEIGHT,
        "downloads": (model.get("stats") or {}).get("downloadCount", 0),
    }


def pick(models: list[dict], query: str, architecture: str | None = None) -> list[dict]:
    """Entries for the models that name the character and fit the architecture, best first."""
    ranked = []
    for model in models:
        if (model.get("type") or "LORA").upper() not in ("LORA", "LOCON", "DORA"):
            continue
        score = name_score(query, model.get("name") or "")
        if score < 0.99:
            # Civitai's search also matches tags and descriptions; insist the name is in the title.
            continue
        version, rank = _version_for(model, architecture)
        if version is None or rank == 99:
            continue
        entry = to_entry(model, version)
        if entry is None:
            continue
        downloads = (model.get("stats") or {}).get("downloadCount", 0)
        ranked.append(((rank, -downloads), entry))
    ranked.sort(key=lambda item: item[0])
    return [entry for _, entry in ranked]


def search(name: str, architecture: str | None = None, api_key: str | None = None, limit: int = 20, timeout: float = 20, fetch=None) -> list[dict]:
    """
    Character LoRAs on Civitai for a character name, best first (empty when none fit).

    fetch(url, headers) -> parsed JSON replaces the HTTP call (for tests).
    """
    name = (name or "").strip()
    if not name:
        return []
    params = {"query": name, "types": "LORA", "sort": "Most Downloaded", "limit": str(limit), "nsfw": "true"}
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    headers = {"User-Agent": "AutoExpress", "Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if fetch is None:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    else:
        data = fetch(url, headers)
    return pick(data.get("items") or [], name, architecture)


def lora_tag(entry: dict, installed_name: str | None = None) -> str:
    """The prompt text that turns the LoRA on: <lora:name:weight> plus its trigger words."""
    tag = f"<lora:{installed_name or entry['name']}:{entry.get('weight', DEFAULT_WEIGHT)}>"
    return f"{tag}, {entry['trigger']}" if entry.get("trigger") else tag
