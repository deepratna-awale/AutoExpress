import dataclasses
import os
import threading
import time
import uuid

from flask import Flask, g, jsonify, render_template, request, send_from_directory
from loguru import logger as log
from PIL import Image, UnidentifiedImageError
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from autoexpress import frontend
from autoexpress.config import Settings, configure_logging
from autoexpress.jobs import CANCELLED, COMPLETED, FINISHED, JobManager, JobSpec, run_expression_job
from autoexpress.modules import expression_sets, image_parser
from autoexpress.modules.expression_loras import CIVITAI_KEY_ENV
from autoexpress.validation import ValidationError, resolve_inside, validate_generate
from autoexpress_core import get_expressions, instruction_edit, resolve_flavor
from autoexpress_core.backends.base import (
    BackendAuthError,
    BackendError,
    BackendNotReady,
    BackendTimeout,
    BackendUnavailable,
    connection_fix,
)
from autoexpress_core.backends.detect import detect_backend, not_a_webui
from autoexpress_core.backends.registry import AUTO, REMOTE_BACKENDS, create_backend, describe_backends
from autoexpress_core.civitai_key import find_civitai_key

settings = Settings.from_env()
configure_logging(settings)

autoexpress = Flask(__name__)
autoexpress.register_blueprint(frontend.frontend)
autoexpress.config["UPLOAD_FOLDER"] = str(settings.upload_dir)
autoexpress.config["MAX_CONTENT_LENGTH"] = settings.max_upload_mb * 1024 * 1024
Image.MAX_IMAGE_PIXELS = settings.max_image_pixels

settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.output_dir.mkdir(parents=True, exist_ok=True)


class AppState:
    """The WebUI the sidebar is connected to. Running jobs keep their own backend."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.detected = None
        kind = settings.backend
        if kind == AUTO:
            kind = self._detect_at_startup()
        elif kind not in REMOTE_BACKENDS:
            log.warning(f"Unknown AUTOEXPRESS_BACKEND '{settings.backend}', using a1111.")
            kind = "a1111"
        self.backend = create_backend(kind, settings.backend_url, **settings.connection_options())

    def _detect_at_startup(self) -> str:
        if not settings.backend_url:
            return "a1111"
        try:
            detection = detect_backend(settings.backend_url, **settings.connection_options())
        except (BackendError, ValueError) as e:
            log.warning(f"Could not detect the WebUI at {settings.backend_url}: {e}")
            return "a1111"
        self.detected = detection.kind
        return detection.kind or "a1111"

    def connect(self, kind: str, url: str | None, credentials: dict | None = None):
        """
        Switch WebUI and/or URL. kind "auto" asks the WebUI what it is.

        Raises:
            ValueError: Unknown id or a bad URL.
            BackendError: "auto" could not reach the WebUI, was refused, or found no supported WebUI.
        """
        options = settings.connection_options()
        if credentials is not None:
            options.update(credentials)
        detected = None
        if kind == AUTO:
            detection = detect_backend(url, **options)
            if not detection.kind:
                raise not_a_webui(url, detection)
            kind = detected = detection.kind
        backend = create_backend(kind, url, **options)
        with self.lock:
            self.backend = backend
            self.detected = detected
        return backend


state = AppState()
jobs = JobManager(run_expression_job, history=settings.job_history)

is_realistic = False
model_family = expression_sets.AUTO
lora_settings = {
    "enabled": True,
    "lora_dir": os.environ.get("AUTOEXPRESS_LORA_DIR", ""),
    "civitai_api_key": os.environ.get(CIVITAI_KEY_ENV, ""),
}


def civitai_key_for(backend) -> tuple[str | None, str | None]:
    """The key typed into AutoExpress, else one the WebUI's Civitai extension or node has, else the environment."""
    explicit = lora_settings["civitai_api_key"] or None
    return find_civitai_key(explicit, () if explicit else backend.civitai_key_sources())


def current_backend():
    with state.lock:
        return state.backend


def error_response(code: str, message: str, http_status: int, **extra):
    body = {"status": "Failed", "message": message, "error": {"code": code, "message": message, **extra}}
    return jsonify(body), http_status


# Request logging ------------------------------------------------------------
@autoexpress.before_request
def start_request():
    g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    g.started = time.monotonic()
    g.log_context = log.contextualize(request_id=g.request_id)
    g.log_context.__enter__()


@autoexpress.after_request
def finish_request(response):
    response.headers["X-Request-ID"] = g.get("request_id", "-")
    if request.path.startswith("/static/") or request.path in ("/health",):
        return response
    elapsed = (time.monotonic() - g.get("started", time.monotonic())) * 1000
    log.info(f"{request.method} {request.path} -> {response.status_code} in {elapsed:.0f} ms")
    return response


