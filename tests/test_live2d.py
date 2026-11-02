"""Live2D model kits: PSD writer, layer naming, blink/mouth art, model files, guidance, Civitai lookup, pipeline, API."""

import io
import json
import zipfile

import pytest
from PIL import Image, ImageDraw

from autoexpress_core.backends.comfyui_api import ComfyUIClient
from autoexpress_core.images import b64_to_pil, pil_to_b64
from autoexpress_core.live2d import DECOMPOSE, character_lora, guidance, kit, layers, model_files, psd

from test_remote_backends import ComfySession, FakeResponse, comfy_routes

psd_tools = pytest.importorskip("psd_tools")


# Helpers --------------------------------------------------------------------
def blob(size, box, color, shape="ellipse"):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    getattr(draw, shape)(box, fill=color)
    return image


def character(size=(400, 400), eyes_closed=False, mouth_open=False) -> Image.Image:
    """A simple drawn character on white: back hair, face, eyes, mouth, front hair, body."""
    image = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(image)
    draw.rectangle((140, 260, 260, 399), fill=(60, 90, 160))  # body
    draw.ellipse((110, 60, 290, 280), fill=(70, 40, 30))  # back hair
    draw.ellipse((135, 90, 265, 250), fill=(250, 220, 200))  # face
    for x in (165, 215):
        if eyes_closed:
            draw.line((x, 160, x + 22, 160), fill=(40, 20, 20), width=3)
        else:
            draw.ellipse((x, 145, x + 22, 175), fill=(255, 255, 255))
            draw.ellipse((x + 5, 150, x + 17, 172), fill=(40, 90, 200))
    if mouth_open:
        draw.ellipse((188, 205, 212, 228), fill=(140, 30, 40))
    else:
        draw.line((190, 212, 210, 212), fill=(150, 60, 60), width=2)
    draw.rectangle((130, 70, 270, 110), fill=(80, 50, 35))  # fringe
    return image


def seethrough_parts(canvas=400):
    """What See-through would return for character(): tags, full-canvas layers, depths (lower is nearer)."""
    size = (canvas, canvas)
    return [
        layers.Part("front hair", blob(size, (130, 70, 270, 110), (80, 50, 35, 255), "rectangle"), 0, 0, 0.2),
        layers.Part("face", blob(size, (135, 90, 265, 250), (250, 220, 200, 255)), 0, 0, 0.5),
        layers.Part("eyewhite-r", blob(size, (165, 145, 187, 175), (255, 255, 255, 255)), 0, 0, 0.45),
        layers.Part("irides-r", blob(size, (170, 150, 182, 172), (40, 90, 200, 255)), 0, 0, 0.44),
        layers.Part("eyewhite-l", blob(size, (215, 145, 237, 175), (255, 255, 255, 255)), 0, 0, 0.45),
        layers.Part("irides-l", blob(size, (220, 150, 232, 172), (40, 90, 200, 255)), 0, 0, 0.44),
        layers.Part("mouth", blob(size, (190, 210, 210, 214), (150, 60, 60, 255), "rectangle"), 0, 0, 0.46),
        layers.Part("topwear", blob(size, (140, 260, 260, 399), (60, 90, 160, 255), "rectangle"), 0, 0, 0.6),
        layers.Part("back hair", blob(size, (110, 60, 290, 280), (70, 40, 30, 255)), 0, 0, 0.9),
        layers.Part("head", blob(size, (110, 60, 290, 280), (1, 1, 1, 255)), 0, 0, 0.5),
    ]


