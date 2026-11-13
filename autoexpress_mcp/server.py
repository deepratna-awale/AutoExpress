"""
The AutoExpress MCP server: tools for any MCP client to drive a running AutoExpress standalone app.

It talks to the app over its HTTP API (AUTOEXPRESS_URL), so the app and the WebUI behind it can run anywhere.
"""

from __future__ import annotations

import asyncio
import io
import os
import pathlib
import time
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import Context, Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

from .client import AppError, AutoExpressClient, result_path

GUIDE_PATH = pathlib.Path(__file__).resolve().parent.parent / "skills" / "autoexpress" / "SKILL.md"
GUIDE_URL = "https://github.com/deepratna-awale/AutoExpress/blob/main/skills/autoexpress/SKILL.md"
DEFAULT_APP_URL = "http://127.0.0.1:5000"
FINISHED = {"completed", "failed", "cancelled"}

INSTRUCTIONS = """\
AutoExpress makes a character's 28 expression sprites (the emotions SillyTavern detects) from one picture, and can
also pose, animate and remove backgrounds, or build a Live2D puppet. It drives a Stable Diffusion WebUI (ComfyUI,
A1111/Forge/reForge, SD.Next, SwarmUI, InvokeAI) that may run anywhere; never assume it's local.

Workflow: autoexpress_status -> connect_webui (if no WebUI is connected) -> check_capabilities (do what each fix
says, don't guess) -> generate_expressions with wait=false -> wait_for_job -> list_results / get_result_image /
save_results. Retry a single bad expression with retry_expression. Jobs run one at a time; they can take minutes.
Read the autoexpress://guide resource for the full guide and rules (SFW examples; characters react, never talk).
"""


def env_flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    def __init__(self, app_url: str | None = None, allow_local_files: bool | None = None, results_dir: str | None = None):
        self.app_url = app_url or os.environ.get("AUTOEXPRESS_URL") or DEFAULT_APP_URL
        self.allow_local_files = env_flag("AUTOEXPRESS_MCP_LOCAL_FILES", True) if allow_local_files is None else allow_local_files
        self.results_dir = pathlib.Path(results_dir or os.environ.get("AUTOEXPRESS_MCP_RESULTS_DIR") or "autoexpress-results").expanduser()
        self.timeout = float(os.environ.get("AUTOEXPRESS_MCP_TIMEOUT", "60"))


