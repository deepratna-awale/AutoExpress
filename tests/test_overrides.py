"""Per-expression prompts and settings: the saved file, the generator and the app routes."""

import json

import pytest

from autoexpress_core import ExpressionGenerator, overrides
from autoexpress_core.expressions import get_expressions
from autoexpress_core.generator import default_expression_prompt
from autoexpress_core.payload import find_nested_key


def test_normalize_cleans_and_refuses_bad_values():
    data = {"expressions": {"Joy": {"prompt": "  laughing  ", "settings": {"seed": "12", "ad_denoising_strength": 0.6, "ad_steps": ""}}, "anger": {}}}
    assert overrides.normalize(data) == {"joy": {"prompt": "laughing", "settings": {"seed": 12, "ad_denoising_strength": 0.6}}}
    with pytest.raises(overrides.OverrideError) as error:
        overrides.normalize({"joy": {"settings": {"seed": "x", "ad_denoising_strength": 2, "bogus": 1}}})
    assert set(error.value.errors) == {"joy.settings.seed", "joy.settings.ad_denoising_strength", "joy.settings.bogus"}
    with pytest.raises(overrides.OverrideError):
        overrides.normalize(["joy"])


def test_save_load_and_clear(tmp_path):
    overrides.save(tmp_path, {"joy": {"prompt": "grin"}})
    saved = json.loads((tmp_path / overrides.FILE_NAME).read_text())
    assert saved == {"version": 1, "expressions": {"joy": {"prompt": "grin"}}}
    assert overrides.load(tmp_path) == {"joy": {"prompt": "grin"}}
    overrides.save(tmp_path, {})
    assert not (tmp_path / overrides.FILE_NAME).exists()
    (tmp_path / overrides.FILE_NAME).write_text("not json")
    assert overrides.load(tmp_path) == {}


def test_generator_uses_one_expressions_prompt_and_settings(face_image, fake_backend):
    generator = ExpressionGenerator(fake_backend)
    generator.generate(
        face_image,
        {
            "ad_prompt": "1girl",
            "seed": 5,
            "ad_denoising_strength": 0.4,
            "expression_intensity": 0.5,
            "expression_overrides": {"joy": {"prompt": "laughing, tears of joy", "settings": {"seed": 77, "ad_denoising_strength": 0.6}}},
        },
        flavor="anime",
        only=["joy", "anger"],
    )
    anger, joy = fake_backend.payloads  # file order
    assert find_nested_key(joy, "ad_prompt") == "masterpiece, best quality, 1girl, laughing, tears of joy"
    assert find_nested_key(joy, "seed") == 77 and find_nested_key(joy, "ad_denoising_strength") == 0.6
    assert find_nested_key(anger, "ad_prompt") == "masterpiece, best quality, 1girl, " + get_expressions("danbooru")["anger"]
    assert find_nested_key(anger, "seed") == 5 and find_nested_key(anger, "ad_denoising_strength") == 0.4


def test_default_expression_prompt_matches_what_a_run_uses():
    assert default_expression_prompt("joy", family="anime") == get_expressions("danbooru")["joy"]
    assert "(" in default_expression_prompt("joy", family="anime", intensity=1.0)
    instruction = default_expression_prompt("joy", "instruct", family="anime")
    assert instruction.startswith("Change only the facial expression.")
    with pytest.raises(KeyError):
        default_expression_prompt("nope", family="anime")


# App routes ----------------------------------------------------------------

flask = pytest.importorskip("flask")
pytest.importorskip("sd_parsers")

from test_app import FakeEditWebUI, FakeWebUI, body, client  # noqa: E402,F401
from autoexpress import views  # noqa: E402
from autoexpress_core.backends import registry  # noqa: E402


def test_retry_one_expression_with_its_own_prompt_and_remember_it(client, tmp_path, monkeypatch):
    seen = []
    original = FakeWebUI.img2img

    def record(self, payload):
        seen.append((find_nested_key(payload, "ad_prompt"), find_nested_key(payload, "seed")))
        return original(self, payload)

    monkeypatch.setattr(FakeWebUI, "img2img", record)
    assert client.post("/generate", json=body()).get_json()["status"] == "success"

    retry = body(expressions=["joy"], overrides={"joy": {"prompt": "big grin", "settings": {"seed": 42}}}, save_overrides=True)
    result = client.post("/generate", json=retry).get_json()
    assert result["status"] == "success" and result["job"]["progress"]["total"] == 1
    assert seen[-1][0].endswith("1girl, big grin") and seen[-1][1] == 42

    saved = client.get("/expression-overrides?output_dir=Alice").get_json()
    assert saved["expressions"] == {"joy": {"prompt": "big grin", "settings": {"seed": 42}}}

    # A later full run remembers it; use_saved_overrides false skips it.
    seen.clear()
    client.post("/generate", json=body())
    prompts = dict((p.rsplit(", ", 1)[-1], s) for p, s in seen)
    assert prompts.get("big grin") == 42
    seen.clear()
    client.post("/generate", json=body(use_saved_overrides=False))
    assert not any(p.endswith("big grin") for p, _ in seen)


def test_export_import_and_validate_overrides(client):
    data = {"version": 1, "expressions": {"anger": {"prompt": "furious", "settings": {"expression_intensity": 0.8}}}}
    response = client.put("/expression-overrides", json={"output_dir": "Bob", **data})
    assert response.status_code == 200
    export = client.get("/expression-overrides?output_dir=Bob&download=1")
    assert "attachment" in export.headers["Content-Disposition"] and export.get_json() == data

    bad = client.put("/expression-overrides", json={"output_dir": "Bob", "expressions": {"anger": {"settings": {"seed": "x"}}}})
    assert bad.status_code == 400 and "overrides.anger.settings.seed" in bad.get_json()["error"]["fields"]
    unknown = client.put("/expression-overrides", json={"output_dir": "Bob", "expressions": {"nope": {"prompt": "x"}}})
    assert unknown.status_code == 400
    assert client.post("/generate", json=body(overrides={"joy": {"settings": {"seed": "x"}}})).status_code == 400

    assert client.put("/expression-overrides", json={"output_dir": "Bob", "expressions": {}}).status_code == 200
    assert client.get("/expression-overrides?output_dir=Bob").get_json()["expressions"] == {}


def test_expression_prompt_defaults(client):
    tags = client.post("/expression-prompt", json={"expressions": ["joy"], "family": "anime"}).get_json()
    assert tags["kind"] == "tags" and tags["prompts"]["joy"] == get_expressions("danbooru")["joy"]
    everything = client.post("/expression-prompt", json={"method": "instruct"}).get_json()
    assert everything["kind"] == "instruction" and len(everything["prompts"]) == 28


def test_instruction_edit_override_replaces_the_instruction(client, monkeypatch):
    monkeypatch.setitem(registry.REMOTE_BACKENDS, "fake_edit", FakeEditWebUI)
    FakeEditWebUI.instructions = []
    views.state.connect("fake_edit", None)
    custom = {"joy": {"prompt": "Make her laugh with her eyes closed.", "settings": {"seed": 3}}}
    result = client.post("/generate", json=body(method="instruct", seed="9", overrides=custom)).get_json()
    assert result["status"] == "success"
    by_text = dict(FakeEditWebUI.instructions)
    assert by_text["Make her laugh with her eyes closed."] == 3
    assert sorted(by_text.values()) == [3, 9]
