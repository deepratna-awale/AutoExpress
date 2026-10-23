"""Transport behaviour (retries, timeouts, auth, typed errors) against a real local HTTP server."""

import base64
import json
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from autoexpress_core import build_expression_payload
from autoexpress_core.backends.a1111_api import A1111Client
from autoexpress_core.backends.base import (
    BackendAuthError,
    BackendTimeout,
    BackendUnavailable,
    normalize_url,
    split_credentials,
)
from autoexpress_core.images import pil_to_b64


class FakeA1111(BaseHTTPRequestHandler):
    """A tiny A1111 API. Behaviour is driven by class attributes set per test."""

    flaky_503 = 0  # answer 503 this many times first
    delay = 0.0
    require_auth = None  # "user:pass"
    seen_auth = []
    hits = {}
    options = {}

    def log_message(self, *args):
        pass

    def _send(self, status, body):
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _route(self):
        cls = type(self)
        cls.hits[self.path] = cls.hits.get(self.path, 0) + 1
        cls.seen_auth.append(self.headers.get("Authorization"))
        if cls.require_auth:
            expected = "Basic " + base64.b64encode(cls.require_auth.encode()).decode()
            if self.headers.get("Authorization") != expected:
                return self._send(401, {"detail": "Incorrect username or password"})
        if cls.flaky_503:
            cls.flaky_503 -= 1
            return self._send(503, {"detail": "busy"})
        if cls.delay:
            time.sleep(cls.delay)
        path = self.path.split("?")[0]
        if path == "/sdapi/v1/samplers":
            return self._send(200, [{"name": "Euler a"}])
        if path == "/sdapi/v1/sd-models":
            return self._send(200, [{"model_name": "anything-v5"}])
        if path == "/sdapi/v1/script-info":
            return self._send(200, [{"name": "adetailer", "is_alwayson": True, "is_img2img": True}])
        if path == "/sdapi/v1/progress":
            if "pass=idle" in self.path:  # counters left over from the previous job
                return self._send(200, {"progress": 0, "eta_relative": 0, "state": {"job": "", "sampling_step": 0, "sampling_steps": 16}})
            if "pass=base" in self.path:
                return self._send(200, {"progress": 1.0, "eta_relative": -0.01, "state": {"job": "scripts_img2img", "job_count": 1, "job_no": 1, "sampling_step": 0, "sampling_steps": 1}})
            # Captured from A1111 1.10.1 + ADetailer 26.2.0 during the ADetailer pass
            return self._send(200, {"progress": 0.771, "eta_relative": 3.01, "state": {"job": "scripts_img2img", "job_count": 2, "job_no": 1, "sampling_step": 12, "sampling_steps": 23}})
        if path == "/sdapi/v1/options":
            return self._send(200, cls.options)
        if path == "/sdapi/v1/cmd-flags":
            return self._send(200, {"api_auth": None})
        if path == "/sdapi/v1/img2img":
            length = int(self.headers.get("Content-Length", 0))
            json.loads(self.rfile.read(length))
            image = pil_to_b64(Image.new("RGB", (8, 8)), data_uri=False)
            return self._send(200, {"images": [image], "info": json.dumps({"infotexts": ["smile"]})})
        return self._send(404, {"detail": "Not Found"})

    do_GET = _route
    do_POST = _route


@pytest.fixture
def server():
    FakeA1111.flaky_503 = 0
    FakeA1111.delay = 0.0
    FakeA1111.require_auth = None
    FakeA1111.seen_auth = []
    FakeA1111.hits = {}
    FakeA1111.options = {}
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeA1111)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture
def payload():
    return build_expression_payload(pil_to_b64(Image.new("RGB", (8, 8))), {"ad_prompt": "1girl"}, "smile")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_end_to_end_img2img_keeps_infotext(server, payload):
    backend = A1111Client(url=server)
    assert backend.check_ready() == (True, "ok")
    image = backend.img2img(payload)
    assert image.size == (8, 8) and image.info["parameters"] == "smile"


