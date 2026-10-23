"""
Runs AutoExpress payloads inside A1111 / Forge / reForge / SD.Next.

The request body is the same one the standalone app sends to /sdapi/v1/img2img,
and it is turned into a StableDiffusionProcessingImg2Img the same way the
WebUI's own API does it, so ADetailer receives identical arguments. Nothing
here goes through HTTP, so the WebUI does not need the --api flag.

Every WebUI import is done lazily so this module can be imported anywhere.
"""

import threading
from contextlib import closing

from PIL import Image

from ..images import b64_to_pil
from ..log import log


class A1111InProcessBackend:

    def __init__(self, outpath_samples: str | None = None) -> None:
        self._outpath_samples = outpath_samples
        self._default_args = None

    @staticmethod
    def _queue_lock():
        """The WebUI's generation queue lock, so jobs from other tabs wait their turn."""
        try:
            from modules.call_queue import queue_lock

            return queue_lock
        except ImportError:
            return threading.Lock()

    def _runner(self):
        from modules import scripts

        return scripts.scripts_img2img

    def _default_script_args(self, runner) -> list:
        """Default value of every script UI component, mirroring the WebUI API."""
        if self._default_args is not None:
            return list(self._default_args)

        import gradio as gr

        last_arg_index = 1
        for script in runner.scripts:
            if last_arg_index < script.args_to:
                last_arg_index = script.args_to

        script_args = [None] * last_arg_index
        script_args[0] = 0
        with gr.Blocks():
            for script in runner.scripts:
                components = script.ui(script.is_img2img)
                if components:
                    script_args[script.args_from:script.args_to] = [
                        getattr(component, "value", None) for component in components
                    ]

        self._default_args = script_args
        return list(script_args)

    def _script_args(self, runner, alwayson_scripts: dict) -> list:
        script_args = self._default_script_args(runner)
        titles = {script.title().lower(): script for script in runner.alwayson_scripts}

        for name, config in (alwayson_scripts or {}).items():
            script = titles.get(name.lower())
            if script is None:
                log.debug(f"Skipping '{name}', no such always-on script in this WebUI.")
                continue
            args = config.get("args", [])[: script.args_to - script.args_from]
            script_args[script.args_from:script.args_from + len(args)] = args

        return script_args

    @staticmethod
    def has_adetailer() -> bool:
        try:
            runner = A1111InProcessBackend()._runner()
        except ImportError:
            return False
        return any(script.title().lower() == "adetailer" for script in runner.alwayson_scripts)

    def img2img(self, payload: dict) -> Image.Image | None:
        from modules import processing, shared

        init_image = payload["init_images"][0]
        if isinstance(init_image, str):
            init_image = b64_to_pil(init_image)
        init_image = init_image.convert("RGB")

        runner = self._runner()

        processed = None
        with self._queue_lock():
            p = processing.StableDiffusionProcessingImg2Img(
                sd_model=shared.sd_model,
                outpath_samples=self._outpath_samples or shared.opts.outdir_img2img_samples,
                outpath_grids=shared.opts.outdir_img2img_grids,
                prompt=payload.get("prompt", ""),
                negative_prompt=payload.get("negative_prompt", ""),
                seed=int(payload.get("seed", -1)),
                sampler_name=payload.get("sampler_name", "Euler"),
                batch_size=1,
                n_iter=1,
                steps=int(payload.get("steps", 1)),
                cfg_scale=float(payload.get("cfg_scale", 7)),
                width=init_image.width,
                height=init_image.height,
                init_images=[init_image],
                denoising_strength=float(payload.get("denoising_strength", 0.75)),
                resize_mode=int(payload.get("resize_mode", 0)),
                do_not_save_samples=True,
                do_not_save_grid=True,
            )
            with closing(p):
                if hasattr(p, "scheduler") and payload.get("scheduler"):
                    p.scheduler = payload["scheduler"]

                p.scripts = runner
                p.script_args = tuple(self._script_args(runner, payload.get("alwayson_scripts")))

                shared.state.begin(job="autoexpress")
                try:
                    processed = processing.process_images(p)
                except Exception as e:
                    log.error(f"Generation failed: {e}")
                finally:
                    shared.state.end()

        if not processed or not processed.images:
            return None
        return processed.images[0]

    def interrupt(self) -> None:
        from modules import shared

        shared.state.interrupt()
