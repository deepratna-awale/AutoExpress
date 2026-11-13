"""
Work out which WebUI is behind a URL from its API, so the user only has to paste the address.

sdmux does the probing: one cheap request per API family (ComfyUI /system_stats, InvokeAI
/api/v1/app/version, SwarmUI /API/GetNewSession, the A1111 /sdapi/v1 API and its Forge / SD.Next
variants). Nothing assumes the WebUI runs on this machine: it works the same for
http://127.0.0.1:7860, a LAN address, or an https RunPod proxy with a sub-path and a login.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import sdmux

from ..log import log
from .base import BackendNotReady, Fix, backend_error, normalize_url, redact_url
from .registry import REMOTE_BACKENDS

# RunPod's HTTP proxy: https://<pod id>-<port>.proxy.runpod.net. It answers on every port, exposed or not.
RUNPOD_PROXY = re.compile(r"^(?P<pod>[a-z0-9]+)-(?P<port>\d+)\.proxy\.runpod\.net$")

# The probes sdmux sends, in order, for the "tried" list of an address that isn't a WebUI.
PROBES = ("GET /system_stats", "GET /api/v1/app/version", "POST /API/GetNewSession", "GET /sdapi/v1/samplers", "GET /sdapi/v1/options")

# Servers sdmux knows that AutoExpress can't drive: they have no face detailer or inpainting route it uses.
UNSUPPORTED = {"drawthings": "Draw Things", "sdcpp": "stable-diffusion.cpp"}


@dataclass
class Detection:
    kind: str | None
    evidence: str = ""
    tried: list[str] = field(default_factory=list)
    # A server sdmux recognised that AutoExpress doesn't support (see UNSUPPORTED).
    unsupported: str | None = None


def detect_backend(url: str | None, **options) -> Detection:
    """
    Identify the WebUI at url. options are ConnectionOptions fields (username, password, token, ...).

    Raises:
        BackendUnavailable: Nothing answers at that address.
        BackendAuthError: Something answered but refused the login, and no probe got through.
        ValueError: Not an http(s) URL.
    """
    url = normalize_url(url, "http://127.0.0.1:7860")
    options = {**options, "retries": 0}
    try:
        found = sdmux.detect(url, **options)
    except sdmux.NotReady:
        return Detection(None, tried=list(PROBES))
    except sdmux.SdmuxError as e:
        raise backend_error(e) from e
    if found.kind in REMOTE_BACKENDS:
        log.info(f"Detected {found.kind} at {redact_url(url)} ({found.evidence})")
        return Detection(found.kind, found.evidence, list(found.tried))
    return Detection(None, found.evidence, list(found.tried), unsupported=UNSUPPORTED.get(found.kind or "", found.kind))


def not_a_webui(url: str | None, detection: Detection) -> BackendNotReady:
    """The error for an address that answers but isn't a supported WebUI, with what to check for that host."""
    host = (urlsplit(url if url and "://" in url else f"http://{url or ''}").hostname or "").lower()
    runpod = RUNPOD_PROXY.match(host)
    if runpod:
        port = runpod["port"]
        error = BackendNotReady(
            f"RunPod's proxy answers at {host}, but nothing behind it is a WebUI. Port {port} is probably not "
            "exposed on the pod, or the WebUI on it isn't running."
        )
        error.fix = Fix(
            [
                f"In RunPod, open the pod, choose Edit Pod, and add {port} to Expose HTTP Ports. Save; the pod restarts.",
                f"Check that the WebUI on the pod listens on port {port} on all interfaces "
                "(--listen for A1111/Forge/SD.Next, --listen 0.0.0.0 for ComfyUI).",
                "Or use the port the pod's Connect menu lists for the WebUI, e.g. 7860 (A1111/Forge) or 8188 (ComfyUI).",
            ],
            links=[Fix.link("RunPod: expose ports", "https://docs.runpod.io/pods/configuration/expose-ports")],
        )
        return error
    if detection.unsupported:
        error = BackendNotReady(
            f"{detection.unsupported} answers at {redact_url(url or 'that address')}, but AutoExpress can't drive it: "
            "it has no face inpainting route AutoExpress uses."
        )
        error.fix = Fix(["Use AUTOMATIC1111, Forge/reForge, SD.Next, ComfyUI, SwarmUI or InvokeAI 5+ instead."])
        return error
    error = BackendNotReady(
        f"Something answers at {redact_url(url or 'that address')}, but not a WebUI AutoExpress supports "
        f"(tried {', '.join(detection.tried)})."
    )
    error.fix = Fix(
        [
            "Check the address, including the port and any sub-path a reverse proxy puts the WebUI under.",
            "A1111, Forge and reForge only serve their API when started with --api.",
            "Supported: AUTOMATIC1111, Forge/reForge, SD.Next, ComfyUI, SwarmUI and InvokeAI 5+.",
        ],
        ["--api"],
    )
    return error
