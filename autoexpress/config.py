"""
Settings for the standalone app, read from environment variables.

Every variable is optional. The WebUI can be on this machine or anywhere else
(https, behind a proxy or sub-path, with a login); with AUTOEXPRESS_BACKEND=auto
its type is read from its API.

| Variable | Default | Meaning |
| --- | --- | --- |
| AUTOEXPRESS_BACKEND | auto | WebUI to start with: auto (detect), a1111, forge, sdnext, comfyui, swarmui, invokeai |
| AUTOEXPRESS_BACKEND_URL | the WebUI's default | Its address, e.g. https://<pod-id>-8188.proxy.runpod.net |
| AUTOEXPRESS_BACKEND_USERNAME / _PASSWORD | | Basic auth (A1111 --api-auth), SwarmUI login, InvokeAI email login |
| AUTOEXPRESS_BACKEND_TOKEN | | Bearer token (or SwarmUI swarm_token) |
| AUTOEXPRESS_BACKEND_HEADERS | | Extra headers for a login proxy: "Name: value" lines or a JSON object (e.g. Cloudflare Access service token) |

The login above is only sent to AUTOEXPRESS_BACKEND_URL's host when that is set,
never to another address typed in the app. Secrets never appear in logs or API responses.
| AUTOEXPRESS_CONNECT_TIMEOUT | 5 | Seconds to wait for a connection |
| AUTOEXPRESS_REQUEST_TIMEOUT | 30 | Seconds to wait for listings and other quick calls |
| AUTOEXPRESS_JOB_TIMEOUT | 1800 | Seconds one expression may take |
| AUTOEXPRESS_RETRIES | 2 | Retries on connection errors and 502/503/504 |
| AUTOEXPRESS_VERIFY_TLS | true | Verify HTTPS certificates |
| AUTOEXPRESS_OUTPUT_DIR | ./Output | Where expressions are saved |
| AUTOEXPRESS_UPLOAD_DIR | ./uploads | Where uploaded images are kept |
| AUTOEXPRESS_MAX_UPLOAD_MB | 32 | Largest accepted request / upload |
| AUTOEXPRESS_MAX_IMAGE_PIXELS | 16777216 | Largest accepted input image (width x height) |
| AUTOEXPRESS_JOB_HISTORY | 50 | Finished jobs kept in memory |
| AUTOEXPRESS_LOG_LEVEL | INFO | Log level |
| AUTOEXPRESS_LOG_JSON | false | One JSON object per log line |
| AUTOEXPRESS_LOG_FILE | | Also log to this file (rotated at 10 MB) |
| AUTOEXPRESS_BACKGROUND_MODEL | isnet-anime / u2net_human_seg | rembg model for "Remove background" (illustration / photo) |
| AUTOEXPRESS_CORS_ORIGINS | http://localhost:8000,http://127.0.0.1:8000 | Web pages allowed to call the API from the browser (comma separated, `*` for any, empty for none). The default is SillyTavern's address, for the SillyTavern extension |
"""

import os
import pathlib
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parent.parent

# SillyTavern's default address, so its AutoExpress extension works without setup.
DEFAULT_CORS_ORIGINS = ("http://localhost:8000", "http://127.0.0.1:8000")


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _number(name: str, default, cast=float):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    try:
        return cast(value)
    except ValueError as e:
        raise ValueError(f"{name} must be a number, got {value!r}") from e


