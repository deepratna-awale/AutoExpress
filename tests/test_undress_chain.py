"""The undress chain for Live2D: garment tagging and derivation, the pixel, colour and skin locks, layers, the fixed-pose runtime and puppet."""

import json

import numpy as np
import pytest
from PIL import Image, ImageDraw

from autoexpress_core.images import b64_to_pil
from autoexpress_core.live2d import (
    fixed_pose,
    garments,
    kit,
    layers,
    model_files,
    puppet,
    undress,
)

psd_tools = pytest.importorskip("psd_tools")

SKIN = (240, 200, 178)


# A tagged outfit ------------------------------------------------------------------------------
def garment(gid, slot, kind, colour, covers, sleeves="n/a", length="n/a", worn_over=(), half=None):
    return {"id": gid, "slot": slot, "type": kind, "colour": {"primary": colour}, "covers_regions": list(covers), "sleeves": sleeves,
            "length": length, "worn_over": list(worn_over), "half_state": half, "front": "open" if slot == "outerwear" else "closed"}


OFFICE = [
    garment("blazer", "outerwear", "blazer", "tan", ["shoulders", "upper_arms", "forearms", "back"], "long", "hip", ["shirt"], "slipped off both shoulders, hanging at the elbows"),
    garment("shirt", "top", "shirt", "light blue", ["chest", "bust", "midriff", "waist", "shoulders"], "long", "hip", half="unbuttoned and hanging open at the front"),
    garment("skirt", "bottom", "pencil_skirt", "red", ["hips", "thighs"], length="knee", half="hem pulled up to the upper thigh"),
    garment("loafers", "footwear", "loafers", "brown", ["feet"]),
    garment("tights", "legwear", "tights", "dark brown", ["thighs", "knees", "shins"]),
    garment("ribbon", "accessory", "hair_ribbon", "red", []),
]
INNER = [
    {"id": "bra", "slot": "inner_top", "type": "bra", "colour": {"primary": "white"}, "desc": "a plain white bra", "under": ["shirt"]},
    {"id": "panties", "slot": "inner_bottom", "type": "panties", "colour": {"primary": "white"}, "desc": "plain white panties", "under": ["skirt"]},
]


def see(visible=OFFICE, box=(60, 0, 140, 300)):
    return {"character": {"sex": "female", "age_look": "adult", "skin_tone_words": "fair warm"}, "visible_garments_outermost_first": [dict(g, bbox_2d=None) for g in visible],
            "accessories_visible": [], "figure_bbox_2d": list(box), "visible_skin_regions": ["head", "neck", "hands"]}


def imagine(adult=True):
    return {"adult_confirmed": adult, "character_summary": "an office worker", "hidden_items_imagined": INNER, "half_states": [], "style_rules": ["same skin tone as the face"]}


def test_derive_orders_the_outfit_outermost_first_and_names_internal_states():
    manifest = garments.build_manifest(see(), imagine(), adult_allowed=True, name="mira")
    assert manifest["undress_order"] == ["blazer", "shirt", "skirt", "loafers", "tights", "bra", "panties"]
    states = manifest["states"]
    assert [s["name"] for s in states][:3] == ["s0_full", "s1_no_blazer", "s2_no_shirt"]
    # The bra shows once the shirt is off: from there on every state is internal, the earlier ones are not.
    assert [s["internal"] for s in states] == [False, False, True, True, True, True, True, True]
    assert states[1]["file"] == "s1_no_blazer.png" and states[2]["file"] == "INTERNAL_s2_no_shirt.png"
    assert states[-1]["file"].startswith("INTERNAL_") and states[-1]["wearing"] == []
    # Accessories stay on and are not part of the chain.
    assert "ribbon" not in manifest["undress_order"] and manifest["accessories_visible"][0]["id"] == "ribbon"
    halves = {h["garment"]: h for h in manifest["half_states"]}
    assert set(halves) == {"blazer", "shirt", "skirt"}
    assert halves["blazer"]["from"] == "s0_full" and halves["blazer"]["over"] == "s1_no_blazer" and not halves["blazer"]["internal"]
    assert halves["shirt"]["internal"] and halves["shirt"]["file"] == "INTERNAL_half_shirt.png"
    count = manifest["layer_count"]
    assert count["garments_visible"] == 5 and count["garments_hidden"] == 2 and count["half_variants"] == 3 and count["body"] == 1
    assert count["edits"] == 7 + 3


