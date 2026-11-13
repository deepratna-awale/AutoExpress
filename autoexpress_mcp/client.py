"""A small client for the standalone app's HTTP API, with readable errors for the model."""

from __future__ import annotations

import base64
import io
import mimetypes
import pathlib
import re
import urllib.parse

import requests

MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".json"}


class AppError(RuntimeError):
    """The app answered with an error, or could not be reached."""


class AutoExpressClient:
    def __init__(self, base_url: str, timeout: float = 60.0, allow_local_files: bool = True, session: requests.Session | None = None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.allow_local_files = allow_local_files
        self.session = session or requests.Session()

    def url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def request(self, method: str, path: str, *, json: dict | None = None, params: dict | None = None, timeout: float | None = None):
        try:
            response = self.session.request(method, self.url(path), json=json, params=params, timeout=timeout or self.timeout)
        except requests.RequestException as e:
            raise AppError(
                f"Couldn't reach the AutoExpress app at {self.base_url} ({e.__class__.__name__}). "
                "Start it with `python -m autoexpress` (or ./run.sh, or Docker) and set AUTOEXPRESS_URL to its address."
            ) from e
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code >= 400:
            raise AppError(describe_error(response.status_code, body, response.text))
        return body

    def get(self, path: str, **params):
        return self.request("GET", path, params={k: v for k, v in params.items() if v is not None} or None)

    def post(self, path: str, body: dict | None = None, timeout: float | None = None):
        return self.request("POST", path, json=body or {}, timeout=timeout)

    def put(self, path: str, body: dict):
        return self.request("PUT", path, json=body)

    def download(self, path: str) -> tuple[bytes, str]:
        """The bytes and content type of a file the app serves (results under /image/...)."""
        try:
            response = self.session.get(self.url(path), timeout=self.timeout, stream=True)
        except requests.RequestException as e:
            raise AppError(f"Couldn't reach the AutoExpress app at {self.base_url}: {e}") from e
        if response.status_code >= 400:
            raise AppError(f"{path}: HTTP {response.status_code}, no such file.")
        data = read_capped(response, MAX_DOWNLOAD_BYTES)
        return data, response.headers.get("Content-Type", "application/octet-stream").split(";")[0]

    def load_image(self, image: str) -> str:
        """
        An image for the app as base64: a data URI or base64 is passed through, an http(s) URL is downloaded,
        anything else is read as a path on this machine (when local files are allowed).
        """
        if not isinstance(image, str) or not image.strip():
            raise AppError("An image is required: a file path, an http(s) URL, a data URI or base64.")
        image = image.strip()
        if image.startswith("data:"):
            return image
        if image.startswith(("http://", "https://")):
            try:
                response = requests.get(image, timeout=self.timeout, stream=True)
                response.raise_for_status()
            except requests.RequestException as e:
                raise AppError(f"Couldn't download the image at {image}: {e}") from e
            return base64.b64encode(read_capped(response, MAX_DOWNLOAD_BYTES)).decode()
        encoded = is_base64(image)
        if len(image) < 4096 and looks_like_path(image):
            path = pathlib.Path(image).expanduser()
            if self.allow_local_files and path.is_file():
                if path.stat().st_size > MAX_DOWNLOAD_BYTES:
                    raise AppError(f"{path} is larger than {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB.")
                mime = mimetypes.guess_type(path.name)[0] or "image/png"
                return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
            if not encoded:
                if not self.allow_local_files:
                    raise AppError("This server doesn't read local files (HTTP mode). Send the image as a URL, a data URI or base64.")
                raise AppError(f"No such image file: {path}")
        if not encoded:
            raise AppError(f"Not an image path, URL, data URI or base64: {image[:80]!r}")
        return image


def looks_like_path(text: str) -> bool:
    return (
        pathlib.Path(text).suffix.lower() in IMAGE_SUFFIXES
        or text.startswith(("/", "~", ".", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", text) is not None
    )


def is_base64(text: str) -> bool:
    compact = re.sub(r"\s+", "", text)
    if len(compact) < 16 or not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", compact):
        return False
    try:
        base64.b64decode(compact[:4096] + "=" * (-len(compact[:4096]) % 4), validate=True)
    except ValueError:
        return False
    return True


def read_capped(response: requests.Response, limit: int) -> bytes:
    buffer = io.BytesIO()
    for chunk in response.iter_content(65536):
        buffer.write(chunk)
        if buffer.tell() > limit:
            raise AppError(f"Download is larger than {limit // (1024 * 1024)} MB.")
    return buffer.getvalue()


def describe_error(status: int, body, text: str) -> str:
    """One readable message from the app's error body, keeping the fix steps it sends."""
    if not isinstance(body, dict):
        return f"HTTP {status}: {text[:500]}"
    error = body.get("error")
    if isinstance(error, str):
        return f"HTTP {status}: {error}"
    message = body.get("message") or (error or {}).get("message") or f"HTTP {status}"
    lines = [f"{message} (HTTP {status}{', ' + error['code'] if isinstance(error, dict) and error.get('code') else ''})"]
    if isinstance(error, dict):
        for field, problem in (error.get("fields") or {}).items():
            lines.append(f"- {field}: {problem}")
        fix = error.get("fix") or {}
        for step in fix.get("steps") or []:
            lines.append(f"- {step}")
        for command in fix.get("commands") or []:
            lines.append(f"  $ {command}")
        for link in fix.get("links") or []:
            lines.append(f"  {link.get('url') if isinstance(link, dict) else link}")
    return "\n".join(lines)


def result_path(folder: str, file: str) -> str:
    """The app's URL path of a saved result."""
    return "/image/" + "/".join(urllib.parse.quote(part) for part in [*folder.split("/"), *file.split("/")] if part)