def _origins(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.environ.get(name)
    if value is None:
        return default
    return tuple(origin.strip().rstrip("/") for origin in value.split(",") if origin.strip())


def _headers(name: str) -> dict[str, str]:
    from autoexpress_core.backends.base import parse_headers

    try:
        return parse_headers(os.environ.get(name))
    except ValueError as e:
        raise ValueError(f"{name}: {e}") from e


def _path(name: str, default: pathlib.Path) -> pathlib.Path:
    value = os.environ.get(name)
    return pathlib.Path(value).expanduser().resolve() if value else default


@dataclass
class Settings:
    backend: str = "auto"
    backend_url: str | None = None
    username: str | None = None
    # Secrets stay out of repr() so they never reach a log line.
    password: str | None = field(default=None, repr=False)
    token: str | None = field(default=None, repr=False)
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    connect_timeout: float = 5.0
    request_timeout: float = 30.0
    job_timeout: float = 1800.0
    retries: int = 2
    verify_tls: bool = True
    output_dir: pathlib.Path = field(default_factory=lambda: ROOT / "Output")
    upload_dir: pathlib.Path = field(default_factory=lambda: ROOT / "uploads")
    max_upload_mb: int = 32
    max_image_pixels: int = 4096 * 4096
    job_history: int = 50
    log_level: str = "INFO"
    log_json: bool = False
    log_file: str | None = None
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            backend=os.environ.get("AUTOEXPRESS_BACKEND", "auto").strip().lower(),
            backend_url=os.environ.get("AUTOEXPRESS_BACKEND_URL") or None,
            username=os.environ.get("AUTOEXPRESS_BACKEND_USERNAME") or None,
            password=os.environ.get("AUTOEXPRESS_BACKEND_PASSWORD") or None,
            token=os.environ.get("AUTOEXPRESS_BACKEND_TOKEN") or None,
            headers=_headers("AUTOEXPRESS_BACKEND_HEADERS"),
            connect_timeout=_number("AUTOEXPRESS_CONNECT_TIMEOUT", 5.0),
            request_timeout=_number("AUTOEXPRESS_REQUEST_TIMEOUT", 30.0),
            job_timeout=_number("AUTOEXPRESS_JOB_TIMEOUT", 1800.0),
            retries=_number("AUTOEXPRESS_RETRIES", 2, int),
            verify_tls=_bool("AUTOEXPRESS_VERIFY_TLS", True),
            output_dir=_path("AUTOEXPRESS_OUTPUT_DIR", ROOT / "Output"),
            upload_dir=_path("AUTOEXPRESS_UPLOAD_DIR", ROOT / "uploads"),
            max_upload_mb=_number("AUTOEXPRESS_MAX_UPLOAD_MB", 32, int),
            max_image_pixels=_number("AUTOEXPRESS_MAX_IMAGE_PIXELS", 4096 * 4096, int),
            job_history=_number("AUTOEXPRESS_JOB_HISTORY", 50, int),
            log_level=os.environ.get("AUTOEXPRESS_LOG_LEVEL", "INFO").upper(),
            log_json=_bool("AUTOEXPRESS_LOG_JSON", False),
            log_file=os.environ.get("AUTOEXPRESS_LOG_FILE") or None,
            cors_origins=_origins("AUTOEXPRESS_CORS_ORIGINS", DEFAULT_CORS_ORIGINS),
        )

    def credentials_for(self, url: str | None) -> dict:
        """
        The login from the environment, when it belongs to url.

        With AUTOEXPRESS_BACKEND_URL set, the login is only for that host, so typing another
        address in the app never sends it elsewhere. Without it, it is used for any address.
        """
        from autoexpress_core.backends.base import same_origin

        if self.backend_url and not same_origin(url or self.backend_url, self.backend_url):
            return {"username": None, "password": None, "token": None, "headers": {}}
        return {"username": self.username, "password": self.password, "token": self.token, "headers": dict(self.headers)}

    def connection_options(self, url: str | None = None) -> dict:
        """Keyword arguments for create_backend, with the login when it belongs to url."""
        return {
            **self.credentials_for(url),
            "connect_timeout": self.connect_timeout,
            "timeout": self.request_timeout,
            "job_timeout": self.job_timeout,
            "retries": self.retries,
            "verify_tls": self.verify_tls,
        }


def configure_logging(settings: Settings) -> None:
    """Send loguru output to stderr (and optionally a file), as text or JSON lines."""
    import sys

    from loguru import logger

    # diagnose=False: tracebacks never print local variables, which can hold passwords and tokens.
    logger.remove()
    fmt = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {extra[request_id]} | {name}:{function}:{line} - {message}"
    logger.configure(extra={"request_id": "-"})
    logger.add(sys.stderr, level=settings.log_level, serialize=settings.log_json, format=fmt, backtrace=False, diagnose=False)
    if settings.log_file:
        logger.add(settings.log_file, level=settings.log_level, serialize=settings.log_json, format=fmt, rotation="10 MB", retention=5, diagnose=False)
