"""
Work out which WebUI is behind a URL from its API, so the user only has to paste the address.

Nothing here assumes the WebUI runs on this machine: it works the same for
http://127.0.0.1:7860, a LAN address, or an https RunPod proxy with a sub-path and a login.
Each probe is one cheap request that only one kind of WebUI answers:

    ComfyUI     GET  /system_stats             {"system": {...}, "devices": [...]}
    InvokeAI    GET  /api/v1/app/version       {"version": "5.x"}
    SwarmUI     POST /API/GetNewSession        {"session_id": ...} (or a SwarmUI error_id)
    A1111 API   GET  /sdapi/v1/samplers        then Forge / SD.Next / A1111 from their flags and version
"""

from dataclasses import dataclass, field

from ..log import log
from .base import BackendAuthError, BackendRejected, BackendUnavailable, RemoteBackend

# Launch flags only Forge and reForge have, as /sdapi/v1/cmd-flags reports them.
FORGE_FLAGS = ("forge_ref_a1111_home", "cuda_malloc", "pin_shared_memory", "always_offload_from_vram", "unet_in_fp8_e4m3fn")


@dataclass
class Detection:
    kind: str | None
    evidence: str = ""
    tried: list[str] = field(default_factory=list)


class _Probe(RemoteBackend):
    kind = "probe"
    label = "WebUI"


def _json(probe: _Probe, method: str, path: str, **kwargs):
    """The JSON a probe answered with, None when the route doesn't exist there. Auth and network errors raise."""
    response = probe._request(method, path, timeout=10, **kwargs)
    if response.status_code >= 400:
        return None
    try:
        return response.json()
    except ValueError:
        return None


def _a1111_variant(probe: _Probe) -> tuple[str, str]:
    version = _json(probe, "GET", "/sdapi/v1/version") or {}
    if isinstance(version, dict) and "next" in str(version.get("app", "")).lower():
        return "sdnext", "/sdapi/v1/version names SD.Next"
    flags = _json(probe, "GET", "/sdapi/v1/cmd-flags") or {}
    if isinstance(flags, dict):
        if any(flag in flags for flag in FORGE_FLAGS):
            return "forge", "Forge launch flags in /sdapi/v1/cmd-flags"
        if "use_ipex" in flags and "backend" in flags:
            return "sdnext", "SD.Next launch flags in /sdapi/v1/cmd-flags"
    return "a1111", "/sdapi/v1 API"


def detect_backend(url: str | None, **options) -> Detection:
    """
    Identify the WebUI at url. options are ConnectionOptions fields (username, password, token, ...).

    Raises:
        BackendUnavailable: Nothing answers at that address.
        BackendAuthError: Something answered but refused the login, and no probe got through.
        ValueError: Not an http(s) URL.
    """
    options = {**options, "retries": 0}
    probe = _Probe(url=url, **options)
    detection = Detection(None)
    refused = None

    probes = (
        ("comfyui", "GET", "/system_stats", {}, lambda r: isinstance(r, dict) and "system" in r and "devices" in r),
        ("invokeai", "GET", "/api/v1/app/version", {}, lambda r: isinstance(r, dict) and "version" in r),
        ("swarmui", "POST", "/API/GetNewSession", {"json": {}},
         lambda r: isinstance(r, dict) and ("session_id" in r or "error_id" in r)),
        ("a1111", "GET", "/sdapi/v1/samplers", {}, lambda r: isinstance(r, list)),
    )
    for kind, method, path, kwargs, matches in probes:
        detection.tried.append(f"{method} {path}")
        try:
            answer = _json(probe, method, path, **kwargs)
        except BackendAuthError as e:
            refused = refused or e
            continue
        except BackendUnavailable:
            raise
        except BackendRejected:
            continue
        if not matches(answer):
            continue
        if kind == "a1111":
            kind, detection.evidence = _a1111_variant(probe)
        else:
            detection.evidence = f"{method} {path}"
        detection.kind = kind
        log.info(f"Detected {kind} at {probe.get_url()} ({detection.evidence})")
        return detection

    if refused is not None:
        raise refused
    return detection
