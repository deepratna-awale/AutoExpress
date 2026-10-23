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


def create_backend(kind: str | None = None, url: str | None = None) -> RemoteBackend:
    """Create the backend for a WebUI id; raises ValueError for unknown ids."""
    kind = kind or DEFAULT_BACKEND
    if kind not in REMOTE_BACKENDS:
        raise ValueError(f"Unknown backend '{kind}'. Choose from: {', '.join(REMOTE_BACKENDS)}")
    return REMOTE_BACKENDS[kind](url=url)
