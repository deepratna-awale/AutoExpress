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
from autoexpress_core import background  # noqa: E402
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


def wait_for(client, job_id, timeout=120):
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


class FakeEditWebUI(FakeWebUI):
    kind = "fake_edit"
    edit_methods = ("inpaint", "instruct")
    instructions = []

    def ensure_edit_ready(self):
        if not FakeWebUI.ready:
            raise BackendNotReady("Fake WebUI has no Qwen-Image-Edit.")

    def instruction_edit(self, image, instruction, settings):
        FakeEditWebUI.instructions.append((instruction, settings.seed))
        return Image.new("RGB", (16, 16))


def test_edit_methods_follow_the_backend(client, monkeypatch):
    methods = client.get("/edit-methods").get_json()
    assert {m["id"]: m["available"] for m in methods["methods"]} == {"inpaint": True, "instruct": False}
    assert "24 GB" in methods["vram_note"]

    response = client.post("/generate", json=body(method="instruct"))
    assert response.status_code == 400 and "ComfyUI" in response.get_json()["error"]["fields"]["method"]
    assert client.post("/generate", json=body(method="nope")).status_code == 400

    monkeypatch.setitem(registry.REMOTE_BACKENDS, "fake_edit", FakeEditWebUI)
    views.state.connect("fake_edit", None)
    assert all(m["available"] for m in client.get("/edit-methods").get_json()["methods"])


def test_generate_with_instruction_edit(client, monkeypatch, tmp_path):
    monkeypatch.setitem(registry.REMOTE_BACKENDS, "fake_edit", FakeEditWebUI)
    monkeypatch.setitem(views.lora_settings, "enabled", True)
    FakeEditWebUI.instructions = []
    views.state.connect("fake_edit", None)

    result = client.post("/generate", json=body(method="instruct", seed="9", expressions=["joy", "sadness"])).get_json()
    assert result["status"] == "success" and result["job"]["method"] == "instruct"
    assert FakeWebUI.calls == 0  # no inpainting
    assert [text.split(". ")[1].split(":")[0] for text, _ in FakeEditWebUI.instructions] == ["The character is overjoyed", "The character is sad"]
    assert {seed for _, seed in FakeEditWebUI.instructions} == {9}
    assert sorted(p.name for p in (tmp_path / "out" / "Alice").iterdir()) == ["joy.png", "sadness.png"]

    FakeWebUI.ready = False
    response = client.post("/generate", json=body(method="instruct"))
    assert response.status_code == 409 and "Qwen-Image-Edit" in response.get_json()["message"]


def test_generate_with_poses(client, monkeypatch, tmp_path):
    response = client.post("/generate", json=body(pose=True))
    assert response.status_code == 400 and "ComfyUI" in response.get_json()["error"]["fields"]["pose"]
    assert client.post("/generate", json=body(pose="yes")).status_code == 400

    monkeypatch.setitem(registry.REMOTE_BACKENDS, "fake_edit", FakeEditWebUI)
    FakeEditWebUI.instructions = []
    views.state.connect("fake_edit", None)
    result = client.post("/generate", json=body(method="instruct", pose=True, expressions=["anger"])).get_json()
    assert result["status"] == "success"
    assert "Both hands are balled into loose fists" in FakeEditWebUI.instructions[0][0]

    # Face inpainting poses with Qwen first, then inpaints the face.
    FakeEditWebUI.instructions, calls = [], FakeWebUI.calls
    result = client.post("/generate", json=body(method="inpaint", pose=True, expressions=["anger"])).get_json()
    assert result["status"] == "success" and FakeWebUI.calls == calls + 1
    assert FakeEditWebUI.instructions[0][0].startswith("Change only the pose.")


def test_generate_rejects_unknown_edit_style_or_intensity(client):
    response = client.post("/generate", json=body(edit_style="sketch", expression_intensity="1.5"))
    fields = response.get_json()["error"]["fields"]
    assert response.status_code == 400 and set(fields) == {"edit_style", "expression_intensity"}


