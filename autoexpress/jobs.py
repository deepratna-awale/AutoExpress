"""
Background generation jobs for the standalone app.

A WebUI renders one image at a time, so jobs run one after another on a single
worker thread. Requests return straight away with a job id; the job's status,
progress and results are read back with JobManager.get. Each job keeps its own
backend instance, so switching WebUI in the UI never affects a running job.
"""

import pathlib
import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from loguru import logger as log

from autoexpress_core.backends.base import BackendError, BackendNotReady, GenerationCancelled, RemoteBackend

QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED = "queued", "running", "completed", "failed", "cancelled"
FINISHED = (COMPLETED, FAILED, CANCELLED)


@dataclass
class JobSpec:
    """Everything a job needs, captured when it is submitted."""

    backend: RemoteBackend
    image: str
    settings: dict
    output_name: str
    output_path: str
    expressions: list[str]
    family: str = "auto"
    is_realistic: bool = False
    use_expression_loras: bool = True
    lora_dir: str | None = None
    civitai_api_key: str | None = None
    method: str = "inpaint"
    # rembg model to cut every saved expression out of its background with, or None to keep it.
    background_model: str | None = None
    # Animated sprites: animation.AnimationSettings fields (frames, fps, formats, idle_motion, ...), or None for stills only.
    animate: dict | None = None
    # "illustration" or "photo": the wording of the animation prompts.
    style: str = "illustration"
    # Animate the stills already in the output folder instead of generating new ones.
    animate_existing: bool = False
    # A Live2D model kit instead of expressions: {"images": [base64], "name", "settings", "character_lora"}.
    live2d: dict | None = None


@dataclass
class Job:
    spec: JobSpec
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = QUEUED
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    completed: list[str] = field(default_factory=list)
    error: dict | None = None
    notes: list[dict] = field(default_factory=list)
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    generator: object = None
    # Live2D kits: the current stage (label, fraction) and the finished kit's files.
    stage: tuple[str, float] | None = None
    result: dict | None = None

    @property
    def total(self) -> int:
        return len(self.spec.expressions)

    @property
    def current(self) -> str | None:
        if self.status != RUNNING or len(self.completed) >= self.total:
            return None
        if self.spec.live2d is not None and self.stage:
            return self.stage[0]
        return self.spec.expressions[len(self.completed)]

    def to_dict(self, include_step: bool = True) -> dict:
        step = None
        if include_step and self.status == RUNNING:
            try:
                step = self.spec.backend.progress()
            except BackendError:
                step = None
        done = len(self.completed)
        fraction = (done + (step or {}).get("fraction", 0.0)) / self.total if self.total else 0.0
        if self.spec.live2d is not None and self.stage and not done:
            fraction = self.stage[1]
        return {
            "id": self.id,
            "status": self.status,
            "backend": self.spec.backend.kind,
            "backend_name": self.spec.backend.label,
            "method": self.spec.method,
            "output_dir": self.spec.output_name,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": {
                "done": done,
                "total": self.total,
                "fraction": round(min(fraction, 1.0), 4),
                "current": self.current,
                "step": step,
            },
            "images": [] if self.spec.live2d is not None else [self._image_entry(name) for name in self.completed],
            "animate": bool(self.spec.animate),
            "live2d": self.result if self.spec.live2d is not None else None,
            "error": self.error,
            "notes": self.notes,
        }


    def _image_entry(self, name: str) -> dict:
        entry = {"expression": name, "url": f"/image/{self.spec.output_name}/{name}.png"}
        if self.spec.animate:
            folder = pathlib.Path(self.spec.output_path)
            for fmt in animation_formats(self.spec.animate):
                ext = ANIMATION_EXTENSIONS[fmt]
                if (folder / f"{name}{ext}").exists():
                    entry.setdefault("animation", f"/image/{self.spec.output_name}/{name}{ext}")
                    entry.setdefault("animations", {})[fmt] = f"/image/{self.spec.output_name}/{name}{ext}"
        return entry


def animation_formats(settings: dict) -> list[str]:
    from autoexpress_core.animation import AnimationSettings

    return list(AnimationSettings.from_settings(settings).formats)


ANIMATION_EXTENSIONS = {"webp": ".webp", "apng": ".apng", "gif": ".gif"}


