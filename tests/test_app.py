"""The standalone Flask app: routes, validation, job queue."""

import io
import threading
import time

import pytest
from PIL import Image

pytest.importorskip("flask")
pytest.importorskip("sd_parsers")

from autoexpress import views  # noqa: E402
from autoexpress_core.backends import registry  # noqa: E402
from autoexpress_core.backends.base import BackendNotReady, RemoteBackend  # noqa: E402
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


def test_backend_not_ready_is_reported(client):
    FakeWebUI.ready = False
    result = client.post("/generate", json=body()).get_json()
    assert result["status"] == "Failed"
    assert result["error"]["code"] == "backend_not_ready" and "ADetailer" in result["message"]


def test_backend_failure_mid_job_is_reported(client):
    FakeWebUI.fail_at = 2
    result = client.post("/generate", json=body()).get_json()
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
