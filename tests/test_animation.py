"""Animated sprites: character cards, idle motions, the Wan 2.2 workflow, frame cut-outs and the saved animations."""

import base64
import io
import json

import pytest
from PIL import Image, ImageSequence, PngImagePlugin

from autoexpress_core import animation, character_card
from autoexpress_core.backends.comfyui_api import ComfyUIClient
from autoexpress_core.images import pil_to_b64

from test_remote_backends import ComfySession, comfy_routes


def card_png(chunks: dict) -> bytes:
    info = PngImagePlugin.PngInfo()
    for key, data in chunks.items():
        info.add_text(key, base64.b64encode(json.dumps(data).encode()).decode())
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG", pnginfo=info)
    return buffer.getvalue()


V2 = {"spec": "chara_card_v2", "spec_version": "2.0", "data": {"name": "Mira", "description": "{{char}} is a shy librarian who teases {{user}}.", "personality": "", "tags": ["Fantasy", "Female"]}}
# Some exporters write the V2 fields without the wrapper.
FLAT = {"name": "Hanabi", "description": "A strict heiress and kunoichi with charming winks and jokes.", "personality": "playful", "tags": ["Naruto"]}


# Character cards -------------------------------------------------------------
def test_reads_v2_v3_and_flat_cards_from_png():
    card = character_card.read_card(card_png({"chara": V2}))
    assert (card.name, card.spec, card.tags) == ("Mira", "chara_card_v2", ["Fantasy", "Female"])
    assert "Mira is a shy librarian who teases the viewer." in card.persona()

    v3 = {"spec": "chara_card_v3", "data": {**V2["data"], "name": "Mira V3"}}
    assert character_card.read_card(card_png({"chara": V2, "ccv3": v3})).name == "Mira V3"  # V3 wins

    flat = character_card.read_card(card_png({"chara": FLAT}))
    assert flat.name == "Hanabi" and flat.spec == "chara_card_v1" and "Personality: playful" in flat.persona()


def test_reads_cards_from_json_data_uris_and_files(tmp_path):
    assert character_card.read_card(json.dumps(V2).encode()).name == "Mira"
    data_uri = "data:image/png;base64," + base64.b64encode(card_png({"chara": V2})).decode()
    assert character_card.read_card(data_uri).name == "Mira"
    path = tmp_path / "mira.png"
    path.write_bytes(card_png({"chara": V2}))
    assert character_card.read_card(str(path)).name == "Mira"


def test_pictures_without_a_card_give_none():
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buffer, format="PNG")
    assert character_card.read_card(buffer.getvalue()) is None
    assert character_card.read_card(pil_to_b64(Image.new("RGB", (8, 8)))) is None
    assert character_card.read_card(b"not an image") is None
    assert character_card.read_card(card_png({"chara": {"description": "no name"}})) is None


# Idle motion and prompts -----------------------------------------------------
def test_idle_motion_follows_the_persona():
    shy = animation.idle_motion("A shy, timid girl who is nervous around people.", "Mira")
    assert shy.startswith("Mira idles in place") and "glances away shyly" in shy and "blinks" in shy
    assert "wink" in animation.idle_motion(FLAT["description"] + " Playful and teasing.", "Hanabi")
    assert animation.idle_motion("", "") == "The character idles in place: breathes gently, blinks naturally, and the hair and clothes sway slightly."


def test_resolve_idle_motion_uses_the_llm_and_falls_back(monkeypatch):
    card = character_card.from_json(FLAT)
    monkeypatch.setattr(animation, "look_up_character", lambda name, tags=None: None)
    monkeypatch.setattr(animation, "describe_idle_with_llm", lambda persona, **kw: "She twirls a kunai and winks.")
    assert animation.resolve_idle_motion(card, source="llm", llm={"url": "http://llm"}) == ("She twirls a kunai and winks.", "llm")
    monkeypatch.setattr(animation, "describe_idle_with_llm", lambda persona, **kw: None)
    motion, origin = animation.resolve_idle_motion(card, source="llm")
    assert origin == "card" and "Hanabi idles in place" in motion
    monkeypatch.setattr(animation, "look_up_character", lambda name, tags=None: "Hanabi is cheerful and energetic.")
    assert animation.resolve_idle_motion(card, source="web")[1] == "web"