class JobManager:
    """A FIFO of jobs with one worker thread, plus a bounded history of finished jobs."""

    def __init__(self, runner: Callable[[Job], None], history: int = 50) -> None:
        self._runner = runner
        self._history = history
        self._queue: queue.Queue[Job] = queue.Queue()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def _ensure_worker(self) -> None:
        if self._worker is None or not self._worker.is_alive():
            self._worker = threading.Thread(target=self._work, name="autoexpress-jobs", daemon=True)
            self._worker.start()

    def submit(self, spec: JobSpec) -> Job:
        job = Job(spec)
        with self._lock:
            self._jobs[job.id] = job
            self._prune()
            self._ensure_worker()
        self._queue.put(job)
        log.info(f"Queued job {job.id}: {job.total} expressions on {spec.backend.label} -> {spec.output_name}")
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    @property
    def active(self) -> Job | None:
        with self._lock:
            return next((job for job in self._jobs.values() if job.status == RUNNING), None)

    def cancel(self, job_id: str) -> Job | None:
        """Cancel a queued job, or interrupt a running one. Returns the job, or None if unknown."""
        job = self.get(job_id)
        if job is None or job.status in FINISHED:
            return job
        job.cancel_requested.set()
        if job.status == QUEUED:
            self._finish(job, CANCELLED)
        elif job.generator is not None:
            try:
                job.generator.stop()
            except BackendError as e:
                log.warning(f"Interrupting job {job.id} failed: {e}")
        log.info(f"Cancel requested for job {job.id}")
        return job

    def cancel_all(self) -> int:
        jobs = [job for job in self.list() if job.status not in FINISHED]
        for job in jobs:
            self.cancel(job.id)
        return len(jobs)

    def _prune(self) -> None:
        finished = sorted((j for j in self._jobs.values() if j.status in FINISHED), key=lambda j: j.created_at)
        for job in finished[: max(0, len(finished) - self._history)]:
            del self._jobs[job.id]

    def _finish(self, job: Job, status: str, error: dict | None = None) -> None:
        job.status = status
        job.error = error
        job.finished_at = time.time()
        job.done.set()

    def _work(self) -> None:
        while True:
            job = self._queue.get()
            try:
                if job.status != QUEUED:
                    continue  # cancelled while waiting
                job.status = RUNNING
                job.started_at = time.time()
                with log.contextualize(request_id=f"job-{job.id}"):
                    self._run(job)
            finally:
                self._queue.task_done()

    def _run(self, job: Job) -> None:
        try:
            self._runner(job)
        except GenerationCancelled:
            self._finish(job, CANCELLED)
        except BackendError as e:
            log.error(f"Job {job.id} failed: {e}")
            self._finish(job, FAILED, e.to_dict())
        except Exception as e:  # never let one job kill the worker
            log.exception(f"Job {job.id} crashed")
            self._finish(job, FAILED, {"code": "internal_error", "message": str(e)})
        else:
            if job.cancel_requested.is_set() and len(job.completed) < job.total:
                self._finish(job, CANCELLED)
            elif len(job.completed) < job.total:
                error = job.spec.backend.last_error
                self._finish(
                    job,
                    FAILED,
                    error.to_dict() if error else {"code": "backend_error", "message": "Generation stopped early."},
                )
            else:
                self._finish(job, COMPLETED)
        log.info(f"Job {job.id} {job.status}: {len(job.completed)}/{job.total} expressions")


def run_expression_job(job: Job) -> None:
    """Default runner: check the WebUI, then generate and save each expression."""
    from autoexpress.modules import expression_generator
    from autoexpress_core import ExpressionGenerator

    spec = job.spec
    if spec.live2d is not None:
        run_live2d_job(job)
        return
    for needed in ([] if spec.animate_existing else [spec.method]) + (["animate"] if spec.animate else []):
        ready, message = spec.backend.check_ready(needed)
        if not ready:
            raise spec.backend.last_error or BackendNotReady(message)

    job.generator = ExpressionGenerator(spec.backend)
    if job.cancel_requested.is_set():
        raise GenerationCancelled("Cancelled before start.")
    if spec.animate is not None:
        prepare_idle_motion(job)

    if spec.animate_existing:
        for name in spec.expressions:
            if job.cancel_requested.is_set():
                break
            animate_expression(job, name)
            job.completed.append(name)
        return

    for name, _ in expression_generator.iter_expressions(
        spec.backend,
        spec.output_path,
        spec.settings,
        image_str=spec.image,
        is_realistic=spec.is_realistic,
        model_family=spec.family,
        use_expression_loras=spec.use_expression_loras,
        lora_dir=spec.lora_dir,
        civitai_api_key=spec.civitai_api_key,
        generator=job.generator,
        only=spec.expressions,
        method=spec.method,
        notes=job.notes,
    ):
        if spec.background_model:
            cut_out_background(job, name)
        if spec.animate and not job.cancel_requested.is_set():
            animate_expression(job, name)
        job.completed.append(name)
        if job.cancel_requested.is_set():
            break


def cut_out_background(job: Job, name: str) -> None:
    """Replace the saved <name>.png with a transparent background copy. On failure keep it and add a note, once."""
    from autoexpress_core import background
    from autoexpress_core.generator import save_png
    from PIL import Image

    spec = job.spec
    if any(note.get("kind") == "background_removal_failed" for note in job.notes):
        return
    path = pathlib.Path(spec.output_path) / f"{name}.png"
    try:
        with Image.open(path) as image:
            image.load()
        cut_out = background.remove_background(image, spec.background_model)
        if image.info.get("parameters"):
            cut_out.info["parameters"] = image.info["parameters"]
        save_png(cut_out, path)
    except Exception as e:  # a missing model download or a bad runtime must not lose the expressions
        log.exception(f"Background removal failed for {name}")
        job.notes.append(
            {
                "kind": "background_removal_failed",
                "title": "Background removal",
                "message": f"Could not remove the background ({e}). The rest of the expressions keep theirs.",
            }
        )


