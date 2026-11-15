import dataclasses
import pathlib
import threading
from typing import Iterator, Protocol

from PIL import Image, PngImagePlugin

from . import expression_sets, instruction_edit, overrides
from . import intensity as expression_intensity
from .expressions import DEFAULT_FLAVOR, resolve_flavor
from .images import pil_to_b64
from .log import log
from .payload import build_expression_payload, find_nested_key, load_payload


def save_png(image: Image.Image, path: pathlib.Path) -> None:
    """Save as PNG, keeping the generation parameters (infotext) when the backend set them."""
    pnginfo = None
    if image.info.get("parameters"):
        pnginfo = PngImagePlugin.PngInfo()
        pnginfo.add_text("parameters", str(image.info["parameters"]))
    image.save(path, pnginfo=pnginfo)


class Backend(Protocol):
    """Something that can run an A1111 style img2img request body."""

    def img2img(self, payload: dict) -> Image.Image | None:
        """Run the request and return the first resulting image, or None on failure."""
        ...

    def interrupt(self) -> None:
        ...


class ExpressionGenerator:
    """Runs one ADetailer pass (or, in the instruction edit mode, one image edit) per expression against a Backend."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend
        self.family = None
        self._stop = threading.Event()

    def stop(self) -> None:
        """Stop after the current expression and interrupt the running one."""
        self._stop.set()
        self.backend.interrupt()

    @property
    def stopped(self) -> bool:
        return self._stop.is_set()

    def iter_generate(
        self,
        image: Image.Image | str,
        settings: dict | None = None,
        flavor: str = DEFAULT_FLAVOR,
        only: list[str] | None = None,
        output_dir: str | pathlib.Path | None = None,
        lora_prompt: str = "",
        is_realistic: bool = False,
        method: str = instruction_edit.INPAINT,
    ) -> Iterator[tuple[str, Image.Image]]:
        """
        Generate expressions one by one.

        Args:
            image (Image.Image | str): Input image, or its base64 string.
            settings (dict | None): Payload overrides (ad_prompt, ad_steps, seed, ...), plus
                expression_intensity (0..1, defaults to the family's calibrated value).
            flavor (str): "auto" or a model family id, see expressions.FLAVORS. "auto"
                picks the family from settings["ad_checkpoint"].
            only (list[str] | None): Subset of expression names to generate.
            output_dir (str | Path | None): When set, each image is saved as <expression>.png.
            lora_prompt (str): Expression LoRA tags appended to the base prompt.
            is_realistic (bool): Tie-breaker for "auto" when the checkpoint name says nothing.
            method (str): instruction_edit.INPAINT (face inpainting with the family's prompts) or
                instruction_edit.INSTRUCT (Qwen-Image-Edit with one sentence per expression; flavor,
                lora_prompt and the ad_* settings are not used, edit_* settings and seed are; the
                wording is edit_style, else photo for realistic images, else the family's default).
                Either method also changes the body pose when settings["pose"] is on: a small sprite
                gesture per expression (instruction_edit.get_poses(), or settings["poses"] as
                {expression: sentence}) made by Qwen-Image-Edit from the current pose, keeping the
                outfit. Face inpainting then adds the expression on top of the posed image, so poses
                need a backend with the instruction edit mode (ComfyUI) either way.
                settings["expression_overrides"] ({expression: {"prompt", "settings"}}, see overrides)
                gives single expressions their own prompt and settings.

        Yields:
            tuple[str, Image.Image]: Expression name and the generated image.
        """
        self._stop.clear()
        b64_image = image if isinstance(image, str) else pil_to_b64(image)
        settings = dict(settings or {})

        family = resolve_flavor(flavor, settings.get("ad_checkpoint"), is_realistic)
        defaults = expression_sets.family_defaults(family)
        poses = self._poses(settings)
        custom = overrides.normalize(settings.pop("expression_overrides", None))

        if method == instruction_edit.INSTRUCT:
            yield from self._iter_instruction_edits(b64_image, settings, only, output_dir, is_realistic, defaults, poses, custom)
            return
        if poses is not None:
            self._require_edit_mode("Poses need")

        self.family = family
        default_intensity = defaults["intensity"]
        base_denoise = settings.get("ad_denoising_strength")
        if base_denoise is None:
            base_denoise = find_nested_key(load_payload(), "ad_denoising_strength")
        expressions = expression_sets.load_family(family)["expressions"]
        if only:
            wanted = {name.strip().lower() for name in only if name and name.strip()}
            expressions = {name: tags for name, tags in expressions.items() if name in wanted}

        log.info(
            f"Using {family} expression prompts at intensity "
            f"{expression_intensity.resolve(settings.get('expression_intensity', default_intensity)):g}."
        )
        output_dir = self._prepare_output(output_dir)

        for expression_name in expressions:
            if self._stop.is_set():
                log.info("Interrupted by user. Stopping..")
                return

            override = custom.get(expression_name)
            local = overrides.apply(settings, override)
            if override:
                log.info(f"Using the saved prompt and settings for {expression_name}: {override}")
            intensity = expression_intensity.resolve(local.pop("expression_intensity", default_intensity))
            denoise = local.get("ad_denoising_strength") if override and "ad_denoising_strength" in override.get("settings", {}) else base_denoise
            if denoise is not None:
                local["ad_denoising_strength"] = round(min(1.0, float(denoise) * expression_intensity.denoise_scale(intensity)), 3)
            base_prompt = expression_sets.join_prompt(local.get("ad_prompt", ""), expression_intensity.scale_lora_tags(lora_prompt, intensity))
            local["ad_negative_prompt"] = expression_sets.build_negative(local.get("ad_negative_prompt", ""), family)

            source = b64_image
            if poses is not None and poses.get(expression_name):
                log.info(f"Posing the character for {expression_name}.")
                posed = self.backend.instruction_edit(
                    b64_image,
                    instruction_edit.build_pose_instruction(expression_name, poses[expression_name], style=self._pose_style(local, is_realistic, defaults)),
                    dataclasses.replace(instruction_edit.EditSettings.from_settings(local), pose=True),
                )
                if posed is None:
                    log.error(f"Pose edit failed for {expression_name}, stopping.")
                    return
                source = pil_to_b64(posed)

            log.info(f"Generating image for {expression_name} expression.")
            local["ad_prompt"] = expression_sets.build_prompt(
                base_prompt, expression_name, family, intensity=intensity, expression_prompt=(override or {}).get("prompt")
            )
            payload = build_expression_payload(source, local)
            result = self.backend.img2img(payload)

            if result is None:
                log.error(f"Generation failed for {expression_name}, stopping.")
                return

            if output_dir is not None:
                save_png(result, output_dir / f"{expression_name}.png")

            yield expression_name, result

        log.info(f"Generated {len(expressions)} expressions.")

    @staticmethod
    def _poses(settings: dict) -> dict[str, str] | None:
        """Expression -> pose sentence when settings["pose"] is on (settings["poses"] overrides single ones), else None."""
        pose = settings.pop("pose", False)
        custom = settings.pop("poses", None) or {}
        if pose in (None, False, "", 0, "off", "false", "False"):
            return None
        poses = instruction_edit.get_poses()
        poses.update({str(name).strip().lower(): str(text).strip() for name, text in custom.items() if name})
        return poses

    def _require_edit_mode(self, feature: str = "The instruction edit mode needs") -> None:
        if instruction_edit.INSTRUCT not in getattr(self.backend, "edit_methods", ()):
            raise ValueError(f"{feature} Qwen-Image-Edit, which {type(self.backend).__name__} doesn't have; use the ComfyUI backend.")

    @staticmethod
    def _pose_style(settings: dict, is_realistic: bool, defaults: dict) -> str:
        style = settings.get("edit_style")
        if style in instruction_edit.STYLES:
            return style
        return instruction_edit.PHOTO if is_realistic else defaults["edit_style"]

    def _iter_instruction_edits(
        self, b64_image: str, settings: dict, only, output_dir, is_realistic=False, defaults=None, poses=None, custom=None
    ) -> Iterator[tuple[str, Image.Image]]:
        self._require_edit_mode()
        self.family = instruction_edit.INSTRUCT
        instructions = instruction_edit.get_instructions(only)
        defaults = defaults or expression_sets.FALLBACK_DEFAULTS
        custom = custom or {}
        style = self._pose_style(settings, is_realistic, defaults)
        default_intensity = instruction_default_intensity(style, defaults)
        intensity = expression_intensity.resolve(settings.get("expression_intensity", default_intensity))
        extra = settings.get("edit_instruction", "")
        # Animated sprites keep the mouth closed, see instruction_edit.build_instruction.
        closed_mouth = bool(settings.pop("closed_mouth", False))
        output_dir = self._prepare_output(output_dir)
        log.info(f"Using {style} instruction edits at intensity {intensity:g} ({len(instructions)} expressions).")

        for expression_name in instructions:
            if self._stop.is_set():
                log.info("Interrupted by user. Stopping..")
                return
            log.info(f"Editing the expression to {expression_name}.")
            override = custom.get(expression_name)
            local = overrides.apply(settings, override)
            if override:
                log.info(f"Using the saved prompt and settings for {expression_name}: {override}")
            edit_settings = instruction_edit.EditSettings.from_settings(local)
            own_intensity = expression_intensity.resolve(local.get("expression_intensity", intensity))
            value = instruction_edit.expression_intensity_for(expression_name, own_intensity, style)
            pose = (poses or {}).get(expression_name) or None
            instruction = (override or {}).get("prompt") or instruction_edit.build_instruction(
                expression_name, extra, style, value, pose=pose, closed_mouth=closed_mouth
            )
            result = self.backend.instruction_edit(
                b64_image, instruction, dataclasses.replace(edit_settings, intensity=value, photo=style == instruction_edit.PHOTO, pose=bool(pose))
            )
            if result is None:
                log.error(f"Instruction edit failed for {expression_name}, stopping.")
                return
            if output_dir is not None:
                save_png(result, output_dir / f"{expression_name}.png")
            yield expression_name, result

        log.info(f"Generated {len(instructions)} expressions.")

    @staticmethod
    def _prepare_output(output_dir):
        if output_dir is None:
            return None
        output_dir = pathlib.Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        log.info(f"Output Directory: {output_dir.absolute()}")
        return output_dir

    def generate(self, *args, **kwargs) -> dict[str, Image.Image]:
        """Same as iter_generate but returns every result at once."""
        return dict(self.iter_generate(*args, **kwargs))


def instruction_default_intensity(style: str, defaults: dict) -> float:
    """The instruction edit intensity when none is set: the family's, but gentler for photos of a drawn-style family."""
    value = defaults["intensity"]
    if style == instruction_edit.PHOTO and defaults["edit_style"] != instruction_edit.PHOTO:
        value = min(value, expression_intensity.PHOTO_DEFAULT)
    return value


def default_expression_prompt(
    expression: str,
    method: str = instruction_edit.INPAINT,
    family: str = DEFAULT_FLAVOR,
    checkpoint: str | None = None,
    intensity: float | None = None,
    style: str | None = None,
    is_realistic: bool = False,
    pose: bool = False,
    extra: str = "",
) -> str:
    """
    What a run would use for one expression's own part of the prompt, the text a per-expression
    override replaces: the weighted expression tags for face inpainting, the whole edit instruction
    for the instruction edit mode. Raises KeyError for an unknown expression.
    """
    resolved = resolve_flavor(family, checkpoint, is_realistic)
    defaults = expression_sets.family_defaults(resolved)
    expression = expression.strip().lower()
    if method == instruction_edit.INSTRUCT:
        style = style if style in instruction_edit.STYLES else (instruction_edit.PHOTO if is_realistic else defaults["edit_style"])
        value = expression_intensity.resolve(intensity if intensity is not None else instruction_default_intensity(style, defaults))
        value = instruction_edit.expression_intensity_for(expression, value, style)
        gesture = instruction_edit.get_poses().get(expression) if pose else None
        return instruction_edit.build_instruction(expression, extra, style, value, pose=gesture or None)
    tags = expression_sets.load_family(resolved)["expressions"][expression]
    value = expression_intensity.resolve(intensity if intensity is not None else defaults["intensity"])
    return expression_intensity.weight_expression(tags, value, natural_language=resolved == "natural_language")
