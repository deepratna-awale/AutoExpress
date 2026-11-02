"""Live2D model kits: PSD writer, layer naming, blink/mouth art, model files, guidance, Civitai lookup, pipeline, API."""

import io
import json
import zipfile

import pytest
from PIL import Image, ImageDraw

from autoexpress_core.backends.comfyui_api import ComfyUIClient
from autoexpress_core.images import b64_to_pil, pil_to_b64
from autoexpress_core.live2d import DECOMPOSE, character_lora, guidance, kit, layers, model_files, outfits, prompt_data, psd, puppet, skeleton

from test_remote_backends import ComfySession, FakeResponse, comfy_routes

psd_tools = pytest.importorskip("psd_tools")


# Helpers --------------------------------------------------------------------
def blob(size, box, color, shape="ellipse"):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    getattr(draw, shape)(box, fill=color)
    return image


def character(size=(400, 400), eyes_closed=False, mouth_open=False, outfit="clothed") -> Image.Image:
    """A simple drawn character on white: back hair, face, eyes, mouth, front hair, body (clothed, inner or nude)."""
    image = Image.new("RGB", (400, 400), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    if outfit == "clothed":
        draw.rectangle((140, 260, 260, 399), fill=(60, 90, 160))  # body
    else:
        draw.rectangle((150, 260, 250, 399), fill=(245, 215, 195))  # the body under the clothes
        if outfit == "inner":
            draw.rectangle((150, 300, 250, 330), fill=(20, 20, 20))
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
    return image.resize(size) if size != (400, 400) else image


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


def test_keep_touching_drops_pieces_away_from_the_feature():
    mask = Image.new("L", (100, 60), 0)
    draw = ImageDraw.Draw(mask)
    draw.rectangle((40, 25, 60, 35), fill=255)  # the feature
    draw.line((5, 0, 5, 59), fill=255, width=3)  # a redrawn hair strand at the edge of the box
    kept = layers.keep_touching(mask, (35, 20, 65, 40))
    assert kept.getpixel((50, 30)) == 255 and kept.getpixel((5, 30)) == 0


def test_eye_overlays_skip_the_brows_and_stray_strands():
    brow_box = (217, 133, 235, 137)
    parts = seethrough_parts() + [layers.Part("eyebrow-l", blob((400, 400), brow_box, (90, 60, 40, 255), "rectangle"), 0, 0, 0.47)]
    base = character().convert("RGBA")
    closed = character(eyes_closed=True).convert("RGBA")
    ImageDraw.Draw(base).rectangle(brow_box, fill=(90, 60, 40, 255))
    ImageDraw.Draw(closed).rectangle((brow_box[0], brow_box[1] - 1, brow_box[2], brow_box[3] + 1), fill=(10, 10, 10, 255))  # the edit redrew the brow
    ImageDraw.Draw(closed).line((239, 130, 239, 180), fill=(80, 50, 35, 255), width=2)  # and a stray strand in the box
    overlays = {overlay.name: overlay for overlay in layers.edit_overlays(parts, base, closed, None)}
    eye = overlays["Eye L closed"]
    alpha = Image.new("L", base.size, 0)
    alpha.paste(eye.image.getchannel("A"), (eye.left, eye.top))
    centre = ((brow_box[0] + brow_box[2]) // 2, (brow_box[1] + brow_box[3]) // 2)
    assert alpha.getpixel(centre) < 32
    assert alpha.getpixel((226, 160)) > 200  # the closed eye itself


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
_REAL_NEUTRAL_POSE = kit.neutral_pose


@pytest.fixture(autouse=True)
def keep_the_pose(monkeypatch):
    """The fake split wants the square test picture: the pipeline tests skip the A-pose redraw (tested on its own)."""
    monkeypatch.setattr(kit, "neutral_pose", lambda backend, picture, settings, log: (None, ""))


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
        # Small pictures are upscaled to the split's resolution first.
        assert picture.size == (1024, 1024) and settings.resolution == 1024
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
    edits = [call[1] for call in backend.calls if call[0] == "edit"]
    # Eyes closed and mouth open (Qwen: no character LoRA), angry brows, a grin and tears for the
    # strongest emotions, then the coat off for the clothing slots (half-off states fade the
    # garment instead of being drawn).
    assert len(edits) == 6 and edits[2].startswith("Make the eyebrows furious") and "grin" in edits[3] and "teary" in edits[4]
    assert edits[5].startswith("Take off only her outermost")
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
        assert "hina/puppet/hina/hina.puppet.model.json" in archive.namelist()
    with zipfile.ZipFile(result.puppet_zip) as archive:
        names = archive.namelist()
        assert {"hina/hina.puppet.model.json", "hina/sillytavern_settings.json", "hina/preview.html", "hina/puppet.js"} <= set(names)
        assert any(n.startswith("hina/textures/") for n in names) and "hina/expressions/joy.exp3.json" in names


# Puppets ---------------------------------------------------------------------------
def test_puppet_roles_cover_the_kit_layers():
    assert puppet.role_of("Eye L", "Iris L") == ("iris", "L")
    assert puppet.role_of("Eye R", "Eye R closed") == ("eye_closed", "R")
    assert puppet.role_of("Face", "Eyebrow L") == ("brow", "L")
    assert puppet.role_of("Mouth", "Mouth open") == ("mouth_open", None)
    assert puppet.role_of("Body", "Arm R") == ("arm", "R")
    assert puppet.role_of("Body", "Neck") == ("neck", None)
    assert puppet.role_of("Front hair", "Front hair") == ("front_hair", None)
    assert puppet.role_of("Other", "Whiskers") == ("body", None)


def test_build_puppet_writes_a_playable_puppet(tmp_path):
    parts = seethrough_parts()
    base = character().convert("RGBA")
    overlays = layers.edit_overlays(parts, base, character(eyes_closed=True).convert("RGBA"), character(mouth_open=True).convert("RGBA"))
    tree, manifest = layers.build_tree(parts, overlays)
    folder = tmp_path / "hina"
    document = puppet.build_puppet(tree, manifest, (400, 400), folder, "hina", parts)
    saved = puppet.load(folder / "hina.puppet.model.json")
    assert saved == document and saved["Type"] == puppet.FORMAT
    assert puppet.is_puppet("assets/live2d/hina/hina.puppet.model.json") and "model" in "hina.puppet.model.json"
    entries = saved["Layers"]
    roles = [entry["Role"] for entry in entries]
    # Drawn bottom to top: back hair first, front hair last, the closed eye above the open one.
    assert roles[0] == "back_hair" and roles[-1] == "front_hair"
    assert roles.index("eye_closed") > roles.index("iris")
    assert roles.index("mouth_open") > roles.index("face")
    for entry in entries:
        with Image.open(folder / entry["Texture"]) as texture:
            assert texture.size == (entry["Width"], entry["Height"])
        assert entry["Grid"][0] >= 2 and entry["Grid"][1] >= 2
    rig = saved["Rig"]
    assert set(rig["Eyes"]) == {"L", "R"} and rig["Eyes"]["L"]["Box"][0] > rig["Eyes"]["R"]["Box"][0]
    assert rig["Mouth"]["Open"] is not None and rig["Head"]["Pivot"][1] > rig["Head"]["Center"][1]
    names = [area["Name"] for area in saved["HitAreas"]]
    assert names[:2] == ["Face", "Head"] and names[-1] == "Body"  # most specific first
    st = json.loads((folder / "sillytavern_settings.json").read_text())
    assert st["hit_areas"]["Head"]["expression"] == saved["Reactions"]["Head"] and st["hit_areas"]["Face"]["motion"].endswith("_id=0")
    ids = {p["Id"] for p in saved["Parameters"]}
    for item in saved["FileReferences"]["Expressions"]:
        expression = json.loads((folder / item["File"]).read_text())
        assert {p["Id"] for p in expression["Parameters"]} <= ids  # every expression drives puppet parameters
    assert "Idle" in saved["FileReferences"]["Motions"]
    settings = json.loads((folder / "sillytavern_settings.json").read_text())
    assert settings["classify_mapping"]["joy"]["expression"] == "joy" and settings["param_mouth_open_y_id"] == "ParamMouthOpenY"
    assert (folder / "puppet.js").exists() and "hina.puppet.model.json" in (folder / "preview.html").read_text()


def test_puppet_from_an_existing_kit_folder(tmp_path):
    result = kit.build_kit(FakeBackend(), [character()], tmp_path, "mira", {"resolution": 1024}, log=lambda _: None)
    out = puppet.from_kit(result.folder, tmp_path / "again")
    again = puppet.load(out / "mira.puppet.model.json")
    first = puppet.load(result.folder / "puppet" / "mira" / "mira.puppet.model.json")
    assert [e["Role"] for e in again["Layers"]] == [e["Role"] for e in first["Layers"]]


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
    assert len(prompts) == 5 and all("<lora:hinata_il:0.8>, hyuuga hinata" in p for p in prompts)
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
                        {"name": "face", "filename": f"{prefix}_face.png", "left": 100, "top": 50, "right": 200, "bottom": 150, "depth_median": 0.5, "depth_filename": f"{prefix}_face_depth.png"},
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
    # The face's depth map comes along (the iris had none).
    assert parts[0].depth_map is not None and parts[0].depth_map.mode == "L" and parts[1].depth_map is None
    workflow = next(kw["json"]["prompt"] for m, p, kw in backend.session.calls if p == "/prompt")
    assert workflow["layerdiff"]["inputs"]["model"] == "layerdifforg/seethroughv0.0.2_layerdiff3d"
    assert workflow["depth_model"]["inputs"]["model"] == "seethroughv0.0.1_marigold"  # the local copy
    assert "group_offload" not in workflow["depth_model"]["inputs"]  # this version doesn't take it
    assert workflow["layers"]["inputs"]["seed"] == 7 and workflow["layers"]["inputs"]["resolution"] == 2048
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


# Cleaning the split, outfits, soft body ------------------------------------------------------
def test_solidify_makes_skin_opaque_but_keeps_the_edge():
    image = Image.new("RGBA", (10, 1), (200, 150, 140, 0))
    for x, alpha in enumerate((0, 10, 40, 80, 120, 150, 200, 255, 255, 255)):
        image.putpixel((x, 0), (200, 150, 140, alpha))
    alphas = [image.getpixel((x, 0))[3] for x in range(10)]
    solid = [layers.solidify(image).getpixel((x, 0))[3] for x in range(10)]
    assert solid[0] == 0 and solid[1] == 0  # outside stays outside
    assert 0 < solid[2] < 255 and solid[2] > alphas[2]  # the anti-aliased edge stays soft
    assert all(v == 255 for v in solid[4:])  # a half-transparent neck becomes solid
    parts = layers.solidify_parts([layers.Part("neck", image), layers.Part("irides-l", image)])
    assert parts[0].image.getpixel((5, 0))[3] == 255 and parts[1].image.getpixel((5, 0))[3] == 150


def test_hair_underlay_paints_hair_colour_under_the_bangs_above_the_brows():
    size = (400, 400)
    parts = seethrough_parts() + [layers.Part("eyebrow-l", blob(size, (215, 130, 237, 136), (60, 30, 20, 255), "rectangle"), 0, 0, 0.44)]
    underlay = layers.hair_underlay(parts, size)
    assert underlay is not None and underlay.tag == "hair underlay"
    assert underlay.top >= 60 and underlay.top + underlay.image.height <= 136  # not below the brows
    r, g, b, a = underlay.image.getpixel((underlay.image.width // 2, 10))
    assert a == 255 and abs(r - 80 * 0.85) < 25 and b < 60  # the darker hair colour
    tree, _ = layers.build_tree(parts + [underlay])
    front = next(group for group in tree if group.name == "Front hair")
    assert [layer.name for layer in front.children] == ["Front hair", "Hair underlay"]  # under the bangs, over the face
    assert puppet.role_of("Front hair", "Hair underlay") == ("hair_under", None)


def test_match_picture_cuts_collars_over_the_neck_and_fixes_grey_hair():
    size = (200, 200)
    picture = Image.new("RGB", size, (255, 255, 255))
    draw = ImageDraw.Draw(picture)
    draw.rectangle((80, 40, 120, 120), fill=(240, 200, 180))  # neck
    draw.rectangle((40, 120, 160, 199), fill=(60, 90, 160))  # shirt
    draw.rectangle((10, 20, 30, 199), fill=(70, 40, 30))  # hair at the side
    neck = layers.Part("neck", blob(size, (80, 40, 120, 130), (240, 200, 180, 255), "rectangle"), 0, 0, 0.5)
    # The split's shirt also has the back of the collar over the neck.
    shirt_image = blob(size, (40, 120, 160, 199), (60, 90, 160, 255), "rectangle")
    ImageDraw.Draw(shirt_image).rectangle((80, 80, 120, 120), fill=(50, 70, 120, 255))
    shirt = layers.Part("topwear", shirt_image, 0, 0, 0.4)
    hair = layers.Part("back hair", blob(size, (10, 20, 30, 199), (180, 180, 180, 255), "rectangle"), 0, 0, 0.9)
    fixed = {p.tag: p for p in layers.match_picture([neck, shirt, hair], picture)}
    top = fixed["topwear"]
    assert top.image.getpixel((100 - top.left, 100 - top.top))[3] == 0  # collar gone from over the neck
    assert top.image.getpixel((100 - top.left, 160 - top.top))[3] == 255  # the shirt itself stays
    r, g, b, _ = fixed["back hair"].image.getpixel((20 - fixed["back hair"].left, 100 - fixed["back hair"].top))
    assert (r, g, b) == (70, 40, 30)  # visible grey hair takes the picture's colour


def test_outfit_layers_need_an_adult_drawn_character():
    drawn = character()
    on = {"outfit_layers": True, "adult_confirmed": True}
    assert outfits.check(on, drawn, "mira") == (True, "")
    assert not outfits.check({"outfit_layers": True}, drawn)[0]  # no adult confirmation
    assert not outfits.check({}, drawn)[0]
    assert not outfits.check({**on, "is_realistic": True}, drawn)[0]
    noisy = Image.effect_noise((400, 400), 60).convert("RGB")  # grain everywhere, like a photo
    allowed, reason = outfits.check(on, noisy)
    assert not allowed and "photo" in reason
    # Safe mode off skips only the drawing check: the adult confirmation and the child check stay.
    assert outfits.check({**on, "safe_mode": False}, noisy) == (True, "")
    assert not outfits.check({"outfit_layers": True, "safe_mode": False}, drawn)[0]
    assert not outfits.check({**on, "character_description": "loli"}, drawn, safe_mode=False)[0]
    for text in ("a shy schoolgirl", "she is 15 years old", "loli", "aged 12", "a teen idol"):
        assert not outfits.check({**on, "character_description": text}, drawn)[0], text
    for text in ("a 19 year old person", "nineteen, tall", "18 years old", "an adult sorceress, 25", "Sonia, a swordswoman"):
        assert outfits.blocked_terms(text) == [], text


def test_outfit_parts_cut_the_body_and_inner_wear():
    size = (400, 400)
    parts = seethrough_parts()
    nude = character(outfit="nude").convert("RGBA")
    inner = character(outfit="inner").convert("RGBA")
    extra = outfits.outfit_parts(parts, size, nude, inner)
    assert [p.tag for p in extra] == ["nude body", "inner wear"]
    body, wear = extra
    assert body.top >= 230  # below the chin: no copy of the face
    assert body.image.getpixel((200 - body.left, 350 - body.top))[:3] == (245, 215, 195)
    assert wear.top >= 295 and wear.top + wear.image.height <= 340  # just the inner wear
    tree, _ = layers.build_tree(parts + extra)
    names = [layer.name for layer in next(g for g in tree if g.name == "Body").children]
    assert names[-2:] == ["Inner wear", "Body"]  # under the clothes: body at the bottom


class OutfitBackend(FakeBackend):
    def instruction_edit(self, image, instruction, settings):
        if "Remove all of the clothing" in instruction or "Dress " in instruction:
            self.calls.append(("edit", instruction))
            return character(b64_to_pil(image).size, outfit="nude" if "Remove" in instruction else "inner")
        return super().instruction_edit(image, instruction, settings)


def test_build_kit_with_swappable_clothing(tmp_path):
    backend = OutfitBackend()
    settings = {"resolution": 1024, "outfit_layers": True, "adult_confirmed": True, "character_description": "an adult knight", "inner_wear": "black lace"}
    result = kit.build_kit(backend, [character()], tmp_path, "mira", settings, log=lambda _: None)
    edits = [call[1] for call in backend.calls if call[0] == "edit"]
    assert any("Remove all of the clothing" in e and "an adult knight" in e for e in edits)
    assert any(e.startswith("Dress her in black lace") for e in edits)
    assert result.manifest["outfits"]["made"] == ["nude body", "inner wear"]
    folder = result.folder / "puppet" / "mira"
    document = puppet.load(folder / "mira.puppet.model.json")
    roles = [e["Role"] for e in document["Layers"]]
    assert roles.index("nude_body") < roles.index("inner") < roles.index("clothing")
    assert document["Outfits"][0] == "outfit_full" and {"outfit_inner", "outfit_nude"} <= set(document["Outfits"])
    nude = json.loads((folder / "expressions" / "outfit_nude.exp3.json").read_text())
    values = {p["Id"]: p["Value"] for p in nude["Parameters"]}
    assert values["ParamClothesOuter"] == 0 and values["ParamClothesInner"] == 0
    assert "hair_under" in roles


def test_build_kit_reads_clothing_from_prompt_data_and_changes_the_outfit(tmp_path):
    backend = OutfitBackend()
    picture = character()
    picture.info["parameters"] = "1girl, adult, office lady, grey blazer, (pencil skirt:1.2), red lace bra, <lora:x:1>\nNegative prompt: bad"
    settings = {"resolution": 1024, "outfit_layers": True, "adult_confirmed": True, "outfit_prompt": "a red kimono"}
    result = kit.build_kit(backend, [picture], tmp_path, "mira", settings, log=lambda _: None)
    edits = [call[1] for call in backend.calls if call[0] == "edit"]
    assert any(e.startswith("Change her clothes to a red kimono") for e in edits)
    assert any(e.startswith("Dress her in red lace bra") for e in edits)  # inner wear from the prompt
    assert any("Her outfit: a red kimono" in e for e in edits if "Remove all" in e)
    clothing = result.manifest["clothing"]
    assert clothing["outfit"] == "grey blazer, pencil skirt" and clothing["inner_wear"] == "red lace bra" and clothing["outfit_changed"]


def test_revealing_outfit_needs_the_clothing_check(tmp_path):
    backend = OutfitBackend()
    result = kit.build_kit(backend, [character()], tmp_path, "mira", {"resolution": 1024, "outfit_prompt": "black lingerie"}, log=lambda _: None)
    assert not any(call[1].startswith("Change") for call in backend.calls if call[0] == "edit")
    assert any("outfit wasn't changed" in note and "confirm" in note for note in result.manifest["notes"])
    picture = character()
    picture.info["parameters"] = "1girl, loli, white dress"
    settings = {"resolution": 1024, "outfit_layers": True, "adult_confirmed": True}
    result = kit.build_kit(OutfitBackend(), [picture], tmp_path, "nia", settings, log=lambda _: None)
    assert "child" in result.manifest["outfits"]["refused"]  # the prompt data is checked too


def test_prompt_data_reads_webui_metadata():
    image = Image.new("RGB", (8, 8))
    image.info["parameters"] = "masterpiece, white shirt, black_thighhighs, no bra, striped panties\nNegative prompt: nsfw\nSteps: 20"
    prompt = prompt_data.prompt_of(image)
    assert prompt.endswith("striped panties") and "Negative" not in prompt
    assert prompt_data.clothing(prompt) == ("white shirt, black thighhighs", "striped panties")
    graph = {
        "3": {"class_type": "KSampler", "inputs": {"positive": ["6", 0], "negative": ["7", 0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "1girl, sailor uniform, pleated skirt", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "lowres, bad anatomy, worst quality, extra fingers", "clip": ["4", 1]}},
    }
    image = Image.new("RGB", (8, 8))
    image.info["prompt"] = json.dumps(graph)
    assert prompt_data.prompt_of(image) == "1girl, sailor uniform, pleated skirt"
    assert prompt_data.prompt_of(Image.new("RGB", (8, 8))) == ""


def test_inner_wear_splits_into_top_and_bottom_at_the_midriff():
    size = (400, 400)
    parts = [
        layers.Part("topwear", blob(size, (140, 200, 260, 300), (60, 90, 160, 255), "rectangle"), 0, 0, 0.6),
        layers.Part("bottomwear", blob(size, (140, 300, 260, 380), (160, 40, 60, 255), "rectangle"), 0, 0, 0.6),
    ]
    two_piece = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(two_piece)
    draw.rectangle((160, 220, 240, 250), fill=(20, 20, 20, 255))  # bra
    draw.rectangle((165, 310, 235, 340), fill=(20, 20, 20, 255))  # briefs
    pieces = outfits.split_inner(two_piece, parts, size)
    assert [tag for tag, _ in pieces] == ["inner top", "inner bottom"]
    top, bottom = (piece.getchannel("A").getbbox() for _, piece in pieces)
    assert top[3] <= 260 and bottom[1] >= 300
    one_piece = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(one_piece).rectangle((160, 220, 240, 340), fill=(20, 20, 20, 255))  # a swimsuit
    assert [tag for tag, _ in outfits.split_inner(one_piece, parts, size)] == ["inner wear"]


def test_half_off_outfits_and_accessories(tmp_path):
    entries = [
        {"Role": "nude_body", "Name": "Body"},
        {"Role": "inner", "Name": "Inner top", "Garment": "inner_top", "Switch": "ParamInnerTop"},
        {"Role": "inner", "Name": "Inner bottom", "Garment": "inner_bottom", "Switch": "ParamInnerBottom"},
        {"Role": "clothing", "Name": "Topwear", "Garment": "topwear", "Switch": "ParamClothesTop"},
        {"Role": "clothing", "Name": "Bottomwear", "Garment": "bottomwear", "Switch": "ParamClothesBottom"},
        {"Role": "headwear", "Name": "Headwear", "Accessory": True},
    ]
    written = {item["Name"]: item["File"] for item in puppet.write_outfits(tmp_path, entries)}
    assert list(written) == [
        "outfit_full", "outfit_top_off", "outfit_bottom_off", "outfit_inner", "outfit_topless",
        "outfit_inner_top_off", "outfit_inner_bottom_off", "outfit_nude", "accessories_off", "accessories_on",
    ]
    topless = {p["Id"]: p["Value"] for p in json.loads((tmp_path / written["outfit_topless"]).read_text())["Parameters"]}
    assert topless["ParamClothesTop"] == 0 and topless["ParamInnerTop"] == 0
    assert topless["ParamClothesBottom"] == 1 and topless["ParamInnerBottom"] == 1 and topless["ParamClothesOuter"] == 1
    # Without a body layer only the accessories switch; without accessories, nothing.
    assert [i["Name"] for i in puppet.write_outfits(tmp_path, entries[3:])] == ["accessories_off", "accessories_on"]
    assert puppet.write_outfits(tmp_path, entries[3:5]) == []
    assert puppet.role_of("Body", "Inner top") == ("inner", None)


def test_build_kit_refuses_clothing_layers_without_confirmation(tmp_path):
    backend = OutfitBackend()
    result = kit.build_kit(backend, [character()], tmp_path, "mira", {"resolution": 1024, "outfit_layers": True}, log=lambda _: None)
    assert not any("Remove all" in call[1] for call in backend.calls if call[0] == "edit")
    assert "confirm" in result.manifest["outfits"]["refused"]
    document = puppet.load(result.folder / "puppet" / "mira" / "mira.puppet.model.json")
    assert document["Outfits"] == [] and "nude_body" not in {e["Role"] for e in document["Layers"]}


def test_puppet_rig_has_soft_body_and_cloth_for_a_full_body():
    size = (400, 1000)
    parts = [
        layers.Part("face", blob(size, (160, 40, 240, 140), (250, 220, 200, 255)), 0, 0, 0.5),
        layers.Part("neck", blob(size, (185, 130, 215, 175), (250, 220, 200, 255), "rectangle"), 0, 0, 0.55),
        layers.Part("topwear", blob(size, (120, 170, 280, 480), (60, 90, 160, 255), "rectangle"), 0, 0, 0.6),
        layers.Part("bottomwear", blob(size, (110, 470, 290, 700), (160, 40, 60, 255), "rectangle"), 0, 0, 0.6),
        layers.Part("legwear", blob(size, (140, 690, 260, 990), (30, 30, 30, 255), "rectangle"), 0, 0, 0.6),
    ]
    tree, manifest = layers.build_tree(parts)
    entries = [{"Id": l.name, "Role": puppet.role_of(g.name, l.name)[0], "Side": None, "X": l.left, "Y": l.top, "Width": l.image.width,
                "Height": l.image.height, "Depth": 0.5, **({"Garment": l.name.lower()} if puppet.role_of(g.name, l.name)[0] == "clothing" else {})}
               for g in tree for l in g.children]
    for entry in entries:
        box = entry and layers.part_box(next(p for p in parts if layers.classify(p.tag)[1] == entry["Id"]))
        entry.update(X=box[0], Y=box[1], Width=box[2] - box[0], Height=box[3] - box[1])
    rig = puppet.build_rig(entries, size)
    bust, hips = rig["Bust"], rig["Hips"]
    assert len(bust["Centers"]) == 2 and 140 < bust["Centers"][0][1] < hips["Centers"][0][1] < 990
    assert [c["Layer"] for c in rig["Cloth"]] == ["Bottomwear"]
    assert {"soft", "cloth", "drag"} <= set(rig["Physics"])
    ids = {p[0] for p in puppet.PARAMETERS}
    assert {"ParamBustX", "ParamBustY", "ParamHipY", "ParamClothesOuter", "ParamClothesInner"} <= ids


def test_small_pictures_are_upscaled_with_the_backends_model():
    class Upscaler:
        def __init__(self):
            self.asked = 0

        def upscale(self, image):
            self.asked += 1
            source = b64_to_pil(image)
            return source.resize((source.width * 4, source.height * 4))

    backend = Upscaler()
    picture = kit.prepare_picture(character((300, 200)), backend=backend, min_side=1024)
    assert backend.asked == 1 and picture.size == (1024, 683)
    assert kit.prepare_picture(character((300, 200)), min_side=1024).size == (1024, 683)  # Lanczos without a model
    assert kit.prepare_picture(character((300, 200))).size == (300, 200)


def test_defringe_drops_the_pale_halo_but_keeps_the_outline():
    image = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((4, 4, 35, 35), fill=(250, 250, 250, 255))  # pale halo baked in around the hair
    draw.rectangle((7, 7, 32, 32), fill=(20, 10, 5, 255))  # dark outline
    draw.rectangle((9, 9, 30, 30), fill=(90, 60, 40, 255))  # the hair
    fixed = layers.defringe(image)
    assert sum(fixed.getpixel((5, 20))[:3]) < 400  # halo recoloured
    assert fixed.getpixel((8, 20))[:3] == (20, 10, 5)  # outline kept
    assert fixed.getpixel((20, 20))[:3] == (90, 60, 40)


def test_slot_parts_split_the_coat_from_the_top_and_fade_half_off_states():
    size = (400, 400)
    white = (255, 255, 255)

    def dressed(coat=True, coat_half=False, top_open=False):
        image = Image.new("RGB", size, white)
        draw = ImageDraw.Draw(image)
        draw.rectangle((150, 200, 250, 399), fill=(245, 215, 195))  # body
        draw.rectangle((160, 220, 240, 300), fill=(240, 240, 240) if not top_open else (245, 215, 195))  # shirt
        if top_open:
            draw.rectangle((160, 220, 175, 300), fill=(240, 240, 240))
            draw.rectangle((225, 220, 240, 300), fill=(240, 240, 240))
            draw.rectangle((180, 235, 220, 255), fill=(20, 20, 20))  # the bra in the opening
        draw.rectangle((160, 300, 240, 360), fill=(160, 40, 60))  # skirt
        if coat:
            top = 260 if coat_half else 200
            draw.rectangle((140, top, 165, 380), fill=(30, 90, 50))
            draw.rectangle((235, top, 260, 380), fill=(30, 90, 50))
        return image.convert("RGBA")

    picture = dressed()
    alpha = Image.new("L", size, 0)
    ImageDraw.Draw(alpha).rectangle((140, 200, 260, 299), fill=255)
    top = picture.copy()
    top.putalpha(alpha)
    bottom_alpha = Image.new("L", size, 0)
    ImageDraw.Draw(bottom_alpha).rectangle((140, 300, 260, 380), fill=255)
    bottom = picture.copy()
    bottom.putalpha(bottom_alpha)
    face = layers.Part("face", Image.new("RGBA", (60, 70), (245, 215, 195, 255)), 170, 120, 0.4)
    parts = [face, layers.Part("topwear", top, 0, 0, 0.6), layers.Part("bottomwear", bottom, 0, 0, 0.6)]
    inner = dressed(coat=False)
    inner_draw = ImageDraw.Draw(inner)
    inner_draw.rectangle((160, 220, 240, 300), fill=(245, 215, 195))
    inner_draw.rectangle((180, 235, 220, 255), fill=(20, 20, 20))
    edits = {outfits.MID: dressed(coat=False)}
    result = outfits.slot_parts(parts, size, picture, edits, nude=None, inner=inner)
    tags = {p.tag: p for p in result}
    assert {"outer wear", "outer wear half", "topwear half", "topwear", "bottomwear"} <= set(tags)
    coat = tags["outer wear"]
    assert coat.left <= 145 and coat.left + coat.image.width >= 255  # both coat panels
    shirt = layers._on_canvas(tags["topwear"], size)
    assert shirt.getpixel((200, 250))[3] > 200
    assert max(abs(a - b) for a, b in zip(shirt.getpixel((152, 250))[:3], (245, 215, 195))) < 30  # under the coat: what the edit drew
    # Half off is the same garment with part of it faded out, so the layers under it show.
    opened = layers._on_canvas(tags["topwear half"], size)
    assert opened.getpixel((168, 260))[3] > 200 and opened.getpixel((200, 245))[3] < 30  # opened at the front
    assert opened.getpixel((168, 260))[:3] == shirt.getpixel((168, 260))[:3]  # the same art, not redrawn
    slipped = layers._on_canvas(tags["outer wear half"], size)
    assert slipped.getpixel((150, 210))[3] < 30 and slipped.getpixel((150, 340))[3] > 200  # off the shoulders, hanging lower down
    lifted = layers._on_canvas(tags["bottomwear half"], size)
    assert lifted.getpixel((200, 375))[3] < 30 and lifted.getpixel((150, 305))[3] > 200


def test_trim_neck_takes_the_chin_out_of_the_neck_layer():
    size = (200, 300)
    face = Image.new("RGBA", (100, 120), (240, 200, 180, 255))
    neck = Image.new("RGBA", (60, 100), (230, 190, 170, 255))
    parts = [layers.Part("face", face, 50, 20, 0.4), layers.Part("neck", neck, 70, 100, 0.6)]
    trimmed = {p.tag: p for p in layers.trim_neck(parts, size, overlap=6)}
    neck_part = trimmed["neck"]
    # The neck now starts just under the face's edge (keeping a few pixels of overlap), not over the chin.
    assert neck_part.top == 140 - 6
    assert neck_part.image.size[1] == 200 - (140 - 6)
    assert trimmed["face"] is parts[0]


def test_body_layer_keeps_an_arm_raised_beside_the_head():
    size = (300, 400)
    face = layers.Part("face", Image.new("RGBA", (80, 100), (240, 200, 180, 255)), 110, 40, 0.4)
    # A sleeve raised beside the head, above the chin, and the top under the face.
    top = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(top).rectangle((20, 20, 70, 160), fill=(30, 80, 40, 255))
    ImageDraw.Draw(top).rectangle((80, 150, 260, 380), fill=(30, 80, 40, 255))
    parts = [face, layers.Part("topwear", top, 0, 0, 0.6)]
    nude = Image.new("RGBA", size, (255, 255, 255, 255))
    ImageDraw.Draw(nude).rectangle((20, 20, 70, 160), fill=(230, 180, 160, 255))
    ImageDraw.Draw(nude).rectangle((80, 150, 260, 380), fill=(230, 180, 160, 255))
    body = outfits.body_layer(nude, parts, size)
    alpha = body.getchannel("A")
    assert alpha.getpixel((45, 40)) > 200  # the raised arm, above the chin
    assert alpha.getpixel((150, 120)) == 0  # nothing above the chin under the face


def test_expression_art_becomes_switchable_layers_and_strong_emotions_use_it():
    size = (400, 400)
    base = character().convert("RGBA")
    ImageDraw.Draw(base).rectangle((165, 128, 187, 133), fill=(60, 40, 30))  # the brow
    parts = seethrough_parts() + [layers.Part("eyebrow-r", blob(size, (165, 128, 187, 133), (60, 40, 30, 255), "rectangle"), 0, 0, 0.45)]
    angry = character().convert("RGBA")
    ImageDraw.Draw(angry).line((165, 124, 189, 138), fill=(60, 40, 30), width=6)  # scowling, inner end down
    grin = character().convert("RGBA")
    ImageDraw.Draw(grin).chord((182, 200, 218, 222), 0, 180, fill=(255, 255, 255), outline=(150, 60, 60))
    teary = character().convert("RGBA")
    for x in (175, 225):
        ImageDraw.Draw(teary).line((x, 176, x, 200), fill=(150, 200, 255), width=4)
    overlays = {o.name: o for o in layers.edit_overlays(parts, base, None, None, angry_brows=angry, grin=grin, tears=teary)}
    assert overlays["Brow R angry"].parameter == "ParamBrowAngry"
    assert overlays["Mouth grin"].parameter == "ParamMouthGrin"
    assert {"Eye L tears", "Eye R tears"} <= set(overlays) and overlays["Eye L tears"].parameter == "ParamTear"
    assert puppet.role_of("Face", "Brow R angry") == ("brow_angry", "R")
    assert puppet.role_of("Eye L", "Eye L tears") == ("eye_tears", "L")
    assert puppet.role_of("Mouth", "Mouth grin") == ("mouth_grin", None)
    assert model_files.expression_parameters("anger")["ParamBrowAngry"] == 1.0
    assert model_files.expression_parameters("joy")["ParamMouthGrin"] == 1.0
    assert model_files.expression_parameters("grief")["ParamTear"] == 1.0


def test_neutral_pose_redraws_the_character_full_body_on_a_portrait_canvas():
    backend = FakeBackend()
    posed, note = _REAL_NEUTRAL_POSE(backend, character((400, 300)), {}, lambda _: None)
    assert note == "" and posed.size[0] / posed.size[1] == pytest.approx(kit.NEUTRAL_ASPECT, abs=0.01)
    instruction = backend.calls[-1][1]
    assert "neutral A-pose" in instruction and "full body" in instruction

    class NoQwen(FakeBackend):
        edit_methods = ("inpaint",)

    assert _REAL_NEUTRAL_POSE(NoQwen(), character(), {}, lambda _: None)[0] is None


def test_skeleton_from_a_pose_proportions_has_limbs_with_mirrored_limits():
    face = (400, 100, 600, 340)
    joints = skeleton.from_proportions(face, (150, 300, 850, 2000))
    sk = skeleton.bones(joints, face)
    names = [b["Name"] for b in sk["Bones"]]
    assert names[0] == "Hips" and {"UpperArmL", "ForearmR", "ShinL", "Head"} <= set(names)
    # Parents come first, so the player can chain the matrices in order.
    seen = set()
    for bone in sk["Bones"]:
        assert bone["Parent"] is None or bone["Parent"] in seen
        seen.add(bone["Name"])
    by = {b["Name"]: b for b in sk["Bones"]}
    assert by["UpperArmL"]["Head"][0] > 500 > by["UpperArmR"]["Head"][0]  # L is on the right of the picture
    assert (by["UpperArmL"]["Min"], by["UpperArmL"]["Max"]) == (-by["UpperArmR"]["Max"], -by["UpperArmR"]["Min"])
    # A bust-up picture has no legs.
    short = skeleton.bones(skeleton.from_proportions(face, (150, 300, 850, 900)), face)
    assert not any(b["Name"].startswith("Shin") for b in short["Bones"])
    assert ("ParamBoneHips", -8, 8, 0) in skeleton.parameters(sk)


def test_skeleton_from_openpose_keypoints():
    face = (400, 100, 600, 340)
    flat = [0.0] * 54
    points = {0: (500, 250), 1: (500, 400), 2: (380, 450), 3: (340, 650), 4: (320, 850), 5: (620, 450), 6: (660, 650), 7: (680, 850),
              8: (450, 1000), 9: (440, 1350), 10: (440, 1700), 11: (550, 1000), 12: (560, 1350), 13: (560, 1700)}
    for index, (x, y) in points.items():
        flat[index * 3:index * 3 + 3] = [x, y, 0.9]
    joints = skeleton.from_keypoints([{"pose_keypoints_2d": flat}], face, (1000, 2000))
    assert joints["wrist_L"] == (680, 850) and joints["hip_R"] == (450, 1000)
    sk = skeleton.bones(joints, face)
    assert len(sk["Bones"]) == len(skeleton.BONES)


def test_puppet_from_a_neutral_pose_gets_a_skeleton_and_bone_parameters(tmp_path):
    parts = seethrough_parts(1024)
    tree, manifest = layers.build_tree(parts)
    document = puppet.build_puppet(tree, manifest, (1024, 1024), tmp_path / "p", "p", parts, neutral_pose=True)
    bones = document["Rig"]["Skeleton"]["Bones"]
    assert bones and "Arms" not in document["Rig"]
    ids = {p["Id"] for p in document["Parameters"]}
    assert {b["Param"] for b in bones} <= ids


def test_skeleton_fits_the_arms_to_the_hands_and_the_legs_to_the_body():
    face = (450, 100, 550, 230)
    size = (1000, 1400)
    joints = skeleton.from_proportions(face, (300, 100, 700, 1350))
    # A body standing with the hands well out from the hips and the legs apart.
    whole = Image.new("L", size, 0)
    draw = ImageDraw.Draw(whole)
    draw.rectangle((400, 260, 600, 700), fill=255)  # torso
    draw.rectangle((330, 270, 380, 690), fill=255)  # right arm, apart from the torso
    draw.rectangle((620, 270, 670, 690), fill=255)
    draw.rectangle((420, 700, 480, 1340), fill=255)  # right leg
    draw.rectangle((520, 700, 580, 1340), fill=255)
    hands = {}
    for side, x in (("R", 355), ("L", 645)):
        hand = Image.new("L", size, 0)
        ImageDraw.Draw(hand).ellipse((x - 22, 620, x + 22, 700), fill=255)
        hands[side] = hand
    fitted, radii = skeleton.fit_to_layers(joints, face, hands, whole)
    assert abs(fitted["wrist_L"][0] - 645) < 8 and abs(fitted["wrist_R"][0] - 355) < 8
    assert fitted["hand_L"][1] > fitted["wrist_L"][1] > fitted["elbow_L"][1] > fitted["shoulder_L"][1]
    assert abs(fitted["knee_L"][0] - 550) < 8 and abs(fitted["ankle_R"][0] - 450) < 8
    assert radii["UpperArmL"] > 0 and radii["HandR"] > 0
    sk = skeleton.bones(fitted, face, radii)
    by = {b["Name"]: b for b in sk["Bones"]}
    assert by["HandL"]["Radius"] == radii["HandL"]
    # Below the crotch everything is a leg, by side; above it nothing is.
    masks = skeleton.limb_masks(sk, size)
    assert masks["leg_L"].getpixel((560, 1200)) == 255 and masks["leg_R"].getpixel((440, 1200)) == 255
    assert masks["leg_L"].getpixel((560, 600)) == 0


def test_split_limbs_keeps_a_skirt_whole_and_paints_behind_a_hand(tmp_path):
    size = (400, 600)
    (tmp_path / "textures").mkdir()
    skirt = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(skirt).rectangle((140, 300, 260, 420), fill=(150, 30, 40, 255))
    skirt.save(tmp_path / "textures" / "skirt.png")
    jacket = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(jacket).rectangle((120, 100, 280, 300), fill=(180, 150, 120, 255))
    jacket.save(tmp_path / "textures" / "jacket.png")
    entries = [
        {"Id": "skirt", "Role": "clothing", "Garment": "bottomwear", "Texture": "textures/skirt.png", "X": 0, "Y": 0, "Width": 400, "Height": 600},
        {"Id": "jacket", "Role": "clothing", "Garment": "topwear", "Texture": "textures/jacket.png", "X": 0, "Y": 0, "Width": 400, "Height": 600},
    ]
    # The half-off skirt is cut short (it fades where it comes off), but it's still the skirt.
    half = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(half).rectangle((140, 300, 260, 380), fill=(150, 30, 40, 255))
    half.save(tmp_path / "textures" / "skirt_half.png")
    entries.append({"Id": "skirt_half", "Role": "clothing", "Garment": "bottomwear", "State": "half", "Switch": "ParamClothesBottom", "Texture": "textures/skirt_half.png", "X": 0, "Y": 0, "Width": 400, "Height": 600})
    entries[0]["Switch"] = "ParamClothesBottom"
    leg_l, leg_r, arm = (Image.new("L", size, 0) for _ in range(3))
    ImageDraw.Draw(leg_l).rectangle((200, 340, 300, 600), fill=255)
    ImageDraw.Draw(leg_r).rectangle((100, 340, 199, 600), fill=255)
    ImageDraw.Draw(arm).rectangle((180, 150, 220, 250), fill=255)  # a hand in front of the jacket
    result = puppet.split_limbs(tmp_path, entries, {"leg_L": leg_l, "leg_R": leg_r, "arm_L": arm}, {})
    ids = {e["Id"]: e for e in result}
    assert set(ids) >= {"skirt", "jacket__torso", "jacket__arm_L"} and ids["skirt"]["Piece"] == "torso"
    assert ids["skirt_half"]["Piece"] == "torso"
    torso = Image.open(tmp_path / "textures" / "jacket__torso.png")
    entry = ids["jacket__torso"]
    # The hole the hand leaves is painted in with the jacket's colour.
    r, g, b, a = torso.getpixel((200 - entry["X"], 200 - entry["Y"]))
    assert a == 255 and abs(r - 180) < 12 and abs(g - 150) < 12


def test_edits_are_lined_up_with_the_picture_before_cutting():
    size = (400, 600)
    base = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    draw.ellipse((150, 60, 250, 180), fill=(120, 80, 50, 255))  # head
    draw.rectangle((120, 180, 280, 560), fill=(200, 160, 140, 255))  # body
    face = (165, 90, 235, 175)
    # The edit: the same character drawn 3% bigger and 14 px higher, on white.
    edited = Image.new("RGBA", size, (255, 255, 255, 255))
    scale = 1.03
    moved = base.resize((round(size[0] * scale), round(size[1] * scale)))
    edited.alpha_composite(moved, (round(200 - 200 * scale), round(300 - 300 * scale) - 14))
    aligned = layers.align_edit(base, edited, face)
    a = layers._silhouette(base)
    b = layers._silhouette(aligned)
    # The head lines up within a pixel or two.
    rows = slice(60, 200)
    assert abs(int(a[rows].sum()) - int(b[rows].sum())) < a[rows].sum() * 0.03
    assert (a[rows] ^ b[rows]).sum() < a[rows].sum() * 0.06


def test_expression_piece_follows_an_edit_drawn_a_few_pixels_off():
    size = (300, 300)
    base = Image.new("RGBA", size, (240, 210, 190, 255))
    ImageDraw.Draw(base).line((120, 150, 180, 150), fill=(120, 60, 60), width=3)
    edited = Image.new("RGBA", size, (240, 210, 190, 255))
    ImageDraw.Draw(edited).chord((125, 140, 185, 175), 0, 180, fill=(255, 255, 255), outline=(120, 60, 60))  # 5 px right
    skin = Image.new("L", size, 255)
    piece = layers.expression_piece(base, edited, (100, 120, 200, 190), skin, "Mouth", "Mouth grin", "ParamMouthGrin", core=(120, 148, 180, 152))
    assert piece is not None
    # Lined up: the grin's centre sits over the old mouth's centre, not 5 px to the right.
    alpha = piece.image.getchannel("A")
    box = alpha.getbbox()
    centre = piece.left + (box[0] + box[2]) / 2
    assert abs(centre - 150) < 6
    assert layers.expression_piece(base, base, (100, 120, 200, 190), skin, "Mouth", "Mouth grin", "ParamMouthGrin") is None


def test_depth_maps_give_every_mesh_point_a_depth(tmp_path):
    size = (200, 300)
    face = Image.new("RGBA", (60, 80), (240, 200, 180, 255))
    hair = Image.new("RGBA", (100, 120), (90, 60, 40, 255))
    near = Image.new("L", (60, 80), 60)
    far = Image.new("L", (100, 120), 220)
    parts = [layers.Part("face", face, 70, 40, 0.4, near), layers.Part("back hair", hair, 50, 20, 0.9, far), layers.Part("mouth", face, 0, 0, 0.3)]
    maps = layers.depth_canvases(parts, size)
    # The mouth had no map; the nearest surface ("") covers the edits made later.
    assert set(maps) == {"face", "back hair", ""}
    # Past the layer's edge the depth is the layer's own.
    assert maps["face"].getpixel((5, 5)) == 60 and maps[""].getpixel((100, 80)) == 60
    puppet.save_depth(tmp_path / "depth", maps)
    loaded = puppet.load_depth(tmp_path / "depth")
    assert set(loaded) == set(maps)
    entries = [
        {"Role": "face", "Tag": "face", "X": 70, "Y": 40, "Width": 60, "Height": 80, "Grid": [3, 4]},
        {"Role": "back_hair", "Tag": "back hair", "X": 50, "Y": 20, "Width": 100, "Height": 120, "Grid": [4, 4]},
        {"Role": "inner", "Tag": "inner wear", "X": 60, "Y": 150, "Width": 50, "Height": 50, "Grid": [2, 2]},
    ]
    rig = {"Head": {"Box": [70, 40, 130, 120]}, "Body": {"Box": [40, 120, 160, 300]}}
    depth = puppet.add_depth(entries, loaded, rig)
    assert [len(e["Z"]) for e in entries] == [12, 16, 4]
    assert max(entries[0]["Z"]) < min(entries[1]["Z"])  # the face is in front of the back hair
    # The head turns about a point between the face and the back of the head.
    assert 60 < depth["Head"] < 220 and depth["Scale"] > 0


def test_the_player_turns_by_depth_when_the_puppet_has_it():
    import pathlib

    source = (pathlib.Path(puppet.__file__).resolve().parent.parent / "resources" / "puppet.js").read_text(encoding="utf-8")
    # Near points move further than far ones; without depth the drawing order's guess stays.
    assert "depthRig.Head - layer.z[k >> 1]" in source and "depthRig.Body - layer.z[k >> 1]" in source
    assert "1 + parallax * layer.dz" in source