def test_a_character_without_outer_wear_gets_fewer_layers():
    full = garments.build_manifest(see(), imagine(), True)
    plain = garments.build_manifest(see(OFFICE[1:]), imagine(), True)
    assert plain["undress_order"][0] == "shirt" and "blazer" not in plain["undress_order"]
    assert len(plain["states"]) == len(full["states"]) - 1
    assert plain["layer_count"]["total_body_group"] == full["layer_count"]["total_body_group"] - 2  # the blazer and its half state


def test_without_an_adult_confirmation_only_outer_layers_come_off():
    for manifest in (garments.build_manifest(see(), imagine(adult=False), True), garments.build_manifest(see(), imagine(), adult_allowed=False)):
        assert manifest["undress_order"] == ["blazer"] and manifest["blocked"]
        assert manifest["hidden_items_imagined"] == [] and not any(s["internal"] for s in manifest["states"])
        assert manifest["character"]["adult_confirmed"] is False
    teen = see()
    teen["character"]["age_look"] = "teen"
    assert garments.build_manifest(teen, imagine(), True)["undress_order"] == ["blazer"]


def test_tags_are_normalised_and_half_states_filled_in():
    raw = [{"id": "outer", "slot": "jacket", "type": "Hoodie", "colour": "grey", "covers_regions": ["head", "chest", "hands", "wings"], "half_state": "worn normally"},
           {"id": "skirt", "slot": "skirt", "type": "pleated skirt", "colour": {"primary": "navy"}, "worn": "tucked_in"}]
    visible = garments.settle_half_states([garments.norm_garment(g, i) for i, g in enumerate(raw)])
    hoodie, skirt = visible
    assert hoodie["slot"] == "outerwear" and hoodie["id"] == "hoodie" and hoodie["covers_regions"] == ["chest"]
    assert hoodie["half_state"] == garments.HALF_DEFAULTS["outerwear"] and hoodie["half_state_source"] == "library"
    assert skirt["slot"] == "bottom" and skirt["worn"] == ["worn_normally"] and "hem" in skirt["half_state"]
    assert garments.parse_json('```json\n{"a": [1, 2,],}\n```') == {"a": [1, 2]}
    assert garments.parse_json("no json here") is None
    assert garments.box_mode([100, 0, 500, 1000], [20, 0, 100, 200], (200, 200))[0] == "norm1000"


# Pixel, colour and skin locks -----------------------------------------------------------------
def test_pixel_lock_changes_no_pixel_outside_the_region():
    rng = np.random.default_rng(0)
    prev = rng.integers(0, 256, (120, 90, 3), dtype=np.uint8)
    edit = rng.integers(0, 256, (120, 90, 3), dtype=np.uint8)  # the edit differs everywhere
    region = np.zeros((120, 90), bool)
    region[30:80, 20:60] = True
    locked = undress.pixel_lock(prev, edit, region)
    assert undress.changed_outside(prev, locked, region) == 0
    assert np.array_equal(locked[~region], prev[~region])
    inner = undress.shrink(region, undress.FEATHER + 1)
    assert np.array_equal(locked[inner], edit[inner])  # well inside, the edit as drawn


def test_removal_region_never_reaches_the_protected_head():
    mask = np.zeros((60, 60), bool)
    mask[20:40, 20:40] = True
    head = np.zeros((60, 60), bool)
    head[:22] = True
    region = undress.removal_region(mask, head)
    assert region[25, 18] and not region[:22].any() and not region[50, 50]


