"""The instruction edit mode: edit instructions, the Qwen-Image-Edit workflow, the app's method option."""

import json
import pathlib

import pytest
from PIL import Image

from autoexpress_core import ExpressionGenerator, expression_names, instruction_edit
from autoexpress_core.backends.a1111_api import A1111Client
from autoexpress_core.backends.comfyui_api import ComfyUIClient
from autoexpress_core.images import pil_to_b64

from test_remote_backends import ComfySession, FakeResponse, comfy_routes, done_history

ROOT = pathlib.Path(__file__).resolve().parents[1]


# Instructions ---------------------------------------------------------------
def test_every_expression_has_an_instruction():
    assert instruction_edit.instruction_names() == expression_names("danbooru")


def test_build_instruction_wraps_the_sentence():
    text = instruction_edit.build_instruction("anger", "Keep the glasses on.")
    assert text.startswith("Change only the facial expression. The character is furious")
    assert "Keep the glasses on. Keep the same character" in text
    assert text.endswith("framing and background.")
    with pytest.raises(KeyError):
        instruction_edit.build_instruction("smug")


def test_tuned_instructions_for_known_problems():
    # "deep blush" turned the whole face red, and sadness tilted the head.
    embarrassment = instruction_edit.get_instructions(["embarrassment"])["embarrassment"]
    assert "only on the cheeks" in embarrassment and "deep blush" not in embarrassment
    assert "blush" not in instruction_edit.get_instructions(["joy"])["joy"]
    assert "does not move" in instruction_edit.get_instructions(["sadness"])["sadness"]


def test_photo_style_keeps_photos_realistic():
    text = instruction_edit.build_instruction("joy", style="photo")
    assert text.startswith("Edit this photograph: change only the person's facial expression. The person is overjoyed")
    assert text.endswith("Do not stylize or cartoonize.")
    assert instruction_edit.resolve_style(None, is_realistic=True) == "photo"
    assert instruction_edit.resolve_style("illustration", is_realistic=True) == "illustration"
    assert instruction_edit.resolve_style("auto") == "illustration"
    with pytest.raises(KeyError):
        instruction_edit.build_instruction("joy", style="sketch")


def test_edit_settings_from_app_settings():
    settings = instruction_edit.EditSettings.from_settings({"seed": "7", "edit_steps": 12, "edit_lightning": False})
    assert (settings.seed, settings.steps, settings.lightning) == (7, 12, False)
    defaults = instruction_edit.EditSettings()
    assert (defaults.resolved_steps(True), defaults.resolved_cfg(True)) == (8, 1.0)
    assert (defaults.resolved_steps(False), defaults.resolved_cfg(False)) == (40, 4.0)


def test_find_model_prefers_the_newest_edit_model():
    choices = ["flux1-dev.safetensors", "qwen_image_edit_fp8_e4m3fn.safetensors", "Qwen/qwen_image_edit_2509_fp8_e4m3fn.safetensors"]
    assert instruction_edit.find_model("diffusion_model", choices) == "Qwen/qwen_image_edit_2509_fp8_e4m3fn.safetensors"
    assert instruction_edit.find_model("diffusion_model", choices, "qwen_image_edit_fp8_e4m3fn.safetensors") == choices[1]
    assert instruction_edit.find_model("vae", ["ae.safetensors"]) is None
    assert instruction_edit.find_model("lightning_lora", ["Qwen-Image-Lightning-8steps-V1.1.safetensors"])


def test_missing_models_and_check_command(tmp_path, capsys):
    (tmp_path / "models" / "vae").mkdir(parents=True)
    (tmp_path / "models" / "vae" / "qwen_image_vae.safetensors").write_bytes(b"")
    (tmp_path / "models" / "unet").mkdir()
    (tmp_path / "models" / "unet" / "qwen_image_edit_2509_fp8_e4m3fn.safetensors").write_bytes(b"")
    missing = [model.role for model in instruction_edit.missing_models(tmp_path)]
    assert missing == ["text_encoder", "lightning_lora"]
    assert instruction_edit.main(["check", str(tmp_path)]) == 1
    assert "qwen_2.5_vl_7b_fp8_scaled" in capsys.readouterr().out


def test_download_models_falls_back_and_skips_present(tmp_path, monkeypatch):
    import requests

    for folder, name in (("diffusion_models", "qwen_image_edit_2509_fp8_e4m3fn.safetensors"), ("text_encoders", "qwen_2.5_vl_7b_fp8_scaled.safetensors"), ("vae", "qwen_image_vae.safetensors")):
        (tmp_path / "models" / folder).mkdir(parents=True)
        (tmp_path / "models" / folder / name).write_bytes(b"")

    fetched = []

    class Response:
        def __init__(self, url):
            self.status_code = 404 if "Qwen-Image-Edit-2509/" in url else 200
            self.headers = {"Content-Length": "4"}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield b"lora"

    def get(url, **kwargs):
        fetched.append(url)
        return Response(url)

    monkeypatch.setattr(requests, "get", get)
    saved = instruction_edit.download_models(tmp_path, log=lambda message: None)
    assert len(fetched) == 2  # only the LoRA, the 2509 path then the fallback
    assert saved == [tmp_path / "models" / "loras" / "Qwen-Image-Lightning-8steps-V1.1.safetensors"]
    assert saved[0].read_bytes() == b"lora"