def build_server(settings: Settings | None = None, client: AutoExpressClient | None = None) -> MCPServer:
    settings = settings or Settings()
    app = client or AutoExpressClient(settings.app_url, timeout=settings.timeout, allow_local_files=settings.allow_local_files)
    server = MCPServer("AutoExpress", instructions=INSTRUCTIONS, website_url="https://github.com/deepratna-awale/AutoExpress")

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except AppError as e:
            raise ToolError(str(e)) from None

    def image_arg(image: str) -> str:
        return call(app.load_image, image)

    def local_files_only(what: str):
        if not settings.allow_local_files:
            raise ToolError(f"{what} needs local file access, which is off on this server. Use get_result_image or the app's /image/ URLs instead.")

    # Status and the WebUI ------------------------------------------------------------------------------
    @server.tool()
    def autoexpress_status() -> dict:
        """Is the AutoExpress app up, which WebUI is selected, is it reachable and ready. Call this first."""
        health = call(app.get, "/health")
        backends = call(app.get, "/backends")
        status = call(app.get, "/backend/status")
        return {
            "app_url": app.base_url,
            "app": health,
            "webui": {"selected": backends.get("selected"), "url": backends.get("url"), "detected": backends.get("detected"), "login": backends.get("login"), **status},
            "webui_choices": [b.get("id", b) if isinstance(b, dict) else b for b in backends.get("backends", [])],
        }

    @server.tool()
    def connect_webui(
        url: Annotated[str, Field(description="The WebUI address, e.g. http://127.0.0.1:8188 or https://<pod>-8188.proxy.runpod.net")],
        backend: Annotated[str, Field(description="'auto' detects it; or comfyui, a1111, forge (also reForge), sdnext, swarmui, invokeai")] = "auto",
        username: str | None = None,
        password: str | None = None,
        token: Annotated[str | None, Field(description="Bearer token for WebUIs behind a proxy or login")] = None,
    ) -> dict:
        """Point AutoExpress at a Stable Diffusion WebUI, then report what it has for AutoExpress (with fixes)."""
        body: dict[str, Any] = {"text": url, "backend": backend}
        body.update({k: v for k, v in {"username": username, "password": password, "token": token}.items() if v})
        connected = call(app.post, "/receive_data", body)
        return {"connected": connected, "capabilities": call(app.get, "/backend/capabilities")}

    @server.tool()
    def check_capabilities(
        feature: Literal["expressions", "animation", "live2d", "all"] = "expressions",
    ) -> dict:
        """
        What the connected WebUI is missing for a feature, each with fix steps, commands and links. Follow them
        rather than guessing. Animation, poses, instruction edit and Live2D need ComfyUI.
        """
        report: dict[str, Any] = {}
        if feature in ("expressions", "all"):
            report["expressions"] = call(app.get, "/backend/capabilities")
            report["edit_methods"] = call(app.get, "/edit-methods")
            report["background_removal"] = call(app.get, "/background-removal")
        if feature in ("animation", "all"):
            report["animation"] = call(app.get, "/animation")
        if feature in ("live2d", "all"):
            report["live2d"] = call(app.get, "/live2d")
        return report

    @server.tool()
    def list_webui_options(kind: Literal["models", "samplers", "schedulers", "loras"] = "models") -> list:
        """Checkpoints, samplers, schedulers or LoRAs on the connected WebUI (empty when it can't be reached)."""
        return call(app.get, f"/get-{kind}")

    # Prompt styles and expressions ---------------------------------------------------------------------
    @server.tool()
    def list_prompt_styles() -> dict:
        """The expression prompt styles (model families such as anime, pony, realistic) and the selected one."""
        return call(app.get, "/expression-families")

    @server.tool()
    def set_prompt_style(family: Annotated[str, Field(description="A family id from list_prompt_styles, or 'auto' to pick it from the checkpoint")]) -> dict:
        """Select the expression prompt style."""
        return call(app.post, "/expression-family", {"family": family})

    @server.tool()
    def get_expression_prompts(
        expressions: Annotated[list[str] | None, Field(description="Names; default all 28")] = None,
        method: Literal["inpaint", "instruct"] = "inpaint",
        checkpoint: str | None = None,
        intensity: Annotated[float | None, Field(ge=0, le=1)] = None,
        pose: bool = False,
    ) -> dict:
        """
        The 28 expression names and the default wording of each (tags for face inpainting, an instruction for
        instruction edit). This is the text a per-expression prompt override replaces.
        """
        body = {"expressions": expressions, "method": method, "ad_checkpoint": checkpoint, "expression_intensity": intensity, "pose": pose}
        return call(app.post, "/expression-prompt", {k: v for k, v in body.items() if v is not None})

    # Generation ---------------------------------------------------------------------------------------
    def generate_body(image, character, expressions, method, checkpoint, seed, intensity, remove_background, pose, animate, animation, overrides, save_overrides, settings_extra, loras):
        body: dict[str, Any] = {
            "init_images": [image_arg(image)],
            "output_dir": character,
            "wait": False,
            "remove_background": remove_background,
            "pose": pose,
        }
        optional = {
            "expressions": expressions,
            "method": method,
            "ad_checkpoint": checkpoint,
            "seed": seed,
            "expression_intensity": intensity,
            "overrides": overrides,
            "loras": [{"lora_name": name, "lora_strength": strength} for name, strength in (loras or {}).items()] or None,
        }
        body.update({k: v for k, v in optional.items() if v is not None})
        if save_overrides:
            body["save_overrides"] = True
        if animate:
            body["animate"] = True
            body["animation"] = animation or {}
        for key, value in (settings_extra or {}).items():
            body.setdefault(key, value)
        return body

    @server.tool()
    def generate_expressions(
        image: Annotated[str, Field(description="The character picture: a file path on this machine, an http(s) URL, a data URI or base64")],
        character: Annotated[str, Field(description="Output folder name, usually the character's name")],
        expressions: Annotated[list[str] | None, Field(description="A subset of expression names; default all 28")] = None,
        method: Annotated[Literal["inpaint", "instruct"] | None, Field(description="inpaint = face inpainting (any WebUI); instruct = Qwen-Image-Edit (ComfyUI). Default: the prompt style's choice")] = None,
        checkpoint: Annotated[str | None, Field(description="Checkpoint for face inpainting, from list_webui_options")] = None,
        seed: Annotated[int | None, Field(description="-1 for random")] = None,
        intensity: Annotated[float | None, Field(ge=0, le=1, description="How strong the expressions are")] = None,
        remove_background: bool = False,
        pose: Annotated[bool, Field(description="Also change the pose with each expression (needs Qwen-Image-Edit on ComfyUI)")] = False,
        animate: Annotated[bool, Field(description="Also make a looping animation of each expression (Wan 2.2 on ComfyUI)")] = False,
        animation: Annotated[dict | None, Field(description="Animation settings: frames, fps, resolution, formats [webp, apng, gif], idle_source, idle_motion, loop")] = None,
        overrides: Annotated[dict[str, dict] | None, Field(description="Per-expression {name: {prompt, settings}}")] = None,
        save_overrides: Annotated[bool, Field(description="Remember the overrides for this character")] = False,
        loras: Annotated[dict[str, float] | None, Field(description="Extra LoRAs {name: strength} for face inpainting")] = None,
        settings: Annotated[dict | None, Field(description="Any other /generate field, e.g. ad_steps, ad_denoising_strength, ad_sampler, edit_style")] = None,
    ) -> dict:
        """
        Start making expression sprites from one picture. Returns a job at once: follow it with wait_for_job or
        get_job, then fetch results with list_results / get_result_image / save_results.
        """
        body = generate_body(image, character, expressions, method, checkpoint, seed, intensity, remove_background, pose, animate, animation, overrides, save_overrides, settings, loras)
        return call(app.post, "/generate", body)

    @server.tool()
    def retry_expression(
        image: Annotated[str, Field(description="The same character picture used for the set")],
        character: Annotated[str, Field(description="The character's output folder")],
        expression: Annotated[str, Field(description="The expression to redo, e.g. 'joy'")],
        prompt: Annotated[str | None, Field(description="A new prompt for this expression only (see get_expression_prompts)")] = None,
        settings: Annotated[dict | None, Field(description="Per-expression settings, e.g. {ad_denoising_strength: 0.5}")] = None,
        remember: Annotated[bool, Field(description="Save the prompt and settings for this character's later runs")] = False,
        method: Literal["inpaint", "instruct"] | None = None,
        remove_background: bool = False,
    ) -> dict:
        """Redo one expression with a new seed, optionally with its own prompt and settings. Returns a job."""
        name = expression.strip().lower()
        override = {k: v for k, v in {"prompt": prompt, "settings": settings}.items() if v}
        body = generate_body(image, character, [name], method, None, -1, None, remove_background, False, False, None, {name: override} if override else None, remember, None, None)
        return call(app.post, "/generate", body)

    @server.tool()
    def get_expression_overrides(character: str) -> dict:
        """The per-expression prompts and settings saved for a character."""
        return call(app.get, "/expression-overrides", output_dir=character)

    @server.tool()
    def set_expression_overrides(
        character: str,
        expressions: Annotated[dict[str, dict], Field(description="{name: {prompt, settings}}; replaces what is saved; {} clears")],
    ) -> dict:
        """Replace a character's saved per-expression prompts and settings."""
        return call(app.put, "/expression-overrides", {"output_dir": character, "expressions": expressions})

    # Jobs ---------------------------------------------------------------------------------------------
    @server.tool()
    def get_job(job_id: str) -> dict:
        """A job's status (queued, running, completed, failed, cancelled), progress, images, notes and error."""
        return call(app.get, f"/jobs/{job_id}")

    @server.tool()
    async def wait_for_job(
        job_id: str,
        ctx: Context,
        timeout_seconds: Annotated[int, Field(ge=5, le=3600, description="Stop waiting after this long; the job keeps running")] = 600,
    ) -> dict:
        """Wait until a job finishes (or the timeout passes), reporting progress. Returns the job."""
        deadline = time.monotonic() + timeout_seconds
        last = None
        while True:
            job = await asyncio.to_thread(call, app.get, f"/jobs/{job_id}")
            progress = job.get("progress") or {}
            key = (job.get("status"), progress.get("done"), progress.get("current"))
            if key != last:
                last = key
                message = f"{job.get('status')}: {progress.get('done', 0)}/{progress.get('total', 0)}" + (f", {progress['current']}" if progress.get("current") else "")
                try:
                    await ctx.report_progress(float(progress.get("fraction") or 0.0), 1.0, message)
                except Exception:
                    pass
            if job.get("status") in FINISHED:
                return job
            if time.monotonic() >= deadline:
                return {**job, "note": f"Still {job.get('status')} after {timeout_seconds}s; call wait_for_job again."}
            await asyncio.sleep(3)

    @server.tool()
    def list_jobs() -> dict:
        """Recent jobs, newest first."""
        return call(app.get, "/jobs")

    @server.tool()
    def cancel_job(job_id: Annotated[str | None, Field(description="Omit to cancel every queued and running job")] = None) -> Any:
        """Cancel one job, or all of them."""
        return call(app.post, f"/jobs/{job_id}/cancel") if job_id else call(app.post, "/interrupt")

    # Results ------------------------------------------------------------------------------------------
    @server.tool()
    def list_results(character: Annotated[str, Field(description="Output folder (a Live2D kit is under live2d/<name>)")]) -> dict:
        """The files saved for a character, with the app URL of each."""
        files = call(app.get, f"/images/{character}")
        return {"folder": character, "files": [{"name": name, "url": app.url(result_path(character, name))} for name in files]}

    @server.tool()
    def get_result_image(
        character: str,
        file: Annotated[str, Field(description="File name from list_results, e.g. joy.png")],
        max_size: Annotated[int, Field(ge=64, le=2048, description="Longest side of the returned picture")] = 768,
    ) -> Image:
        """A saved picture, so you can look at it (downscaled; save_results keeps full size)."""
        data, mime = call(app.download, result_path(character, file))
        if not mime.startswith("image/"):
            raise ToolError(f"{file} is {mime}, not a picture. Use save_results to download it.")
        try:
            from PIL import Image as PILImage

            with PILImage.open(io.BytesIO(data)) as picture:
                picture.seek(0)
                picture = picture.convert("RGBA")
                picture.thumbnail((max_size, max_size))
                out = io.BytesIO()
                picture.save(out, "PNG", optimize=True)
                return Image(data=out.getvalue(), format="png")
        except ImportError:
            return Image(data=data, format=mime.split("/", 1)[1])

    @server.tool()
    def save_results(
        character: str,
        destination: Annotated[str | None, Field(description="Folder on this machine; default AUTOEXPRESS_MCP_RESULTS_DIR/<character>")] = None,
        files: Annotated[list[str] | None, Field(description="Only these files; default all")] = None,
    ) -> dict:
        """Download a character's results (sprites, animations, Live2D zips) to a folder on this machine."""
        local_files_only("Saving results")
        names = files or call(app.get, f"/images/{character}")
        target = pathlib.Path(destination).expanduser() if destination else settings.results_dir / character
        target.mkdir(parents=True, exist_ok=True)
        saved = []
        for name in names:
            safe = pathlib.Path(name).name
            data, _ = call(app.download, result_path(character, name))
            (target / safe).write_bytes(data)
            saved.append(str(target / safe))
        return {"folder": str(target.resolve()), "saved": saved}

    # Animation ----------------------------------------------------------------------------------------
    @server.tool()
    def animate_expressions(
        character: Annotated[str, Field(description="Output folder with expression stills from an earlier run")],
        expressions: Annotated[list[str] | None, Field(description="Default: every still in the folder")] = None,
        animation: Annotated[dict | None, Field(description="frames, fps, resolution, formats, idle_source (card/web/llm/none), idle_motion, loop")] = None,
        image: Annotated[str | None, Field(description="The character card or picture, for the idle motion")] = None,
    ) -> dict:
        """Animate expression stills already saved (Wan 2.2 on ComfyUI). Returns a job."""
        body: dict[str, Any] = {"output_dir": character, "animation": animation or {}, "wait": False}
        if expressions:
            body["expressions"] = expressions
        if image:
            body["image"] = image_arg(image)
        return call(app.post, "/animate", body)

    @server.tool()
    def read_character_card(
        image: Annotated[str | None, Field(description="A SillyTavern character card PNG or JSON (path, URL, data URI or base64)")] = None,
        name: str | None = None,
        persona: str | None = None,
        idle_source: Literal["card", "web", "llm"] = "card",
    ) -> dict:
        """Read a character card (name, persona) and the idle motion AutoExpress would animate for it."""
        body: dict[str, Any] = {"idle_source": idle_source}
        if image:
            body["image"] = image_arg(image)
        body.update({k: v for k, v in {"name": name, "persona": persona}.items() if v})
        return call(app.post, "/character-card", body)

    # Live2D -------------------------------------------------------------------------------------------
    @server.tool()
    def live2d_check_pictures(images: Annotated[list[str], Field(description="1-8 pictures of the character")]) -> dict:
        """Score pictures for a Live2D model (pose, framing, occlusion) and say which works best and why."""
        return call(app.post, "/live2d/check", {"images": [image_arg(image) for image in images]})

    @server.tool()
    def live2d_find_character_lora(name: str, checkpoint: str | None = None) -> dict:
        """Look for the character's LoRA on Civitai, with whether the WebUI already has it and how to install it."""
        return call(app.post, "/live2d/character-lora", {k: v for k, v in {"name": name, "checkpoint": checkpoint}.items() if v})

    @server.tool()
    def build_live2d_kit(
        images: Annotated[list[str], Field(description="1-8 pictures of the character; the best one is the base")],
        name: Annotated[str, Field(description="The model's name (folder under live2d/)")],
        settings: Annotated[dict | None, Field(description="resolution, steps, seed, low_vram, base_index, variants (auto/instruct/inpaint/none), remove_background")] = None,
        character_lora: Annotated[dict | None, Field(description="A result from live2d_find_character_lora: {entry, installed_name}")] = None,
    ) -> dict:
        """
        Build a Live2D model kit and ready-to-play puppet (ComfyUI with the See-through nodes). Returns a job; when
        it completes, job.live2d has the puppet zip, PSD and preview paths (fetch them with save_results on live2d/<name>).
        """
        body: dict[str, Any] = {"images": [image_arg(image) for image in images], "name": name, "settings": settings or {}, "wait": False}
        if character_lora:
            body["character_lora"] = character_lora
        return call(app.post, "/live2d", body, timeout=max(app.timeout, 120))

    # Options ------------------------------------------------------------------------------------------
    @server.tool()
    def configure_options(
        expression_loras: Annotated[bool | None, Field(description="Use expression LoRAs for face inpainting")] = None,
        civitai_api_key: Annotated[str | None, Field(description="For LoRA downloads (write-only)")] = None,
        llm_url: Annotated[str | None, Field(description="OpenAI compatible endpoint that writes idle motions")] = None,
        llm_model: str | None = None,
        llm_api_key: Annotated[str | None, Field(description="Write-only")] = None,
        realistic: Annotated[bool | None, Field(description="The character is a photo / realistic render")] = None,
    ) -> dict:
        """Read or change app options. Call with no arguments to see the current ones (keys are never shown)."""
        lora_body = {k: v for k, v in {"enabled": expression_loras, "civitai_api_key": civitai_api_key}.items() if v is not None}
        llm_body = {k: v for k, v in {"url": llm_url, "model": llm_model, "api_key": llm_api_key}.items() if v is not None}
        result = {
            "expression_loras": call(app.post, "/expression-loras", lora_body) if lora_body else call(app.get, "/expression-loras"),
            "llm": call(app.post, "/llm-settings", llm_body) if llm_body else call(app.get, "/llm-settings"),
        }
        if realistic is not None:
            result["realistic"] = call(app.post, "/toggle", {"isRealistic": realistic})
        return result

    # Guide --------------------------------------------------------------------------------------------
    @server.resource("autoexpress://guide", name="AutoExpress guide", description="How to use AutoExpress well: workflow, features, rules", mime_type="text/markdown")
    def guide() -> str:
        if GUIDE_PATH.is_file():
            return GUIDE_PATH.read_text(encoding="utf-8")
        return f"{INSTRUCTIONS}\nThe full guide: {GUIDE_URL}\n"

    @server.prompt(name="make_expression_sprites", description="Make a character's expression sprites end to end")
    def make_expression_sprites(image: str, character: str) -> str:
        return (
            f"Make the 28 expression sprites for {character} from {image} with AutoExpress. Check the app and the WebUI "
            "with autoexpress_status and check_capabilities, fix anything missing by following the fix steps, start "
            "generate_expressions (wait=false), follow it with wait_for_job, look at a few results with "
            "get_result_image, retry any expression that came out wrong with retry_expression, then save_results."
        )

    return server