def test_skin_lock_meets_the_face_colour():
    face = undress.to_lab(np.array([[SKIN]], np.uint8))[0, 0]
    image = np.full((80, 80, 3), 255, np.uint8)
    image[10:70, 10:70] = (226, 180, 150)  # the edit's skin: darker and redder than the face
    image[40:70, 10:70] = (205, 160, 135)  # with its shading
    region = np.zeros((80, 80), bool)
    region[5:75, 5:75] = True
    before = undress.skin_error(image, region, face)
    locked = undress.skin_lock(image, region, face)
    after = undress.skin_error(locked, region, face)
    assert before > undress.SKIN_DE and after < undress.SKIN_DE
    lab = undress.to_lab(locked)
    assert lab[50, 40, 0] < lab[20, 40, 0]  # the shading survives
    # The CIEDE2000 itself (Sharma et al.'s first test pair).
    assert undress.de2000((50, 2.6772, -79.7751), (50, 0, -82.7485)) == pytest.approx(2.0425, abs=1e-3)


def test_lab_round_trips_and_colour_lock_takes_out_drift():
    rgb = np.random.default_rng(1).integers(0, 250, (40, 40, 3), dtype=np.uint8)
    assert np.abs(undress.from_lab(undress.to_lab(rgb)).astype(int) - rgb).max() <= 1
    rgb = np.random.default_rng(2).integers(60, 200, (40, 40, 3), dtype=np.uint8)
    drifted = undress.from_lab(undress.to_lab(rgb) * (1.04, 1, 1) + (2, 3, -3))  # Qwen's kind of drift: a little lighter, a tint
    fixed = undress.colour_lock(rgb, drifted, np.ones((40, 40), bool))
    assert np.abs(fixed.astype(int) - rgb).mean() < np.abs(drifted.astype(int) - rgb).mean() / 3


def test_align_finds_the_shift_of_an_edit():
    prev = np.full((160, 120, 3), 255, np.uint8)
    prev[30:130, 30:90] = (90, 60, 40)
    prev[40:60, 40:80] = (20, 120, 200)
    edit = np.full_like(prev, 255)
    edit[33:133, 32:92] = (90, 60, 40)  # drawn 2 px right and 3 px down
    edit[43:63, 42:82] = (20, 120, 200)
    _, _, before, after = undress.align(prev, edit, np.ones((160, 120), bool))
    assert after < before / 4


# Layers ---------------------------------------------------------------------------------------
def test_half_garment_keeps_only_the_garments_pixels_over_the_next_state():
    nxt = np.full((60, 60, 3), 255, np.uint8)
    nxt[10:50, 20:40] = SKIN  # the next state: the garment off
    edit = nxt.copy()
    edit[10:30, 15:45] = (60, 90, 160)  # the garment, slipped down to the elbows
    found = np.zeros((60, 60), bool)
    found[10:30, 15:45] = True
    piece = undress.half_garment(edit, nxt, found, undress.grow(found, 2))
    layer = undress.rgba(edit, piece * 255)
    stack = undress.compose(nxt, [layer])
    assert np.array_equal(stack, edit)  # half state = next state + the garment's own pixels
    assert not piece[35:50].any()


def figure(removed=(), shift=(0, 0)):
    """A drawn figure on white, with the garments not in removed: tan blazer > blue shirt > red skirt, over white inner wear on skin."""
    image = Image.new("RGB", (200, 300), (255, 255, 255))
    d = ImageDraw.Draw(image)
    dx, dy = shift
    d.rectangle((70 + dx, 60 + dy, 130 + dx, 290 + dy), fill=SKIN)  # body
    d.ellipse((75 + dx, 8 + dy, 125 + dx, 62 + dy), fill=SKIN)  # head
    d.rectangle((75 + dx, 8 + dy, 125 + dx, 22 + dy), fill=(80, 50, 35))  # hair
    for name, box, colour in (("panties", (80, 170, 120, 192), (236, 236, 240)), ("bra", (76, 90, 124, 112), (236, 236, 240)),
                              ("skirt", (72, 160, 128, 225), (180, 30, 40)), ("shirt", (70, 78, 130, 165), (150, 180, 220)),
                              ("blazer", (64, 74, 136, 172), (196, 160, 110))):
        if name not in removed:
            d.rectangle(tuple(v + (dx if i % 2 == 0 else dy) for i, v in enumerate(box)), fill=colour)
    return image