def prepare_idle_motion(job: Job) -> None:
    """Fill in the idle motion (the neutral clip's motion) from the character card in the input image, and note it."""
    from autoexpress_core import animation, character_card

    spec = job.spec
    settings = dict(spec.animate)
    source = settings.pop("idle_source", "card")
    llm = settings.pop("llm", None)
    if not settings.get("idle_motion") and source != "none" and animation.IDLE in spec.expressions:
        card = character_card.read_card(spec.image) if spec.image else None
        motion, origin = animation.resolve_idle_motion(card, source=source, llm=llm)
        settings["idle_motion"] = motion
        where = {"llm": "the LLM", "web": "the character card and a wiki lookup", "card": "the character card"}.get(origin, "the default idle")
        job.notes.append({"kind": "idle_motion", "title": "Idle animation", "message": f"Idle motion from {where}: {motion}"})
        log.info(f"Idle motion ({origin}): {motion}")
    spec.animate = settings


def animate_expression(job: Job, name: str) -> None:
    """Turn the saved <name>.png into a looping animation next to it (<name>.webp etc.)."""
    from autoexpress_core import animation
    from PIL import Image

    spec = job.spec
    folder = pathlib.Path(spec.output_path)
    with Image.open(folder / f"{name}.png") as still:
        still.load()
    settings = animation.AnimationSettings.from_settings(spec.animate)
    log.info(f"Animating {name}.")
    try:
        frames = animation.animate_sprite(spec.backend, still, name, settings, spec.style, spec.background_model)
    except ImportError as e:
        job.notes.append(
            {"kind": "animation_background_failed", "title": "Animated background removal", "message": f"rembg is missing ({e}), so {name} was not animated."}
        )
        return
    except RuntimeError as e:
        if job.cancel_requested.is_set():
            raise GenerationCancelled("Interrupted.") from e
        raise spec.backend.last_error or BackendNotReady(str(e)) from e
    animation.save_animation(frames, folder / name, settings.fps, settings.formats, comment=f"AutoExpress {name}")


LIVE2D_KIT = "live2d kit"


def run_live2d_job(job: Job) -> None:
    """Build a Live2D model kit (see autoexpress_core.live2d.kit) into the output folder."""
    from autoexpress_core import ExpressionGenerator
    from autoexpress_core.images import b64_to_pil
    from autoexpress_core.live2d.kit import KitCancelled, build_kit

    spec = job.spec
    data = spec.live2d
    job.generator = ExpressionGenerator(spec.backend)  # its stop() interrupts the backend
    images = []
    for item in data["images"]:
        image = b64_to_pil(item)
        image.load()
        images.append(image)

    def progress(label: str, fraction: float) -> None:
        job.stage = (label, fraction)

    try:
        result = build_kit(
            spec.backend,
            images,
            pathlib.Path(spec.output_path),
            data["name"],
            data.get("settings") or {},
            character_lora=data.get("character_lora"),
            log=log.info,
            cancelled=job.cancel_requested.is_set,
            progress=progress,
        )
    except KitCancelled as e:
        raise GenerationCancelled("Cancelled.") from e
    except RuntimeError as e:
        if job.cancel_requested.is_set():
            raise GenerationCancelled("Interrupted.") from e
        raise spec.backend.last_error or BackendNotReady(str(e)) from e
    base = f"/image/{spec.output_name}"
    name = data["name"]
    job.result = {
        "name": name,
        "zip": f"{base}/{result.zip_path.name}",
        "psd": f"{base}/{name}/{name}.psd",
        "seethrough_psd": f"{base}/{name}/{name}_seethrough.psd",
        "puppet_zip": f"{base}/{result.puppet_zip.name}" if result.puppet_zip else None,
        "puppet_preview": f"{base}/{name}/puppet/{name}/preview.html" if result.puppet_zip else None,
        "preview": f"{base}/{name}/preview.png",
        "sheet": f"{base}/{name}/sheet.jpg",
        "layers": sum(len(group["layers"]) for group in result.manifest["groups"]),
        "groups": [group["name"] for group in result.manifest["groups"]],
        "switches": result.manifest.get("switches", []),
        "missing": result.manifest["missing"],
        "picture": result.manifest["picture"],
        "notes": result.manifest["notes"],
    }
    for note in result.manifest["notes"]:
        job.notes.append({"kind": "live2d", "title": "Live2D kit", "message": note})
    job.completed.append(LIVE2D_KIT)