# PSD writer -------------------------------------------------------------------
def test_psd_round_trips_through_psd_tools(tmp_path):
    eye = blob((30, 30), (0, 0, 29, 29), (0, 0, 255, 200))
    body = Image.new("RGBA", (60, 40), (255, 0, 0, 255))
    nodes = [
        psd.Group("Face", [psd.Layer("Eye L", eye, 10, 10), psd.Layer("Eye L closed", eye, 50, 10, visible=False), psd.Group("Inner", [psd.Layer("Skin", body)])]),
        psd.Layer("Body", body, 20, 50),
        psd.Layer("Empty", Image.new("RGBA", (5, 5))),
        psd.Layer("Off canvas", body, -100, -100),
        psd.Layer("名前", body, 90, 110),
    ]
    path = tmp_path / "test.psd"
    psd.write_psd(path, nodes, (100, 120))
    document = psd_tools.PSDImage.open(path)
    assert document.size == (100, 120)
    found = {layer.name: layer for layer in document.descendants()}
    assert found["Face"].is_group() and found["Inner"].is_group()
    assert found["Eye L"].bbox == (10, 10, 40, 40) and found["Eye L"].visible
    assert not found["Eye L closed"].visible
    assert found["Body"].bbox == (20, 50, 80, 90)
    assert found["名前"].bbox == (90, 110, 100, 120)  # unicode name, clipped to the canvas
    assert found["Empty"].bbox == (0, 0, 0, 0)
    # Top to bottom order: Face above Body.
    top_level = [layer.name for layer in document]
    assert top_level.index("Face") > top_level.index("Body")  # psd-tools lists bottom first
    composite = document.composite()
    assert composite.getpixel((25, 15))[2] > 150  # the eye over the skin


# Layer naming ------------------------------------------------------------------
@pytest.mark.parametrize(
    "tag, expected",
    [
        ("irides-l", ("Eye L", "Iris L", 2)),
        ("eyewhite-r", ("Eye R", "Eye white R", 3)),
        ("eyelash-l", ("Eye L", "Eyelash L", 1)),
        ("browr", ("Face", "Eyebrow R", 1)),
        ("eyel", ("Eye L", "Eye L", 2)),
        ("hairf", ("Front hair", "Front hair", 0)),
        ("back hair", ("Back hair", "Back hair", 0)),
        ("handwear-r", ("Body", "Arm R", 0)),
        ("ears-l", ("Ears", "Ear L", 1)),
        ("mouth", ("Mouth", "Mouth", 1)),
        ("whiskers", ("Other", "Whiskers", 0)),
    ],
)
def test_classify_names_see_through_tags_for_cubism(tag, expected):
    assert layers.classify(tag) == expected


def test_build_tree_orders_groups_and_keeps_features_on_the_face():
    tree, manifest = layers.build_tree(seethrough_parts())
    names = [group.name for group in tree]
    assert names[0] == "Front hair" and names[-1] == "Back hair"
    assert names.index("Eye L") < names.index("Face") and names.index("Mouth") < names.index("Face")
    assert names.index("Face") < names.index("Body")
    eye = next(group for group in tree if group.name == "Eye L")
    assert [layer.name for layer in eye.children] == ["Iris L", "Eye white L"]
    assert "Other" not in names  # the whole-head layer is dropped when the face was split
    missing = {item["part"] for item in manifest["missing"]}
    assert missing == set()  # everything expected was found


def test_build_tree_reports_missing_parts():
    parts = [part for part in seethrough_parts() if not part.tag.startswith(("eyewhite-l", "irides-l", "mouth"))]
    _, manifest = layers.build_tree(parts)
    assert {item["part"] for item in manifest["missing"]} == {"Eye L", "Mouth"}


def test_edit_overlays_cut_the_changed_eyes_and_mouth():
    parts = seethrough_parts()
    base = character().convert("RGBA")
    overlays = layers.edit_overlays(parts, base, character(eyes_closed=True).convert("RGBA"), character(mouth_open=True).convert("RGBA"))
    found = {overlay.name: overlay for overlay in overlays}
    assert set(found) == {"Eye L closed", "Eye R closed", "Mouth open"}
    assert found["Eye L closed"].group == "Eye L" and found["Eye L closed"].parameter == "ParamEyeLOpen"
    assert found["Eye L closed"].left >= 200  # the character's left eye is on the right of the picture
    mouth = found["Mouth open"]
    assert mouth.parameter == "ParamMouthOpenY" and mouth.top <= 207 and mouth.top + mouth.image.height >= 226

    tree, manifest = layers.build_tree(parts, overlays)
    eye = next(group for group in tree if group.name == "Eye L")
    assert eye.children[0].name == "Eye L closed" and not eye.children[0].visible  # on top, hidden
    assert {s["layer"] for s in manifest["switches"]} == set(found)