BOXES = {"head, hair, face": (75, 8, 125, 62), "face": (80, 24, 120, 60)}
COLOURS = {"tan blazer": (196, 160, 110), "light blue shirt": (150, 180, 220), "red pencil skirt": (180, 30, 40), "white bra": (236, 236, 240), "white panties": (236, 236, 240)}
SIMPLE = [OFFICE[0], OFFICE[1], OFFICE[2]]
ORDER = ["blazer", "shirt", "skirt", "bra", "panties"]
GARMENT_ART = {"blazer": ((64, 74, 136, 172), (196, 160, 110)), "shirt": ((70, 78, 130, 165), (150, 180, 220)), "skirt": ((72, 160, 128, 225), (180, 30, 40))}


class ChainBackend:
    """Draws the figure without what has come off (2 px off, like Qwen), segments by name, tags from fixed answers."""

    label = "Fake"
    edit_methods = ("inpaint", "instruct")
    can_decompose = True

    def __init__(self):
        self.last_error = None
        self.calls = []
        self.removed = []

    def describe(self, image, prompt):
        self.calls.append(("describe", prompt[:40]))
        if "zoomed crop" in prompt:
            return '{"present": true, "main_colour": "", "front": "n/a"}'
        if "IMAGINATION" in prompt:
            return json.dumps(imagine())
        return json.dumps(see(SIMPLE, (64, 8, 136, 290)))

    def segment_model(self):
        return "sam3.safetensors"

    def segment(self, image, prompt):
        self.calls.append(("segment", prompt))
        picture = b64_to_pil(image)
        colour = COLOURS.get(prompt)
        if colour is not None:  # a garment: wherever it is drawn
            found = np.abs(np.asarray(picture.convert("RGB")).astype(int) - colour).max(-1) < 30
            return Image.fromarray((found * 255).astype(np.uint8))
        mask = Image.new("L", picture.size, 0)
        box = BOXES.get(prompt)
        if box is not None:
            sx, sy = picture.width / 200, picture.height / 300
            ImageDraw.Draw(mask).rectangle((box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy), fill=255)
        return mask

    def instruction_edit(self, image, instruction, settings):
        self.calls.append(("edit", instruction))
        picture = b64_to_pil(image)
        for name, words in (("blazer", "tan blazer"), ("shirt", "light blue shirt"), ("skirt", "red pencil skirt"), ("bra", "white bra"), ("panties", "white panties")):
            if f"Remove the {words}" in instruction:
                self.removed.append(name)
        result = figure(self.removed, shift=(2, 1))
        for name, words in (("blazer", "tan blazer"), ("shirt", "light blue shirt"), ("skirt", "red pencil skirt")):
            if f"Her {words} is now" in instruction:  # a half state: drawn from the state where it is outermost, slipped down
                before = ORDER[: ORDER.index(name)]
                result = figure([*before, name], shift=(2, 1))
                box, colour = GARMENT_ART[name]
                ImageDraw.Draw(result).rectangle((box[0] + 2, box[1] + 13, box[2] + 2, box[3] + 13), fill=colour)
        return result.resize(picture.size) if picture.size != result.size else result


def test_run_chain_locks_every_state_and_its_layers_rebuild_the_picture():
    backend = ChainBackend()
    picture = figure()
    manifest = garments.tag_garments(backend, picture, adult_allowed=True, name="mira")
    assert manifest["undress_order"] == ["blazer", "shirt", "skirt", "bra", "panties"]
    chain = undress.run_chain(backend, picture, manifest)
    assert chain.order == [s["name"] for s in manifest["states"]]
    for name in chain.order[1:]:
        assert chain.metrics[name]["changed_outside_R"] == 0
        assert chain.metrics[name]["mask"] == "segmentation"
    # Revealed skin meets the face (after the shirt and the inner wear come off).
    assert all(chain.metrics[n]["skin_dE00"] is None or chain.metrics[n]["skin_dE00"] < undress.SKIN_DE for n in chain.order[1:] if "skin_dE00" in chain.metrics[n])
    head = np.zeros((300, 200), bool)
    head[9:62, 76:125] = True  # the segmented head, less its 1 px rim
    for name in chain.order[1:]:
        assert np.array_equal(chain.states[name][head], chain.states[chain.order[0]][head])  # the head never changes
    found = undress.chain_layers(chain, manifest)
    tags_found = [layer.tag for layer in found]
    assert tags_found[:5] == ["outer wear", "topwear", "bottomwear", "inner top", "inner bottom"] and tags_found[-1] == "nude body"
    assert {"outer wear half", "topwear half", "bottomwear half"} <= set(tags_found)
    names = {layer.tag: layer.name for layer in found}
    assert names["outer wear"] == "layer_blazer" and names["inner top"].startswith("INTERNAL_") and names["nude body"].startswith("INTERNAL_")
    assert undress.check_stack(chain, found) < 0.01 * (300 * 200)