# ComfyUI workflow -----------------------------------------------------------
def edit_routes():
    routes = comfy_routes(done_history())
    combo = lambda *options: [list(options)]  # noqa: E731
    info = {
        "UNETLoader": {"input": {"required": {"unet_name": combo("qwen_image_edit_2509_fp8_e4m3fn.safetensors"), "weight_dtype": combo("default", "fp8_e4m3fn")}}},
        "CLIPLoader": {"input": {"required": {"clip_name": combo("qwen_2.5_vl_7b_fp8_scaled.safetensors"), "type": combo("stable_diffusion", "qwen_image")}, "optional": {"device": combo("default", "cpu")}}},
        "VAELoader": {"input": {"required": {"vae_name": combo("qwen_image_vae.safetensors")}}},
        "LoraLoaderModelOnly": {"input": {"required": {"model": ["MODEL"], "lora_name": combo("Qwen-Image-Edit-2509-Lightning-8steps-V1.0-bf16.safetensors"), "strength_model": ["FLOAT", {"default": 1.0}]}}},
        "ModelSamplingAuraFlow": {"input": {"required": {"model": ["MODEL"], "shift": ["FLOAT", {"default": 1.73}]}}},
        "CFGNorm": {"input": {"required": {"model": ["MODEL"], "strength": ["FLOAT", {"default": 1.0}]}}},
        "ImageScaleToTotalPixels": {"input": {"required": {"image": ["IMAGE"], "upscale_method": combo("nearest-exact", "lanczos"), "megapixels": ["FLOAT", {"default": 1.0}], "resolution_steps": ["INT", {"default": 1}]}}},
        "TextEncodeQwenImageEditPlus": {"input": {"required": {"clip": ["CLIP"], "prompt": ["STRING", {"multiline": True}]}, "optional": {"vae": ["VAE"], "image1": ["IMAGE"], "image2": ["IMAGE"]}}},
        "KSampler": {"input": {"required": {"model": ["MODEL"], "seed": ["INT", {}], "steps": ["INT", {}], "cfg": ["FLOAT", {}], "sampler_name": combo("euler", "res_multistep"), "scheduler": combo("simple", "normal"), "positive": ["CONDITIONING"], "negative": ["CONDITIONING"], "latent_image": ["LATENT"], "denoise": ["FLOAT", {"default": 1.0}]}}},
        "VAEEncode": {"input": {"required": {"pixels": ["IMAGE"], "vae": ["VAE"]}}},
        "VAEDecode": {"input": {"required": {"samples": ["LATENT"], "vae": ["VAE"]}}},
        "LoadImage": {"input": {"required": {"image": combo("x.png")}}},
    }
    routes.update({f"GET /object_info/{node}": {node: spec} for node, spec in info.items()})
    return routes


def test_comfyui_builds_qwen_edit_workflow(face_image):
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(edit_routes())
    assert backend.check_ready("instruct") == (True, "ok")

    instruction = instruction_edit.build_instruction("joy")
    result = backend.instruction_edit(pil_to_b64(face_image), instruction, instruction_edit.EditSettings(seed=5))
    assert result.size == face_image.size

    workflow = next(kw["json"]["prompt"] for m, p, kw in backend.session.calls if p == "/prompt")
    assert workflow["unet"]["inputs"]["unet_name"] == "qwen_image_edit_2509_fp8_e4m3fn.safetensors"
    assert workflow["lightning"]["inputs"]["model"] == ["unet", 0]
    assert workflow["shift"]["inputs"] == {"model": ["lightning", 0], "shift": 3.0}
    assert workflow["clip"]["inputs"]["type"] == "qwen_image"
    assert workflow["scaled"]["inputs"]["resolution_steps"] == 1  # filled from object_info
    assert workflow["positive"]["inputs"]["prompt"] == instruction
    assert workflow["positive"]["inputs"]["image1"] == ["scaled", 0]
    assert workflow["negative"]["inputs"]["prompt"] == ""
    sampler = workflow["sampler"]["inputs"]
    assert (sampler["steps"], sampler["cfg"], sampler["seed"], sampler["scheduler"]) == (8, 1.0, 5, "simple")
    assert sampler["model"] == ["cfg_norm", 0]
    assert "face_detailer" not in workflow
    assert result.info["parameters"].startswith(instruction + "\nNegative prompt:")
    assert "Seed: 5" in result.info["parameters"]