def test_reads_are_retried_on_503(server):
    FakeA1111.flaky_503 = 2
    backend = A1111Client(url=server, retries=2)
    assert backend.models == ["anything-v5"]
    assert FakeA1111.hits["/sdapi/v1/sd-models"] == 3


def test_generation_posts_are_not_retried(server, payload):
    backend = A1111Client(url=server, retries=3)
    backend.alwayson_scripts()  # cached, so the 503 below hits img2img
    FakeA1111.flaky_503 = 1
    assert backend.img2img(payload) is None
    assert FakeA1111.hits["/sdapi/v1/img2img"] == 1
    assert backend.last_error.code == "backend_rejected"


def test_unreachable_server_is_a_typed_error(payload):
    backend = A1111Client(url=f"http://127.0.0.1:{free_port()}", retries=0, connect_timeout=1)
    ok, message = backend.check_ready()
    assert not ok and "Could not reach" in message
    assert isinstance(backend.last_error, BackendUnavailable)
    assert backend.img2img(payload) is None and isinstance(backend.last_error, BackendUnavailable)
    assert backend.models == []
    health = backend.health()
    assert health["ready"] is False and health["error"]["code"] == "backend_unavailable"


def test_read_timeout_is_a_typed_error(server):
    FakeA1111.delay = 1.0
    backend = A1111Client(url=server, timeout=0.2, retries=0)
    with pytest.raises(BackendTimeout):
        backend._get_json("/sdapi/v1/samplers")


def test_basic_auth_from_url_and_options(server):
    # Throwaway credentials made up per run, only known to this fake server.
    user, password = "tester", secrets.token_hex(8)
    FakeA1111.require_auth = f"{user}:{password}"
    scheme, host = server.split("//")

    backend = A1111Client(url=f"{scheme}//{FakeA1111.require_auth}@{host}")
    assert backend.get_url() == server  # credentials are not kept in the URL
    assert backend.models == ["anything-v5"]

    backend = A1111Client(url=server, username=user, password=password)
    assert backend.check_ready()[0]

    backend = A1111Client(url=server, username=user, password=secrets.token_hex(8), retries=0)
    with pytest.raises(BackendAuthError):
        backend._get_json("/sdapi/v1/samplers")
    ok, message = backend.check_ready()
    assert not ok and backend.last_error.code == "backend_auth"


def test_bearer_token_header(server):
    A1111Client(url=server, token="abc").models
    assert "Bearer abc" in FakeA1111.seen_auth


def test_progress_and_health(server):
    backend = A1111Client(url=server)
    assert backend.progress() == {"fraction": 0.5217, "eta": 3.0, "step": 12, "steps": 23}
    path = backend._endpoints["progress"]
    backend._endpoints["progress"] = path + "?pass=base"
    assert backend.progress() == {"fraction": 0.0, "eta": None, "step": 0, "steps": 0}
    backend._endpoints["progress"] = path + "?pass=idle"
    assert backend.progress() is None
    backend._endpoints["progress"] = path
    health = backend.health()
    assert health["ready"] and health["info"]["alwayson_scripts"] == ["adetailer"]


def test_url_helpers():
    assert split_credentials("https://u:p%40ss@host:7860/x") == ("https://host:7860/x", "u", "p@ss")
    assert normalize_url("host:7860/", "http://d") == "http://host:7860"
    with pytest.raises(ValueError):
        normalize_url("ftp://host", "http://d")


def test_civitai_key_from_the_webui_extension(server):
    key = secrets.token_hex(8)
    FakeA1111.options = {"ch_civiai_api_key": key, "sd_model_checkpoint": "anything-v5"}
    sources = dict(A1111Client(url=server).civitai_key_sources())
    assert sources == {"Civitai Browser+": None, "Civitai Helper": key}
