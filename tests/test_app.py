"""The standalone Flask app: routes, validation, job queue."""

import io
import secrets
import threading
import time

import pytest
from PIL import Image

pytest.importorskip("flask")
pytest.importorskip("sd_parsers")

from autoexpress import views  # noqa: E402
from autoexpress_core.backends import registry  # noqa: E402
from autoexpress_core.backends.base import BackendNotReady, BackendUnavailable, RemoteBackend  # noqa: E402
from autoexpress_core.images import pil_to_b64  # noqa: E402


class FakeWebUI(RemoteBackend):
    kind = "fake"
    label = "Fake WebUI"
    default_url = "http://fake:1"

    delay = 0.0
    fail_at = None
    ready = True
    started = threading.Event()
    calls = 0
    civitai_key = None

    def ensure_ready(self):
        if not FakeWebUI.ready:
            raise BackendNotReady("Fake WebUI has no ADetailer.")

    @property
    def models(self):
        return ["model-a"]

    def img2img(self, payload):
        FakeWebUI.calls += 1
        FakeWebUI.started.set()
        deadline = time.monotonic() + FakeWebUI.delay
        while time.monotonic() < deadline and not getattr(self, "_stop", False):
            time.sleep(0.01)
        if getattr(self, "_stop", False):
            return None
        if FakeWebUI.fail_at == FakeWebUI.calls:
            return self._fail(BackendNotReady("boom"))
        return Image.new("RGB", (16, 16), (FakeWebUI.calls * 10 % 255, 0, 0))

    def interrupt(self):
        self._stop = True

    def progress(self):
        return {"fraction": 0.5, "eta": None}

    def civitai_key_sources(self):
        return [("Fake Civitai extension", FakeWebUI.civitai_key)]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setitem(registry.REMOTE_BACKENDS, "fake", FakeWebUI)
    monkeypatch.setattr(views.settings, "output_dir", tmp_path / "out")
    monkeypatch.setattr(views.settings, "upload_dir", tmp_path / "up")
    (tmp_path / "out").mkdir()
    (tmp_path / "up").mkdir()
    monkeypatch.setitem(views.autoexpress.config, "UPLOAD_FOLDER", str(tmp_path / "up"))
    monkeypatch.setitem(views.lora_settings, "enabled", False)
    FakeWebUI.delay, FakeWebUI.fail_at, FakeWebUI.ready, FakeWebUI.calls = 0.0, None, True, 0
    FakeWebUI.started = threading.Event()
    FakeWebUI.civitai_key = None
    views.state.connect("fake", None)
    yield views.autoexpress.test_client()
    views.jobs.cancel_all()
    views.state.connect("a1111", None)


def body(**overrides):
    data = {
        "init_images": pil_to_b64(Image.new("RGB", (32, 32))),
        "output_dir": "Alice",
        "ad_prompt": "1girl",
        "ad_steps": "20",
        "seed": "-1",
        "loras": [],
        "expressions": ["joy", "anger"],
    }
    data.update(overrides)
    return data


