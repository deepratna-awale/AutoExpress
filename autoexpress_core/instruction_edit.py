"""
Instruction edit mode: change the expression with an image edit model instead of face inpainting.

The default mode inpaints the face with ADetailer / FaceDetailer and a tag
prompt. This mode hands the whole image to Qwen-Image-Edit-2509 with one
sentence per expression ("Change only the facial expression. The character is
furious: ..."). It needs no face detector and no expression LoRA, keeps the
character and style, and gives much stronger expressions, but it only runs on
ComfyUI and needs a big GPU:

- qwen_image_edit_2509_fp8_e4m3fn  ~20 GB  (models/diffusion_models)
- qwen_2.5_vl_7b_fp8_scaled        ~9 GB   (models/text_encoders)
- qwen_image_vae                   ~0.25 GB (models/vae)
- Qwen-Image-Edit-2509 Lightning 8-step LoRA ~0.85 GB (models/loras), optional

24 GB of VRAM (RTX 3090 / 4090) is the comfortable minimum; ComfyUI offloads
the text encoder between steps. 16 GB cards work with --lowvram at a few
times the run time. Without the Lightning LoRA it takes 40 steps at CFG 4
instead of 8 steps at CFG 1.

Download the files into a ComfyUI install with either of:

    python -m autoexpress_core.instruction_edit download /path/to/ComfyUI
    python custom_nodes/AutoExpress/autoexpress_core/instruction_edit.py download /path/to/ComfyUI

(check instead of download lists what is missing).

Only the standard library (and requests for downloads) is used, so ComfyUI,
the standalone app and the backends can all import it.
"""

import json
import os
import pathlib
import re
import sys
from dataclasses import dataclass
from functools import lru_cache

if __package__:
    from . import intensity as expression_intensity
else:  # run as a script: python .../autoexpress_core/instruction_edit.py check <ComfyUI folder>
    import intensity as expression_intensity

INPAINT = "inpaint"
INSTRUCT = "instruct"

METHODS = {
    INPAINT: {
        "name": "Face inpainting",
        "description": "Inpaints the face with ADetailer (A1111, Forge, SD.Next), FaceDetailer (ComfyUI) or the WebUI's own face refiner, using the model's expression prompts and LoRAs.",
    },
    INSTRUCT: {
        "name": "Instruction edit (Qwen-Image-Edit)",
        "description": "Rewrites the expression with Qwen-Image-Edit-2509 from one sentence per expression. Stronger expressions, same character, no face detector or LoRA. ComfyUI only, about 24 GB of VRAM.",
    },
}

# Wording that keeps the input's look: illustrations stay drawn, photos stay photos (without it Qwen cartoonizes photos).
ILLUSTRATION = "illustration"
PHOTO = "photo"
STYLES = (ILLUSTRATION, PHOTO)


INSTRUCTIONS_FILE = pathlib.Path(__file__).resolve().parent / "resources" / "edit_instructions.json"

VRAM_NOTE = (
    "Qwen-Image-Edit-2509 fp8 needs about 24 GB of VRAM (20 GB model + 9 GB text encoder, "
    "offloaded by ComfyUI). 16 GB cards work with ComfyUI's --lowvram, several times slower."
)


@lru_cache(maxsize=None)
def _load() -> dict:
    with open(INSTRUCTIONS_FILE, "r", encoding="utf-8") as instructions_file:
        return json.load(instructions_file)


def instruction_names() -> list[str]:
    """Expression names that have an edit instruction, in file order."""
    return list(_load()["expressions"])


def get_instructions(only: list[str] | None = None) -> dict[str, str]:
    """Expression name -> its sentence, optionally limited to some names (kept in file order)."""
    expressions = dict(_load()["expressions"])
    if only:
        wanted = {name.strip().lower() for name in only if name and name.strip()}
        expressions = {name: text for name, text in expressions.items() if name in wanted}
    return expressions


def build_instruction(expression: str, extra: str = "", style: str = ILLUSTRATION, intensity: float | None = None) -> str:
    """
    The full edit instruction for one expression.

    Args:
        expression (str): An expression name, see instruction_names().
        extra (str): Optional text added before the "keep the same ..." sentence, e.g. "Keep the glasses on."
        style (str): ILLUSTRATION (anime, cartoon, furry art) or PHOTO (realistic photos).
        intensity (float | None): 0..1, see intensity.edit_tier; None uses the default for the style
            (low for photos, where full-strength expressions look like a cartoon).
    """
    data = _load()
    if expression not in data["expressions"]:
        raise KeyError(f"No edit instruction for '{expression}'. Valid names: {', '.join(data['expressions'])}")
    if style not in data["styles"]:
        raise KeyError(f"Unknown instruction style '{style}'. Choose from: {', '.join(data['styles'])}")
    tier = expression_intensity.edit_tier(expression_intensity.resolve(intensity, realistic=style == PHOTO), photo=style == PHOTO)
    sentence = data["subtle" if tier in ("subtle", "minimal", "trace") else "expressions"][expression]
    if style == PHOTO:
        sentence = sentence.replace("The character", "The person")
    parts = [
        data["styles"][style]["prefix"],
        sentence,
        data["intensity"][tier],
        (extra or "").strip(),
        data["styles"][style]["suffix"],
    ]
    return " ".join(part for part in parts if part)