def test_fake_chain_backend_handles_half_states():
    backend = ChainBackend()
    manifest = garments.build_manifest(see(SIMPLE), imagine(), True)
    chain = undress.run_chain(backend, figure(), manifest)
    assert set(chain.halves) == {"blazer_half", "shirt_half", "skirt_half"}
    blazer = np.asarray(chain.halves["blazer_half"])
    assert blazer[..., 3].sum() > 0 and blazer[180, 100, 3] == 255  # the slipped blazer hangs below its old hem
    assert blazer[40, 100, 3] == 0  # nothing of the head comes in with it
    assert not any("Couldn't" in note for note in chain.notes)


# The fixed-pose runtime -----------------------------------------------------------------------
POSE_IDS = ("ParamArm", "ParamHand", "ParamBone", "ParamLeg", "ParamIK")


def test_fixed_pose_runtime_has_28_distinct_emotions_and_no_arm_motion(tmp_path):
    written = fixed_pose.write_runtime(tmp_path)
    names = [e["Name"] for e in written["Expressions"]]
    assert set(model_files.EMOTIONS) <= set(names) and len(model_files.EMOTIONS) == 28
    assert {"Boop", "Pat", "Poke", "Tap"} <= set(names)
    faces = set()
    for emotion in model_files.EMOTIONS:
        data = json.loads((tmp_path / "expressions" / f"{emotion}.exp3.json").read_text())
        faces.add(json.dumps(sorted((p["Id"], p["Value"]) for p in data["Parameters"])))
    assert len(faces) == 28
    motions = written["Motions"]
    assert set(model_files.EMOTIONS) <= set(motions) and len(motions["Idle"]) == 2
    for group, items in motions.items():
        for item in items:
            data = json.loads((tmp_path / item["File"]).read_text())
            ids = [c["Id"] for c in data["Curves"]]
            assert not [i for i in ids if i.startswith(POSE_IDS)], (group, ids)
            assert data["Meta"]["CurveCount"] == len(ids)
    st = json.loads((tmp_path / "sillytavern_settings.json").read_text())
    assert set(st["classify_mapping"]) == set(model_files.EMOTIONS)
    assert st["hit_areas"]["Nose"] == {"expression": "Boop", "motion": "Boop_id=random", "message": ""}
    assert st["hit_areas"]["Head"]["motion"] == "Pat_id=random" and st["hit_areas"]["Cheek"]["expression"] == "Poke" and st["hit_areas"]["Body"]["expression"] == "Tap"
    assert st["cursor_param"]["idParamAngleX"] == "ParamAngleX" and st["cursor_param"]["idParamBreath"] == "ParamBreath"


def test_fixed_pose_motions_refuse_arm_curves_and_big_turns():
    with pytest.raises(ValueError):
        fixed_pose.build_motion(1.0, {"hx": [(0.5, 40)]})
    data = fixed_pose.build_motion(1.0, {"ParamArmLA": [(0.5, 10)], "hy": [(0.5, 5)]})
    assert "ParamArmLA" not in [c["Id"] for c in data["Curves"]]