def test_llm_call_shape(monkeypatch):
    import requests

    sent = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "<think>hmm</think> *She sways and winks.*"}}]}

    def post(url, json=None, headers=None, timeout=None):
        sent.update(url=url, body=json, headers=headers)
        return Response()

    monkeypatch.setattr(requests, "post", post)
    assert animation.describe_idle_with_llm("Name: Hanabi", url="http://localhost:11434/v1", api_key="k", model="llama3") == "She sways and winks."
    assert sent["url"] == "http://localhost:11434/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer k" and sent["body"]["model"] == "llama3"
    assert animation.describe_idle_with_llm("x", url="") is None


def test_motion_prompts():
    for name in ("joy", "anger", "surprise"):
        assert animation.motions()[name] in animation.build_motion_prompt(name)
    prompt = animation.build_motion_prompt("neutral", "She sways playfully.")
    assert "She sways playfully." in prompt and "camera is completely static" in prompt
    assert "realistic video" in animation.build_motion_prompt("joy", style="photo")
    assert len(animation.motions()) == 28


def test_settings_and_video_size():
    settings = animation.AnimationSettings.from_settings({"frames": 50, "formats": ["gif", "bogus"], "lightning": "auto"})
    assert settings.frame_count == 49 and settings.formats == ("gif",) and settings.lightning is None
    assert settings.resolved_steps(True) == 4 and settings.resolved_cfg(False) == 3.5
    assert animation.video_size(400, 600) == (480, 720)
    assert animation.video_size(1216, 832) == (704, 480)
    width, height = animation.video_size(300, 3000)
    assert height == 960 and width % 16 == 0  # very tall images are capped


# Frames ----------------------------------------------------------------------
def frames(count=5, size=(24, 32), alpha=False):
    result = []
    for index in range(count):
        frame = Image.new("RGBA" if alpha else "RGB", size, (index * 40, 100, 200, 255) if alpha else (index * 40, 100, 200))
        if alpha:
            frame.putpixel((0, 0), (0, 0, 0, 0))
        result.append(frame)
    return result


def test_save_animation_in_every_format(tmp_path):
    written = animation.save_animation(frames(alpha=True), tmp_path / "joy", fps=16, formats=("webp", "apng", "gif"))
    assert [p.name for p in written] == ["joy.webp", "joy.apng", "joy.gif"]
    for path in written:
        with Image.open(path) as image:
            assert getattr(image, "n_frames", 1) == 5, path
            first = next(ImageSequence.Iterator(image)).convert("RGBA")
            assert first.getpixel((0, 0))[3] == 0, path  # transparent stays transparent
            assert first.getpixel((5, 5))[3] == 255, path


def test_key_color_and_despill():
    green = Image.new("RGBA", (8, 8), (30, 200, 40, 255))
    assert animation.pick_key_color(green) != (0, 255, 0)
    assert animation.pick_key_color(Image.new("RGBA", (8, 8), (200, 50, 50, 255))) == (0, 255, 0)
    # Half the character's orange, half the green key: the green share comes back out.
    edge = Image.new("RGBA", (2, 1))
    edge.putpixel((0, 0), (100, 178, 25, 128))
    edge.putpixel((1, 0), (200, 100, 50, 255))
    fixed = animation.despill(edge, (0, 255, 0))
    assert abs(fixed.getpixel((0, 0))[1] - 100) <= 3
    assert fixed.getpixel((1, 0)) == (200, 100, 50, 255)


def test_remove_background_frames_smooths_alpha_over_time(monkeypatch):
    from autoexpress_core import background

    def cut(image, model):
        value = 255 if image.getpixel((0, 0))[0] % 80 == 0 else 0  # every other frame flickers
        result = image.convert("RGBA")
        result.putalpha(value)
        return result

    monkeypatch.setattr(background, "remove_background", cut)
    result = animation.remove_background_frames(frames(4), "isnet-anime")
    alphas = [frame.getpixel((3, 3))[3] for frame in result]
    assert all(0 < a < 255 for a in alphas)  # averaged with its neighbours, wrapping around