def test_comfyui_qwen_edit_without_lightning_uses_more_steps(face_image):
    routes = edit_routes()
    routes["GET /object_info/LoraLoaderModelOnly"]["LoraLoaderModelOnly"]["input"]["required"]["lora_name"] = [["other.safetensors"]]
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(routes)
    backend.instruction_edit(pil_to_b64(face_image), "x", instruction_edit.EditSettings())
    workflow = next(kw["json"]["prompt"] for m, p, kw in backend.session.calls if p == "/prompt")
    assert "lightning" not in workflow
    assert (workflow["sampler"]["inputs"]["steps"], workflow["sampler"]["inputs"]["cfg"]) == (40, 4.0)


def test_comfyui_edit_ready_names_missing_models():
    routes = edit_routes()
    routes["GET /object_info/UNETLoader"]["UNETLoader"]["input"]["required"]["unet_name"] = [["flux1-dev.safetensors"]]
    backend = ComfyUIClient()
    backend.session = ComfySession(routes)
    ok, message = backend.check_ready("instruct")
    assert not ok and "qwen_image_edit_2509_fp8_e4m3fn" in message and "instruction_edit download" in message

    routes = edit_routes()
    routes["GET /object_info/TextEncodeQwenImageEditPlus"] = {}
    backend.session = ComfySession(routes)
    ok, message = backend.check_ready("instruct")
    assert not ok and "TextEncodeQwenImageEditPlus" in message


def test_comfyui_edit_mode_does_not_need_impact_pack():
    routes = edit_routes()
    routes["GET /object_info/FaceDetailer"] = {}
    backend = ComfyUIClient()
    backend.session = ComfySession(routes)
    assert backend.check_ready("instruct") == (True, "ok")
    assert not backend.check_ready("inpaint")[0]


def test_other_backends_have_no_edit_mode():
    backend = A1111Client()
    assert backend.edit_methods == ("inpaint",)
    ok, message = backend.check_ready("instruct")
    assert not ok and "ComfyUI" in message


def test_generator_runs_one_edit_per_expression(face_image, tmp_path):
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(edit_routes())
    results = ExpressionGenerator(backend).generate(
        face_image, settings={"seed": 3, "edit_instruction": "Keep the hat."}, only=["joy", "anger"], output_dir=tmp_path, method="instruct"
    )
    assert list(results) == ["anger", "joy"]  # file order
    prompts = [kw["json"]["prompt"] for m, p, kw in backend.session.calls if p == "/prompt"]
    assert [w["positive"]["inputs"]["prompt"] for w in prompts] == [
        instruction_edit.build_instruction(name, "Keep the hat.") for name in ("anger", "joy")
    ]
    assert sorted(path.name for path in tmp_path.iterdir()) == ["anger.png", "joy.png"]
    assert "Change only the facial expression" in Image.open(tmp_path / "joy.png").info["parameters"]


def test_generator_rejects_edit_mode_on_other_backends(face_image, fake_backend):
    with pytest.raises(ValueError):
        ExpressionGenerator(fake_backend).generate(face_image, method="instruct")


def test_example_workflow_wires_the_instruction_node():
    workflow = json.loads((ROOT / "example_workflows" / "AutoExpress Qwen-Image-Edit expressions.json").read_text())
    types = {node["id"]: node["type"] for node in workflow["nodes"]}
    assert "AutoExpressEditInstructions" in types.values() and "TextEncodeQwenImageEditPlus" in types.values()
    links = {link[0]: link for link in workflow["links"]}
    for node in workflow["nodes"]:
        for slot in node["inputs"]:
            if slot["link"] is not None:
                link = links[slot["link"]]
                assert link[3] == node["id"] and node["inputs"][link[4]] is slot
        for output in node["outputs"]:
            for link_id in output["links"]:
                assert links[link_id][1] == node["id"]
    instructions = next(n for n in workflow["nodes"] if n["type"] == "AutoExpressEditInstructions")
    prompt_link = instructions["outputs"][0]["links"][0]
    assert types[links[prompt_link][3]] == "TextEncodeQwenImageEditPlus"


def test_generator_uses_photo_wording_for_realistic_images(face_image):
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(edit_routes())
    ExpressionGenerator(backend).generate(face_image, only=["joy"], method="instruct", is_realistic=True)
    ExpressionGenerator(backend).generate(face_image, settings={"edit_style": "illustration"}, only=["joy"], method="instruct", is_realistic=True)
    prompts = [kw["json"]["prompt"]["positive"]["inputs"]["prompt"] for m, p, kw in backend.session.calls if p == "/prompt"]
    assert prompts[0].startswith("Edit this photograph") and prompts[1].startswith("Change only the facial expression.")
