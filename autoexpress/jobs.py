"""
Background generation jobs for the standalone app.

A WebUI renders one image at a time, so jobs run one after another on a single
worker thread. Requests return straight away with a job id; the job's status,
progress and results are read back with JobManager.get. Each job keeps its own
backend instance, so switching WebUI in the UI never affects a running job.
"""

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

    @property
    def total(self) -> int:
        return len(self.spec.expressions)

    @property
    def current(self) -> str | None:
        if self.status != RUNNING or len(self.completed) >= self.total:
            return None
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
        return {
            "id": self.id,
            "status": self.status,
            "backend": self.spec.backend.kind,
            "backend_name": self.spec.backend.label,
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
            "images": [
                {"expression": name, "url": f"/image/{self.spec.output_name}/{name}.png"} for name in self.completed
            ],
            "error": self.error,
            "notes": self.notes,
        }


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
    ready, message = spec.backend.check_ready()
    if not ready:
        raise spec.backend.last_error or BackendNotReady(message)

    job.generator = ExpressionGenerator(spec.backend)
    if job.cancel_requested.is_set():
        raise GenerationCancelled("Cancelled before start.")

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
        notes=job.notes,
    ):
        job.completed.append(name)
        if job.cancel_requested.is_set():
            break