class FakeAnimator:
    def __init__(self, count=5):
        self.count = count
        self.calls = []
        self.last_error = None

    def animate(self, image, prompt, negative, settings):
        self.calls.append((image, prompt, settings))
        return [Image.new("RGB", (48, 64), (0, 255, 0)) for _ in range(self.count)]


def test_animate_sprite_loops_and_matches_the_still():
    backend = FakeAnimator()
    still = Image.new("RGB", (24, 32), (200, 50, 50))
    result = animation.animate_sprite(backend, still, "neutral", animation.AnimationSettings(idle_motion="She hums."))
    assert len(result) == 4 and result[0].size == (24, 32)  # last (= first) frame dropped, scaled back
    assert "She hums." in backend.calls[0][1]


def test_animate_sprite_keeps_transparent_stills_transparent(monkeypatch):
    from autoexpress_core import background

    monkeypatch.setattr(background, "remove_background", lambda image, model: image.convert("RGBA"))
    backend = FakeAnimator()
    still = Image.new("RGBA", (24, 32), (200, 50, 50, 255))
    still.putpixel((0, 0), (0, 0, 0, 0))
    result = animation.animate_sprite(backend, still, "joy", animation.AnimationSettings(), background_model="isnet-anime")
    sent = Image.open(io.BytesIO(base64.b64decode(backend.calls[0][0].split(",", 1)[1])))
    assert sent.mode == "RGB" and sent.getpixel((0, 0)) == (0, 255, 0)  # animated on the key color
    assert "flat single-color background" in backend.calls[0][1]
    assert result[0].mode == "RGBA"


def test_animate_sprite_raises_with_the_backend_error():
    class Broken(FakeAnimator):
        def animate(self, *args):
            self.last_error = RuntimeError("out of memory")
            return None

    with pytest.raises(RuntimeError, match="out of memory"):
        animation.animate_sprite(Broken(), Image.new("RGB", (8, 8)), "joy", animation.AnimationSettings())


# ComfyUI ---------------------------------------------------------------------
def wan_routes(lightning=True):
    combo = lambda *options: [list(options)]  # noqa: E731
    loras = ["wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors", "wan2.2_i2v_lightx2v_4steps_lora_v1_low_noise.safetensors"] if lightning else ["other.safetensors"]
    info = {
        "UNETLoader": {"input": {"required": {"unet_name": combo("wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors", "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors"), "weight_dtype": combo("default")}}},
        "CLIPLoader": {"input": {"required": {"clip_name": combo("umt5_xxl_fp8_e4m3fn_scaled.safetensors"), "type": combo("stable_diffusion", "wan")}, "optional": {"device": combo("default")}}},
        "VAELoader": {"input": {"required": {"vae_name": combo("wan_2.1_vae.safetensors")}}},
        "LoraLoaderModelOnly": {"input": {"required": {"model": ["MODEL"], "lora_name": combo(*loras), "strength_model": ["FLOAT", {"default": 1.0}]}}},
        "ModelSamplingSD3": {"input": {"required": {"model": ["MODEL"], "shift": ["FLOAT", {"default": 3.0}]}}},
        "KSamplerAdvanced": {"input": {"required": {name: ["ANY"] for name in ("model", "add_noise", "noise_seed", "steps", "cfg", "sampler_name", "scheduler", "positive", "negative", "latent_image", "start_at_step", "end_at_step", "return_with_leftover_noise")}}},
        "WanFirstLastFrameToVideo": {
            "input": {
                "required": {name: ["ANY"] for name in ("positive", "negative", "vae", "width", "height", "length", "batch_size")},
                "optional": {name: ["ANY"] for name in ("clip_vision_start_image", "clip_vision_end_image", "start_image", "end_image")},
            }
        },
        "CLIPTextEncode": {"input": {"required": {"text": ["STRING", {}], "clip": ["CLIP"]}}},
        "VAEDecode": {"input": {"required": {"samples": ["LATENT"], "vae": ["VAE"]}}},
        "LoadImage": {"input": {"required": {"image": combo("x.png")}}},
    }
    history = {
        "p1": {
            "status": {"status_str": "success", "completed": True, "messages": []},
            "outputs": {"output": {"images": [{"filename": f"frame_{i}.png", "subfolder": "", "type": "temp"} for i in range(3)]}},
        }
    }
    routes = comfy_routes(history)
    routes.update({f"GET /object_info/{node}": {node: spec} for node, spec in info.items()})
    return routes