@autoexpress.teardown_request
def end_request(_error=None):
    context = g.pop("log_context", None)
    if context is not None:
        context.__exit__(None, None, None)


@autoexpress.errorhandler(ValidationError)
def handle_validation_error(e: ValidationError):
    return error_response(e.code, str(e), 400, fields=e.errors)


@autoexpress.errorhandler(BackendError)
def handle_backend_error(e: BackendError):
    fix = getattr(e, "fix", None)
    if fix is None and isinstance(e, (BackendUnavailable, BackendTimeout, BackendAuthError)):
        fix = connection_fix(e)
    extra = {"fix": dataclasses.asdict(fix)} if fix else {}
    return error_response(e.code, str(e), e.http_status, **extra)


@autoexpress.errorhandler(HTTPException)
def handle_http_error(e: HTTPException):
    if request.path.startswith("/static/") or request.path == "/":
        return e
    return error_response(e.name.lower().replace(" ", "_"), e.description, e.code)


@autoexpress.errorhandler(Exception)
def handle_unexpected_error(e: Exception):
    log.exception(f"Unhandled error on {request.method} {request.path}")
    return error_response("internal_error", "Internal error, see the server log.", 500)


# AutoExpress UI
@autoexpress.route("/", methods=["GET"])
def index():
    if frontend.is_built():
        return frontend.index()
    return classic()


@autoexpress.route("/classic", methods=["GET"])
def classic():
    return render_template("index.html", backends=describe_backends(include_auto=True), selected=AUTO)


# Health and WebUI status ----------------------------------------------------
@autoexpress.route("/health", methods=["GET"])
def health():
    """Liveness of AutoExpress itself; does not call the WebUI."""
    active = jobs.active
    return jsonify({"status": "ok", "backend": current_backend().kind, "active_job": active.id if active else None})


@autoexpress.route("/backend/status", methods=["GET"])
def backend_status():
    """Is the selected WebUI reachable and ready, with its version where it reports one."""
    return jsonify(current_backend().health())


@autoexpress.route("/backend/capabilities", methods=["GET"])
def backend_capabilities():
    """
    Everything AutoExpress needs on the selected WebUI, checked over its API, item by item.

    Each missing item carries a fix (steps, commands to copy, links), so the UI can walk the user through it.
    """
    report = current_backend().check_capabilities()
    report["detected"] = state.detected is not None
    return jsonify(report)


@autoexpress.route("/backends", methods=["GET"])
def list_backends():
    backend = current_backend()
    return jsonify(
        {
            "selected": backend.kind,
            "detected": state.detected is not None,
            "url": backend.get_url(),
            "backends": describe_backends(include_auto=True),
        }
    )


# Stable diffusion API Calls
@autoexpress.route("/interrupt", methods=["POST"])
def interrupt_generation():
    """Cancel the running job and anything queued after it."""
    cancelled = jobs.cancel_all()
    log.info(f"Interrupt: cancelled {cancelled} job(s).")
    return jsonify(True)


@autoexpress.route("/get-models")
def get_models():
    return jsonify(current_backend().models)


@autoexpress.route("/get-samplers")
def get_samplers():
    return jsonify(current_backend().samplers)


@autoexpress.route("/get-schedulers")
def get_schedulers():
    return jsonify(current_backend().schedulers)


@autoexpress.route("/get-loras")
def get_loras():
    return jsonify(current_backend().loras)

# End of Stable diffusion API Calls

