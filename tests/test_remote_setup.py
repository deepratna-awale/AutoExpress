"""WebUIs hosted anywhere: detecting the WebUI from its API, capability reports with fixes, remote LoRA installs."""

import base64
import json
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from autoexpress.modules import expression_generator
from autoexpress_core import expression_loras
from autoexpress_core.backends.a1111_api import A1111Client
from autoexpress_core.backends.base import BackendAuthError, BackendUnavailable
from autoexpress_core.backends.comfyui_api import ComfyUIClient
from autoexpress_core.backends.detect import detect_backend
from autoexpress_core.backends.invokeai_api import InvokeAIClient

from test_remote_backends import ComfySession, FakeResponse, InvokeSession, comfy_routes, done_history


class FakeWebUI(BaseHTTPRequestHandler):
    """Answers "METHOD /path" from routes (status, body), optionally under a sub-path and behind basic auth."""

    routes = {}
    prefix = ""
    login = None

    def log_message(self, *args):
        pass

    def _route(self):
        cls = type(self)
        if cls.login:
            expected = "Basic " + base64.b64encode(cls.login.encode()).decode()
            if self.headers.get("Authorization") != expected:
                return self._send(401, {"detail": "Not authenticated"})
        path = self.path.split("?")[0]
        if not path.startswith(cls.prefix):
            return self._send(404, {"detail": "Not Found"})
        status, body = cls.routes.get(f"{self.command} {path[len(cls.prefix):]}", (404, {"detail": "Not Found"}))
        return self._send(status, body)

    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = _route

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        return self._route()


@pytest.fixture
def webui():
    FakeWebUI.routes, FakeWebUI.prefix, FakeWebUI.login = {}, "", None
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeWebUI)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


SAMPLERS = (200, [{"name": "Euler a"}])


@pytest.mark.parametrize(
    "routes, kind",
    [
        ({"GET /system_stats": (200, {"system": {"comfyui_version": "0.42.0"}, "devices": []})}, "comfyui"),
        ({"GET /api/v1/app/version": (200, {"version": "5.6.0"})}, "invokeai"),
        ({"POST /API/GetNewSession": (200, {"session_id": "s", "version": "0.9"})}, "swarmui"),
        ({"GET /sdapi/v1/samplers": SAMPLERS, "GET /sdapi/v1/cmd-flags": (200, {"api": True})}, "a1111"),
        ({"GET /sdapi/v1/samplers": SAMPLERS, "GET /sdapi/v1/cmd-flags": (200, {"pin_shared_memory": False})}, "forge"),
        ({"GET /sdapi/v1/samplers": SAMPLERS, "GET /sdapi/v1/version": (200, {"app": "sd.next"})}, "sdnext"),
    ],
)
def test_detects_each_webui_from_its_api(webui, routes, kind):
    FakeWebUI.routes = routes
    assert detect_backend(webui).kind == kind


def test_detects_behind_a_sub_path_and_a_login(webui):
    user, password = "tester", secrets.token_hex(8)
    FakeWebUI.routes = {"GET /system_stats": (200, {"system": {}, "devices": []})}
    FakeWebUI.prefix, FakeWebUI.login = "/comfy", f"{user}:{password}"

    assert detect_backend(f"{webui}/comfy/", username=user, password=password).kind == "comfyui"
    with pytest.raises(BackendAuthError):
        detect_backend(f"{webui}/comfy")

    # The detected backend keeps the sub-path for every request
    backend = ComfyUIClient(url=f"{webui}/comfy", username=user, password=password)
    assert backend.get_url().endswith("/comfy") and backend.server_info()["devices"] == []


def test_unknown_and_unreachable(webui):
    detection = detect_backend(webui)
    assert detection.kind is None and "GET /sdapi/v1/samplers" in detection.tried

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    with pytest.raises(BackendUnavailable):
        detect_backend(f"http://127.0.0.1:{port}", connect_timeout=1)


# Capabilities ------------------------------------------------------------------
def a1111_routes(adetailer=True, face_models=("face_yolov8n.pt",)):
    scripts = [{"name": "adetailer", "is_alwayson": True, "is_img2img": True}] if adetailer else []
    return {
        "GET /sdapi/v1/samplers": SAMPLERS,
        "GET /sdapi/v1/sd-models": (200, [{"model_name": "anything-v5"}]),
        "GET /sdapi/v1/script-info": (200, scripts),
        "GET /sdapi/v1/extensions": (200, []),
        "GET /sdapi/v1/loras": (200, []),
        "GET /sdapi/v1/cmd-flags": (200, {"lora_dir": "/workspace/not/here"}),
        "GET /adetailer/v1/ad_model": (200, {"ad_model": list(face_models) + ["hand_yolov8n.pt"]}),
    }


def items(report):
    return {item["key"]: item for item in report["items"]}


def test_a1111_ready_report(webui):
    FakeWebUI.routes = a1111_routes()
    report = A1111Client(url=webui).check_capabilities()
    assert report["ready"] and report["missing"] == []
    found = items(report)
    assert found["face_model"]["ok"] and "face_yolov8n.pt" in found["face_model"]["detail"]
    # The WebUI's LoRA folder isn't on this machine: optional, with what to do instead
    assert not found["lora_folder"]["ok"] and not found["lora_folder"]["required"]
    assert found["lora_folder"]["fix"]["steps"]