def test_expression_defaults_follow_the_checkpoint(client):
    realistic = client.get("/expression-defaults?checkpoint=juggernautXL_v9.safetensors&family=sdxl_base").get_json()
    assert realistic["family"] == "sdxl_base" and realistic["defaults"]["edit_style"] == "photo"
    anime = client.get("/expression-defaults?checkpoint=animagine-xl-3.1.safetensors&family=auto").get_json()
    assert anime["family"] == "danbooru" and anime["defaults"]["intensity"] == 0.5
    assert client.get("/expression-defaults?family=nope").status_code == 400


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
        "login": {"username": None, "password": False, "token": False, "headers": []},
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
    assert "--api" in response.get_json()["error"]["fix"]["commands"]

    # RunPod's proxy answers on ports the pod doesn't expose
    response = client.post("/receive_data", json={"text": "https://abc123xyz-7999.proxy.runpod.net", "backend": "auto"})
    fix = response.get_json()["error"]["fix"]
    assert response.status_code == 409 and fix["steps"][0].startswith("In RunPod, open the pod")
    assert "add 7999 to Expose HTTP Ports" in fix["steps"][0]


def test_generate_without_method_uses_the_family_default(client, monkeypatch):
    monkeypatch.setitem(registry.REMOTE_BACKENDS, "fake_edit", FakeEditWebUI)
    monkeypatch.setattr(views, "model_family", "sdxl_base")
    views.state.connect("fake_edit", None)
    FakeEditWebUI.instructions = []
    result = client.post("/generate", json=body(expressions=["joy"])).get_json()
    assert result["job"]["method"] == "instruct" and FakeEditWebUI.instructions[0][0].startswith("smiling. Keep it a realistic photo")

    views.state.connect("fake", None)  # no edit mode: falls back to inpainting
    assert client.post("/generate", json=body(expressions=["joy"])).get_json()["job"]["method"] == "inpaint"


def test_generate_can_remove_backgrounds(client, tmp_path, monkeypatch):
    models = []

    def cut_out(image, model):
        models.append(model)
        result = image.convert("RGBA")
        result.putalpha(0)
        return result

    monkeypatch.setattr(background, "available", lambda: True)
    monkeypatch.setattr(background, "remove_background", cut_out)
    info = client.get("/background-removal").get_json()
    assert info["available"] is True and info["models"]["illustration"] == background.ILLUSTRATION_MODEL

    result = client.post("/generate", json=body(remove_background=True)).get_json()
    assert result["status"] == "success"
    assert models == [background.ILLUSTRATION_MODEL] * 2
    with Image.open(tmp_path / "out" / "Alice" / "joy.png") as image:
        assert image.mode == "RGBA" and image.getpixel((0, 0))[3] == 0

    result = client.post("/generate", json=body(output_dir="Bob", edit_style="photo", remove_background=True)).get_json()
    assert result["status"] == "success"
    assert models[-1] == background.PHOTO_MODEL


def test_background_removal_failure_keeps_the_images(client, tmp_path, monkeypatch):
    def broken(image, model):
        raise RuntimeError("no model")

    monkeypatch.setattr(background, "available", lambda: True)
    monkeypatch.setattr(background, "remove_background", broken)
    result = client.post("/generate", json=body(remove_background=True)).get_json()
    assert result["status"] == "success"
    assert [note["kind"] for note in result["job"]["notes"]] == ["background_removal_failed"]
    with Image.open(tmp_path / "out" / "Alice" / "joy.png") as image:
        assert image.mode == "RGB"


def test_remove_background_needs_rembg(client, monkeypatch):
    monkeypatch.setattr(background, "available", lambda: False)
    response = client.post("/generate", json=body(remove_background=True))
    assert response.status_code == 400
    assert "rembg" in response.get_json()["error"]["fields"]["remove_background"]
    assert client.post("/generate", json=body(remove_background="yes")).status_code == 400


# Animated sprites --------------------------------------------------------------
class FakeAnimWebUI(FakeEditWebUI):
    kind = "fake_anim"
    can_animate = True
    prompts = []

    def ensure_animate_ready(self):
        if not FakeWebUI.ready:
            raise BackendNotReady("Fake WebUI has no Wan 2.2.")

    def animate(self, image, prompt, negative, settings):
        FakeAnimWebUI.prompts.append(prompt)
        return [Image.new("RGB", (16, 16), (i * 20, 0, 0)) for i in range(5)]


def card_image(name="Hanabi", description="A playful kunoichi who loves jokes and charming winks."):
    import base64
    import json

    from PIL import PngImagePlugin

    info = PngImagePlugin.PngInfo()
    info.add_text("chara", base64.b64encode(json.dumps({"spec": "chara_card_v2", "data": {"name": name, "description": description}}).encode()).decode())
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


def test_animate_needs_a_backend_that_can(client):
    info = client.get("/animation").get_json()
    assert info["available"] is False and info["formats"] == ["webp", "apng", "gif"] and len(info["motions"]) == 28
    response = client.post("/generate", json=body(animate=True))
    assert response.status_code == 400 and "Wan 2.2" in response.get_json()["error"]["fields"]["animate"]
    assert client.post("/generate", json=body(animate="yes")).status_code == 400


