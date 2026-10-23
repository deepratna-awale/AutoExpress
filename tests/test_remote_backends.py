import io
import json

import pytest
import requests
from PIL import Image

from autoexpress_core import ExpressionGenerator, build_expression_payload
from autoexpress_core.backends.base import FaceEditRequest, extract_loras, match_choice, normalize_url
from autoexpress_core.backends.a1111_api import A1111Client, ForgeClient
from autoexpress_core.backends.comfyui_api import ComfyUIClient, combo_options
from autoexpress_core.backends.registry import REMOTE_BACKENDS, create_backend, describe_backends
from autoexpress_core.backends.swarmui_api import SwarmUIClient
from autoexpress_core.images import pil_to_b64


class FakeResponse:
    def __init__(self, body=None, status=200, content=None):
        self._body = body
        self.status_code = status
        self.content = content if content is not None else b""
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class FakeSession:
    """Routes "METHOD /path" to a body, a FakeResponse, or a callable taking the request kwargs."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, timeout=None, **kwargs):
        path = "/" + url.split("/", 3)[3]
        self.calls.append((method, path, kwargs))
        handler = self.routes.get(f"{method} {path}")
        if handler is None:
            return FakeResponse({"detail": "Not Found"}, 404)
        if callable(handler):
            handler = handler(kwargs)
        return handler if isinstance(handler, FakeResponse) else FakeResponse(handler)


def png_bytes(color=(10, 20, 30), size=(64, 96)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def payload(face_image):
    settings = {
        "ad_prompt": "1girl, <lora:detail_tweaker:0.5>, red hair",
        "ad_negative_prompt": "lowres",
        "ad_steps": "30",
        "ad_cfg_scale": "6.5",
        "ad_sampler": "DPM++ 2M",
        "ad_scheduler": "Karras",
        "ad_checkpoint": "animagine-xl-3.1",
        "ad_denoising_strength": "0.45",
        "ad_clip_skip": "2",
        "seed": "1234",
    }
    return build_expression_payload(pil_to_b64(face_image), settings, "smile")


# Shared helpers -----------------------------------------------------------
@pytest.mark.parametrize(
    "typed, expected",
    [
        ("", "http://127.0.0.1:7860"),
        (None, "http://127.0.0.1:7860"),
        ("192.168.1.2:7860", "http://192.168.1.2:7860"),
        ("https://abc-7860.proxy.runpod.net/", "https://abc-7860.proxy.runpod.net"),
    ],
)
def test_normalize_url(typed, expected):
    assert normalize_url(typed, "http://127.0.0.1:7860") == expected


def test_extract_loras():
    prompt, loras = extract_loras("1girl, <lora:detail_tweaker:0.5>, red hair, <lora: add_detail: 1>, ")
    assert prompt == "1girl, red hair"
    assert loras == [("detail_tweaker", 0.5), ("add_detail", 1.0)]


def test_match_choice_ignores_folders_extensions_and_hashes():
    choices = ["SDXL/animagine-xl-3.1.safetensors", "sd15/anything-v5.ckpt"]
    assert match_choice("animagine-xl-3.1", choices) == choices[0]
    assert match_choice("anything-v5 [7f96a1a9ca]", choices) == choices[1]
    assert match_choice("missing", choices) is None


def test_face_edit_request_reads_the_adetailer_payload(payload):
    request = FaceEditRequest.from_payload(payload)
    assert request.prompt == "1girl, red hair, smile"
    assert request.loras == [("detail_tweaker", 0.5)]
    assert request.negative_prompt == "lowres"
    assert (request.steps, request.cfg_scale, request.denoise, request.seed, request.clip_skip) == (30, 6.5, 0.45, 1234, 2)
    assert (request.sampler, request.scheduler, request.checkpoint) == ("DPM++ 2M", "Karras", "animagine-xl-3.1")
    assert request.detector == "face_yolov8n.pt"


def test_face_edit_request_same_checkpoint_is_none(face_image):
    payload = build_expression_payload(pil_to_b64(face_image), {"ad_checkpoint": ""}, "smile")
    assert FaceEditRequest.from_payload(payload).checkpoint is None


def test_registry():
    assert set(REMOTE_BACKENDS) == {"a1111", "forge", "sdnext", "comfyui", "swarmui", "invokeai"}
    assert {b["id"] for b in describe_backends()} == set(REMOTE_BACKENDS)
    backend = create_backend("comfyui", "localhost:8188")
    assert isinstance(backend, ComfyUIClient) and backend.get_url() == "http://localhost:8188"
    with pytest.raises(ValueError):
        create_backend("nope")


# A1111 family -------------------------------------------------------------
def a1111_routes(scripts=("ADetailer", "Seed", "Sampler", "Extra options")):
    return {
        "GET /sdapi/v1/script-info": [
            {"name": name.lower(), "is_alwayson": True, "is_img2img": True} for name in scripts
        ],
        "GET /sdapi/v1/samplers": [{"name": "Euler a"}, {"name": "DPM++ 2M"}],
        "GET /sdapi/v1/sd-models": [{"model_name": "animagine-xl-3.1"}],
        "POST /sdapi/v1/img2img": lambda kw: {"images": [pil_to_b64(Image.new("RGB", (8, 8)), data_uri=False)]},
    }


def test_a1111_drops_scripts_the_server_does_not_have(payload):
    backend = ForgeClient(url="localhost:7860")
    backend.session = FakeSession(a1111_routes())

    assert backend.img2img(payload).size == (8, 8)
    sent = backend.session.calls[-1][2]["json"]
    assert set(sent["alwayson_scripts"]) == {"ADetailer", "Seed", "Sampler", "Extra options"}
    assert "Hypertile" in payload["alwayson_scripts"]  # caller's payload untouched


def test_a1111_without_script_info_sends_payload_as_is(payload):
    routes = a1111_routes()
    del routes["GET /sdapi/v1/script-info"]
    backend = A1111Client()
    backend.session = FakeSession(routes)

    backend.img2img(payload)
    assert set(backend.session.calls[-1][2]["json"]["alwayson_scripts"]) == set(payload["alwayson_scripts"])


def test_a1111_check_ready_and_missing_scheduler_endpoint():
    backend = A1111Client()
    backend.session = FakeSession(a1111_routes())
    assert backend.check_ready() == (True, "ok")
    assert backend.schedulers == []
    assert backend.models == ["animagine-xl-3.1"]

    backend = A1111Client()
    routes = a1111_routes(scripts=("Seed",))
    routes["GET /sdapi/v1/extensions"] = [{"name": "sd-webui-controlnet", "enabled": True}]
    backend.session = FakeSession(routes)
    ok, message = backend.check_ready()
    assert not ok and "ADetailer" in message


def test_a1111_finds_adetailer_by_extension_folder_name():
    routes = a1111_routes(scripts=("Seed",))
    del routes["GET /sdapi/v1/script-info"]
    routes["GET /sdapi/v1/extensions"] = [{"name": "!adetailer", "enabled": True}]
    backend = A1111Client()
    backend.session = FakeSession(routes)
    assert backend.is_extension()


# ComfyUI ------------------------------------------------------------------
FACE_DETAILER_INFO = {
    "input": {
        "required": {
            "image": ["IMAGE"],
            "model": ["MODEL"],
            "clip": ["CLIP"],
            "vae": ["VAE"],
            "guide_size": ["FLOAT", {"default": 512}],
            "seed": ["INT", {"default": 0}],
            "steps": ["INT", {"default": 20}],
            "cfg": ["FLOAT", {"default": 8.0}],
            "sampler_name": [["euler", "dpmpp_2m"]],
            "scheduler": [["normal", "karras"]],
            "positive": ["CONDITIONING"],
            "negative": ["CONDITIONING"],
            "denoise": ["FLOAT", {"default": 0.5}],
            "bbox_detector": ["BBOX_DETECTOR"],
            "wildcard": ["STRING", {"multiline": True}],
            "some_new_input": ["INT", {"default": 7}],
        },
        "optional": {"inpaint_model": ["BOOLEAN", {"default": False}]},
    }
}


def comfy_routes(history):
    info = {
        "CheckpointLoaderSimple": {"input": {"required": {"ckpt_name": [["SDXL/animagine-xl-3.1.safetensors", "other.safetensors"]]}}},
        "LoraLoader": {
            "input": {
                "required": {
                    "model": ["MODEL"],
                    "clip": ["CLIP"],
                    "lora_name": ["COMBO", {"options": ["detail_tweaker.safetensors"]}],
                    "strength_model": ["FLOAT", {"default": 1.0}],
                    "strength_clip": ["FLOAT", {"default": 1.0}],
                }
            }
        },
        "KSampler": {"input": {"required": {"sampler_name": [["euler", "dpmpp_2m"]], "scheduler": [["normal", "karras"]]}}},
        "UltralyticsDetectorProvider": {"input": {"required": {"model_name": [["bbox/hand_yolov8n.pt", "bbox/face_yolov8m.pt"]]}}},
        "FaceDetailer": FACE_DETAILER_INFO,
    }
    routes = {f"GET /object_info/{node}": {node: spec} for node, spec in info.items()}
    routes.update(
        {
            "POST /upload/image": {"name": "autoexpress_x.png", "subfolder": "", "type": "input"},
            "POST /prompt": {"prompt_id": "p1", "number": 1, "node_errors": {}},
            "GET /history/p1": history,
            "GET /view?": None,
            "POST /interrupt": FakeResponse(None, 200),
        }
    )
    return routes


class ComfySession(FakeSession):
    def request(self, method, url, timeout=None, **kwargs):
        if "/view" in url:
            self.calls.append((method, "/view", kwargs))
            return FakeResponse(None, 200, content=png_bytes())
        if "/object_info/" in url and f"{method} /{url.split('/', 3)[3]}" not in self.routes:
            return FakeResponse({})  # ComfyUI answers {} for nodes it does not know
        return super().request(method, url, timeout, **kwargs)


def done_history():
    return {
        "p1": {
            "status": {"status_str": "success", "completed": True, "messages": []},
            "outputs": {"output": {"images": [{"filename": "ComfyUI_temp_1.png", "subfolder": "", "type": "temp"}]}},
        }
    }


def test_comfyui_builds_face_detailer_workflow(payload):
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(comfy_routes(done_history()))

    result = backend.img2img(payload)
    assert result.size == (64, 96)

    workflow = next(kw["json"]["prompt"] for m, p, kw in backend.session.calls if p == "/prompt")
    assert workflow["ckpt"]["inputs"]["ckpt_name"] == "SDXL/animagine-xl-3.1.safetensors"
    assert workflow["lora_0"]["inputs"]["lora_name"] == "detail_tweaker.safetensors"
    assert workflow["lora_0"]["inputs"]["strength_model"] == 0.5
    assert workflow["clip_skip"]["inputs"]["stop_at_clip_layer"] == -2
    assert workflow["positive"]["inputs"]["text"] == "1girl, red hair, smile"
    assert workflow["detector"]["inputs"]["model_name"] == "bbox/face_yolov8m.pt"

    detailer = workflow["face_detailer"]["inputs"]
    assert detailer["sampler_name"] == "dpmpp_2m" and detailer["scheduler"] == "karras"
    assert (detailer["steps"], detailer["cfg"], detailer["denoise"], detailer["seed"]) == (30, 6.5, 0.45, 1234)
    assert detailer["model"] == ["lora_0", 0] and detailer["clip"] == ["clip_skip", 0]
    assert detailer["some_new_input"] == 7  # filled from object_info
    assert "sam_threshold" not in detailer  # not declared by this server
    assert workflow["image"]["inputs"]["image"] == "autoexpress_x.png"


def test_comfyui_uploads_the_image_once(payload, face_image):
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(comfy_routes(done_history()))
    ExpressionGenerator(backend).generate(face_image, only=["joy", "anger"])
    uploads = [c for c in backend.session.calls if c[1] == "/upload/image"]
    prompts = [c for c in backend.session.calls if c[1] == "/prompt"]
    assert len(uploads) == 1 and len(prompts) == 2


def test_comfyui_failed_job_returns_none(payload):
    history = {"p1": {"status": {"status_str": "error", "completed": False, "messages": [["execution_error", {}]]}, "outputs": {}}}
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(comfy_routes(history))
    assert backend.img2img(payload) is None


def test_comfyui_rejected_workflow_returns_none(payload):
    routes = comfy_routes(done_history())
    routes["POST /prompt"] = FakeResponse({"error": "bad", "node_errors": {"x": {}}}, 400)
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(routes)
    assert backend.img2img(payload) is None


def test_comfyui_check_ready_reports_missing_impact_pack():
    routes = comfy_routes(done_history())
    routes["GET /object_info/FaceDetailer"] = {}
    backend = ComfyUIClient()
    backend.session = ComfySession(routes)
    ok, message = backend.check_ready()
    assert not ok and "Impact-Pack" in message

    backend.session = ComfySession(comfy_routes(done_history()))
    assert backend.check_ready() == (True, "ok")
    assert backend.models == ["SDXL/animagine-xl-3.1.safetensors", "other.safetensors"]
    assert backend.loras == ["detail_tweaker.safetensors"]


def test_combo_options_formats():
    assert combo_options([["a", "b"]]) == ["a", "b"]
    assert combo_options(["COMBO", {"options": ["a"]}]) == ["a"]
    assert combo_options(["INT", {"default": 1}]) == []


# SwarmUI ------------------------------------------------------------------
def swarm_routes(generate):
    return {
        "POST /API/GetNewSession": {"session_id": "s1"},
        "POST /API/ListModels": lambda kw: {
            "files": [{"name": "SDXL/animagine-xl-3.1.safetensors"}] if kw["json"]["subtype"] == "Stable-Diffusion" else [{"name": "detail_tweaker"}],
            "folders": [],
        },
        "POST /API/ListT2IParams": {
            "list": [
                {"id": "sampler", "values": ["euler///Euler", "dpmpp_2m///DPM++ 2M"]},
                {"id": "scheduler", "values": ["normal", "karras"]},
                {"id": "yolomodelinternal", "values": ["face_yolov8m-seg_60.pt"]},
            ]
        },
        "POST /API/GenerateText2Image": generate,
        "POST /API/InterruptAll": {},
    }


def test_swarmui_generates_with_segment_syntax(payload):
    backend = SwarmUIClient()
    backend.session = FakeSession(swarm_routes({"images": [pil_to_b64(Image.new("RGB", (64, 96)))]}))

    assert backend.img2img(payload).size == (64, 96)
    body = next(kw["json"] for m, p, kw in backend.session.calls if p == "/API/GenerateText2Image")
    assert body["session_id"] == "s1"
    assert body["model"] == "SDXL/animagine-xl-3.1.safetensors"
    assert body["initimagecreativity"] == 0 and body["initimage"].startswith("data:image/png;base64,")
    assert "<segment:yolo-face_yolov8m-seg_60.pt,0.45,0.3> 1girl, red hair, smile, <lora:detail_tweaker:0.5>" in body["prompt"]
    assert (body["sampler"], body["scheduler"], body["clipstopatlayer"]) == ("dpmpp_2m", "karras", -2)
    assert (body["width"], body["height"], body["steps"], body["seed"]) == (64, 96, 30, 1234)


def test_swarmui_renews_an_expired_session(payload):
    calls = {"n": 0}

    def generate(kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"error_id": "invalid_session_id"}
        return {"images": ["View/local/raw/out.png"]}

    class Session(FakeSession):
        def request(self, method, url, timeout=None, **kwargs):
            if url.endswith("/View/local/raw/out.png"):
                return FakeResponse(None, 200, content=png_bytes())
            return super().request(method, url, timeout, **kwargs)

    backend = SwarmUIClient()
    backend.session = Session(swarm_routes(generate))
    assert backend.img2img(payload) is not None
    assert len([c for c in backend.session.calls if c[1] == "/API/GetNewSession"]) == 2


def test_swarmui_error_returns_none(payload):
    backend = SwarmUIClient()
    backend.session = FakeSession(swarm_routes({"error": "Model not found"}))
    assert backend.img2img(payload) is None


# InvokeAI -----------------------------------------------------------------
from autoexpress_core.backends.invokeai_api import InvokeAIClient, scheduler_name  # noqa: E402

INVOKE_MODELS = {
    "main": [
        {"key": "k1", "hash": "h1", "name": "animagine-xl-3.1", "base": "sdxl", "type": "main"},
        {"key": "k2", "hash": "h2", "name": "anything-v5", "base": "sd-1", "type": "main"},
        {"key": "k3", "hash": "h3", "name": "flux-dev", "base": "flux", "type": "main"},
    ],
    "lora": [{"key": "l1", "hash": "lh", "name": "detail_tweaker", "base": "sdxl", "type": "lora"}],
}


class InvokeSession(FakeSession):
    def __init__(self, item):
        super().__init__({})
        self.item = item

    def request(self, method, url, timeout=None, **kwargs):
        path = "/" + url.split("/", 3)[3]
        self.calls.append((method, path, kwargs))
        if path == "/api/v2/models/":
            return FakeResponse({"models": INVOKE_MODELS[kwargs["params"]["model_type"]]})
        if path == "/api/v1/images/upload":
            return FakeResponse({"image_name": "up.png"}, 201)
        if path == "/api/v1/queue/default/enqueue_batch":
            return FakeResponse({"batch": {"batch_id": "b"}, "item_ids": [7]})
        if path == "/api/v1/queue/default/i/7":
            return FakeResponse(self.item)
        if path.endswith("/full"):
            return FakeResponse(None, 200, content=png_bytes(size=(64, 96)))
        return FakeResponse({"detail": "Not Found"}, 404)


def invoke_done():
    return {
        "status": "completed",
        "session": {"source_prepared_mapping": {"output": ["p-out"]}, "results": {"p-out": {"image": {"image_name": "out.png"}}}},
    }


def test_invokeai_builds_sdxl_inpaint_graph(payload):
    backend = InvokeAIClient(poll_interval=0)
    backend.session = InvokeSession(invoke_done())

    assert backend.img2img(payload).size == (64, 96)
    graph = next(kw["json"]["batch"]["graph"] for m, p, kw in backend.session.calls if p.endswith("enqueue_batch"))
    nodes = graph["nodes"]
    assert nodes["model_loader"]["type"] == "sdxl_model_loader"
    assert nodes["model_loader"]["model"] == {"key": "k1", "hash": "h1", "name": "animagine-xl-3.1", "base": "sdxl", "type": "main"}
    assert nodes["positive"]["type"] == "sdxl_compel_prompt" and nodes["positive"]["prompt"] == "1girl, red hair, smile"
    assert nodes["lora_0"]["lora"]["key"] == "l1" and nodes["lora_0"]["weight"] == 0.5
    assert nodes["denoise"]["scheduler"] == "dpmpp_2m_k"
    assert nodes["denoise"]["denoising_start"] == 0.55
    assert (nodes["noise"]["seed"], nodes["noise"]["width"], nodes["noise"]["height"]) == (1234, 64, 96)

    def sources(dest, field):
        return [(e["source"]["node_id"], e["source"]["field"]) for e in graph["edges"]
                if e["destination"] == {"node_id": dest, "field": field}]

    assert sources("gradient_mask", "mask") == [("face_mask", "mask")]
    assert sources("denoise", "denoise_mask") == [("gradient_mask", "denoise_mask")]
    assert sources("denoise", "unet") == [("lora_loader", "unet")]
    assert sources("positive", "clip2") == [("lora_loader", "clip2")]
    assert sources("output", "latents") == [("denoise", "latents")]
    # every edge points at nodes that exist
    for e in graph["edges"]:
        assert e["source"]["node_id"] in nodes and e["destination"]["node_id"] in nodes


def test_invokeai_sd1_uses_clip_skip_and_skips_mismatched_lora(face_image):
    payload = build_expression_payload(
        pil_to_b64(face_image), {"ad_checkpoint": "anything-v5", "ad_clip_skip": 2, "ad_prompt": "<lora:detail_tweaker:1>"}, "smile"
    )
    backend = InvokeAIClient(poll_interval=0)
    graph = backend_graph(backend, payload)
    assert graph["nodes"]["model_loader"]["type"] == "main_model_loader"
    assert graph["nodes"]["clip_skip"]["skipped_layers"] == 1
    assert "lora_loader" not in graph["nodes"]  # the lora is SDXL, the model SD1


def backend_graph(backend, payload):
    backend.session = InvokeSession(invoke_done())
    backend.img2img(payload)
    return next(kw["json"]["batch"]["graph"] for m, p, kw in backend.session.calls if p.endswith("enqueue_batch"))


def test_invokeai_failed_job_and_listings(payload):
    backend = InvokeAIClient(poll_interval=0)
    backend.session = InvokeSession({"status": "failed", "error_message": "boom"})
    assert backend.img2img(payload) is None
    assert backend.models == ["animagine-xl-3.1", "anything-v5"]  # flux is not supported
    assert backend.check_ready() == (True, "ok")


@pytest.mark.parametrize(
    "sampler, scheduler, expected",
    [("DPM++ 2M", "Karras", "dpmpp_2m_k"), ("Euler a", "Automatic", "euler_a"), ("euler_k", None, "euler_k"), (None, None, "euler")],
)
def test_invokeai_scheduler_names(sampler, scheduler, expected):
    assert scheduler_name(sampler, scheduler) == expected
