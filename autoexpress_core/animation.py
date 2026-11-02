"""
Animated expression sprites: each expression's still becomes a short looping clip.

The stills come from the usual pipeline (face inpainting or Qwen-Image-Edit, with poses
if asked for). Each one is then animated with Wan 2.2 image to video (14B, open weights,
no content filter) on ComfyUI, using the still as both the first and the last frame, so
every clip loops without a jump. neutral gets the character's idle motion, which comes
from the character card (persona keywords), optionally rewritten by an LLM that knows the
character, and optionally helped by a wiki lookup of the character.

With background removal on, the still is cut out first and put on a flat key color, so
Wan animates the character on a plain background; every frame is then cut out again and
the alpha is smoothed over time so the edges don't flicker. Clips are saved as animated
WebP (transparent, small, shown by SillyTavern and browsers), and optionally APNG or GIF.

Only Pillow is needed here; rembg (background removal) and requests (LLM / wiki lookup)
are imported when used.
"""

import dataclasses
import json
import os
import pathlib
import re
import sys
from functools import lru_cache

from PIL import Image, ImageChops, ImageMath

from .instruction_edit import HF, PHOTO, ModelFile

RESOURCE = pathlib.Path(__file__).resolve().parent / "resources" / "animations.json"

# check_ready() method name for the animation step.
ANIMATE = "animate"
IDLE = "neutral"
FORMATS = ("webp", "apng", "gif")
DEFAULT_FORMATS = ("webp",)
EXTENSIONS = {"webp": ".webp", "apng": ".apng", "gif": ".gif"}
# Wan 2.2 14B makes 16 fps video; lengths are 4n+1 frames.
WAN_FPS = 16
DEFAULT_FRAMES = 49
KEY_COLOR = (0, 255, 0)

LLM_URL_ENV = "AUTOEXPRESS_LLM_URL"
LLM_KEY_ENV = "AUTOEXPRESS_LLM_API_KEY"
LLM_MODEL_ENV = "AUTOEXPRESS_LLM_MODEL"

VRAM_NOTE = (
    "Animated sprites use Wan 2.2 image to video 14B (fp8, about 36 GB of files). "
    "They need a GPU with 24 GB of VRAM or more (48 GB or more is comfortable); "
    "a rented GPU (RunPod etc.) works the same as a local one."
)

WAN = "Comfy-Org/Wan_2.2_ComfyUI_Repackaged/resolve/main/split_files"
WAN21 = "Comfy-Org/Wan_2.1_ComfyUI_repackaged/resolve/main/split_files"
MODELS = (
    ModelFile(
        "high_noise",
        "diffusion_models",
        "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",
        (f"{HF}/{WAN}/diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors",),
        14.3,
        pattern=r"wan2\.?2.*i2v.*high.?noise",
    ),
    ModelFile(
        "low_noise",
        "diffusion_models",
        "wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",
        (f"{HF}/{WAN}/diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors",),
        14.3,
        pattern=r"wan2\.?2.*i2v.*low.?noise",
    ),
    ModelFile(
        "text_encoder",
        "text_encoders",
        "umt5_xxl_fp8_e4m3fn_scaled.safetensors",
        (f"{HF}/{WAN21}/text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors",),
        6.7,
        pattern=r"umt5.?xxl",
    ),
    ModelFile(
        "vae",
        "vae",
        "wan_2.1_vae.safetensors",
        (f"{HF}/{WAN21}/vae/wan_2.1_vae.safetensors",),
        0.25,
        pattern=r"wan.?2\.?1.?vae",
    ),
    ModelFile(
        "lightning_high",
        "loras",
        "wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",
        (f"{HF}/{WAN}/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors",),
        1.2,
        required=False,
        pattern=r"i2v.*(lightx2v|lightning).*high.?noise",
    ),
    ModelFile(
        "lightning_low",
        "loras",
        "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",
        (f"{HF}/{WAN}/loras/wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors",),
        1.2,
        required=False,
        pattern=r"i2v.*(lightx2v|lightning).*low.?noise",
    ),
)
MODEL_BY_ROLE = {model.role: model for model in MODELS}