def wait_for(client, job_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = client.get(f"/jobs/{job_id}").get_json()
        if job["status"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def test_health_backends_and_status(client):
    assert client.get("/health").get_json()["status"] == "ok"
    backends = client.get("/backends").get_json()
    assert backends["selected"] == "fake"
    status = client.get("/backend/status").get_json()
    assert status["ready"] is True and status["backend"] == "fake"
    assert client.get("/get-models").get_json() == ["model-a"]
    assert client.get("/health").headers["X-Request-ID"]


def test_receive_data_validates(client):
    assert client.post("/receive_data", json={"text": "", "backend": "nope"}).status_code == 400
    assert client.post("/receive_data", json={"text": "ftp://x", "backend": "fake"}).status_code == 400
    assert client.post("/receive_data", json={"text": "u:p@host:9", "backend": "fake"}).status_code == 200
    backend = views.current_backend()
    assert backend.get_url() == "http://host:9" and backend.session.auth == ("u", "p")


def test_generate_waits_by_default_and_saves_files(client, tmp_path):
    result = client.post("/generate", json=body()).get_json()
    assert result["status"] == "success"
    assert result["job"]["progress"]["done"] == 2
    assert sorted(p.name for p in (tmp_path / "out" / "Alice").iterdir()) == ["anger.png", "joy.png"]
    assert client.get("/images/Alice").get_json() == ["anger.png", "joy.png"]
    assert client.get("/image/Alice/joy.png").status_code == 200


def test_generate_async_job_progress_and_cancel(client):
    FakeWebUI.delay = 5
    response = client.post("/generate", json=body(wait=False))
    assert response.status_code == 202
    job_id = response.get_json()["job_id"]
    assert FakeWebUI.started.wait(5)

    job = client.get(f"/jobs/{job_id}").get_json()
    assert job["status"] == "running"
    assert job["progress"]["current"] == "anger" and job["progress"]["step"] == {"fraction": 0.5, "eta": None}
    assert job["progress"]["fraction"] == 0.25

    assert client.post(f"/jobs/{job_id}/cancel").status_code in (200, 202)
    assert wait_for(client, job_id)["status"] == "cancelled"


def test_jobs_run_one_at_a_time(client):
    FakeWebUI.delay = 0.05
    first = client.post("/generate", json=body(wait=False, output_dir="A")).get_json()["job_id"]
    second = client.post("/generate", json=body(wait=False, output_dir="B")).get_json()["job_id"]
    a, b = wait_for(client, first), wait_for(client, second)
    assert a["status"] == b["status"] == "completed"
    assert a["finished_at"] <= b["started_at"]
    assert [j["id"] for j in client.get("/jobs").get_json()["jobs"]][:2] == [second, first]


def test_backend_not_ready_is_reported_before_queueing(client):
    FakeWebUI.ready = False
    before = len(client.get("/jobs").get_json()["jobs"])
    response = client.post("/generate", json=body(wait=False))
    assert response.status_code == 409
    result = response.get_json()
    assert result["status"] == "Failed"
    assert result["error"]["code"] == "backend_not_ready" and "ADetailer" in result["message"]
    assert FakeWebUI.calls == 0 and len(client.get("/jobs").get_json()["jobs"]) == before


def test_unreachable_backend_fails_fast_behind_a_running_job(client, monkeypatch):
    FakeWebUI.delay = 5
    running = client.post("/generate", json=body(wait=False)).get_json()["job_id"]
    assert FakeWebUI.started.wait(5)

    def unreachable(self):
        raise BackendUnavailable("Could not reach Fake WebUI.")

    monkeypatch.setattr(FakeWebUI, "ensure_ready", unreachable)
    started = time.monotonic()
    response = client.post("/generate", json=body())
    assert response.status_code == 503 and response.get_json()["error"]["code"] == "backend_unavailable"
    assert time.monotonic() - started < 2
    client.post(f"/jobs/{running}/cancel")


def test_backend_failure_mid_job_is_reported(client):
    FakeWebUI.fail_at = 2
    response = client.post("/generate", json=body())
    assert response.status_code == 409  # the job failed with BackendNotReady
    result = response.get_json()
    assert result["status"] == "Failed" and result["message"] == "boom"
    assert result["job"]["progress"]["done"] == 1


@pytest.mark.parametrize(
    "overrides, field",
    [
        ({"init_images": "not an image"}, "init_images"),
        ({"ad_steps": "lots"}, "ad_steps"),
        ({"ad_denoising_strength": 3}, "ad_denoising_strength"),
        ({"loras": [{"lora_name": "<evil>", "lora_strength": 1}]}, "loras"),
        ({"expressions": "joy"}, "expressions"),
    ],
)
def test_generate_rejects_bad_input(client, overrides, field):
    response = client.post("/generate", json=body(**overrides))
    assert response.status_code == 400
    assert field in response.get_json()["error"]["fields"]


def test_output_dir_cannot_escape(client, tmp_path):
    result = client.post("/generate", json=body(output_dir="../../etc")).get_json()
    assert result["status"] == "success"
    assert result["job"]["output_dir"] == "etc"
    assert (tmp_path / "out" / "etc" / "joy.png").exists()
    assert client.get("/images/../../").status_code in (400, 404)
    assert client.get("/images/..%2f..%2f").status_code in (400, 404)


def test_upload_rejects_non_images(client):
    response = client.post("/upload", data={"file": (io.BytesIO(b"not a png"), "x.png")}, content_type="multipart/form-data")
    assert response.status_code == 400

    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG")
    buffer.seek(0)
    response = client.post("/upload", data={"file": (buffer, "キャラ.png")}, content_type="multipart/form-data")
    assert response.status_code == 200 and response.get_json()["width"] == 8


def test_unknown_job_is_404_json(client):
    response = client.get("/jobs/nope")
    assert response.status_code == 404 and response.get_json()["error"]["code"] == "not_found"


def test_interrupt_cancels_running_job(client):
    FakeWebUI.delay = 5
    job_id = client.post("/generate", json=body(wait=False)).get_json()["job_id"]
    assert FakeWebUI.started.wait(5)
    assert client.post("/interrupt").get_json() is True
    assert wait_for(client, job_id)["status"] == "cancelled"


def test_civitai_key_comes_from_the_webui_unless_typed_in(client, monkeypatch):
    for name in ("CIVITAI_API_KEY", "CIVITAI_API_TOKEN", "CIVITAI_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(views.lora_settings, "civitai_api_key", "")
    assert client.get("/expression-loras").get_json()["civitai_key_source"] is None

    FakeWebUI.civitai_key = secrets.token_hex(8)
    assert views.civitai_key_for(views.current_backend()) == (FakeWebUI.civitai_key, "Fake Civitai extension")
    assert client.get("/expression-loras").get_json()["civitai_key_source"] == "Fake Civitai extension"

    typed = secrets.token_hex(8)
    monkeypatch.setitem(views.lora_settings, "civitai_api_key", typed)
    assert views.civitai_key_for(views.current_backend()) == (typed, "AutoExpress")


def test_auto_detects_the_webui_and_reports_capabilities(client, monkeypatch):
    from autoexpress_core.backends.detect import Detection

    seen = {}

    def fake_detect(url, **options):
        seen["url"] = url
        return Detection("fake", "GET /fake")

    monkeypatch.setattr(views, "detect_backend", fake_detect)
    response = client.post("/receive_data", json={"text": "https://pod-7860.proxy.example.net/sd", "backend": "auto"})
    assert response.status_code == 200
    assert response.get_json() == {
        "status": "success",
        "backend": "fake",
        "name": "Fake WebUI",
        "url": "https://pod-7860.proxy.example.net/sd",
        "detected": True,
    }
    assert seen["url"] == "https://pod-7860.proxy.example.net/sd"
    assert client.get("/backends").get_json()["backends"][0]["id"] == "auto"

    report = client.get("/backend/capabilities").get_json()
    assert report["ready"] and report["detected"] and report["items"][0]["key"] == "api"

    FakeWebUI.ready = False
    report = client.get("/backend/capabilities").get_json()
    assert not report["ready"] and report["error"] is None and "ADetailer" in report["items"][0]["detail"]


def test_auto_detect_failures_explain_what_to_do(client, monkeypatch):
    from autoexpress_core.backends.base import BackendUnavailable
    from autoexpress_core.backends.detect import Detection

    def unreachable(url, **options):
        raise BackendUnavailable("Could not reach the WebUI.")

    monkeypatch.setattr(views, "detect_backend", unreachable)
    response = client.post("/receive_data", json={"text": "http://10.0.0.5:7860", "backend": "auto"})
    assert response.status_code == 503
    assert "--listen" in " ".join(response.get_json()["error"]["fix"]["steps"])
    assert views.current_backend().kind == "fake"  # still connected to the previous WebUI

    monkeypatch.setattr(views, "detect_backend", lambda url, **options: Detection(None, tried=["GET /x"]))
    response = client.post("/receive_data", json={"text": "http://10.0.0.5:7860", "backend": "auto"})
    assert response.status_code == 409 and "not a WebUI AutoExpress supports" in response.get_json()["message"]