@pytest.mark.parametrize(
    "animation, field",
    [({"frames": 5}, "animation.frames"), ({"formats": ["mp4"]}, "animation.formats"), ({"idle_source": "tarot"}, "animation.idle_source"), ("x", "animation")],
)
def test_animation_settings_are_validated(client, monkeypatch, animation, field):
    monkeypatch.setitem(registry.REMOTE_BACKENDS, "fake_anim", FakeAnimWebUI)
    views.state.connect("fake_anim", None)
    response = client.post("/generate", json=body(animate=True, animation=animation))
    assert response.status_code == 400 and field in response.get_json()["error"]["fields"]


def test_generate_animated_sprites_with_the_idle_from_the_card(client, monkeypatch, tmp_path):
    import base64

    monkeypatch.setitem(registry.REMOTE_BACKENDS, "fake_anim", FakeAnimWebUI)
    FakeAnimWebUI.prompts = []
    views.state.connect("fake_anim", None)
    image = "data:image/png;base64," + base64.b64encode(card_image()).decode()
    result = client.post(
        "/generate", json=body(init_images=image, expressions=["joy", "neutral"], animate=True, animation={"formats": ["webp", "gif"]})
    ).get_json()
    assert result["status"] == "success"
    files = sorted(p.name for p in (tmp_path / "out" / "Alice").iterdir())
    assert files == ["joy.gif", "joy.png", "joy.webp", "neutral.gif", "neutral.png", "neutral.webp"]
    with Image.open(tmp_path / "out" / "Alice" / "joy.webp") as clip:
        assert clip.n_frames == 4  # the repeated loop frame is dropped
    neutral = next(i for i in result["job"]["images"] if i["expression"] == "neutral")
    assert neutral["animation"] == "/image/Alice/neutral.webp" and neutral["animations"]["gif"] == "/image/Alice/neutral.gif"
    assert "Hanabi idles in place" in FakeAnimWebUI.prompts[1] and "wink" in FakeAnimWebUI.prompts[1]
    assert any(note["kind"] == "idle_motion" for note in result["job"]["notes"])


    # A typed idle motion wins over the card.
    FakeAnimWebUI.prompts = []
    client.post("/generate", json=body(init_images=image, expressions=["neutral"], animate=True, animation={"idle_motion": "She stretches."}))
    assert "She stretches." in FakeAnimWebUI.prompts[0]

    # Animate the stills already there, without generating them again.
    FakeAnimWebUI.prompts, calls = [], FakeWebUI.calls
    result = client.post("/animate", json={"output_dir": "Alice", "expressions": ["joy"], "animation": {"formats": ["apng"]}}).get_json()
    assert result["status"] == "success" and FakeWebUI.calls == calls and len(FakeAnimWebUI.prompts) == 1
    assert (tmp_path / "out" / "Alice" / "joy.apng").is_file()
    assert client.post("/animate", json={"output_dir": "Nobody"}).status_code == 400

    FakeWebUI.ready = False
    assert client.post("/generate", json=body(animate=True)).status_code == 409
    response = client.post("/animate", json={"output_dir": "Alice"})
    assert response.status_code == 409 and "Wan 2.2" in response.get_json()["message"]


def test_character_card_route_and_upload(client, monkeypatch):
    import base64

    image = "data:image/png;base64," + base64.b64encode(card_image()).decode()
    result = client.post("/character-card", json={"image": image}).get_json()
    assert result["character"]["name"] == "Hanabi" and result["idle_source"] == "card" and "wink" in result["idle_motion"]
    assert client.post("/character-card", json={"image": image, "idle_source": "astrology"}).status_code == 400
    plain = client.post("/character-card", json={"persona": "A shy, timid girl.", "name": "Mira"}).get_json()
    assert plain["character"]["name"] == "Mira" and "shyly" in plain["idle_motion"]

    uploaded = client.post("/upload", data={"file": (io.BytesIO(card_image()), "hanabi.png")}, content_type="multipart/form-data").get_json()
    assert uploaded["character"]["name"] == "Hanabi"

    assert client.get("/llm-settings").get_json() == {"url": "", "model": "", "has_api_key": False}
    monkeypatch.setitem(views.llm_settings, "url", "")
    assert client.post("/llm-settings", json={"url": "ftp://x"}).status_code == 400
    saved = client.post("/llm-settings", json={"url": "http://127.0.0.1:11434/v1", "model": "llama3", "api_key": "k"}).get_json()
    assert saved == {"url": "http://127.0.0.1:11434/v1", "model": "llama3", "has_api_key": True}
    views.llm_settings.update(url="", model="", api_key="")


