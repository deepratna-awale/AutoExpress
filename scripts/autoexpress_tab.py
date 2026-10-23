"""
AutoExpress tab for AUTOMATIC1111 stable-diffusion-webui and its forks
(Forge, reForge, SD.Next).

Generation runs inside the WebUI process through ADetailer, the same way the
WebUI's own img2img tab runs scripts, so the --api flag is not needed.
"""

import os
import re
import sys

import gradio as gr

from modules import script_callbacks, shared

# The WebUI only puts the extension folder on sys.path while loading scripts.
EXTENSION_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if EXTENSION_ROOT not in sys.path:
    sys.path.insert(0, EXTENSION_ROOT)

from autoexpress_core import (  # noqa: E402
    DEFAULT_FLAVOR,
    FLAVORS,
    ExpressionGenerator,
    civitai_key,
    expression_loras,
    expression_names,
    make_sprite_sheet,
    resolve_flavor,
)
from autoexpress_core.backends.a1111_inprocess import A1111InProcessBackend  # noqa: E402
from autoexpress_core.log import log  # noqa: E402

SAME_CHECKPOINT = "Use same checkpoint"
SAME_SAMPLER = "Use same sampler"
SAME_SCHEDULER = "Use same scheduler"
DETECTOR_MODELS = [
    "face_yolov8n.pt",
    "face_yolov8s.pt",
    "mediapipe_face_full",
    "mediapipe_face_short",
    "mediapipe_face_mesh",
]

backend = A1111InProcessBackend()
generator = ExpressionGenerator(backend)


def checkpoint_choices() -> list[str]:
    from modules import sd_models

    return [SAME_CHECKPOINT] + list(sd_models.checkpoint_tiles())


def sampler_choices() -> list[str]:
    from modules import sd_samplers

    if hasattr(sd_samplers, "visible_sampler_names"):
        names = sd_samplers.visible_sampler_names()
    else:
        names = [sampler.name for sampler in sd_samplers.samplers]
    return [SAME_SAMPLER] + list(names)


def scheduler_choices() -> list[str]:
    try:
        from modules import sd_schedulers
    except ImportError:  # WebUI versions before schedulers were split from samplers
        return [SAME_SCHEDULER]
    return [SAME_SCHEDULER] + [scheduler.label for scheduler in sd_schedulers.schedulers]


def current_checkpoint(checkpoint: str | None) -> str:
    """The checkpoint ADetailer will use, for picking the prompt family and LoRAs."""
    if checkpoint and checkpoint != SAME_CHECKPOINT:
        return checkpoint
    info = getattr(shared.sd_model, "sd_checkpoint_info", None)
    return getattr(info, "name", None) or shared.opts.data.get("sd_model_checkpoint", "") or ""


def lora_dir() -> str:
    from modules import paths

    return getattr(shared.cmd_opts, "lora_dir", None) or os.path.join(paths.models_path, "Lora")


def refresh_loras():
    """Make the built-in Lora extension rescan its folder after a download."""
    networks = sys.modules.get("networks")
    if networks is not None and hasattr(networks, "list_available_networks"):
        networks.list_available_networks()


def expression_lora_prompt(checkpoint: str, family: str, api_key: str | None) -> tuple[str, str]:
    """The LoRA prompt tags, and a note for the status line when no LoRA could be used."""
    failures = []
    architecture = expression_loras.guess_architecture(checkpoint, family)
    api_key, key_source = civitai_key.find_civitai_key(
        explicit=[api_key, shared.opts.data.get("autoexpress_civitai_api_key")],
        host_sources=civitai_key.webui_option_sources(shared.opts.data),
    )
    if key_source:
        log.info(f"AutoExpress: using the Civitai API key from {key_source}")

    prompt = expression_loras.expression_lora_prompt(
        checkpoint,
        family,
        lora_dir=lora_dir(),
        api_key=api_key,
        refresh=refresh_loras,
        log=log.info,
        failures=failures,
    )
    log.info(f"AutoExpress: expression LoRAs ({architecture}): {prompt or 'none'}")

    if prompt:
        note = ""
    elif failures:
        note = f"Expression LoRAs skipped: {' '.join(failures)}"
    else:
        note = f"Expression LoRAs skipped: none are listed for {architecture} models."
    return prompt, note


def output_root() -> str:
    from modules import paths

    outdir = shared.opts.data.get("autoexpress_outdir") or os.path.join("outputs", "autoexpress")
    return os.path.join(paths.data_path, outdir)


def safe_folder_name(name: str) -> str:
    name = re.sub(r"[^\w\- ]", "_", (name or "").strip()).strip()
    return name or "New_Character"


