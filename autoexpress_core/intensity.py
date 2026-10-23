"""
Expression intensity: one 0..1 slider for how far an expression is pushed.

0.5 is the strength AutoExpress always used. Lower values tone the expression
down, which real faces need: a full anime-strength expression on a photo looks
uncanny. Each mode maps the slider onto its own knobs:

- Face inpainting (ADetailer / FaceDetailer): the expression prompt's emphasis
  weight, the expression LoRA strength and the denoising strength.
- Instruction edit (Qwen-Image-Edit): the wording (subtle, normal or strong
  sentences) and the sampler's denoise, so low values keep more of the input.

The curves are plain functions so they can be tuned from test renders.

RunPod photo tests: face inpainting barely moves a real face at any setting
(ADetailer's 0.4 denoise is too low to change a photo, and more breaks the
likeness), so realistic families default to the instruction edit at 0.2.
"""

import re

DEFAULT = 0.5
# Real faces read as uncanny well before drawn ones do.
PHOTO_DEFAULT = 0.25


def resolve(value=None, realistic: bool = False) -> float:
    """The slider value to use: the given one (clamped to 0..1), else the default for drawn or realistic images."""
    try:
        if value is not None and value != "" and value != "auto":
            return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        pass
    return PHOTO_DEFAULT if realistic else DEFAULT


def _lerp(intensity: float, at_zero: float, at_half: float, at_one: float) -> float:
    """Piecewise linear: at_zero at 0, at_half at 0.5 (the classic strength), at_one at 1."""
    if intensity <= 0.5:
        return at_zero + (at_half - at_zero) * intensity / 0.5
    return at_half + (at_one - at_half) * (intensity - 0.5) / 0.5


# Face inpainting ---------------------------------------------------------------
def prompt_weight(intensity: float) -> float:
    """Emphasis weight for the expression tags: 0.6 at 0, 1.0 at 0.5, 1.4 at 1."""
    return round(_lerp(intensity, 0.6, 1.0, 1.4), 2)


def lora_scale(intensity: float) -> float:
    """Multiplier for the expression LoRA weights: off at 0, as listed at 0.5, 1.5x at 1."""
    return round(_lerp(intensity, 0.0, 1.0, 1.5), 2)


def denoise_scale(intensity: float) -> float:
    """Multiplier for the inpainting denoising strength: 0.7x at 0, unchanged at 0.5, 1.3x at 1."""
    return round(_lerp(intensity, 0.7, 1.0, 1.3), 3)


def weight_expression(expression_prompt: str, intensity: float, natural_language: bool = False) -> str:
    """
    Apply the intensity to an expression prompt.

    Tag prompts get A1111 / ComfyUI emphasis, "(tags:0.8)". Sentence prompts for
    T5-style encoders ignore emphasis, so they get a plain-language hint instead.
    """
    expression_prompt = (expression_prompt or "").strip()
    if not expression_prompt:
        return expression_prompt
    if natural_language:
        if intensity < 0.35:
            return f"{expression_prompt} The expression is slight and subtle."
        if intensity > 0.75:
            return f"{expression_prompt} The expression is intense and exaggerated."
        return expression_prompt
    weight = prompt_weight(intensity)
    if weight == 1.0:
        return expression_prompt
    # Nested weights multiply, so the family's own "(angry expression:1.4)" would undo a lower intensity.
    return f"({strip_weights(expression_prompt)}:{weight:g})"


INNER_WEIGHT = re.compile(r"(?<!\\)\(([^()]*?)(?::\s*[-\d.]+)?\s*(?<!\\)\)")


def strip_weights(prompt: str) -> str:
    """'(angry expression:1.4), (furrowed brows), frown' -> 'angry expression, furrowed brows, frown'. Escaped \\( \\) stay."""
    previous = None
    while previous != prompt:
        previous, prompt = prompt, INNER_WEIGHT.sub(r"\1", prompt)
    return prompt


LORA_TAG = re.compile(r"<lora:([^:>]+):([-\d.]+)>", re.IGNORECASE)


def scale_lora_tags(prompt: str, intensity: float) -> str:
    """Scale the weights of <lora:name:weight> tags, dropping tags that end up at 0."""
    scale = lora_scale(intensity)

    def replace(match):
        weight = round(float(match.group(2)) * scale, 2)
        return "" if weight == 0 else f"<lora:{match.group(1)}:{weight:g}>"

    return re.sub(r"\s*,\s*,", ",", LORA_TAG.sub(replace, prompt or "")).strip().strip(",").strip()


# Instruction edit --------------------------------------------------------------
def edit_tier(intensity: float) -> str:
    """Which wording the instruction edit uses: subtle below 0.4, strong from 0.8, normal between."""
    if intensity < 0.4:
        return "subtle"
    if intensity >= 0.8:
        return "strong"
    return "normal"


def edit_denoise(intensity: float) -> float:
    """
    Sampler denoise for Qwen-Image-Edit: 0.55 at 0 up to 1.0 from 0.75.

    Below 1 the edit starts from the input's latent, so it keeps more of the face.
    """
    return round(min(1.0, 0.55 + 0.6 * intensity), 2)