def test_animated_instruction_edits_keep_the_mouth_closed(client, monkeypatch):
    monkeypatch.setitem(registry.REMOTE_BACKENDS, "fake_anim", FakeAnimWebUI)
    views.state.connect("fake_anim", None)
    FakeEditWebUI.instructions = []
    assert client.post("/generate", json=body(method="instruct", expressions=["joy"], animate=True)).get_json()["status"] == "success"
    assert "lips pressed together" in FakeEditWebUI.instructions[0][0]
    FakeEditWebUI.instructions = []
    assert client.post("/generate", json=body(method="instruct", expressions=["joy"])).get_json()["status"] == "success"
    assert "wide open smile" in FakeEditWebUI.instructions[0][0]


# Live2D model kits ------------------------------------------------------------
class FakeLayerWebUI(FakeWebUI):
    kind = "fake_layers"
    edit_methods = ("inpaint", "instruct")
    can_decompose = True

    def ensure_decompose_ready(self):
        pass

    def instruction_edit(self, image, instruction, settings):
        from autoexpress_core.images import b64_to_pil

        return b64_to_pil(image).convert("RGB")

    def decompose_layers(self, image, settings):
        from autoexpress_core.live2d.layers import Part

        face = Image.new("RGBA", (settings.resolution, settings.resolution), (0, 0, 0, 0))
        face.paste((250, 220, 200, 255), (300, 200, 700, 700))
        hair = Image.new("RGBA", (settings.resolution, settings.resolution), (0, 0, 0, 0))
        hair.paste((40, 30, 30, 255), (280, 150, 720, 320))
        return [Part("face", face, 0, 0, 0.5), Part("front hair", hair, 0, 0, 0.2)], (settings.resolution, settings.resolution)


def test_live2d_needs_a_backend_that_splits_layers(client):
    info = client.get("/live2d").get_json()
    assert info["available"] is False and not info["ready"] and info["advice"]["best"]
    response = client.post("/live2d", json={"images": [pil_to_b64(Image.new("RGB", (64, 64)))]})
    assert response.status_code == 400 and "See-through" in response.get_json()["error"]["fields"]["backend"]


def test_live2d_validates_the_request(client):
    assert client.post("/live2d", json={"images": []}).status_code == 400
    response = client.post("/live2d", json={"images": ["not an image"], "settings": {"resolution": 99999, "variants": "x"}})
    fields = response.get_json()["error"]["fields"]
    assert response.status_code == 400 and {"images[0]", "resolution", "variants"} <= set(fields)


def test_live2d_check_ranks_pictures(client):
    small = pil_to_b64(Image.new("RGB", (100, 100), (255, 255, 255)))
    big = Image.new("RGB", (1400, 1400), (255, 255, 255))
    big.paste((200, 50, 50), (400, 200, 1000, 1400))
    response = client.post("/live2d/check", json={"images": [small, pil_to_b64(big)]})
    data = response.get_json()
    assert response.status_code == 200 and data["best"] == 1 and len(data["reports"]) == 2


def test_live2d_builds_a_kit_job(client, monkeypatch, tmp_path):
    monkeypatch.setitem(registry.REMOTE_BACKENDS, "fake_layers", FakeLayerWebUI)
    views.state.connect("fake_layers", None)
    assert client.get("/live2d").get_json()["ready"] is True
    picture = Image.new("RGB", (800, 1000), (255, 255, 255))
    picture.paste((250, 220, 200), (250, 200, 550, 600))
    response = client.post("/live2d", json={"images": [pil_to_b64(picture)], "name": "Mira", "settings": {"resolution": 1024}})
    assert response.status_code == 202
    job = wait_for(client, response.get_json()["job_id"])
    assert job["status"] == "completed", job
    kit = job["live2d"]
    assert kit["zip"] == "/image/live2d/Mira_live2d_kit.zip" and kit["groups"] == ["Front hair", "Face"]
    assert client.get(kit["zip"]).status_code == 200 and client.get(kit["preview"]).status_code == 200
    assert (tmp_path / "out" / "live2d" / "Mira" / "Mira.psd").exists()