def find_model(role: str, choices: list[str]) -> str | None:
    """The file a ComfyUI loader lists for a Wan model role, preferring fp8 over larger variants."""
    model = MODEL_BY_ROLE[role]
    matches = [choice for choice in choices if model.matches(choice)]
    matches.sort(key=lambda name: ("fp8" in name.lower(), "14b" in name.lower()), reverse=True)
    return matches[0] if matches else None


@lru_cache(maxsize=1)
def _load() -> dict:
    with open(RESOURCE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def motions() -> dict[str, str]:
    return dict(_load()["motions"])


def negative_prompt() -> str:
    return _load()["negative"]


# Settings -------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class AnimationSettings:
    frames: int = DEFAULT_FRAMES
    fps: int = WAN_FPS
    # The short side of the video; the long side follows the image's aspect ratio. 480 or 720.
    resolution: int = 480
    steps: int | None = None
    cfg: float | None = None
    shift: float = 5.0
    seed: int = -1
    lightning: bool | None = None
    loop: bool = True
    formats: tuple[str, ...] = DEFAULT_FORMATS
    extra: str = ""
    idle_motion: str = ""

    def resolved_steps(self, lightning: bool) -> int:
        return self.steps or (4 if lightning else 20)

    def resolved_cfg(self, lightning: bool) -> float:
        return self.cfg if self.cfg is not None else (1.0 if lightning else 3.5)

    @property
    def frame_count(self) -> int:
        """Wan wants 4n+1 frames."""
        frames = max(17, min(int(self.frames), 121))
        return frames - (frames - 1) % 4

    @classmethod
    def from_settings(cls, settings: dict | None) -> "AnimationSettings":
        settings = settings or {}
        formats = tuple(f for f in (settings.get("formats") or DEFAULT_FORMATS) if f in FORMATS) or DEFAULT_FORMATS
        lightning = settings.get("lightning")
        return cls(
            frames=int(settings.get("frames") or DEFAULT_FRAMES),
            fps=int(settings.get("fps") or WAN_FPS),
            resolution=int(settings.get("resolution") or 480),
            steps=int(settings["steps"]) if settings.get("steps") else None,
            cfg=float(settings["cfg"]) if settings.get("cfg") not in (None, "") else None,
            shift=float(settings.get("shift") or 5.0),
            seed=int(settings.get("seed", -1) if settings.get("seed") not in (None, "") else -1),
            lightning=None if lightning in (None, "", "auto") else bool(lightning),
            loop=settings.get("loop", True) is not False,
            formats=formats,
            extra=str(settings.get("extra") or "").strip(),
            idle_motion=str(settings.get("idle_motion") or "").strip(),
        )


def video_size(width: int, height: int, resolution: int = 480) -> tuple[int, int]:
    """The video size for an image: short side at resolution, aspect kept, both multiples of 16."""
    scale = resolution / min(width, height)
    long_cap = resolution * 2  # very tall or wide images would be too big for the model
    new_w, new_h = width * scale, height * scale
    if max(new_w, new_h) > long_cap:
        shrink = long_cap / max(new_w, new_h)
        new_w, new_h = new_w * shrink, new_h * shrink
    return max(16, round(new_w / 16) * 16), max(16, round(new_h / 16) * 16)


# Prompts --------------------------------------------------------------------
def build_motion_prompt(expression: str, idle_motion: str = "", style: str = "illustration", extra: str = "") -> str:
    """The Wan prompt for one expression's clip. neutral uses the character's idle motion when there is one."""
    data = _load()
    expression = expression.strip().lower()
    if expression == IDLE and idle_motion:
        motion = idle_motion
    else:
        motion = data["motions"].get(expression) or f"The character shows {expression} with small natural movements."
    suffix = data["photo_suffix"] if style == PHOTO else data["suffix"]
    parts = [data["prefix"], motion, extra.strip(), suffix]
    return " ".join(part for part in parts if part)


def persona_traits(text: str, limit: int = 1) -> list[str]:
    """The idle motions whose keywords show up most in a persona text, best first."""
    text = (text or "").lower()
    scored = []
    for index, trait in enumerate(_load()["idle_traits"]):
        hits = sum(len(re.findall(r"\b" + re.escape(word), text)) for word in trait["keywords"])
        if hits:
            scored.append((-hits, index, trait["motion"]))
    return [motion for _, _, motion in sorted(scored)[:limit]]


def idle_motion(persona: str = "", name: str = "") -> str:
    """
    An idle motion sentence from a persona text (character card description etc.).

    Always breathing and blinking, plus the gesture that fits the persona's strongest traits.
    """
    subject = name.strip() or "The character"
    gestures = persona_traits(persona)
    base = _load()["idle_base"]
    if not gestures:
        return f"{subject} idles in place: {base}."
    return f"{subject} idles in place, {' and '.join(gestures)}; {base}."


LLM_SYSTEM = (
    "You write motion prompts for an image-to-video model that animates a character sprite. "
    "Reply with ONE or two sentences (under 60 words) describing a short, looping idle animation "
    "that fits the character's personality: small in-place movements such as breathing, blinking, "
    "a typical gesture or mannerism. The character stays in place, the camera does not move, the "
    "outfit does not change. No dialogue, no scene changes, no lists."
)


def describe_idle_with_llm(persona: str, url: str | None = None, api_key: str | None = None, model: str | None = None, timeout: float = 60) -> str | None:
    """
    Ask an OpenAI compatible chat endpoint (OpenAI, OpenRouter, a local Ollama or LM Studio, ...) for the idle motion.

    The model can use what it knows about well known characters, so a short card still gets a fitting idle.
    url, api_key and model default to AUTOEXPRESS_LLM_URL, AUTOEXPRESS_LLM_API_KEY and AUTOEXPRESS_LLM_MODEL.
    Returns None when no endpoint is set or the call fails.
    """
    import requests

    url = (url or os.environ.get(LLM_URL_ENV, "")).strip().rstrip("/")
    if not url:
        return None
    if not url.endswith("/chat/completions"):
        url += "/chat/completions" if url.endswith("/v1") else "/v1/chat/completions"
    headers = {"Content-Type": "application/json"}
    api_key = api_key or os.environ.get(LLM_KEY_ENV, "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    body = {
        "model": model or os.environ.get(LLM_MODEL_ENV, "") or "gpt-4o-mini",
        "messages": [{"role": "system", "content": LLM_SYSTEM}, {"role": "user", "content": persona[:6000]}],
        "temperature": 0.7,
        "max_tokens": 160,
    }
    try:
        response = requests.post(url, json=body, headers=headers, timeout=timeout)
        response.raise_for_status()
        text = response.json()["choices"][0]["message"]["content"]
    except (requests.RequestException, KeyError, IndexError, ValueError, TypeError):
        return None
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    text = " ".join(text.replace("*", "").split()).strip().strip('"')
    return text[:500] or None


WIKIPEDIA_API = "https://en.wikipedia.org/w/api.php"
USER_AGENT = "AutoExpress (https://github.com/deepratna-awale/AutoExpress)"


def _wiki_intro(api: str, query: str, timeout: float) -> str | None:
    import requests

    headers = {"User-Agent": USER_AGENT}
    found = requests.get(
        api, params={"action": "query", "list": "search", "srsearch": query, "srlimit": 1, "format": "json"}, headers=headers, timeout=timeout
    )
    found.raise_for_status()
    hits = found.json().get("query", {}).get("search", [])
    if not hits:
        return None
    page = requests.get(
        api, params={"action": "parse", "page": hits[0]["title"], "prop": "text", "section": 0, "format": "json", "redirects": 1}, headers=headers, timeout=timeout
    )
    page.raise_for_status()
    html = page.json().get("parse", {}).get("text", {}).get("*", "")
    html = re.sub(r"<(script|style|table|aside)\b.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>|\[\d+\]", " ", html)
    text = " ".join(text.replace("&#160;", " ").replace("&amp;", "&").split())
    return f"{hits[0]['title']}: {text[:3000]}" if text else None


def look_up_character(name: str, tags: list[str] | None = None, timeout: float = 15) -> str | None:
    """
    Background on a known character from the web: the matching Fandom wiki (guessed from the card's tags), else Wikipedia.

    Returns the article's intro as text, or None.
    """
    import requests

    if not name.strip():
        return None
    for tag in tags or []:
        wiki = re.sub(r"[^a-z0-9]", "", tag.lower())
        if len(wiki) < 3 or wiki in {"female", "male", "anime", "nsfw", "sfw", "oc", "original", "fantasy", "romance", "girl", "boy", "woman", "man"}:
            continue
        try:
            text = _wiki_intro(f"https://{wiki}.fandom.com/api.php", name, timeout)
        except (requests.RequestException, ValueError):
            continue
        if text and name.split()[0].lower() in text.lower():
            return text
    try:
        query = " ".join([name, *(tags or [])[:2]])
        text = _wiki_intro(WIKIPEDIA_API, query, timeout)
    except (requests.RequestException, ValueError):
        return None
    return text if text and name.split()[0].lower() in text.lower() else None


def resolve_idle_motion(card=None, persona: str = "", source: str = "card", llm: dict | None = None) -> tuple[str, str]:
    """
    The idle motion for a character and where it came from ("card", "web", "llm" or "default").

    source "card" reads the card's persona; "web" adds a wiki lookup of the character; "llm" asks the configured
    LLM (with the lookup when it works) and falls back to the card's keywords.
    """
    name = getattr(card, "name", "") or ""
    text = persona or (card.persona() if card is not None else "")
    origin = "card" if text else "default"
    if source in ("web", "llm") and name:
        found = look_up_character(name, getattr(card, "tags", None))
        if found:
            text = f"{text}\nFrom the web: {found}" if text else found
            origin = "web"
    if source == "llm" and text:
        described = describe_idle_with_llm(text, **(llm or {}))
        if described:
            return described, "llm"
    return idle_motion(text, name), origin


# Frames ---------------------------------------------------------------------
def loop_frames(frames: list[Image.Image]) -> list[Image.Image]:
    """Drop the last frame of a first-equals-last clip, so the loop doesn't show the same frame twice."""
    return frames[:-1] if len(frames) > 2 else frames


def _opaque_colors(image: Image.Image) -> list[tuple[int, int, int]]:
    small = image.convert("RGBA").resize((64, 64))
    data = small.get_flattened_data() if hasattr(small, "get_flattened_data") else small.getdata()  # Pillow < 12.1
    return [p[:3] for p in data if p[3] > 128] or [(128, 128, 128)]


def key_distance(image: Image.Image, color: tuple[int, int, int]) -> float:
    """How far (RGB distance) the character's closest color is from a key color."""
    return min(sum((a - b) ** 2 for a, b in zip(color, p)) for p in _opaque_colors(image)) ** 0.5


def pick_key_color(image: Image.Image) -> tuple[int, int, int]:
    """A flat background color far from the character's own colors: green, unless the character has green in it."""
    best, best_distance = KEY_COLOR, -1.0
    for candidate in (KEY_COLOR, (255, 0, 255), (0, 128, 255), (255, 255, 255), (128, 128, 128)):
        distance = key_distance(image, candidate)
        if distance >= 120:
            return candidate
        if distance > best_distance:
            best, best_distance = candidate, distance
    return best


def on_flat_background(cut_out: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    """An RGBA cut-out composited on a flat color, as RGB."""
    background = Image.new("RGB", cut_out.size, color)
    background.paste(cut_out, mask=cut_out.convert("RGBA").getchannel("A"))
    return background


def remove_background_frames(frames: list[Image.Image], model: str, smooth: int = 1) -> list[Image.Image]:
    """
    Cut every frame out with rembg and average each alpha mask with its neighbours (wrapping, since the clip loops).

    Raises:
        ImportError: rembg isn't installed.
    """
    from . import background

    masks = [background.remove_background(frame, model).getchannel("A") for frame in frames]
    if smooth and len(masks) > 2:
        smoothed = []
        for index in range(len(masks)):
            window = [masks[(index + offset) % len(masks)] for offset in range(-smooth, smooth + 1)]
            blended = window[0]
            for count, mask in enumerate(window[1:], start=2):
                blended = Image.blend(blended, mask, 1 / count)
            # Keep edges crisp: a light threshold curve after averaging.
            smoothed.append(blended.point(lambda v: 0 if v < 24 else (255 if v > 232 else v)))
        masks = smoothed
    result = []
    for frame, mask in zip(frames, masks):
        rgba = frame.convert("RGBA")
        rgba.putalpha(mask)
        result.append(rgba)
    return result


def _math(expression: str, func, **images):
    """ImageMath with lambda_eval on Pillow 11+ and the older string eval before it."""
    if hasattr(ImageMath, "lambda_eval"):
        return ImageMath.lambda_eval(lambda e: func(*(e[name] for name in images)), **images)
    return ImageMath.eval(expression, **images)  # Pillow < 11


def key_out(frame: Image.Image, color: tuple[int, int, int], inner: int = 60, outer: int = 110) -> Image.Image:
    """
    Make pixels close to the key color transparent, on top of the cut-out's own alpha.

    rembg sometimes keeps patches of the flat background (between the arms, beside the hair); since the
    key color was picked far from the character's colors, anything this close to it is background.
    Pixels within inner of the key go fully transparent, beyond outer they keep their alpha.
    """
    rgba = frame.convert("RGBA")
    r, g, b, a = (band.convert("F") for band in rgba.split())
    kr, kg, kb = (float(c) for c in color)
    low, high = float(inner * inner), float(outer * outer)
    distance = _math(
        f"(r - {kr}) * (r - {kr}) + (g - {kg}) * (g - {kg}) + (b - {kb}) * (b - {kb})",
        lambda r, g, b: (r - kr) * (r - kr) + (g - kg) * (g - kg) + (b - kb) * (b - kb),
        r=r, g=g, b=b,
    )
    scale = 255.0 / (high - low)
    keyed = distance.point(lambda v: v * scale - low * scale)  # a linear map, so Pillow applies it as scale and offset
    alpha = ImageChops.darker(a.convert("L"), keyed.convert("L"))  # convert("L") clamps to 0..255
    rgba.putalpha(alpha)
    return rgba


def despill(frame: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    """
    Take the key color back out of semi-transparent edge pixels, so cut-outs don't keep a colored fringe.

    An edge pixel is the character's color mixed with the key by its alpha, so the key's share is subtracted
    and the rest scaled back up: c = (pixel - (1 - a) * key) / a.
    """
    rgba = frame.convert("RGBA")
    alpha = rgba.getchannel("A")
    edge = alpha.point(lambda v: 255 if 0 < v < 250 else 0)
    if not edge.getbbox():
        return rgba
    share = alpha.point(lambda v: max(v, 1)).convert("F")
    bands = []
    for band, key in zip(rgba.split()[:3], color):
        value = _math(f"(c * 255.0 - (255.0 - a) * {float(key)}) / a", lambda c, a: (c * 255.0 - (255.0 - a) * key) / a, c=band.convert("F"), a=share)
        bands.append(value.convert("L"))  # clamps to 0..255
    fixed = Image.merge("RGBA", (*bands, alpha))
    return Image.composite(fixed, rgba, edge)


def has_transparency(image: Image.Image) -> bool:
    if image.mode not in ("RGBA", "LA", "PA") and "transparency" not in image.info:
        return False
    low, _ = image.convert("RGBA").getchannel("A").getextrema()
    return low < 250


def animate_sprite(backend, still: Image.Image, expression: str, settings: AnimationSettings, style: str = "illustration", background_model: str | None = None) -> list[Image.Image]:
    """
    Animate one expression's still into looping frames with backend.animate (Wan 2.2 on ComfyUI).

    A transparent still (background already removed) is animated on a flat key color and every frame is cut out
    again with background_model (the illustration model when None), so the clip stays transparent.

    Raises:
        RuntimeError: the backend failed (the reason is in backend.last_error).
    """
    from .images import pil_to_b64

    transparent = has_transparency(still)
    source = still.convert("RGB")
    key = None
    if transparent:
        key = pick_key_color(still)
        source = on_flat_background(still.convert("RGBA"), key)
    prompt = build_motion_prompt(expression, settings.idle_motion, style, settings.extra)
    if transparent:
        prompt += " Plain flat single-color background."
    frames = backend.animate(pil_to_b64(source), prompt, negative_prompt(), settings)
    if not frames:
        error = getattr(backend, "last_error", None)
        raise RuntimeError(str(error) if error else f"Animating {expression} failed.")
    parameters = frames[0].info.get("parameters", "")
    if settings.loop:
        frames = loop_frames(frames)
    # Back to the still's size, so the animation lines up with the PNG sprite.
    frames = [frame.convert("RGB").resize(still.size, Image.LANCZOS) if frame.size != still.size else frame.convert("RGB") for frame in frames]
    if transparent:
        from .background import ILLUSTRATION_MODEL

        frames = remove_background_frames(frames, background_model or ILLUSTRATION_MODEL)
        # Keying out the flat color is only safe when the character has nothing close to it.
        if key_distance(still, key) >= 120:
            frames = [key_out(frame, key) for frame in frames]
        frames = [despill(frame, key) for frame in frames]
    if frames and parameters:
        frames[0].info["parameters"] = parameters
    return frames


# Saving ---------------------------------------------------------------------
def _gif_frame(frame: Image.Image) -> Image.Image:
    rgba = frame.convert("RGBA")
    alpha = rgba.getchannel("A")
    paletted = rgba.convert("RGB").quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    mask = alpha.point(lambda v: 255 if v < 128 else 0)
    paletted.paste(255, mask=mask)
    paletted.info["transparency"] = 255
    return paletted


def save_animation(frames: list[Image.Image], path_stem: str | os.PathLike, fps: int = WAN_FPS, formats=DEFAULT_FORMATS, comment: str = "") -> list[pathlib.Path]:
    """
    Save frames as looping animations, one file per format (webp, apng, gif). Returns the paths written.

    Transparent frames stay transparent in WebP and APNG; GIF only has on/off transparency.
    """
    path_stem = pathlib.Path(path_stem)
    path_stem.parent.mkdir(parents=True, exist_ok=True)
    duration = max(20, round(1000 / max(1, fps)))
    written = []
    for fmt in formats:
        target = path_stem.with_suffix(EXTENSIONS[fmt])
        if fmt == "webp":
            first, *rest = [f.convert("RGBA") for f in frames]
            first.save(target, format="WEBP", save_all=True, append_images=rest, duration=duration, loop=0, quality=88, method=4)
        elif fmt == "apng":
            first, *rest = [f.convert("RGBA") for f in frames]
            first.save(target, format="PNG", save_all=True, append_images=rest, duration=duration, loop=0, disposal=1, blend=0)
        elif fmt == "gif":
            first, *rest = [_gif_frame(f) for f in frames]
            first.save(target, format="GIF", save_all=True, append_images=rest, duration=duration, loop=0, disposal=2, optimize=False, comment=comment[:250])
        written.append(target)
    return written


# Models ---------------------------------------------------------------------
def missing_models(comfyui_dir, include_optional: bool = True):
    from .instruction_edit import missing_models as missing

    return missing(comfyui_dir, include_optional, MODELS)


def download_models(comfyui_dir, include_optional: bool = True, token: str | None = None, log=print):
    from .instruction_edit import download_models as download

    return download(comfyui_dir, include_optional, token, log, MODELS)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m autoexpress_core.animation", description="Wan 2.2 image to video models for animated sprites.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("download", "Download the missing model files"), ("check", "List the missing model files")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("comfyui_dir", help="The ComfyUI folder (the one with models/ in it)")
        command.add_argument("--no-lightning", action="store_true", help="Skip the optional 4-step LoRAs (then 20 steps are used)")
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