def test_a1111_missing_adetailer_says_how_to_install_it(webui):
    FakeWebUI.routes = a1111_routes(adetailer=False)
    report = A1111Client(url=webui).check_capabilities()
    assert not report["ready"] and report["missing"] == ["ADetailer extension"]
    fix = items(report)["adetailer"]["fix"]
    assert "Install from URL" in " ".join(fix["steps"]) and fix["commands"] == ["https://github.com/Bing-su/adetailer"]


def test_a1111_without_api_says_to_add_the_flag(webui):
    report = A1111Client(url=webui).check_capabilities()
    assert not report["ready"] and items(report)["api"]["fix"]["commands"] == ["--api"]


def test_unreachable_and_refused_reports(webui):
    FakeWebUI.login = "someone:" + secrets.token_hex(8)
    report = A1111Client(url=webui, retries=0).check_capabilities()
    assert report["error"]["code"] == "backend_auth"
    assert "username" in " ".join(items(report)["api"]["fix"]["steps"])

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    report = A1111Client(url=f"http://127.0.0.1:{port}", retries=0, connect_timeout=1).check_capabilities()
    assert report["error"]["code"] == "backend_unavailable"
    assert "proxy.runpod.net" in " ".join(items(report)["api"]["fix"]["steps"])


def test_comfyui_report_lists_missing_custom_nodes():
    routes = comfy_routes(done_history())
    routes["GET /system_stats"] = {"system": {"argv": ["/far/away/ComfyUI/main.py"]}, "devices": []}
    del routes["GET /object_info/FaceDetailer"]
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(routes)

    report = backend.check_capabilities()
    assert report["missing"] == ["ComfyUI Impact Pack (FaceDetailer)"]
    fix = items(report)["impact_pack"]["fix"]
    assert fix["commands"][0] == "git clone https://github.com/ltdrdata/ComfyUI-Impact-Pack"
    assert "Custom Nodes Manager" in fix["steps"][0]
    assert items(report)["face_model"]["ok"]
    assert backend.lora_dir is None  # /far/away is not on this machine


def test_comfyui_report_asks_for_a_face_model():
    routes = comfy_routes(done_history())
    routes["GET /system_stats"] = {"system": {}, "devices": []}
    routes["GET /object_info/UltralyticsDetectorProvider"] = {
        "UltralyticsDetectorProvider": {"input": {"required": {"model_name": [["bbox/hand_yolov8n.pt"]]}}}
    }
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(routes)
    fix = items(backend.check_capabilities())["face_model"]["fix"]
    assert fix["commands"][0].startswith("wget -P models/ultralytics/bbox ")


# Expression LoRAs on WebUIs whose folder isn't on this machine ------------------
class RemoteWebUI:
    label = "Remote WebUI"
    lora_dir = None

    def __init__(self, can_install=False):
        self.installed = []
        self.can_install = can_install
        self.install_calls = []

    @property
    def loras(self):
        return list(self.installed)

    lora_stems = loras

    def refresh_loras(self):
        return True

    def can_install_models(self):
        return self.can_install

    def install_lora(self, url, name, access_token=None):
        self.install_calls.append((url, name, access_token))
        self.installed.append(name)
        return True


def test_missing_loras_become_notes_with_download_links(monkeypatch):
    monkeypatch.setattr(expression_loras, "download_lora", lambda *a, **k: pytest.fail("must not write locally"))
    notes = []
    prompt = expression_generator.get_expression_lora_prompt(RemoteWebUI(), "ponyDiffusionV6XL", "auto", notes=notes)
    assert prompt == ""
    assert notes and notes[0]["kind"] == "missing_lora"
    assert notes[0]["url"].startswith("https://civitai.com/models/") and "Remote WebUI" in notes[0]["message"]


def test_webuis_that_can_install_get_the_loras_through_their_api():
    key = secrets.token_hex(8)
    webui = RemoteWebUI(can_install=True)
    notes = []
    prompt = expression_generator.get_expression_lora_prompt(webui, "ponyDiffusionV6XL", "auto", civitai_api_key=key, notes=notes)
    assert notes == [] and "<lora:AutoExpress-expressions-pony:" in prompt
    url, name, token = webui.install_calls[0]
    assert url.startswith("https://civitai.com/api/download/models/") and token == key


def test_invokeai_installs_a_lora_through_the_model_manager():
    backend = InvokeAIClient(poll_interval=0)
    session = InvokeSession({})
    jobs = iter([{"id": 3, "status": "downloading"}, {"id": 3, "status": "completed"}])

    def request(method, url, timeout=None, **kwargs):
        path = "/" + url.split("/", 3)[3]
        session.calls.append((method, path, kwargs))
        if path == "/api/v2/models/install":
            return FakeResponse({"id": 3, "status": "waiting"}, 201)
        if path == "/api/v2/models/install/3":
            return FakeResponse(next(jobs))
        return FakeResponse({"detail": "Not Found"}, 404)

    session.request = request
    backend.session = session
    key = secrets.token_hex(8)
    assert backend.can_install_models() and backend.install_lora("https://civitai.com/api/download/models/1", "x", key)
    method, path, kwargs = session.calls[0]
    assert kwargs["params"] == {"source": "https://civitai.com/api/download/models/1", "inplace": "false", "access_token": key}
    assert kwargs["json"] == {"name": "x"}
