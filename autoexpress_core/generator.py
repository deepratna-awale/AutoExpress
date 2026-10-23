import pathlib
import threading
from typing import Iterator, Protocol

from PIL import Image

from .expressions import DEFAULT_FLAVOR, get_expressions
from .images import pil_to_b64
from .log import log
from .payload import build_expression_payload


class Backend(Protocol):
    """Something that can run an A1111 style img2img request body."""

    def img2img(self, payload: dict) -> Image.Image | None:
        """Run the request and return the first resulting image, or None on failure."""
        ...

    def interrupt(self) -> None:
        ...


class ExpressionGenerator:
    """Runs one ADetailer pass per expression against a Backend."""

    def __init__(self, backend: Backend) -> None:
        self.backend = backend
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
    ) -> Iterator[tuple[str, Image.Image]]:
        """
        Generate expressions one by one.

        Args:
            image (Image.Image | str): Input image, or its base64 string.
            settings (dict | None): Payload overrides (ad_prompt, ad_steps, seed, ...).
            flavor (str): Expression prompt flavor, see expressions.FLAVORS.
            only (list[str] | None): Subset of expression names to generate.
            output_dir (str | Path | None): When set, each image is saved as <expression>.png.

        Yields:
            tuple[str, Image.Image]: Expression name and the generated image.
        """
        self._stop.clear()
        b64_image = image if isinstance(image, str) else pil_to_b64(image)
        expressions = get_expressions(flavor, only)

        if output_dir is not None:
            output_dir = pathlib.Path(output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            log.info(f"Output Directory: {output_dir.absolute()}")

        for expression_name, tags in expressions.items():
            if self._stop.is_set():
                log.info("Interrupted by user. Stopping..")
                return

            log.info(f"Generating image for {expression_name} expression.")
            payload = build_expression_payload(b64_image, settings, tags)
            result = self.backend.img2img(payload)

            if result is None:
                log.error(f"Generation failed for {expression_name}, stopping.")
                return

            if output_dir is not None:
                result.save(output_dir / f"{expression_name}.png")

            yield expression_name, result

        log.info(f"Generated {len(expressions)} expressions.")

    def generate(self, *args, **kwargs) -> dict[str, Image.Image]:
        """Same as iter_generate but returns every result at once."""
        return dict(self.iter_generate(*args, **kwargs))