def test_edit_overlays_ignore_unchanged_and_whole_picture_edits():
    parts = seethrough_parts()
    base = character().convert("RGBA")
    assert layers.edit_overlays(parts, base, base.copy(), None) == []
    shifted = Image.new("RGBA", base.size, (0, 0, 0, 255))  # everything changed: not a feature edit
    assert layers.edit_overlays(parts, base, shifted, shifted) == []


def test_square_placement_matches_see_through_padding():
    assert layers.square_placement((400, 800), 1280) == (320, 0, 960, 1280)
    assert layers.square_placement((1000, 500), 1000) == (0, 250, 1000, 750)
    assert layers.SplitSettings.from_settings({"resolution": 1300, "steps": "99"}) == layers.SplitSettings(resolution=1280, steps=60)


# Model files ---------------------------------------------------------------------
def test_expressions_cover_the_28_emotions_on_standard_parameters():
    assert len(model_files.EMOTIONS) == 28
    joy = model_files.build_expression("joy")
    assert joy["Type"] == "Live2D Expression"
    params = {item["Id"]: item for item in joy["Parameters"]}
    assert params["ParamEyeLSmile"]["Value"] == params["ParamEyeRSmile"]["Value"] == 1.0
    assert params["ParamEyeLOpen"]["Blend"] == "Multiply" and params["ParamMouthForm"]["Blend"] == "Add"
    assert model_files.build_expression("neutral")["Parameters"] == []
    # The characters react, they don't talk: only surprise and realization part the lips.
    talking = [e for e in model_files.EMOTIONS if "ParamMouthOpenY" in model_files.expression_parameters(e)]
    assert sorted(talking) == ["realization", "surprise"]
    limited = model_files.build_expression("joy", parameters={"ParamMouthForm"})
    assert [item["Id"] for item in limited["Parameters"]] == ["ParamMouthForm"]


def test_motion3_counts_match_the_curves():
    for emotion in model_files.EMOTIONS:
        motion = model_files.reaction_motion(emotion)
        if emotion == "neutral":
            assert motion is None
            continue
        meta = motion["Meta"]
        assert meta["CurveCount"] == len(motion["Curves"]) > 0
        segments = points = 0
        for curve in motion["Curves"]:
            data = curve["Segments"]
            index, curve_points = 2, 1
            while index < len(data):
                kind = data[index]
                assert kind == 1  # bezier
                index += 7
                segments += 1
                curve_points += 3
            assert index == len(data)
            points += curve_points
            times = data[0::1]
            assert data[0] == 0
        assert (meta["TotalSegmentCount"], meta["TotalPointCount"]) == (segments, points)
        assert not meta["Loop"] and meta["Duration"] > 0
    idle = model_files.idle_motion()
    assert idle["Meta"]["Loop"] and idle["Meta"]["Duration"] == 6.4


def test_sillytavern_settings_map_every_emotion():
    settings = model_files.sillytavern_settings()
    # Every key the extension's own defaults have, since it replaces them with this file.
    for key in ("scale", "x", "y", "eye", "cursor_param", "param_mouth_open_y_id", "mouth_open_speed", "mouth_time_per_character",
                "animation_starter", "animation_default", "animation_click", "hit_areas", "classify_mapping"):
        assert key in settings
    assert settings["classify_mapping"]["joy"] == {"expression": "joy", "motion": "joy_id=0"}
    assert settings["classify_mapping"]["neutral"] == {"expression": "neutral", "motion": "none"} or "neutral" in settings["classify_mapping"]
    assert settings["cursor_param"]["idParamAngleX"] == "ParamAngleX"
    limited = model_files.sillytavern_settings(parameters={"ParamAngleX"})
    assert limited["cursor_param"]["idParamBreath"] == "none" and limited["param_mouth_open_y_id"] == "none"