def expression_intensity_for(expression: str, intensity: float, style: str = ILLUSTRATION) -> float:
    """The intensity for one expression: photos scale some expressions down (see photo_intensity_scale)."""
    if style != PHOTO:
        return intensity
    scale = _load().get("photo_intensity_scale", {}).get(expression, 1.0)
    return expression_intensity.resolve(round(intensity * scale, 3))


def resolve_style(style: str | None = None, is_realistic: bool = False) -> str:
    """A style id from a user choice; "auto" or None picks PHOTO for realistic images."""
    if style in STYLES:
        return style
    return PHOTO if is_realistic else ILLUSTRATION


@dataclass
class EditSettings:
    """Sampling settings for one Qwen-Image-Edit run. None means "pick from whether the Lightning LoRA is used"."""

    seed: int = -1
    steps: int | None = None
    cfg: float | None = None
    sampler: str = "euler"
    scheduler: str = "simple"
    shift: float = 3.0
    megapixels: float = 1.0
    model: str | None = None
    lightning: bool = True
    keep_size: bool = True
    # 0..1 expression intensity; below 0.75 the sampler starts from the input's latent so less changes.
    intensity: float | None = None
    denoise: float | None = None
    photo: bool = False

    def resolved_denoise(self) -> float:
        if self.denoise is not None:
            return self.denoise
        return 1.0 if self.intensity is None else expression_intensity.edit_denoise(self.intensity, self.photo)

    def resolved_steps(self, lightning: bool) -> int:
        return self.steps or (8 if lightning else 40)

    def resolved_cfg(self, lightning: bool) -> float:
        return self.cfg if self.cfg is not None else (1.0 if lightning else 4.0)

    @classmethod
    def from_settings(cls, settings: dict | None) -> "EditSettings":
        """Read the edit_* keys (and seed) out of the standalone app's settings."""
        settings = settings or {}

        def number(key, cast):
            value = settings.get(key)
            try:
                return None if value in (None, "") else cast(value)
            except (TypeError, ValueError):
                return None

        seed = number("seed", int)
        intensity = number("expression_intensity", float)
        return cls(
            intensity=None if intensity is None else expression_intensity.resolve(intensity),
            seed=-1 if seed is None else seed,
            steps=number("edit_steps", int),
            cfg=number("edit_cfg_scale", float),
            model=settings.get("edit_model") or None,
            lightning=settings.get("edit_lightning", True) is not False,
        )


# Models ---------------------------------------------------------------------
@dataclass(frozen=True)
class ModelFile:
    role: str
    folder: str
    name: str
    urls: tuple[str, ...]
    size_gb: float
    required: bool = True
    pattern: str = ""

    def matches(self, filename: str) -> bool:
        """Whether a file name a ComfyUI loader lists is (a variant of) this model."""
        stem = filename.replace("\\", "/").rsplit("/", 1)[-1].lower()
        return stem == self.name.lower() or bool(self.pattern and re.search(self.pattern, stem))


HF = "https://huggingface.co"
MODELS = (
    ModelFile(
        "diffusion_model",
        "diffusion_models",
        "qwen_image_edit_2509_fp8_e4m3fn.safetensors",
        (f"{HF}/Comfy-Org/Qwen-Image-Edit_ComfyUI/resolve/main/split_files/diffusion_models/qwen_image_edit_2509_fp8_e4m3fn.safetensors",),
        20.4,
        pattern=r"qwen.*image.*edit",
    ),
    ModelFile(
        "text_encoder",
        "text_encoders",
        "qwen_2.5_vl_7b_fp8_scaled.safetensors",
        (f"{HF}/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors",),
        9.4,
        pattern=r"qwen.?2\.?5.?vl",
    ),
    ModelFile(
        "vae",
        "vae",
        "qwen_image_vae.safetensors",
        (f"{HF}/Comfy-Org/Qwen-Image_ComfyUI/resolve/main/split_files/vae/qwen_image_vae.safetensors",),
        0.25,
        pattern=r"qwen.?image.*vae",
    ),
    ModelFile(
        "lightning_lora",
        "loras",
        "Qwen-Image-Edit-2509-Lightning-8steps-V1.0-bf16.safetensors",
        (
            f"{HF}/lightx2v/Qwen-Image-Lightning/resolve/main/Qwen-Image-Edit-2509/Qwen-Image-Edit-2509-Lightning-8steps-V1.0-bf16.safetensors",
            f"{HF}/lightx2v/Qwen-Image-Lightning/resolve/main/Qwen-Image-Lightning-8steps-V1.1.safetensors",
        ),
        0.85,
        required=False,
        pattern=r"qwen.*lightning.*8.?step",
    ),
)
MODEL_BY_ROLE = {model.role: model for model in MODELS}