# Image uploaded
@autoexpress.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if not allowed_file(file.filename):
        return jsonify({"error": "Only png, jpg, jpeg, gif and webp images are accepted."}), 400

    stem, ext = file.filename.rsplit(".", 1)
    filename = secure_filename(f"{secure_filename(stem) or 'image'}_{uuid.uuid4().hex[:8]}.{ext.lower()}")
    filepath = os.path.join(autoexpress.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    try:
        with Image.open(filepath) as image:
            image.verify()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        os.remove(filepath)
        log.info(f"Rejected upload {filename}: {e}")
        return jsonify({"error": "Not a readable image."}), 400

    full_image_data = {"cleaned_data": None, "uncleaned_data": None, "width": None, "height": None}
    full_image_data["cleaned_data"] = image_parser.generate_cleaned_parameters(filepath)
    full_image_data["uncleaned_data"] = image_parser.generate_uncleaned_params(filepath)
    full_image_data["width"], full_image_data["height"] = image_parser.get_size_from_image_metadata(filepath)

    return jsonify(full_image_data), 200


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {"png", "jpg", "jpeg", "gif", "webp"}


# Try connecting to SD
@autoexpress.route("/receive_data", methods=["POST"])
def receive_data():
    """
    Pick the WebUI backend and set its URL.

    Body: {"text": url, "backend": id (optional, keeps the current one),
           "username", "password", "token" (optional, replace stored credentials)}
    """
    data = request.get_json(silent=True) or {}
    url = data.get("text")
    kind = data.get("backend") or current_backend().kind

    credentials = None
    if any(key in data for key in ("username", "password", "token")):
        credentials = {key: (data.get(key) or None) for key in ("username", "password", "token")}

    try:
        backend = state.connect(kind, url, credentials)
    except ValueError as e:
        log.info(f"Could not connect to {kind} at {url}: {e}")
        if kind != AUTO and kind not in REMOTE_BACKENDS:
            return jsonify({"error": f"Unknown WebUI backend. Choose one of: {', '.join([AUTO, *REMOTE_BACKENDS])}."}), 400
        return jsonify({"error": "Not a valid http(s) URL."}), 400

    if not url:
        log.info(f"No url found, defaulting to {backend.get_url()}")
    log.info(f"{backend.label} URL set to: {backend.get_url()}")

    return jsonify(
        {
            "status": "success",
            "backend": backend.kind,
            "name": backend.label,
            "url": backend.get_url(),
            "detected": kind == AUTO,
        }
    )


# Generate Images
@autoexpress.route("/generate", methods=["POST"])
def generate():
    """
    Queue the expressions for generation.

    By default the request waits until the job finishes, like before. Send
    "wait": false to get a job id back immediately (HTTP 202) and follow it
    with GET /jobs/<id>.

    "method": "instruct" uses the instruction edit mode (Qwen-Image-Edit, ComfyUI
    only) instead of face inpainting; see GET /edit-methods.
    """
    request_data = validate_generate(request.get_json(silent=True), settings.max_image_pixels)
    backend = current_backend()
    job_settings = dict(request_data["settings"])
    family = resolve_flavor(model_family, job_settings.get("ad_checkpoint"), is_realistic)
    family_defaults = expression_sets.family_defaults(family)
    method = request_data["method"]
    if method is None:
        # Realistic families default to the instruction edit where the WebUI has it; inpainting barely moves a photo.
        method = family_defaults["method"] if family_defaults["method"] in backend.edit_methods else instruction_edit.INPAINT
    if method not in backend.edit_methods:
        raise ValidationError(
            {"method": f"{backend.label} has no {instruction_edit.METHODS[method]['name']} mode. Use the ComfyUI backend for it."}
        )

    for lora_name, lora_strength in request_data["loras"]:
        job_settings["ad_prompt"] = f"{job_settings.get('ad_prompt', '')} <lora:{lora_name}:{lora_strength}>, "

    if method == instruction_edit.INSTRUCT:
        expressions = list(instruction_edit.get_instructions(request_data["expressions"]))
    else:
        expressions = list(get_expressions(family, request_data["expressions"]))
    if not expressions:
        raise ValidationError({"expressions": "None of the requested expressions exist."})

    output_path = resolve_inside(settings.output_dir, request_data["output_name"])
    if output_path is None:
        raise ValidationError({"output_dir": "Invalid folder name."})

    log.info(f"Generation parameters: { {k: v for k, v in job_settings.items()} }")

    # A fresh client per job, so switching WebUI or interrupting never touches another job.
    job_backend = create_backend(backend.kind, backend.get_url(), options=backend.connection)
    # Fail fast instead of waiting behind queued jobs to find out the WebUI is down.
    ready, message = job_backend.check_ready(method)
    if not ready:
        raise job_backend.last_error or BackendNotReady(message)
    civitai_api_key = None
    if lora_settings["enabled"] and method == instruction_edit.INPAINT:
        civitai_api_key, source = civitai_key_for(job_backend)
        if source:
            log.info(f"Civitai API key from {source}")
    job = jobs.submit(
        JobSpec(
            backend=job_backend,
            image=request_data["image"],
            settings=job_settings,
            output_name=request_data["output_name"],
            output_path=str(output_path),
            expressions=expressions,
            family=family,
            is_realistic=is_realistic,
            # Off for families whose models the expression LoRAs don't help (realistic photos).
            use_expression_loras=lora_settings["enabled"] and family_defaults["expression_loras"],
            lora_dir=lora_settings["lora_dir"] or None,
            civitai_api_key=civitai_api_key,
            method=method,
        )
    )

    if not request_data["wait"]:
        return jsonify({"status": "queued", "job_id": job.id, "job": job.to_dict(include_step=False)}), 202

    job.done.wait()
    result = job.to_dict(include_step=False)
    if job.status == COMPLETED:
        return jsonify({"status": "success", "message": f"Generated {job.total} expressions.", "job": result})
    if job.status == CANCELLED:
        return jsonify({"status": "cancelled", "message": "Generation was interrupted.", "job": result})
    error = job.error or {"code": "backend_error", "message": "Generation failed."}
    status = BackendError.status_for(error.get("code")) if error.get("code") != "internal_error" else 500
    return jsonify({"status": "Failed", "message": error["message"], "error": error, "job": result}), status


# Jobs -----------------------------------------------------------------------
@autoexpress.route("/jobs", methods=["GET"])
def list_jobs():
    return jsonify({"jobs": [job.to_dict(include_step=False) for job in jobs.list()]})


@autoexpress.route("/jobs/<job_id>", methods=["GET"])
def get_job(job_id):
    job = jobs.get(job_id)
    if job is None:
        return error_response("not_found", f"No job {job_id}.", 404)
    return jsonify(job.to_dict())


@autoexpress.route("/jobs/<job_id>/cancel", methods=["POST"])
def cancel_job(job_id):
    job = jobs.cancel(job_id)
    if job is None:
        return error_response("not_found", f"No job {job_id}.", 404)
    return jsonify(job.to_dict(include_step=False)), (200 if job.status in FINISHED else 202)


# Results --------------------------------------------------------------------
@autoexpress.route("/images/<path:subpath>")
def list_images(subpath):
    directory = resolve_inside(settings.output_dir, subpath)
    if directory is None:
        return jsonify({"error": "Invalid folder"}), 400
    if not directory.is_dir():
        log.info(f"Directory not found: {directory}")
        return jsonify({"error": "Directory not found"}), 404
    files = sorted(f.name for f in directory.iterdir() if f.is_file())
    return jsonify(files)


@autoexpress.route("/image/<path:filename>")
def get_image(filename):
    """Endpoint to serve images from the entire output directory."""
    return send_from_directory(settings.output_dir, filename)


@autoexpress.route("/toggle", methods=["POST"])
def handle_toggle():
    global is_realistic
    data = request.get_json(silent=True) or {}
    is_realistic = bool(data.get("isRealistic"))

    return jsonify({"message": f"Is realistic status set to {is_realistic}"})


@autoexpress.route("/expression-families", methods=["GET"])
def get_expression_families():
    return jsonify(
        {"selected": model_family, "families": expression_sets.list_families()}
    )


@autoexpress.route("/expression-family", methods=["POST"])
def set_expression_family():
    global model_family
    family = (request.get_json(silent=True) or {}).get("family") or expression_sets.AUTO

    if family != expression_sets.AUTO:
        try:
            expression_sets.load_family(family)
        except KeyError:
            return jsonify({"error": f"Unknown expression family: {family}"}), 400

    model_family = family
    log.info(f"Expression family set to {model_family}")
    return jsonify({"message": f"Expression family set to {model_family}"})


@autoexpress.route("/expression-defaults", methods=["GET"])
def get_expression_defaults():
    """
    The calibrated defaults (method, intensity, edit_style) of the family a checkpoint uses.

    Query: checkpoint (the selected model), family (optional, else the selected prompt style).
    """
    family_choice = request.args.get("family") or model_family
    try:
        family = resolve_flavor(family_choice, request.args.get("checkpoint"), is_realistic)
    except KeyError:
        return error_response("invalid_request", f"Unknown expression family: {family_choice}", 400)
    return jsonify({"family": family, "defaults": expression_sets.family_defaults(family)})


@autoexpress.route("/edit-methods", methods=["GET"])
def get_edit_methods():
    """The ways to change an expression, and which of them the selected WebUI can do."""
    backend = current_backend()
    return jsonify(
        {
            "backend": backend.kind,
            "methods": [
                {"id": method_id, **info, "available": method_id in backend.edit_methods}
                for method_id, info in instruction_edit.METHODS.items()
            ],
            "vram_note": instruction_edit.VRAM_NOTE,
        }
    )


@autoexpress.route("/expression-loras", methods=["GET"])
def get_expression_lora_settings():
    return jsonify(
        {
            "enabled": lora_settings["enabled"],
            "lora_dir": lora_settings["lora_dir"],
            "has_civitai_api_key": bool(lora_settings["civitai_api_key"]),
            "civitai_key_source": civitai_key_for(current_backend())[1],
        }
    )


@autoexpress.route("/expression-loras", methods=["POST"])
def set_expression_lora_settings():
    data = request.get_json(silent=True) or {}

    if "enabled" in data:
        lora_settings["enabled"] = bool(data["enabled"])
    if "lora_dir" in data:
        lora_settings["lora_dir"] = (data["lora_dir"] or "").strip()
    if data.get("civitai_api_key"):
        lora_settings["civitai_api_key"] = data["civitai_api_key"].strip()

    log.info(
        f"Expression LoRAs {'on' if lora_settings['enabled'] else 'off'}, "
        f"LoRA folder: {lora_settings['lora_dir'] or 'auto'}"
    )
    return get_expression_lora_settings()