def test_attach_writes_the_fixed_pose_runtime(tmp_path):
    (tmp_path / "mira.model3.json").write_text(json.dumps({"Version": 3, "FileReferences": {"Moc": "mira.moc3"}, "HitAreas": [{"Id": "ArtMeshNose", "Name": "Nose"}, {"Id": "ArtMeshBody", "Name": "Body"}]}))
    summary = model_files.attach_to_model(tmp_path, fixed_pose=True)
    model3 = json.loads((tmp_path / "mira.model3.json").read_text())
    assert summary["expressions"] == 32 and "Boop" in model3["FileReferences"]["Motions"]
    st = json.loads((tmp_path / "sillytavern_settings.json").read_text())
    assert set(st["hit_areas"]) == {"Nose", "Body"}


# The fixed-pose puppet with inner wear switches ------------------------------------------------
def chain_parts():
    size = (200, 300)

    def part(tag, box, colour, depth, internal=False):
        image = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(image).rectangle(box, fill=colour)
        return layers.Part(tag, image, 0, 0, depth, internal=internal)

    return [
        part("back hair", (72, 6, 128, 70), (80, 50, 35, 255), 0.9),
        part("face", (80, 10, 120, 60), SKIN + (255,), 0.5),
        part("nose", (98, 38, 102, 42), (220, 160, 150, 255), 0.45),
        part("front hair", (75, 6, 125, 20), (80, 50, 35, 255), 0.2),
        part("nude body", (70, 60, 130, 290), SKIN + (255,), 0.7, True),
        part("inner top", (76, 90, 124, 112), (236, 236, 240, 255), 0.64, True),
        part("inner bottom", (80, 170, 120, 192), (236, 236, 240, 255), 0.65, True),
        part("bottomwear", (72, 160, 128, 225), (180, 30, 40, 255), 0.6),
        part("topwear", (70, 78, 130, 165), (150, 180, 220, 255), 0.58),
        part("topwear half", (70, 78, 130, 165), (150, 180, 220, 255), 0.575, True),
        part("outer wear", (64, 74, 136, 172), (196, 160, 110, 255), 0.55),
    ]


def test_fixed_pose_puppet_has_touch_reactions_inner_wear_switches_and_no_arms(tmp_path):
    parts = chain_parts()
    tree, manifest = layers.build_tree(parts)
    body = next(g for g in manifest["groups"] if g["name"] == "Body")
    hidden = {info["name"]: info for info in body["layers"]}
    assert hidden["Topwear half"]["visible"] is False and hidden["Topwear"]["visible"] is True  # half art starts hidden
    assert hidden["Inner top"].get("internal") and not hidden["Topwear"].get("internal")
    folder = tmp_path / "mira"
    doc = puppet.build_puppet(tree, manifest, (200, 300), folder, "mira", parts, fixed_pose=True)
    ids = {p["Id"] for p in doc["Parameters"]}
    assert not [i for i in ids if i.startswith(POSE_IDS)] and {"ParamInnerTop", "ParamInnerBottom", "ParamBreath"} <= ids
    assert doc["Rig"]["FixedPose"] and doc["Rig"]["Arms"] == {} and "Skeleton" not in doc["Rig"]
    names = [a["Name"] for a in doc["HitAreas"]]
    assert names[:3] == ["Nose", "Cheek", "Cheek"] and {"Face", "Head", "Body"} <= set(names) and "Chest" not in names
    assert doc["Reactions"]["Nose"] == "Boop" and doc["Reactions"]["Head"] == "Pat" and doc["Reactions"]["Cheek"] == "Poke" and doc["Reactions"]["Body"] == "Tap"
    switches = {e["Name"]: e.get("Switch") for e in doc["Layers"]}
    assert switches["Inner top"] == "ParamInnerTop" and switches["Inner bottom"] == "ParamInnerBottom"
    assert {"outfit_inner_top_off", "outfit_inner_bottom_off", "outfit_nude", "outfit_top_open"} <= set(doc["Outfits"])
    textures = {e["Name"]: e["Texture"] for e in doc["Layers"]}
    assert textures["Inner top"].startswith("textures/INTERNAL_") and textures["Body"].startswith("textures/INTERNAL_") and not textures["Topwear"].startswith("textures/INTERNAL_")
    motions = doc["FileReferences"]["Motions"]
    for group in ("Boop", "Pat", "Poke", "Tap", "Idle", "joy"):
        assert group in motions
    for items in motions.values():
        for item in items:
            curves = json.loads((folder / item["File"]).read_text())["Curves"]
            assert not [c for c in curves if c["Id"].startswith(POSE_IDS)]
            assert {c["Id"] for c in curves} <= ids
    for item in doc["FileReferences"]["Expressions"]:
        assert {p["Id"] for p in json.loads((folder / item["File"]).read_text())["Parameters"]} <= ids


