import pathlib
import threading
from typing import Iterator, Protocol

from PIL import Image, PngImagePlugin

from . import expression_sets, instruction_edit
from .expressions import DEFAULT_FLAVOR, resolve_flavor
from .images import pil_to_b64
from .log import log
from .payload import build_expression_payload


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
            settings (dict | None): Payload overrides (ad_prompt, ad_steps, seed, ...).
            flavor (str): "auto" or a model family id, see expressions.FLAVORS. "auto"
                picks the family from settings["ad_checkpoint"].
            only (list[str] | None): Subset of expression names to generate.
            output_dir (str | Path | None): When set, each image is saved as <expression>.png.
            lora_prompt (str): Expression LoRA tags appended to the base prompt.
            is_realistic (bool): Tie-breaker for "auto" when the checkpoint name says nothing.
            method (str): instruction_edit.INPAINT (face inpainting with the family's prompts) or
                instruction_edit.INSTRUCT (Qwen-Image-Edit with one sentence per expression; flavor,
                lora_prompt and the ad_* settings are not used, edit_* settings and seed are).

        Yields:
            tuple[str, Image.Image]: Expression name and the generated image.
        """
        self._stop.clear()
        b64_image = image if isinstance(image, str) else pil_to_b64(image)
        settings = dict(settings or {})

        if method == instruction_edit.INSTRUCT:
            yield from self._iter_instruction_edits(b64_image, settings, only, output_dir)
            return

        family = resolve_flavor(flavor, settings.get("ad_checkpoint"), is_realistic)
        self.family = family
        expressions = expression_sets.load_family(family)["expressions"]
        if only:
            wanted = {name.strip().lower() for name in only if name and name.strip()}
            expressions = {name: tags for name, tags in expressions.items() if name in wanted}

        base_prompt = expression_sets.join_prompt(settings.get("ad_prompt", ""), lora_prompt)
        settings["ad_negative_prompt"] = expression_sets.build_negative(
            settings.get("ad_negative_prompt", ""), family
        )
        log.info(f"Using {family} expression prompts.")

        output_dir = self._prepare_output(output_dir)

        for expression_name in expressions:
            if self._stop.is_set():
                log.info("Interrupted by user. Stopping..")
                return

            log.info(f"Generating image for {expression_name} expression.")
            settings["ad_prompt"] = expression_sets.build_prompt(base_prompt, expression_name, family)
            payload = build_expression_payload(b64_image, settings)
            result = self.backend.img2img(payload)

            if result is None:
                log.error(f"Generation failed for {expression_name}, stopping.")
                return

            if output_dir is not None:
                save_png(result, output_dir / f"{expression_name}.png")

            yield expression_name, result

        log.info(f"Generated {len(expressions)} expressions.")

    def _iter_instruction_edits(self, b64_image: str, settings: dict, only, output_dir) -> Iterator[tuple[str, Image.Image]]:
        if instruction_edit.INSTRUCT not in getattr(self.backend, "edit_methods", ()):
            raise ValueError(f"{type(self.backend).__name__} has no instruction edit mode; use the ComfyUI backend.")
        self.family = instruction_edit.INSTRUCT
        instructions = instruction_edit.get_instructions(only)
        edit_settings = instruction_edit.EditSettings.from_settings(settings)
        extra = settings.get("edit_instruction", "")
        output_dir = self._prepare_output(output_dir)
        log.info(f"Using instruction edits ({len(instructions)} expressions).")

        for expression_name in instructions:
            if self._stop.is_set():
                log.info("Interrupted by user. Stopping..")
                return
            log.info(f"Editing the expression to {expression_name}.")
            instruction = instruction_edit.build_instruction(expression_name, extra)
            result = self.backend.instruction_edit(b64_image, instruction, edit_settings)
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
