import pytest

from autoexpress_core import (
    FLAVORS,
    expression_loras,
    resolve_flavor,
    ExpressionGenerator,
    build_expression_payload,
    expression_names,
    get_expressions,
    join_prompt,
    make_sprite_sheet,
)
from autoexpress_core.images import b64_to_pil, pil_to_b64
from autoexpress_core.payload import find_nested_key
from conftest import FakeBackend


@pytest.mark.parametrize("flavor", list(FLAVORS) + ["anime", "realistic"])
def test_every_flavor_has_the_same_28_expressions(flavor):
    assert list(get_expressions(flavor)) == expression_names("auto")
    assert len(expression_names(flavor)) == 28


def test_legacy_flavors_map_to_families():
    assert resolve_flavor("anime") == "danbooru"
    assert resolve_flavor("realistic") == "sdxl_base"
    assert resolve_flavor("auto", "illustriousXL_v01") == "illustrious"


def test_expression_lora_prompt_uses_host_lora_list():
    prompt = expression_loras.expression_lora_prompt(
        "ponyDiffusionV6XL", installed_names=lambda: ["AutoExpress-expressions-pony"]
    )
    assert prompt == "<lora:AutoExpress-expressions-pony:0.6>, cinematic expression style"
    assert expression_loras.expression_lora_prompt("ponyDiffusionV6XL", installed_names=[]) == ""


def test_get_expressions_subset_keeps_file_order():
    assert list(get_expressions("anime", ["surprise", " Joy ", "anger"])) == ["anger", "joy", "surprise"]


def test_unknown_flavor_raises():
    with pytest.raises(ValueError):
        get_expressions("nope")


@pytest.mark.parametrize(
    "base, tags, expected",
    [
        ("1girl, solo", "smile", "1girl, solo, smile"),
        ("1girl, solo,", "smile", "1girl, solo, smile"),
        ("1girl, solo, ", "smile", "1girl, solo, smile"),
        ("", "smile", "smile"),
        (None, "smile", "smile"),
        ("1girl", "", "1girl"),
    ],
)
def test_join_prompt(base, tags, expected):
    assert join_prompt(base, tags) == expected


def test_payload_applies_settings_and_expression():
    settings = {"ad_prompt": "1girl", "ad_steps": 30, "seed": 1234}
    payload = build_expression_payload("abc", settings, "smile")

    adetailer = payload["alwayson_scripts"]["ADetailer"]["args"]
    assert adetailer[0] is True and adetailer[1] is True
    assert adetailer[2]["ad_prompt"] == "1girl, smile"
    assert adetailer[2]["ad_steps"] == 30
    assert payload["seed"] == 1234
    assert payload["alwayson_scripts"]["Seed"]["args"][0] == 1234
    assert payload["init_images"] == ["abc"]


def test_payload_defaults_to_same_checkpoint():
    payload = build_expression_payload("abc", {"ad_checkpoint": ""}, "smile")
    assert find_nested_key(payload, "ad_checkpoint") == "Use same checkpoint"


def test_payload_is_a_fresh_copy_every_time():
    build_expression_payload("abc", {"ad_prompt": "first"}, "smile")
    payload = build_expression_payload("abc", None, "smile")
    assert find_nested_key(payload, "ad_prompt") == "smile"


def test_image_round_trip(face_image):
    assert b64_to_pil(pil_to_b64(face_image)).size == face_image.size
    assert b64_to_pil(pil_to_b64(face_image, data_uri=False)).size == face_image.size


def test_generator_runs_every_selected_expression(tmp_path, face_image, fake_backend):
    generator = ExpressionGenerator(fake_backend)
    results = generator.generate(
        face_image, {"ad_prompt": "1girl"}, flavor="anime", only=["joy", "anger"], output_dir=tmp_path
    )

    assert list(results) == ["anger", "joy"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["anger.png", "joy.png"]
    prompts = [find_nested_key(p, "ad_prompt") for p in fake_backend.payloads]
    assert prompts[0] == "masterpiece, best quality, 1girl, " + get_expressions("danbooru")["anger"]
    assert generator.family == "danbooru"


def test_generator_picks_family_from_checkpoint_and_adds_loras(face_image, fake_backend):
    generator = ExpressionGenerator(fake_backend)
    generator.generate(
        face_image,
        {"ad_prompt": "1girl", "ad_checkpoint": "ponyDiffusionV6XL", "ad_negative_prompt": "lowres"},
        only=["joy"],
        lora_prompt="<lora:AutoExpress-expressions-pony:0.6>, cinematic expression style",
    )

    payload = fake_backend.payloads[0]
    assert generator.family == "pony"
    assert find_nested_key(payload, "ad_prompt").startswith(
        "score_9, score_8_up, score_7_up, 1girl, <lora:AutoExpress-expressions-pony:0.6>, cinematic expression style, "
    )
    assert find_nested_key(payload, "ad_negative_prompt") == "lowres, score_4, score_5, score_6"


def test_generator_stop_interrupts_backend(face_image, fake_backend):
    generator = ExpressionGenerator(fake_backend)
    produced = []
    for name, _ in generator.iter_generate(face_image):
        produced.append(name)
        generator.stop()

    assert len(produced) == 1
    assert fake_backend.interrupted


def test_generator_stops_on_backend_failure(face_image):
    backend = FakeBackend(fail_on=3)
    results = ExpressionGenerator(backend).generate(face_image)
    assert len(results) == 2


def test_sprite_sheet_layout(face_image):
    sheet = make_sprite_sheet([face_image] * 28, ["joy"] * 28, columns=7)
    assert sheet.width == 7 * 64
    assert sheet.height > 4 * 96

    no_labels = make_sprite_sheet([face_image] * 3, columns=7)
    assert no_labels.size == (3 * 64, 96)


def test_sprite_sheet_labels_without_scalable_font(monkeypatch, face_image):
    from autoexpress_core import grid

    monkeypatch.setattr(grid, "_label_font", lambda size: None)
    tile = face_image.resize((512, 768))
    sheet = make_sprite_sheet([tile] * 2, ["joy", "anger"], columns=2)

    label_strip = sheet.crop((0, 768, sheet.width, sheet.height)).convert("L")
    bright = label_strip.point(lambda v: 255 if v > 200 else 0).getbbox()
    assert bright is not None
    assert bright[3] - bright[1] >= 20  # scaled up, not the 11px bitmap font


def test_generator_keeps_infotext_in_saved_png(tmp_path, face_image):
    from PIL import Image

    class InfoBackend(FakeBackend):
        def img2img(self, payload):
            image = super().img2img(payload)
            image.info["parameters"] = "1girl, smile"
            return image

    ExpressionGenerator(InfoBackend()).generate(face_image, only=["joy"], output_dir=tmp_path)
    with Image.open(tmp_path / "joy.png") as saved:
        assert saved.info["parameters"] == "1girl, smile"