def test_attach_to_model_registers_expressions_and_motions(tmp_path):
    folder = tmp_path / "hinata"
    folder.mkdir()
    model3 = {
        "Version": 3,
        "FileReferences": {
            "Moc": "hinata.moc3",
            "Textures": ["hinata.2048/texture_00.png"],
            "DisplayInfo": "hinata.cdi3.json",
            "Expressions": [{"Name": "custom", "File": "custom.exp3.json"}, {"Name": "joy", "File": "old_joy.exp3.json"}],
            "Motions": {"TapBody": [{"File": "tap.motion3.json"}]},
        },
        "Groups": [{"Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen"]}],
    }
    (folder / "hinata.model3.json").write_text(json.dumps(model3))
    params = ["ParamAngleX", "ParamAngleY", "ParamAngleZ", "ParamEyeLOpen", "ParamEyeROpen", "ParamMouthForm", "ParamMouthOpenY", "ParamBreath"]
    (folder / "hinata.cdi3.json").write_text(json.dumps({"Version": 3, "Parameters": [{"Id": p, "Name": p} for p in params]}))

    summary = model_files.attach_to_model(folder)
    assert summary["expressions"] == 28 and summary["parameters"].startswith("from the model")
    result = json.loads((folder / "hinata.model3.json").read_text())
    names = [item["Name"] for item in result["FileReferences"]["Expressions"]]
    assert names[0] == "custom" and names.count("joy") == 1 and len(names) == 29
    motions = result["FileReferences"]["Motions"]
    assert "TapBody" in motions and "Idle" in motions and "joy" in motions
    assert [g["Name"] for g in result["Groups"]] == ["EyeBlink", "LipSync"]  # existing EyeBlink kept
    joy = json.loads((folder / "expressions" / "joy.exp3.json").read_text())
    assert {item["Id"] for item in joy["Parameters"]} <= set(params)  # only parameters the model has
    settings = json.loads((folder / "sillytavern_settings.json").read_text())
    assert settings["classify_mapping"]["sadness"]["motion"] == "sadness_id=0"
    assert settings["cursor_param"]["idParamEyeBallX"] == "none"  # not in the model
    assert (folder / "hinata.model3.json.bak").exists()

    with pytest.raises(FileNotFoundError):
        model_files.attach_to_model(tmp_path)


# Guidance -------------------------------------------------------------------------
def test_check_image_scores_good_and_poor_pictures():
    good = character((1400, 1400))
    poor = Image.effect_noise((300, 200), 80).convert("RGB")
    good_report, poor_report = guidance.check_image(good), guidance.check_image(poor)
    assert good_report["score"] > poor_report["score"]
    assert all(check["ok"] for check in good_report["checks"] if check["id"] in ("resolution", "background"))
    poor_ids = {check["id"]: check for check in poor_report["checks"]}
    assert not poor_ids["resolution"]["ok"] and poor_ids["resolution"]["level"] == "error"
    assert not poor_ids["background"]["ok"]
    ranked = guidance.rank_images([poor, good])
    assert ranked[0][0] == 1


