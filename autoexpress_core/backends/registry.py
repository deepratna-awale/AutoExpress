"""The WebUIs the standalone app can drive over HTTP, by id."""

from .a1111_api import A1111Client, ForgeClient, SDNextClient
from .base import RemoteBackend
from .comfyui_api import ComfyUIClient
from .invokeai_api import InvokeAIClient
from .swarmui_api import SwarmUIClient

REMOTE_BACKENDS: dict[str, type[RemoteBackend]] = {
    cls.kind: cls for cls in (A1111Client, ForgeClient, SDNextClient, ComfyUIClient, SwarmUIClient, InvokeAIClient)
}
DEFAULT_BACKEND = A1111Client.kind


def describe_backends() -> list[dict[str, str]]:
    return [{"id": kind, "name": cls.label, "default_url": cls.default_url} for kind, cls in REMOTE_BACKENDS.items()]


def create_backend(kind: str | None = None, url: str | None = None, **options) -> RemoteBackend:
    """
    Create the backend for a WebUI id.

    Args:
        kind (str | None): One of REMOTE_BACKENDS, defaults to AUTOMATIC1111.
        url (str | None): Base URL; the WebUI's default address when empty.
        **options: ConnectionOptions fields (username, password, token, timeout, job_timeout, retries, ...).

    Raises:
        ValueError: Unknown id or invalid URL.
    """
    kind = kind or DEFAULT_BACKEND
    if kind not in REMOTE_BACKENDS:
        raise ValueError(f"Unknown backend '{kind}'. Choose from: {', '.join(REMOTE_BACKENDS)}")
    return REMOTE_BACKENDS[kind](url=url, **options)