def read_parameters(image):
    """Fill the settings from the generation parameters embedded in the uploaded image."""
    nothing = [gr.update()] * 7
    if image is None:
        return nothing

    from modules import images

    try:
        from modules.infotext_utils import parse_generation_parameters
    except ImportError:  # A1111 < 1.8
        from modules.generation_parameters_copypaste import parse_generation_parameters

    geninfo, _ = images.read_info_from_image(image)
    if not geninfo:
        return nothing

    params = parse_generation_parameters(geninfo)

    def value(key, cast=None):
        if key not in params:
            return gr.update()
        try:
            return gr.update(value=cast(params[key]) if cast else params[key])
        except (TypeError, ValueError):
            return gr.update()

    return [
        value("Prompt"),
        value("Negative prompt"),
        value("Sampler"),
        value("Schedule type"),
        value("Steps", int),
        value("CFG scale", float),
        value("Seed", int),
    ]


def generate(
    image,
    character_name,
    flavor,
    selected,
    prompt,
    negative_prompt,
    checkpoint,
    sampler,
    scheduler,
    steps,
    cfg_scale,
    denoising_strength,
    clip_skip,
    seed,
    detector,
    sprite_sheet,
    use_expression_loras,
    civitai_api_key,
    intensity=-1,
):
    if image is None:
        yield [], "Upload a character image first.", None
        return

    if not A1111InProcessBackend.has_adetailer():
        yield [], "ADetailer is missing or disabled. Install it from Extensions and restart.", None
        return

    if not selected:
        yield [], "Pick at least one expression.", None
        return

    settings = {
        "ad_prompt": prompt or "",
        "ad_negative_prompt": negative_prompt or "",
        "ad_checkpoint": checkpoint or SAME_CHECKPOINT,
        "ad_use_checkpoint": checkpoint not in (None, "", SAME_CHECKPOINT),
        "ad_sampler": sampler or SAME_SAMPLER,
        "ad_use_sampler": sampler not in (None, "", SAME_SAMPLER),
        "ad_scheduler": scheduler or SAME_SCHEDULER,
        "ad_steps": int(steps),
        "ad_cfg_scale": float(cfg_scale),
        "ad_denoising_strength": float(denoising_strength),
        "ad_clip_skip": int(clip_skip),
        "ad_model": detector or DETECTOR_MODELS[0],
        "seed": int(seed),
    }
    if intensity is not None and float(intensity) >= 0:
        settings["expression_intensity"] = float(intensity)

    root = os.path.normpath(output_root())
    output_dir = os.path.normpath(os.path.join(root, safe_folder_name(character_name)))
    if not output_dir.startswith(root + os.sep):
        yield [], "Invalid character name.", None
        return
    total = len(selected)
    gallery = []

    checkpoint_name = current_checkpoint(checkpoint)
    family = resolve_flavor(flavor, checkpoint_name)

    lora_prompt, lora_note = "", ""
    if use_expression_loras:
        yield gallery, "Checking expression LoRAs…", None
        try:
            lora_prompt, lora_note = expression_lora_prompt(checkpoint_name, family, civitai_api_key)
        except Exception as error:  # LoRAs are a bonus, never block generation on them
            log.warning(f"AutoExpress: skipping expression LoRAs: {error}")
            lora_note = f"Expression LoRAs skipped: {error}"

    def with_note(status: str) -> str:
        return f"{status}\n\n{lora_note}" if lora_note else status

    log.info(f"AutoExpress: generating {total} {family} expressions into {output_dir}")
    yield gallery, with_note(f"Generating 0/{total} ({family} prompts)…"), None

    try:
        for name, result in generator.iter_generate(
            image,
            settings=settings,
            flavor=family,
            only=selected,
            output_dir=output_dir,
            lora_prompt=lora_prompt,
        ):
            gallery.append((result, name.title()))
            yield gallery, with_note(f"Generating {len(gallery)}/{total}… last: **{name}**"), None
    except Exception as error:
        log.exception("AutoExpress: generation failed")
        yield gallery, f"**Error:** {type(error).__name__}: {error}. Full traceback in the console.", None
        return

    if generator.stopped:
        status = f"Interrupted after {len(gallery)}/{total} expressions."
    elif len(gallery) < total:
        status = f"Stopped after {len(gallery)}/{total} expressions, check the console for errors."
    else:
        status = f"Done. Saved {total} expressions to `{output_dir}`."

    sheet = None
    if sprite_sheet and gallery:
        sheet = make_sprite_sheet(
            [img for img, _ in gallery], [label for _, label in gallery], columns=7
        )
        sheet.save(os.path.join(output_dir, "sprite_sheet.png"))

    yield gallery, with_note(status), sheet


def interrupt():
    generator.stop()
    return "Interrupting…"