def test_check_image_flags_cut_off_and_several_characters():
    image = Image.new("RGBA", (1300, 1300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.ellipse((0, 300, 500, 1200), fill=(200, 100, 100, 255))
    draw.ellipse((700, 300, 1200, 1200), fill=(100, 100, 200, 255))
    ids = {check["id"]: check for check in guidance.check_image(image)["checks"]}
    assert ids["background"]["ok"]  # transparent
    assert not ids["cropped"]["ok"] and "left" in ids["cropped"]["message"]
    assert not ids["characters"]["ok"]


# Civitai ------------------------------------------------------------------------
CIVITAI = {
    "items": [
        {
            "id": 1, "name": "Hinata Hyuga | Naruto", "type": "LORA", "stats": {"downloadCount": 9000},
            "modelVersions": [
                {"id": 11, "baseModel": "Pony", "trainedWords": ["hinata"], "files": [{"name": "hinata_pony.safetensors", "primary": True, "sizeKB": 2048, "hashes": {"SHA256": "AA"}}]},
                {"id": 12, "baseModel": "Illustrious", "trainedWords": ["hyuuga hinata", "lavender eyes", "x", "y"], "files": [{"name": "Hinata IL v2.safetensors", "primary": True, "sizeKB": 4096, "hashes": {"SHA256": "BB"}}]},
            ],
        },
        {"id": 2, "name": "Naruto style", "type": "LORA", "stats": {"downloadCount": 99999}, "modelVersions": [{"id": 21, "baseModel": "Illustrious", "files": [{"name": "style.safetensors"}]}]},
        {"id": 3, "name": "Hinata Hyuga (Boruto)", "type": "LORA", "stats": {"downloadCount": 10}, "modelVersions": [{"id": 31, "baseModel": "SD 1.5", "files": [{"name": "h15.safetensors"}]}]},
    ]
}


def test_character_lora_search_picks_the_matching_base_model():
    calls = []
    found = character_lora.search("Hinata Hyuga", "illustrious", api_key="k", fetch=lambda url, headers: calls.append((url, headers)) or CIVITAI)
    assert "query=Hinata+Hyuga" in calls[0][0] and "types=LORA" in calls[0][0] and calls[0][1]["Authorization"] == "Bearer k"
    assert [entry["civitai_version_id"] for entry in found] == [12]  # the style LoRA doesn't name her, the SD 1.5 one doesn't fit
    entry = found[0]
    assert entry["name"] == "Hinata_IL_v2" and entry["sha256"] == "bb" and entry["trigger"] == "hyuuga hinata, lavender eyes, x"
    assert character_lora.lora_tag(entry, "hinata_il") == "<lora:hinata_il:0.8>, hyuuga hinata, lavender eyes, x"
    assert [e["civitai_version_id"] for e in character_lora.search("Hinata Hyuga", "sd15", fetch=lambda u, h: CIVITAI)] == [31]
    assert character_lora.search("", "sdxl", fetch=lambda u, h: CIVITAI) == []


# Pipeline -----------------------------------------------------------------------
class FakeBackend:
    label = "Fake"
    kind = "fake"
    edit_methods = ("inpaint", "instruct")
    can_decompose = True

    def __init__(self):
        self.last_error = None
        self.calls = []

    def check_ready(self, method):
        self.calls.append(("ready", method))
        return True, "ok"

    def instruction_edit(self, image, instruction, settings):
        self.calls.append(("edit", instruction))
        size = b64_to_pil(image).size
        return character(size, eyes_closed="Close both eyes" in instruction, mouth_open="Open the mouth" in instruction)

    def img2img(self, payload):
        self.calls.append(("inpaint", payload))
        return None

    def interrupt(self):
        pass

    def decompose_layers(self, image, settings):
        self.calls.append(("split", settings))
        picture = b64_to_pil(image)
        assert picture.size == (400, 400) and settings.resolution == 1024
        # See-through works on a square canvas at its resolution; the picture is already square here.
        scale = settings.resolution / 400
        parts = []
        for part in seethrough_parts():
            scaled = part.image.resize((int(part.image.width * scale), int(part.image.height * scale)))
            parts.append(layers.Part(part.tag, scaled, 0, 0, part.depth))
        return parts, (settings.resolution, settings.resolution)


def test_build_kit_writes_the_whole_kit(tmp_path):
    backend = FakeBackend()
    result = kit.build_kit(backend, [character((300, 200)), character()], tmp_path, "hina", {"resolution": 1024}, log=lambda _: None)
    assert ("ready", DECOMPOSE) in backend.calls
    assert sum(1 for call in backend.calls if call[0] == "edit") == 2  # eyes closed, mouth open (Qwen: no character LoRA)
    folder = result.folder
    for name in ("hina.psd", "hina_seethrough.psd", "preview.png", "sheet.jpg", "README.txt", "manifest.json", "input.png", "eyes_closed.png", "mouth_open.png",
                 "runtime/sillytavern_settings.json", "runtime/expressions/joy.exp3.json", "runtime/motions/idle.motion3.json"):
        assert (folder / name).exists(), name
    manifest = result.manifest
    assert manifest["picture"]["index"] == 1  # the bigger picture scored better
    assert manifest["canvas"] == [1024, 1024]
    assert {s["layer"] for s in manifest["switches"]} == {"Eye L closed", "Eye R closed", "Mouth open"}
    document = psd_tools.PSDImage.open(folder / "hina.psd")
    groups = [layer.name for layer in document if layer.is_group()]
    assert "Eye L" in groups and "Front hair" in groups
    flat = psd_tools.PSDImage.open(folder / "hina_seethrough.psd")
    assert {layer.name for layer in flat} >= {"front hair", "irides-l", "back hair"}
    with zipfile.ZipFile(result.zip_path) as archive:
        assert "hina/hina.psd" in archive.namelist() and "hina/runtime/expressions/sadness.exp3.json" in archive.namelist()


def test_build_kit_uses_face_inpainting_with_an_installed_character_lora(tmp_path):
    class Inpainter(FakeBackend):
        def img2img(self, payload):
            self.calls.append(("inpaint", payload))
            prompt = json.dumps(payload)
            size = b64_to_pil(payload["init_images"][0]).size
            return character(size, eyes_closed="closed eyes" in prompt, mouth_open="open mouth" in prompt)

    backend = Inpainter()
    lora = {"entry": {"name": "Hinata_IL_v2", "weight": 0.8, "trigger": "hyuuga hinata"}, "installed_name": "hinata_il"}
    result = kit.build_kit(backend, [character()], tmp_path, "h", {"resolution": 1024, "ad_prompt": "1girl"}, character_lora=lora)
    prompts = [json.dumps(call[1]) for call in backend.calls if call[0] == "inpaint"]
    assert len(prompts) == 2 and all("<lora:hinata_il:0.8>, hyuuga hinata" in p for p in prompts)
    assert result.manifest["variants"]["method"] == "inpaint"


def test_build_kit_notes_failed_edits_and_can_skip_them(tmp_path):
    class NoEdits(FakeBackend):
        def instruction_edit(self, image, instruction, settings):
            self.last_error = RuntimeError("out of memory")
            return None

    result = kit.build_kit(NoEdits(), [character()], tmp_path, "a", {"resolution": 1024})
    assert any("out of memory" in note for note in result.manifest["notes"])
    assert "switches" not in result.manifest
    result = kit.build_kit(FakeBackend(), [character()], tmp_path, "b", {"resolution": 1024, "variants": "none"})
    assert result.manifest["variants"]["method"] is None


# ComfyUI ------------------------------------------------------------------------
SEETHROUGH_INFO = {
    "SeeThrough_LoadLayerDiffModel": {"input": {"required": {"model": [["layerdifforg/seethroughv0.0.2_layerdiff3d", "24yearsold/seethroughv0.0.2_layerdiff3d_nf4"]]}, "optional": {"quant_mode": [["none", "nf4"]], "cache_tag_embeds": ["BOOLEAN"], "group_offload": ["BOOLEAN"], "auto_download": ["BOOLEAN"]}}},
    "SeeThrough_LoadDepthModel": {"input": {"required": {"model": [["seethroughv0.0.1_marigold", "layerdifforg/seethroughv0.0.1_marigold", "24yearsold/seethroughv0.0.1_marigold_nf4"]]}, "optional": {"quant_mode": [["none", "nf4"]]}}},
    "SeeThrough_GenerateLayers": {"input": {"required": {"image": ["IMAGE"], "layerdiff_model": ["M"], "seed": ["INT"], "resolution": ["INT"], "num_inference_steps": ["INT"]}}},
    "SeeThrough_GenerateDepth": {"input": {"required": {"layers": ["L"], "depth_model": ["D"], "seed": ["INT"]}, "optional": {"resolution_depth": ["INT"]}}},
    "SeeThrough_PostProcess": {"input": {"required": {"layers_depth": ["L"], "tblr_split": ["BOOLEAN"], "use_lama": ["BOOLEAN"], "new_required": ["INT", {"default": 5}]}}},
    "SeeThrough_SavePSD": {"input": {"required": {"parts": ["P"], "filename_prefix": ["STRING"]}}},
    "LoadImage": {"input": {"required": {"image": [["x.png"]]}}},
}


def seethrough_session(prefix_holder):
    routes = comfy_routes({"p1": {"status": {"status_str": "success", "completed": True, "messages": []}, "outputs": {}}})
    routes.update({f"GET /object_info/{node}": {node: spec} for node, spec in SEETHROUGH_INFO.items()})

    class Session(ComfySession):
        def request(self, method, url, timeout=None, **kwargs):
            if method == "POST" and url.endswith("/prompt"):
                prefix_holder.append(kwargs["json"]["prompt"]["save"]["inputs"]["filename_prefix"])
            if "/view" in url:
                self.calls.append((method, "/view", kwargs))
                name = kwargs["params"]["filename"]
                prefix = prefix_holder[-1]
                if name == "seethrough_psd_info.log":
                    return FakeResponse(None, 200, content=f"{prefix}_t_u_layers.json".encode())
                if name.endswith("_layers.json"):
                    info = {"width": 1280, "height": 1280, "layers": [
                        {"name": "face", "filename": f"{prefix}_face.png", "left": 100, "top": 50, "right": 200, "bottom": 150, "depth_median": 0.5},
                        {"name": "irides-l", "filename": f"{prefix}_irides-l.png", "left": 160, "top": 90, "right": 170, "bottom": 100, "depth_median": 0.4},
                    ]}
                    return FakeResponse(None, 200, content=json.dumps(info).encode())
                buffer = io.BytesIO()
                Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(buffer, format="PNG")
                return FakeResponse(None, 200, content=buffer.getvalue())
            return super().request(method, url, timeout, **kwargs)

    return Session(routes)


def test_comfyui_splits_layers_with_see_through():
    prefixes = []
    backend = ComfyUIClient(poll_interval=0)
    backend.session = seethrough_session(prefixes)
    assert backend.can_decompose and backend.check_ready(DECOMPOSE) == (True, "ok")
    parts, size = backend.decompose_layers(pil_to_b64(Image.new("RGB", (64, 64))), layers.SplitSettings(seed=7))
    assert size == (1280, 1280)
    assert [(p.tag, p.left, p.top, p.depth) for p in parts] == [("face", 100, 50, 0.5), ("irides-l", 160, 90, 0.4)]
    workflow = next(kw["json"]["prompt"] for m, p, kw in backend.session.calls if p == "/prompt")
    assert workflow["layerdiff"]["inputs"]["model"] == "layerdifforg/seethroughv0.0.2_layerdiff3d"
    assert workflow["depth_model"]["inputs"]["model"] == "seethroughv0.0.1_marigold"  # the local copy
    assert "group_offload" not in workflow["depth_model"]["inputs"]  # this version doesn't take it
    assert workflow["layers"]["inputs"]["seed"] == 7 and workflow["layers"]["inputs"]["resolution"] == 1280
    assert workflow["post"]["inputs"]["new_required"] == 5  # filled from object_info
    assert workflow["save"]["inputs"]["filename_prefix"].startswith("autoexpress_live2d_")


def test_comfyui_low_vram_uses_the_4bit_models_and_reports_missing_nodes():
    backend = ComfyUIClient(poll_interval=0)
    backend.session = seethrough_session([])
    workflow = backend.build_decompose_workflow("x.png", "p", layers.SplitSettings(low_vram=True))
    assert workflow["layerdiff"]["inputs"]["model"].endswith("_nf4") and workflow["layerdiff"]["inputs"]["quant_mode"] == "nf4"

    backend = ComfyUIClient(poll_interval=0)
    backend.session = ComfySession(comfy_routes({}))
    ok, message = backend.check_ready(DECOMPOSE)
    assert not ok and "ComfyUI-See-through" in message
    assert backend.last_error.fix.commands
    report = {item.key: item for item in backend.decompose_capabilities()}
    assert not report["seethrough_nodes"].ok and not report["seethrough_nodes"].required


def test_comfyui_refuses_another_jobs_layers():
    prefixes = []
    backend = ComfyUIClient(poll_interval=0)
    session = seethrough_session(prefixes)
    original = session.request

    def request(method, url, timeout=None, **kwargs):
        if "/view" in url and kwargs["params"]["filename"] == "seethrough_psd_info.log":
            return FakeResponse(None, 200, content=b"someone_else_layers.json")
        return original(method, url, timeout, **kwargs)

    session.request = request
    backend.session = session
    assert backend.decompose_layers(pil_to_b64(Image.new("RGB", (8, 8))), layers.SplitSettings()) is None
    assert "Another See-through job" in str(backend.last_error)


def test_other_backends_cant_split_layers():
    from autoexpress_core.backends.a1111_api import A1111Client

    backend = A1111Client()
    assert not backend.can_decompose
    ok, message = backend.check_ready(DECOMPOSE)
    assert not ok and "See-through" in message