def find_model(role: str, choices: list[str], wanted: str | None = None) -> str | None:
    """
    Pick the file for a model role from what a ComfyUI loader lists.

    An exact match of wanted wins; otherwise the newest looking variant (2511 over 2509 over the original).
    """
    if wanted and wanted in choices:
        return wanted
    model = MODEL_BY_ROLE[role]
    matches = [choice for choice in choices if model.matches(choice)]
    if role == "diffusion_model":
        # The first Qwen-Image-Edit only takes one reference image and is weaker at keeping identity.
        matches.sort(key=lambda name: ("2511" in name, "2509" in name, "fp8" in name.lower()), reverse=True)
    return matches[0] if matches else None


def missing_models(comfyui_dir: str | os.PathLike, include_optional: bool = True) -> list[ModelFile]:
    """The model files that are not in a ComfyUI install's models folder yet."""
    models_dir = pathlib.Path(comfyui_dir) / "models"
    missing = []
    for model in MODELS:
        if not model.required and not include_optional:
            continue
        folder = models_dir / model.folder
        # Older installs use models/unet and models/clip.
        folders = [folder] + {"diffusion_models": [models_dir / "unet"], "text_encoders": [models_dir / "clip"]}.get(model.folder, [])
        present = any(model.matches(path.name) for directory in folders if directory.is_dir() for path in directory.rglob("*.safetensors"))
        if not present:
            missing.append(model)
    return missing


def download_models(comfyui_dir: str | os.PathLike, include_optional: bool = True, token: str | None = None, log=print) -> list[pathlib.Path]:
    """
    Download the missing Qwen-Image-Edit files into a ComfyUI install.

    Args:
        comfyui_dir: The ComfyUI folder (the one with models/ in it).
        include_optional (bool): Also fetch the Lightning LoRA.
        token (str | None): Hugging Face token, defaults to HF_TOKEN. The files are public, so it is only needed behind rate limits.

    Returns:
        list[Path]: The files that were downloaded.
    """
    import requests

    token = token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    downloaded = []
    for model in missing_models(comfyui_dir, include_optional):
        target = pathlib.Path(comfyui_dir) / "models" / model.folder / model.name
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        for url in model.urls:
            log(f"Downloading {model.name} (~{model.size_gb:g} GB) from {url}")
            try:
                with requests.get(url, headers=headers, stream=True, timeout=(10, 120), allow_redirects=True) as response:
                    if response.status_code == 404:
                        log(f"Not found at {url}")
                        continue
                    response.raise_for_status()
                    total = int(response.headers.get("Content-Length") or 0)
                    done, reported = 0, 0
                    with open(partial, "wb") as file:
                        for chunk in response.iter_content(chunk_size=8 * 1024 * 1024):
                            file.write(chunk)
                            done += len(chunk)
                            if total and done - reported >= total / 10:
                                reported = done
                                log(f"  {model.name}: {done * 100 // total}%")
            except requests.RequestException as e:
                log(f"Download of {model.name} failed: {e}")
                partial.unlink(missing_ok=True)
                continue
            # The URL's file name can differ (fallback URLs); keep it so the file name says what it is.
            target = target.with_name(url.rsplit("/", 1)[-1])
            partial.replace(target)
            downloaded.append(target)
            log(f"Saved {target}")
            break
        else:
            if model.required:
                raise RuntimeError(f"Could not download {model.name}; get it from {model.urls[0]} into models/{model.folder}.")
            log(f"Skipped the optional {model.name}.")
    return downloaded


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m autoexpress_core.instruction_edit", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("download", "Download the missing model files"), ("check", "List the missing model files")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("comfyui_dir", help="The ComfyUI folder (the one with models/ in it)")
        command.add_argument("--no-lightning", action="store_true", help="Skip the optional Lightning 8-step LoRA")
    args = parser.parse_args(argv)

    if not (pathlib.Path(args.comfyui_dir) / "models").is_dir():
        print(f"{args.comfyui_dir} has no models folder; pass the ComfyUI folder.", file=sys.stderr)
        return 2
    if args.command == "check":
        missing = missing_models(args.comfyui_dir, not args.no_lightning)
        for model in missing:
            print(f"missing: models/{model.folder}/{model.name} (~{model.size_gb:g} GB){'' if model.required else ' (optional)'}")
        print(VRAM_NOTE)
        return 1 if any(model.required for model in missing) else 0
    download_models(args.comfyui_dir, not args.no_lightning)
    print(VRAM_NOTE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
