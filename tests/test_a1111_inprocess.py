"""Runs the in-process backend against stand-ins for the WebUI's modules package."""

import contextlib
import sys
import types

import pytest
from PIL import Image

from autoexpress_core import build_expression_payload
from autoexpress_core.backends.a1111_inprocess import A1111InProcessBackend
from autoexpress_core.images import pil_to_b64


class Component:
    def __init__(self, value):
        self.value = value


class FakeScript:
    def __init__(self, title, args_from, defaults, alwayson=True):
        self._title = title
        self.args_from = args_from
        self.args_to = args_from + len(defaults)
        self.defaults = defaults
        self.alwayson = alwayson
        self.is_img2img = True

    def title(self):
        return self._title

    def ui(self, is_img2img):
        return [Component(value) for value in self.defaults]


class FakeProcessing:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        self.scheduler = None

    def close(self):
        self.closed = True


@pytest.fixture
def webui(monkeypatch):
    adetailer = FakeScript("ADetailer", 1, [False, False, {"ad_model": "None"}, {"ad_model": "None"}])
    seed = FakeScript("Seed", 5, [-1, False, -1, 0, 0, 0])
    runner = types.SimpleNamespace(scripts=[adetailer, seed], alwayson_scripts=[adetailer, seed])

    calls = {}

    def process_images(p):
        calls["p"] = p
        return types.SimpleNamespace(images=[Image.new("RGB", (8, 8), "blue")])

    state = types.SimpleNamespace(
        begin=lambda job: calls.setdefault("begun", job),
        end=lambda: calls.setdefault("ended", True),
        interrupt=lambda: calls.setdefault("interrupted", True),
    )
    opts = types.SimpleNamespace(outdir_img2img_samples="out/img2img", outdir_img2img_grids="out/grids")

    modules = types.ModuleType("modules")
    modules.scripts = types.SimpleNamespace(scripts_img2img=runner)
    modules.processing = types.SimpleNamespace(
        StableDiffusionProcessingImg2Img=FakeProcessing, process_images=process_images
    )
    modules.shared = types.SimpleNamespace(sd_model=object(), opts=opts, state=state)
    modules.call_queue = types.SimpleNamespace(queue_lock=contextlib.nullcontext())

    gradio = types.ModuleType("gradio")
    gradio.Blocks = contextlib.nullcontext

    monkeypatch.setitem(sys.modules, "modules", modules)
    for name in ("scripts", "processing", "shared", "call_queue"):
        monkeypatch.setitem(sys.modules, f"modules.{name}", getattr(modules, name))
    monkeypatch.setitem(sys.modules, "gradio", gradio)
    return calls


def test_payload_becomes_processing_with_adetailer_args(webui, face_image):
    payload = build_expression_payload(pil_to_b64(face_image), {"ad_prompt": "1girl", "seed": 42}, "smile")

    result = A1111InProcessBackend().img2img(payload)

    p = webui["p"]
    assert result.size == (8, 8)
    assert p.kwargs["width"] == face_image.width and p.kwargs["height"] == face_image.height
    assert p.kwargs["do_not_save_samples"] is True
    assert p.closed and webui["ended"]

    args = p.script_args
    assert args[0] == 0
    assert args[1] is True and args[2] is True
    assert args[3]["ad_prompt"] == "1girl, smile"
    assert args[4] == {"ad_model": "None"}  # untouched second ADetailer tab keeps its default
    assert args[5] == 42  # Seed script
    assert p.scheduler == "Automatic"


def test_scripts_missing_from_the_webui_are_skipped(webui, face_image):
    payload = build_expression_payload(pil_to_b64(face_image), None, "smile")
    assert "Soft Inpainting" in payload["alwayson_scripts"]

    assert A1111InProcessBackend().img2img(payload) is not None


def test_has_adetailer_and_interrupt(webui):
    assert A1111InProcessBackend.has_adetailer()
    A1111InProcessBackend().interrupt()
    assert webui["interrupted"]