def test_live2d_character_lora_search(client, monkeypatch):
    from autoexpress_core.live2d import character_lora

    seen = {}

    def fake_search(name, architecture, api_key=None):
        seen.update(name=name, architecture=architecture)
        return [{"name": "Mira_IL", "title": "Mira", "civitai_model_id": 1, "civitai_version_id": 2, "weight": 0.8, "trigger": "mira"}]

    monkeypatch.setattr(character_lora, "search", fake_search)
    data = client.post("/live2d/character-lora", json={"name": "Mira", "checkpoint": "waiIllustriousSDXL_v150.safetensors"}).get_json()
    assert seen == {"name": "Mira", "architecture": "illustrious"}
    result = data["results"][0]
    assert result["installed_name"] is None and "civitai.com/models/1" in result["install"]["url"]
    assert client.post("/live2d/character-lora", json={}).status_code == 400


def _connected(client, **body):
    response = client.post("/receive_data", json={"backend": "fake", **body})
    return response, views.current_backend()


def test_login_fields_are_set_and_never_echoed(client):
    secret = "pa55-" + "x" * 8
    response, backend = _connected(
        client, text="https://pod-7860.proxy.example.net", username="deep", password=secret, token="tok-" + secret,
        headers="CF-Access-Client-Id: id-1\nCF-Access-Client-Secret: " + secret,
    )
    assert response.status_code == 200
    assert secret not in response.get_data(as_text=True)
    assert response.get_json()["login"] == {
        "username": "deep", "password": True, "token": True,
        "headers": ["CF-Access-Client-Id", "CF-Access-Client-Secret"],
    }
    assert backend.connection.password == secret and backend.connection.headers["CF-Access-Client-Secret"] == secret
    assert secret not in client.get("/backends").get_data(as_text=True)
    assert secret not in repr(backend.connection)


def test_login_is_kept_for_the_same_host_only(client):
    _connected(client, text="https://pod-7860.proxy.example.net", username="deep", password="pw", headers={"X-Key": "k"})

    # Reconnecting to the same host (e.g. from SillyTavern) keeps the login.
    _, backend = _connected(client, text="https://pod-7860.proxy.example.net/")
    assert (backend.connection.username, backend.connection.password, backend.connection.headers) == ("deep", "pw", {"X-Key": "k"})

    # A password left out stays; an empty one clears it.
    _, backend = _connected(client, text="https://pod-7860.proxy.example.net", username="deep")
    assert backend.connection.password == "pw"
    _, backend = _connected(client, text="https://pod-7860.proxy.example.net", password="")
    assert backend.connection.password is None and backend.connection.username == "deep"

    # Another host never receives it.
    _, backend = _connected(client, text="https://other-host.example.net")
    assert backend.connection.username is None and backend.connection.headers == {}


def test_switching_account_drops_the_old_password_and_forget_clears(client):
    _connected(client, text="http://10.0.0.9:7860", username="a", password="pw-a", token="t")
    _, backend = _connected(client, text="http://10.0.0.9:7860", username="b")
    assert backend.connection.username == "b" and backend.connection.password is None
    _, backend = _connected(client, text="http://10.0.0.9:7860", forget_login=True)
    assert backend.connection.username is None and backend.connection.token is None


def test_url_credentials_are_split_out(client):
    response, backend = _connected(client, text="https://bob:s3cr%40t@pod-7860.proxy.example.net")
    assert response.get_json()["url"] == "https://pod-7860.proxy.example.net"
    assert (backend.connection.username, backend.connection.password) == ("bob", "s3cr@t")
    assert "s3cr" not in response.get_data(as_text=True)


def test_bad_headers_are_refused_without_echoing_values(client):
    response, _ = _connected(client, text="http://10.0.0.9:7860", headers="Host: evil")
    assert response.status_code == 400 and "Host" in response.get_json()["error"]
    response, _ = _connected(client, text="http://10.0.0.9:7860", headers={"X-Key": "a\r\nInjected: 1"})
    assert response.status_code == 400 and "Injected" not in response.get_json()["error"]


def test_environment_login_only_goes_to_its_own_host(client, monkeypatch):
    monkeypatch.setattr(views.settings, "backend_url", "https://mine.example.net")
    monkeypatch.setattr(views.settings, "username", "env-user")
    monkeypatch.setattr(views.settings, "password", "env-pw")
    _, backend = _connected(client, text="https://mine.example.net")
    assert backend.connection.password == "env-pw"
    _, backend = _connected(client, text="https://elsewhere.example.net")
    assert backend.connection.username is None and backend.connection.password is None