def on_ui_tabs():
    with gr.Blocks(analytics_enabled=False) as autoexpress_tab:
        with gr.Row(equal_height=False):
            with gr.Column(variant="panel"):
                image = gr.Image(label="Character image", type="pil", elem_id="autoexpress_image")
                character_name = gr.Textbox(
                    label="Character name (output folder)",
                    placeholder="New_Character",
                    elem_id="autoexpress_character_name",
                )
                flavor = gr.Dropdown(
                    label="Prompt style (auto picks it from the checkpoint)",
                    choices=list(FLAVORS),
                    value=DEFAULT_FLAVOR,
                    elem_id="autoexpress_flavor",
                )
                with gr.Row():
                    use_expression_loras = gr.Checkbox(
                        label="Expression LoRAs (downloaded from Civitai when missing)",
                        value=True,
                        elem_id="autoexpress_use_loras",
                    )
                    civitai_api_key = gr.Textbox(
                        label="Civitai API key",
                        type="password",
                        placeholder="Optional: Settings → AutoExpress, Civitai Browser+/Helper or CIVITAI_API_KEY also work",
                        elem_id="autoexpress_civitai_key",
                    )
                all_names = expression_names()
                expressions = gr.CheckboxGroup(
                    label="Expressions",
                    choices=all_names,
                    value=all_names,
                    elem_id="autoexpress_expressions",
                )
                with gr.Row():
                    select_all = gr.Button("Select all", size="sm")
                    select_none = gr.Button("Clear", size="sm")

            with gr.Column(variant="panel"):
                prompt = gr.Textbox(label="Prompt", lines=3, elem_id="autoexpress_prompt",
                                    placeholder="Character tags and LoRAs, e.g. 1girl, <lora:name:0.8>")
                negative_prompt = gr.Textbox(label="Negative prompt", lines=2, elem_id="autoexpress_negative_prompt")
                with gr.Row():
                    checkpoint = gr.Dropdown(label="Checkpoint", choices=checkpoint_choices(), value=SAME_CHECKPOINT)
                    refresh = gr.Button("🔄", elem_classes=["autoexpress-refresh"])
                with gr.Row():
                    sampler = gr.Dropdown(label="Sampler", choices=sampler_choices(), value=SAME_SAMPLER)
                    scheduler = gr.Dropdown(label="Scheduler", choices=scheduler_choices(), value=SAME_SCHEDULER)
                with gr.Row():
                    steps = gr.Slider(label="Steps", minimum=1, maximum=150, step=1, value=28)
                    cfg_scale = gr.Slider(label="CFG scale", minimum=1.0, maximum=30.0, step=0.5, value=7.0)
                with gr.Row():
                    denoising_strength = gr.Slider(label="Denoising strength", minimum=0.0, maximum=1.0, step=0.01, value=0.55)
                    clip_skip = gr.Slider(label="Clip skip", minimum=1, maximum=12, step=1, value=2)
                intensity = gr.Slider(
                    label="Expression intensity (-1 = model default: 0.5 anime, lower for realistic)",
                    minimum=-1.0, maximum=1.0, step=0.05, value=-1.0, elem_id="autoexpress_intensity",
                )
                with gr.Row():
                    seed = gr.Number(label="Seed", value=-1, precision=0)
                    detector = gr.Dropdown(label="Face detector", choices=DETECTOR_MODELS,
                                           value=DETECTOR_MODELS[0], allow_custom_value=True)
                sprite_sheet = gr.Checkbox(label="Also build a sprite sheet", value=True)
                with gr.Row():
                    generate_button = gr.Button("Generate", variant="primary", elem_id="autoexpress_generate")
                    interrupt_button = gr.Button("Interrupt", elem_id="autoexpress_interrupt")

        status = gr.Markdown(elem_id="autoexpress_status")
        gallery = gr.Gallery(label="Expressions", columns=7, elem_id="autoexpress_gallery")
        sheet = gr.Image(label="Sprite sheet", type="pil", interactive=False, elem_id="autoexpress_sheet")

        image.change(
            fn=read_parameters,
            inputs=[image],
            outputs=[prompt, negative_prompt, sampler, scheduler, steps, cfg_scale, seed],
        )
        select_all.click(fn=lambda: gr.update(value=expression_names()), outputs=[expressions])
        select_none.click(fn=lambda: gr.update(value=[]), outputs=[expressions])
        refresh.click(
            fn=lambda: [
                gr.update(choices=checkpoint_choices()),
                gr.update(choices=sampler_choices()),
                gr.update(choices=scheduler_choices()),
            ],
            outputs=[checkpoint, sampler, scheduler],
        )
        generate_button.click(
            fn=generate,
            inputs=[
                image, character_name, flavor, expressions, prompt, negative_prompt,
                checkpoint, sampler, scheduler, steps, cfg_scale, denoising_strength,
                clip_skip, seed, detector, sprite_sheet, use_expression_loras, civitai_api_key, intensity,
            ],
            outputs=[gallery, status, sheet],
        )
        interrupt_button.click(fn=interrupt, outputs=[status])

    return [(autoexpress_tab, "AutoExpress", "autoexpress")]


def on_ui_settings():
    section = ("autoexpress", "AutoExpress")
    shared.opts.add_option(
        "autoexpress_outdir",
        shared.OptionInfo(
            os.path.join("outputs", "autoexpress"),
            "Output directory for AutoExpress (one sub folder per character)",
            section=section,
        ),
    )
    shared.opts.add_option(
        "autoexpress_civitai_api_key",
        shared.OptionInfo(
            "",
            "Civitai API key for downloading expression LoRAs (or set CIVITAI_API_KEY)",
            section=section,
        ),
    )


script_callbacks.on_ui_tabs(on_ui_tabs)
script_callbacks.on_ui_settings(on_ui_settings)