# The kit ---------------------------------------------------------------------------------------------
class UndressKitBackend(ChainBackend):
    def check_ready(self, method):
        return True, "ok"

    def img2img(self, payload):
        return None

    def interrupt(self):
        pass

    def decompose_layers(self, image, settings):
        picture = b64_to_pil(image)
        side = settings.resolution
        box = layers.square_placement(picture.size, side)
        scale = (box[2] - box[0]) / picture.width
        parts = []
        for part in chain_parts():
            if part.tag in ("nude body", "inner top", "inner bottom", "topwear half"):
                continue
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            canvas.paste(part.image.resize((round(200 * scale), round(300 * scale))), box[:2])
            parts.append(layers.Part(part.tag, canvas, 0, 0, part.depth))
        return parts, (side, side)


def test_build_kit_with_the_undress_chain(tmp_path, monkeypatch):
    monkeypatch.setattr(kit, "neutral_pose", lambda *a: pytest.fail("the undress chain keeps the picture's pose"))
    backend = UndressKitBackend()
    settings = {"resolution": 512, "undress_chain": True, "adult_confirmed": True, "variants": "none", "use_prompt_data": False, "character_description": "an adult office worker"}
    result = kit.build_kit(backend, [figure()], tmp_path, "mira", settings, log=lambda _: None)
    manifest = result.manifest
    assert manifest["fixed_pose"] and not manifest["neutral_pose"]
    chain = manifest["undress"]
    assert chain["order"][0] == "s1_no_blazer" and all(m.get("changed_outside_R", 0) == 0 for m in chain["metrics"].values())
    folder = result.folder
    assert (folder / "undress" / "garment_manifest.json").exists() and (folder / "undress" / "s1_no_blazer.png").exists()
    assert (folder / "undress" / "INTERNAL_s2_no_shirt.png").exists() and not (folder / "undress" / "s2_no_shirt.png").exists()
    pngs = [p.name for p in (folder / "layers").glob("*.png")]
    assert any(n.startswith("INTERNAL_Body - Body") for n in pngs) and any(n.startswith("INTERNAL_Body - Inner top") for n in pngs)
    assert "Body - Outer wear.png" in pngs
    # The PSD has every final part in draw order, the half-off art hidden.
    document = psd_tools.PSDImage.open(folder / "mira.psd")
    body = next(layer for layer in document if layer.is_group() and layer.name == "Body")
    names = [layer.name for layer in body]
    assert names.index("Body") < names.index("Inner top") < names.index("Topwear") < names.index("Outer wear")
    assert not next(layer for layer in body if layer.name == "Outer wear half").visible
    doc = puppet.load(folder / "puppet" / "mira" / "mira.puppet.model.json")
    assert doc["Rig"].get("FixedPose") and doc["HitAreas"][0]["Name"] == "Nose"
    assert (folder / "runtime" / "expressions" / "Boop.exp3.json").exists()
    again = puppet.load(puppet.from_kit(folder, tmp_path / "again") / "mira.puppet.model.json")
    assert again["Rig"].get("FixedPose") and [e["Role"] for e in again["Layers"]] == [e["Role"] for e in doc["Layers"]]


def test_the_api_takes_the_undress_chain_switch():
    from autoexpress.validation import validate_live2d
    from autoexpress_core.images import pil_to_b64

    body = {"images": [pil_to_b64(figure())], "name": "mira", "settings": {"undress_chain": True, "adult_confirmed": True}}
    assert validate_live2d(body, 10**8)["settings"]["undress_chain"] is True
    assert validate_live2d({**body, "settings": {"undress_chain": "yes"}}, 10**8)["settings"]["undress_chain"] is False