def test_comfyui_builds_the_wan_workflow():
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(wan_routes())
    assert backend.can_animate and backend.check_ready("animate") == (True, "ok")

    still = Image.new("RGB", (400, 600))
    result = backend.animate(pil_to_b64(still), "She waves.", "static", animation.AnimationSettings(seed=3))
    assert len(result) == 3  # every frame of the PreviewImage node

    workflow = next(kw["json"]["prompt"] for m, p, kw in backend.session.calls if p == "/prompt")
    assert workflow["high_unet"]["inputs"]["unet_name"].startswith("wan2.2_i2v_high_noise")
    assert workflow["low_unet"]["inputs"]["unet_name"].startswith("wan2.2_i2v_low_noise")
    assert workflow["high_lightning"]["inputs"]["lora_name"].endswith("high_noise.safetensors")
    assert workflow["clip"]["inputs"]["type"] == "wan"
    video = workflow["video"]["inputs"]
    assert (video["width"], video["height"], video["length"]) == (480, 720, 49)
    assert video["start_image"] == video["end_image"] == ["image", 0]  # loops
    high, low = workflow["sample_high"]["inputs"], workflow["sample_low"]["inputs"]
    assert (high["steps"], high["cfg"], high["end_at_step"], low["start_at_step"]) == (4, 1.0, 2, 2)
    assert high["noise_seed"] == low["noise_seed"] == 3
    assert low["latent_image"] == ["sample_high", 0] and low["add_noise"] == "disable"
    assert workflow["positive"]["inputs"]["text"] == "She waves."


def test_comfyui_wan_without_lightning_and_missing_files():
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(wan_routes(lightning=False))
    backend.animate(pil_to_b64(Image.new("RGB", (64, 64))), "x", "y", animation.AnimationSettings(loop=False))
    workflow = next(kw["json"]["prompt"] for m, p, kw in backend.session.calls if p == "/prompt")
    assert "high_lightning" not in workflow and workflow["sample_high"]["inputs"]["steps"] == 20
    assert "end_image" not in workflow["video"]["inputs"]

    routes = wan_routes()
    routes["GET /object_info/UNETLoader"]["UNETLoader"]["input"]["required"]["unet_name"] = [["flux1-dev.safetensors"]]
    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(routes)
    ok, message = backend.check_ready("animate")
    assert not ok and "wan2.2_i2v_high_noise_14B_fp8_scaled" in message and "autoexpress_core.animation download" in message
    report = {item.key: item for item in backend.animate_capabilities()}
    assert report["wan_nodes"].ok and not report["wan_models"].ok and not report["wan_models"].required


def test_missing_models_lists_the_wan_files(tmp_path):
    (tmp_path / "models").mkdir()
    names = [model.name for model in animation.missing_models(tmp_path)]
    assert "wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors" in names and len(names) == 6
    assert animation.main(["check", str(tmp_path)]) == 1


def test_key_out_clears_leftover_key_color():
    frame = Image.new("RGBA", (3, 1))
    frame.putdata([(250, 5, 250, 255), (200, 60, 190, 255), (30, 40, 50, 255)])
    keyed = animation.key_out(frame, (255, 0, 255))
    assert [keyed.getpixel((x, 0))[3] for x in range(3)] == [0, 217, 255]
    assert animation.key_distance(Image.new("RGB", (4, 4), (0, 255, 0)), (0, 255, 0)) == 0
