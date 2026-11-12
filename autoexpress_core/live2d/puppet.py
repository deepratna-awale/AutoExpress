"""
An open, ready-to-play puppet made from a kit's layers: no Cubism Editor needed.

Live2D's .moc3 format is closed, so this writes its own small format instead, which the
AutoExpress SillyTavern extension plays inside the SillyTavern Live2D extension (see
autoexpress_core/resources/puppet.js): it stands in for a Live2D model there, so expressions, motions,
hit areas, lip sync and cursor following all work the same way.

A puppet folder holds:

    <name>.puppet.model.json   the puppet: layers, their roles and the rig, parameters, hit areas
    textures/*.png             one picture per layer, cropped to its content
    expressions/*.exp3.json    the 28 emotions (the same files as a Cubism model gets)
    motions/*.motion3.json     the reactions and the idle loop
    sillytavern_settings.json  the emotion mapping for the Live2D extension
    preview.html, puppet.js    a page to try the puppet in a browser

The file name has "model" in it because SillyTavern only lists Live2D files whose name does.

The rig is not stored as meshes and keyforms: each layer has a role (face, iris, eyelash, front
hair ...) and the rig gives the boxes and pivots the player needs (head, eyes, mouth, body). The
player deforms every layer from those on each frame (head turn and tilt with depth parallax,
blinking, eye movement, brows, mouth shapes, breathing and hair sway). Anyone can rewrite a
puppet's numbers by hand, and other players can read it.
"""

import base64
import json
import pathlib
import shutil

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageStat

from . import fixed_pose as fixed_runtime
from . import layers, model_files, skeleton

FORMAT = "AutoExpress Puppet"
VERSION = 1
SUFFIX = ".puppet.model.json"
PLAYER = pathlib.Path(__file__).resolve().parent.parent / "resources" / "puppet.js"
HUMANOID_IK = PLAYER.with_name("humanoid_ik.js")  # the full-body IK solver the player imports

# The parameters the player understands (Live2D's standard ids, so expressions and motions carry over).
PARAMETERS = [
    ("ParamAngleX", -30, 30, 0),
    ("ParamAngleY", -30, 30, 0),
    ("ParamAngleZ", -30, 30, 0),
    ("ParamEyeLOpen", 0, 1.2, 1),
    ("ParamEyeROpen", 0, 1.2, 1),
    ("ParamEyeLSmile", 0, 1, 0),
    ("ParamEyeRSmile", 0, 1, 0),
    ("ParamEyeBallX", -1, 1, 0),
    ("ParamEyeBallY", -1, 1, 0),
    ("ParamBrowLY", -1, 1, 0),
    ("ParamBrowRY", -1, 1, 0),
    ("ParamBrowLAngle", -1, 1, 0),
    ("ParamBrowRAngle", -1, 1, 0),
    ("ParamBrowLForm", -1, 1, 0),
    ("ParamBrowRForm", -1, 1, 0),
    ("ParamMouthForm", -1, 1, 0),
    ("ParamMouthOpenY", 0, 1, 0),
    ("ParamCheek", 0, 1, 0),
    ("ParamBrowAngry", 0, 1, 0),
    ("ParamMouthGrin", 0, 1, 0),
    # Lip sync shapes with the mouth in pieces: -1 rounded (oo) to 1 stretched (ee), the tongue raised,
    # the teeth brought to the lips (s, ee, f).
    ("ParamMouthWide", -1, 1, 0),
    ("ParamTongueUp", 0, 1, 0),
    ("ParamTeeth", 0, 1, 0),
    ("ParamTear", 0, 1, 0),
    ("ParamBodyAngleX", -10, 10, 0),
    ("ParamBodyAngleY", -10, 10, 0),
    ("ParamBodyAngleZ", -10, 10, 0),
    ("ParamBreath", 0, 1, 0),
    ("ParamHairFront", -1, 1, 0),
    ("ParamHairSide", -1, 1, 0),
    ("ParamHairBack", -1, 1, 0),
    # Soft body physics (Live2D's standard bust ids; the hips have no standard id).
    ("ParamBustX", -1, 1, 0),
    ("ParamBustY", -1, 1, 0),
    ("ParamHipX", -1, 1, 0),
    ("ParamHipY", -1, 1, 0),
    # Outfit switches: 1 shows the layer. Only puppets with a body layer have something under the clothes.
    # Outer and Inner switch a whole layer of clothing; the others switch one piece of it, so a
    # piece can come off on its own (half off: top off and skirt on, or the bra off and briefs on).
    ("ParamClothesOuter", 0, 1, 1),
    ("ParamClothesInner", 0, 1, 1),
    ("ParamClothesCoat", 0, 1, 1),
    ("ParamClothesTop", 0, 1, 1),
    ("ParamClothesBottom", 0, 1, 1),
    ("ParamClothesLegs", 0, 1, 1),
    ("ParamInnerTop", 0, 1, 1),
    ("ParamInnerBottom", 0, 1, 1),
    ("ParamAccessories", 0, 1, 1),
    # Posing: each arm turns at the shoulder (degrees, + clockwise on screen).
    ("ParamArmLA", -30, 30, 0),
    ("ParamArmRA", -30, 30, 0),
]
# Which piece switch each garment follows (outer clothes by See-through's tag, inner wear by layer).
PIECES = {
    "outerwear": "ParamClothesCoat",
    "topwear": "ParamClothesTop", "neckwear": "ParamClothesTop", "arm": "ParamClothesTop",
    "bottomwear": "ParamClothesBottom",
    "legwear": "ParamClothesLegs", "footwear": "ParamClothesLegs",
    "inner_top": "ParamInnerTop", "inner_bottom": "ParamInnerBottom",
}
_SWITCHES = (
    "ParamClothesOuter", "ParamClothesInner", "ParamClothesCoat", "ParamClothesTop", "ParamClothesBottom", "ParamClothesLegs",
    "ParamInnerTop", "ParamInnerBottom",
)
# Each piece switch: 1 on, 0.5 half off (when the piece has half-off art), 0 off, like a Koikatsu
# clothing slot. name -> (switch values that differ from 1, what it needs). Needs: "body" a body
# layer, "inner" inner wear, "inner_split" its top and bottom apart, "outer_split" an outer top and
# bottom apart, "coat" a coat layer, "<switch> half" that switch's half-off art.
OUTFITS = {
    "outfit_full": ({}, ()),
    "outfit_coat_half": ({"ParamClothesCoat": 0.5}, ("ParamClothesCoat half",)),
    "outfit_coat_off": ({"ParamClothesCoat": 0}, ("coat",)),
    "outfit_top_open": ({"ParamClothesCoat": 0, "ParamClothesTop": 0.5}, ("ParamClothesTop half",)),
    "outfit_skirt_lifted": ({"ParamClothesBottom": 0.5}, ("ParamClothesBottom half",)),
    "outfit_top_off": ({"ParamClothesCoat": 0, "ParamClothesTop": 0}, ("body", "outer_split", "inner")),
    "outfit_bottom_off": ({"ParamClothesBottom": 0, "ParamClothesLegs": 0}, ("body", "outer_split", "inner")),
    "outfit_inner": ({"ParamClothesOuter": 0}, ("body", "inner")),
    "outfit_topless": ({"ParamClothesCoat": 0, "ParamClothesTop": 0, "ParamInnerTop": 0}, ("body", "outer_split", "inner_split")),
    "outfit_inner_top_off": ({"ParamClothesOuter": 0, "ParamInnerTop": 0}, ("body", "inner_split")),
    "outfit_inner_bottom_off": ({"ParamClothesOuter": 0, "ParamInnerBottom": 0}, ("body", "inner_split")),
    "outfit_nude": ({"ParamClothesOuter": 0, "ParamClothesInner": 0}, ("body",)),
}
# Base layer name -> garment (the piece switch it follows, see PIECES).
GARMENTS = {
    "Outer wear": "outerwear", "Topwear": "topwear", "Bottomwear": "bottomwear", "Legwear": "legwear",
    "Footwear": "footwear", "Neckwear": "neckwear", "Inner top": "inner_top", "Inner bottom": "inner_bottom",
}
# Layers that are accessories (switched by ParamAccessories, on their own expression slot).
ACCESSORY_LAYERS = ("Headwear", "Eyewear", "Earwear", "Neckwear", "Objects")

# How far things move at the ends of each parameter, as fractions of the face (head) or canvas.
STRENGTH = {
    "turn": 0.10,  # head turn: shift of the face centre at AngleX = 30, in face widths
    "nod": 0.07,  # head nod: shift at AngleY = 30, in face heights
    "tilt": 0.35,  # degrees of head roll per degree of AngleZ
    "parallax": 0.75,  # how much more the nearest layers move than the face (and the back hair less)
    "body": 0.35,  # degrees of body lean per degree of BodyAngleX
    "breath": 0.012,  # chest rise at Breath = 1, in body heights
    "eyeball": 0.14,  # iris travel at EyeBall = 1, in eye widths
    "brow": 0.35,  # brow travel at BrowY = 1, in eye heights
    "mouth_form": 0.35,  # mouth corner travel at MouthForm = 1, in mouth widths
    "hair": 0.06,  # hair tip sway at full swing, in face widths
    "bust": 1.0,  # soft body jiggle (bust): 0 turns it off, 2 doubles it
    "hips": 1.0,  # soft body jiggle (hips and thighs)
    "cloth": 0.05,  # skirt hem and ribbon sway at full swing, in body widths
    "drag": 1.0,  # how far dragging with the mouse pulls cloth, hair and soft parts
}

# Springs, as a natural frequency (Hz) and a damping ratio (the fraction of critical damping), the
# way a body part really moves. The bust rings at about 2 to 3 Hz up and down and a little slower
# side to side, and lightly damped it bounces a few times before it settles. The hips are firmer and
# damped more. Hair and skirt hems are pendulums in locks and panels of their own, slower still.
# gravity: how far the rest point moves when the body tilts, in radii; limit: the soft stop, in radii.
# stiffness / damping (k, c) are the older single-spring form, still read for the head-driven sway.
PHYSICS = {
    "stiffness": 18.0,
    "damping": 5.5,
    "gravity": 0.0,
    "soft": {"frequency": [1.9, 2.6], "damping": 0.15, "gravity": 0.12, "limit": 0.32},
    "hips": {"frequency": [2.2, 3.0], "damping": 0.22, "gravity": 0.06, "limit": 0.22},
    "hair": {"frequency": 1.15, "damping": 0.18, "locks": 6},
    "cloth": {"frequency": 0.95, "damping": 0.24, "locks": 4},
    "drag": {"stiffness": 110.0, "damping": 5.0},
}

# Group / layer name -> role in the rig.
_ROLES = {
    "Front hair": "front_hair",
    "Back hair": "back_hair",
    "Headwear": "headwear",
    "Ears": "ear",
    "Mouth": "mouth",
    "Tail": "body",
    "Wings": "body",
    "Objects": "body",
}
_FACE_ROLES = {"Eyebrow": "brow", "Eyebrows": "brow", "Nose": "nose", "Face": "face", "Eyewear": "eyewear", "Eyes": "eyes"}
_EYE_ROLES = {"Eyelash": "eyelash", "Iris": "iris", "Eye white": "eye_white", "Eye": "eye_white"}
_BODY_ROLES = {
    "Neck": "neck", "Arm": "arm", "Arms": "arm", "Body": "nude_body", "Inner wear": "inner", "Inner top": "inner", "Inner bottom": "inner",
    "Topwear": "clothing", "Bottomwear": "clothing", "Legwear": "clothing", "Footwear": "clothing", "Neckwear": "clothing",
    "Outer wear": "clothing", "Outer wear half": "clothing", "Topwear half": "clothing", "Bottomwear half": "clothing",
}
# The open mouth cut into pieces for lip sync (layers.mouth_parts).
_MOUTH_PART_ROLES = {"Mouth inside": "mouth_inside", "Teeth upper": "teeth_upper", "Teeth lower": "teeth_lower", "Tongue": "tongue", "Mouth lips": "mouth_lips"}
MOUTH_PART_ROLES = tuple(_MOUTH_PART_ROLES.values())
# The pose detector's keypoints in a kit (OpenPose JSON, the kit's pixels).
POSE_FILE = "pose.json"
# The sleeve map in a kit (the kit's pixels): the outer garment's sleeves magenta, its body cyan.
SLEEVE_FILE = "sleeves.png"
# How much of the head layers' depth spread around the face is kept (add_depth).
HEAD_DEPTH_SPREAD = 0.25
HEAD_ROLES = ("face", "brow", "brow_angry", "nose", "eyewear", "eyes", "eyelash", "iris", "eye_white", "eye_closed", "eye_tears", "mouth", "mouth_open", "mouth_grin", *MOUTH_PART_ROLES, "ear", "front_hair", "hair_under", "headwear", "back_hair")
# The eyes and mouth: small on the canvas, drawn large; their textures get upscaled.
FEATURE_ROLES = ("eyes", "eyelash", "iris", "eye_white", "eye_closed", "eye_tears", "brow", "brow_angry", "mouth", "mouth_open", "mouth_grin", *MOUTH_PART_ROLES)
# The outer clothes: hidden by ParamClothesOuter when the puppet has a body layer under them.
OUTER_ROLES = ("clothing", "arm")


def role_of(group: str, layer_name: str) -> tuple[str, str | None]:
    """(role, side) for a layer of the kit's tree."""
    side = None
    words = layer_name.split()
    if words and words[-1] in ("L", "R"):
        side = words[-1]
    if layer_name.endswith("closed"):
        return "eye_closed", (group.split()[-1] if group.startswith("Eye ") else None)
    if layer_name.endswith("tears"):
        return "eye_tears", (group.split()[-1] if group.startswith("Eye ") else None)
    if layer_name.endswith("angry"):
        return "brow_angry", side or (words[1] if len(words) > 2 and words[1] in ("L", "R") else None)
    if layer_name == "Mouth open":
        return "mouth_open", None
    if layer_name == "Mouth grin":
        return "mouth_grin", None
    if layer_name in _MOUTH_PART_ROLES:
        return _MOUTH_PART_ROLES[layer_name], None
    if layer_name == "Hair underlay":
        return "hair_under", None
    if group.startswith("Eye "):
        base = " ".join(w for w in words if w not in ("L", "R"))
        return _EYE_ROLES.get(base, "eye_white"), group.split()[-1]
    if group == "Face":
        base = " ".join(w for w in words if w not in ("L", "R"))
        return _FACE_ROLES.get(base, "face"), side
    if group == "Body":
        base = " ".join(w for w in words if w not in ("L", "R") and not w.isdigit())
        return _BODY_ROLES.get(base, "body"), side
    return _ROLES.get(group, "body"), side


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name.replace(" ", "_")).strip("_") or "layer"


def _union(boxes):
    return layers.union_box([b for b in boxes if b])


def grid_for(width: int, height: int, step: int = 28, most: int = 40) -> list[int]:
    """Mesh columns and rows for a layer: about one vertex every step pixels, 2 to most per side."""
    return [max(2, min(most, round(width / step) + 1)), max(2, min(most, round(height / step) + 1))]


def build_puppet(
    tree: list,
    manifest: dict,
    size: tuple[int, int],
    folder,
    name: str,
    parts: list | None = None,
    enhance=None,
    joints: dict | None = None,
    people: list | None = None,
    neutral_pose: bool = False,
    depth_maps: dict | None = None,
    sleeve_map=None,
    fixed_pose: bool = False,
) -> dict:
    """
    Write a puppet for the kit's layer tree (top to bottom, as build_tree returns it) into folder.

    parts (the decomposition's layers) gives each layer's depth for the head-turn parallax; without
    it the depth follows the drawing order. enhance, when given, takes the eyes' and mouth's textures
    (RGBA) and returns sharper, larger copies (or None): those are small on the canvas and the
    player draws them biggest, so they get more pixels.

    joints (canvas pixels, from a pose detector: see skeleton.from_keypoints) give the puppet a
    full-body skeleton to pose, as do people (a pose detector's OpenPose "people" list, canvas
    pixels) when joints aren't given; neutral_pose says the character stands in the neutral A-pose, so
    without joints the skeleton comes from anime proportions. depth_maps ({See-through tag: mode L
    canvas}, "" for the nearest surface; see layers.depth_canvases) give every mesh point a depth
    ("Z"), so turning the head or the body shows real parallax. sleeve_map (RGB, canvas size; see
    skeleton.sleeve_map_masks) marks the outer garment's sleeves, so each comes off whole with its
    arm. fixed_pose keeps the picture's pose: no skeleton and no arm parameters, the fixed-pose
    runtime (fixed_pose.py: 28 emotions with head and body reactions, breathing and sway, and the
    boop, pat, poke and tap touch reactions on the nose, head, cheeks and body). Returns the puppet
    document.
    """
    folder = pathlib.Path(folder)
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "textures").mkdir(parents=True)
    depths = {}
    for part in parts or []:
        depths[part.tag] = part.depth

    entries = []
    used = set()
    features = []  # (texture path, image) of the eyes and mouth, for enhance
    total = sum(len(group.children) for group in tree)
    order = 0
    # Bottom to top: the player draws in this order.
    for group, group_info in zip(reversed(tree), reversed(manifest["groups"])):
        for layer, info in zip(reversed(group.children), reversed(group_info["layers"])):
            image = layer.image.convert("RGBA")
            bbox = _solid_bbox(image.getchannel("A"))
            if bbox is None:
                continue
            pad = 2
            bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(image.width, bbox[2] + pad), min(image.height, bbox[3] + pad))
            image = image.crop(bbox)
            left, top = layer.left + bbox[0], layer.top + bbox[1]
            role, side = role_of(group.name, layer.name)
            file_id = _safe(f"{group.name}_{layer.name}")
            if info.get("internal") or role in ("inner", "nude_body"):
                file_id = layers.INTERNAL_PREFIX + file_id  # shows inner wear or less
            while file_id in used:
                file_id += "_"
            used.add(file_id)
            image.save(folder / "textures" / f"{file_id}.png")
            if role in FEATURE_ROLES:
                features.append((folder / "textures" / f"{file_id}.png", image))
            depth = depths.get(info.get("tag") or "", None)
            if depth is None:
                depth = 1.0 - order / max(1, total - 1)
            entry = {
                    "Id": file_id,
                    "Name": layer.name,
                    "Part": group.name,
                    "Role": role,
                    "Side": side,
                    "Texture": f"textures/{file_id}.png",
                    "X": left,
                    "Y": top,
                    "Width": image.width,
                    "Height": image.height,
                    "Depth": round(float(depth), 4),
                    "Grid": grid_for(image.width, image.height),
                    "Visible": bool(layer.visible),
            }
            if info.get("tag"):
                entry["Tag"] = info["tag"]
            base = " ".join(w for w in layer.name.split() if w not in ("L", "R") and not w.isdigit())
            if base.endswith(" half"):
                base = base[: -len(" half")]
                entry["State"] = "half"
            if role in ("clothing", "inner") and base in GARMENTS:
                entry["Garment"] = GARMENTS[base]
            elif role == "clothing":
                entry["Garment"] = base.split()[0].lower()
            elif role == "arm":
                entry["Garment"] = "arm"
            if entry.get("Garment") in PIECES:
                entry["Switch"] = PIECES[entry["Garment"]]
            if " ".join(w for w in layer.name.split() if w not in ("L", "R")) in ACCESSORY_LAYERS:
                entry["Accessory"] = True
            entries.append(entry)
            order += 1

    if enhance and features:
        try:
            sharper = enhance([image for _, image in features])
        except Exception:  # noqa: BLE001 - sharper textures are a bonus; the puppet works without
            sharper = None
        for (path, image), better in zip(features, sharper or []):
            if better is not None and better.width >= image.width:
                better.save(path)

    rig = build_rig(entries, size)
    cloth_sway(folder, entries, rig.get("Cloth", []))
    if rig.get("Mouth"):
        rig["Mouth"]["Jaw"] = jaw_line(folder, entries, rig["Mouth"]["Box"])
    radii, arm_alpha = None, {}
    if fixed_pose:
        # The picture's pose stays: no arm to swing, no skeleton to pose.
        joints = people = None
        neutral_pose = False
        rig["Arms"] = {}
        rig["FixedPose"] = True
    if joints is None and people:
        detected = skeleton.from_keypoints(people, rig["Head"]["Box"], size)
        if detected:
            joints = skeleton.complete(detected, rig["Head"]["Box"])
    if neutral_pose:
        if joints is None:
            joints = skeleton.from_proportions(rig["Head"]["Box"], rig["Body"]["Box"])
        arm_alpha, silhouette = limb_alphas(folder, entries, size)
        joints, radii = skeleton.fit_to_layers(joints, rig["Head"]["Box"], arm_alpha, silhouette)
        # Only the hands come off with the arms from their own layers (the split leaves stray bits of
        # an arm under a sleeve, which would punch holes in the body).
        face_h = rig["Head"]["Box"][3] - rig["Head"]["Box"][1]
        for side in list(arm_alpha):
            if f"wrist_{side}" not in joints:
                del arm_alpha[side]
                continue
            hand = arm_alpha[side].point(lambda v: 255 if v > 128 else 0).filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(7))
            hand.paste(0, (0, 0, size[0], max(0, int(joints[f"wrist_{side}"][1] - face_h * 0.15))))
            arm_alpha[side] = hand
    bones = skeleton.bones(joints, rig["Head"]["Box"], radii) if joints else None
    parameters = [p for p in PARAMETERS if not (fixed_pose and p[0].startswith(fixed_runtime.POSE_PREFIXES))]
    if bones:
        # Posed by the bones: the arms bend with them, and the body layers get finer meshes to bend smoothly.
        rig["Skeleton"] = bones
        rig.pop("Arms", None)
        parameters += skeleton.parameters(bones)
        picture = body_picture(folder, entries, size)
        sleeves = skeleton.sleeve_map_masks(sleeve_map, size) if sleeve_map is not None else None
        masks = skeleton.split_legs(skeleton.split_arms(skeleton.limb_masks(bones, size, arms=arm_alpha), bones, picture, arm_alpha, sleeves), bones, picture)
        entries = split_limbs(folder, entries, masks, rig, hands=arm_alpha)
        for entry in entries:
            if entry["Role"] not in HEAD_ROLES:
                entry["Grid"] = grid_for(entry["Width"], entry["Height"], step=20, most=64)
    if depth_maps:
        rig["Depth"] = add_depth(entries, depth_maps, rig)
    areas = hit_areas(rig, size, entries, fixed_pose)
    ids = {p[0] for p in parameters}
    if fixed_pose:
        written = fixed_runtime.write_runtime(folder, ids, [a["Name"] for a in areas], settings=False)
        reactions = {a["Name"]: fixed_runtime.HIT_AREAS.get(a["Name"], "Tap") for a in areas}
        st = fixed_runtime.sillytavern_settings(written["Motions"], ids, [a["Name"] for a in areas])
    else:
        written = model_files.write_model_files(folder)
        reactions = dict(REACTIONS)
        st = model_files.sillytavern_settings(motions=set(written["Motions"]), parameters=ids, reactions={k: v for k, v in REACTIONS.items() if k != "Drag"})
    outfits = write_outfits(folder, entries)
    written["Expressions"] = written["Expressions"] + outfits
    (folder / model_files.SETTINGS_FILE).write_text(json.dumps(st, indent=2) + "\n", encoding="utf-8")
    document = {
        "Type": FORMAT,
        "Version": VERSION,
        "Name": name,
        "Canvas": {"Width": size[0], "Height": size[1]},
        "Parameters": [{"Id": pid, "Min": low, "Max": high, "Default": default} for pid, low, high, default in parameters],
        "Layers": entries,
        "Rig": rig,
        "HitAreas": areas,
        "Reactions": reactions,
        "Outfits": [item["Name"] for item in outfits if item["Name"].startswith("outfit_")],
        "FileReferences": {"Expressions": written["Expressions"], "Motions": written["Motions"]},
        "Groups": [
            {"Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen", "ParamEyeROpen"]},
            {"Target": "Parameter", "Name": "LipSync", "Ids": ["ParamMouthOpenY"]},
        ],
    }
    (folder / f"{name}{SUFFIX}").write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_preview(folder, name)
    return document


# Layers made from edits after the split, and which of See-through's layers' depth they take.
DEPTH_FALLBACK = {"nude body": "", "inner wear": "", "inner top": "", "inner bottom": "", "hair underlay": "front hair"}


def save_depth(folder, depth_maps: dict) -> None:
    """Write depth canvases (layers.depth_canvases) as PNGs with an index.json of tag -> file."""
    folder = pathlib.Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    index = {}
    for tag, depth in depth_maps.items():
        file = (_safe(tag) if tag else "nearest") + ".png"
        depth.save(folder / file)
        index[tag] = file
    (folder / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


def load_depth(folder) -> dict:
    """What save_depth wrote ({} without it)."""
    folder = pathlib.Path(folder)
    try:
        index = json.loads((folder / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    result = {}
    for tag, file in index.items():
        try:
            with Image.open(folder / file) as depth:
                result[tag] = depth.convert("L")
        except OSError:
            continue
    return result


def add_depth(entries: list[dict], depth_maps: dict, rig: dict) -> dict:
    """
    Give every layer's mesh points a depth ("Z": 0 nearest to 255 farthest, row by row over its
    Grid) from its See-through layer (or the nearest surface), and return the rig's depth: the head's
    and the body's turning centre and how many canvas pixels one step of depth is.
    """
    import numpy as np

    face_box = rig["Head"]["Box"]
    face_w = face_box[2] - face_box[0]
    # Smooth: the estimate is noisy along strands and edges, and neighbouring points moving apart
    # by different amounts tear the mesh.
    radius = max(2.0, face_w * 0.12)
    arrays = {tag: np.asarray(depth.filter(ImageFilter.GaussianBlur(radius))) for tag, depth in depth_maps.items()}
    nearest = arrays.get("")
    for entry in entries:
        tag = entry.get("Tag") or ""
        depth = arrays.get(tag)
        if depth is None:
            depth = arrays.get(DEPTH_FALLBACK.get(tag.removesuffix(" half"), ""), nearest)
        if depth is None:
            continue
        cols, rows = entry["Grid"]
        xs = np.clip(np.round(entry["X"] + np.linspace(0, entry["Width"], cols)).astype(int), 0, depth.shape[1] - 1)
        ys = np.clip(np.round(entry["Y"] + np.linspace(0, entry["Height"], rows)).astype(int), 0, depth.shape[0] - 1)
        entry["Z"] = depth[np.ix_(ys, xs)].astype(int).ravel().tolist()

    def median(roles):
        values = [z for e in entries if e["Role"] in roles and e.get("Z") for z in e["Z"]]
        return float(np.median(values)) if values else None

    face = median(("face",)) or 0.0
    back = median(("back_hair",))
    # From the face to the back of the head is about a face's width.
    span = max(20.0, (back - face) if back is not None else 60.0)
    scale = face_w * 1.1 / span
    # The head turns nearly as one piece. Its layers' estimated depths spread far too wide (the
    # eyes half a face in front of the cheeks, the fringe more), and the top and back of the skull
    # that would hide the back hair aren't drawn: turned by their full depths, the fringe slides
    # off the face and the back hair swings out past the head as a lump. Around the face's depth
    # they keep only a little of their spread, so the back hair trails the face instead.
    for entry in entries:
        if entry["Role"] in HEAD_ROLES and entry.get("Z"):
            entry["Z"] = [round(face + HEAD_DEPTH_SPREAD * (z - face)) for z in entry["Z"]]
    body_z = median(("clothing", "nude_body")) or face
    body_w = rig["Body"]["Box"][2] - rig["Body"]["Box"][0]
    body_centre = body_z + body_w * 0.25 / scale
    if nearest is not None:
        # Each joint sits inside the body, half its thickness behind the surface drawn over it
        # (canvas pixels in front of the body's centre: negative is behind).
        for bone in rig.get("Skeleton", {}).get("Bones", []):
            x, y = (int(min(max(v, 0), limit - 1)) for v, limit in zip(bone["Head"], (nearest.shape[1], nearest.shape[0])))
            surface = float(nearest[y, x])
            bone["HeadZ"] = round((body_centre - surface) * scale - bone["Radius"] * 0.5, 1)
    return {
        "Head": round(face + span / 2, 1),
        # The body turns about its middle, a quarter of its width behind its front.
        "Body": round(body_centre, 1),
        "Scale": round(scale, 4),
    }


def jaw_line(folder, entries: list[dict], mouth_box) -> list | None:
    """
    [[x, y], ...]: the bottom of the face (the jaw and chin) across and around the mouth, so the
    player keeps a moving mouth, and the art that replaces it, inside the face instead of clipping
    over the chin.
    """
    import numpy as np

    face = next((e for e in entries if e["Role"] == "face"), None)
    if face is None:
        return None
    try:
        alpha = np.asarray(Image.open(pathlib.Path(folder) / face["Texture"]).convert("RGBA").getchannel("A")) > 128
    except OSError:
        return None
    width = mouth_box[2] - mouth_box[0]
    points = []
    for i in range(9):
        x = mouth_box[0] - width * 0.5 + width * 2 * i / 8
        column = int(round(x - face["X"]))
        if not 0 <= column < alpha.shape[1]:
            continue
        rows = np.nonzero(alpha[:, column])[0]
        if len(rows):
            points.append([round(x, 1), round(float(rows.max()) + face["Y"], 1)])
    return points or None


def body_picture(folder, entries: list[dict], size) -> Image.Image:
    """The body below the head as the puppet shows it at first (RGBA, canvas size)."""
    folder = pathlib.Path(folder)
    picture = Image.new("RGBA", size, (0, 0, 0, 0))
    for entry in entries:
        if entry["Role"] in HEAD_ROLES or entry["Role"] in ("back_hair", "front_hair", "cheek", "cheek_hatch", "nude_body", "inner"):
            continue
        if entry.get("State") == "half" or not entry.get("Visible", True):
            continue
        try:
            with Image.open(folder / entry["Texture"]) as image:
                picture.alpha_composite(image.convert("RGBA"), (entry["X"], entry["Y"]))
        except (OSError, ValueError):
            continue
    return picture


def limb_alphas(folder, entries: list[dict], size) -> tuple[dict, Image.Image]:
    """Each arm layer's alpha ({"L"/"R": mode L, canvas size}) and the alpha of the whole body below the head."""
    folder = pathlib.Path(folder)
    arms: dict = {}
    silhouette = Image.new("L", size, 0)
    for entry in entries:
        if entry["Role"] in HEAD_ROLES or entry["Role"] in ("back_hair", "front_hair", "cheek", "cheek_hatch"):
            continue
        try:
            alpha = Image.open(folder / entry["Texture"]).convert("RGBA").getchannel("A")
        except OSError:
            continue
        canvas = Image.new("L", size, 0)
        canvas.paste(alpha, (entry["X"], entry["Y"]))
        silhouette = ImageChops.lighter(silhouette, canvas)
        if entry["Role"] == "arm" and entry.get("Side") in ("L", "R"):
            arms[entry["Side"]] = ImageChops.lighter(arms[entry["Side"]], canvas) if entry["Side"] in arms else canvas
    return arms, silhouette


def _skirt(alpha: Image.Image, box, masks: dict) -> bool:
    """Whether a bottomwear layer is a skirt (whole across the middle between the legs) rather than trousers."""
    import numpy as np

    legs = [masks[g].getbbox() for g in ("leg_L", "leg_R") if g in masks and masks[g].getbbox()]
    if len(legs) < 2:
        return False
    top = min(b[1] for b in legs)
    mid = sum((b[0] + b[2]) / 2 for b in legs) / 2
    a = np.asarray(alpha) > 128
    x = int(mid) - box[0]
    if not 0 <= x < a.shape[1]:
        return False
    below = a[max(0, top - box[1]):]
    counts = below.sum(axis=1)
    # The garment's own rows (not stray bits further down).
    rows = counts >= 0.4 * max(1, counts.max())
    if rows.sum() < 4:
        return False
    return below[rows, max(0, x - 2):x + 3].any(axis=1).mean() > 0.8


def _unlike(image: Image.Image, alpha: Image.Image, distance: int = 70) -> Image.Image:
    """Where a layer's colour is far from its usual colour (mode L mask)."""
    rgb = image.convert("RGB")
    median = tuple(int(v) for v in ImageStat.Stat(rgb, alpha.point(lambda v: 255 if v > 128 else 0)).median)
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, median)).convert("L")
    return diff.point(lambda v: 255 if v > distance * 0.6 else 0).filter(ImageFilter.MaxFilter(5))


def _trim_below_bulk(alpha: Image.Image) -> Image.Image:
    """alpha without what lies well below the rows the layer mostly fills."""
    import numpy as np

    a = np.asarray(alpha).copy()
    counts = (a > 128).sum(axis=1)
    rows = np.nonzero(counts >= 0.4 * max(1, counts.max()))[0]
    if len(rows):
        a[rows.max() + max(8, a.shape[0] // 50):] = 0
    return Image.fromarray(a, "L")


def _fill_behind(image: Image.Image, alpha: Image.Image, torso: Image.Image, sides: bool = False) -> tuple[Image.Image, Image.Image]:
    """
    The body behind a limb cut out of the torso piece: where the cut leaves a hole inside the torso
    (a hand in front of the skirt, a sleeve over the side of the jacket), the hole is painted in from
    the torso around it, so moving the limb away doesn't show a gap. Holes at the torso's edge stay
    open (nothing was there).
    """
    import numpy as np

    a = np.asarray(alpha).astype(np.float32) / 255
    t = np.asarray(torso).astype(np.float32) / 255
    removed = (a > 0.5) & (t < 0.5)
    if not removed.any():
        return image, torso
    kept = t > 0.5
    # Bounded on both sides in its row by torso that stays.
    hole = np.zeros_like(removed)
    for y in np.nonzero(removed.any(axis=1))[0]:
        xs = np.nonzero(kept[y])[0]
        if len(xs) > 1:
            hole[y, xs.min():xs.max() + 1] = removed[y, xs.min():xs.max() + 1]
    if sides:
        hole |= _hidden_sides(kept, removed)
    if not hole.any():
        return image, torso
    rgb = np.asarray(image.convert("RGB")).astype(np.float32)
    # Spread from the cloth's lit colours only: next to the hole the drawing is in the limb's shadow
    # (under a sleeve the jacket's side is dark) and its outline is dark too, and spread from those
    # the side showed as a dark smudge in the armpit once the arm rose.
    luma = rgb.mean(axis=2)
    lit = kept & (luma >= 0.6 * float(np.median(luma[kept])))
    filled = _push_pull(rgb, lit if lit.sum() >= 0.2 * kept.sum() else kept)
    # Smoothed, so the fill shows no blocks from the pyramid.
    smooth = np.asarray(Image.fromarray(filled.clip(0, 255).astype(np.uint8), "RGB").filter(ImageFilter.GaussianBlur(4))).astype(np.float32)
    out = rgb.copy()
    out[hole] = smooth[hole]
    new_alpha = np.maximum(t, hole.astype(np.float32) * a)
    result = Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")
    result.putalpha(image.getchannel("A"))
    return result, Image.fromarray((new_alpha * 255).clip(0, 255).astype(np.uint8), "L")


def _hidden_sides(kept, removed):
    """
    Where the torso's sides run on behind a limb (bool mask): in the rows where a limb covers the
    torso's edge, the edge is drawn on from the rows above and below where it shows, so lifting
    the arm shows the side of the body instead of a gap under it.
    """
    import numpy as np

    height = kept.shape[0]
    rows = np.nonzero(kept.any(axis=1))[0]
    extra = np.zeros_like(kept)
    if len(rows) < 3:
        return extra
    for side in (0, 1):
        edge = np.full(height, np.nan)
        hidden = np.zeros(height, bool)
        for y in rows:
            xs = np.nonzero(kept[y])[0]
            x = xs.min() if side == 0 else xs.max()
            edge[y] = x
            beyond = x - 1 if side == 0 else x + 1
            hidden[y] = 0 <= beyond < kept.shape[1] and removed[y, beyond]
        shown = rows[~hidden[rows]]
        if len(shown) < 2 or not hidden.any():
            continue
        line = np.interp(np.arange(height), shown, edge[shown])
        for y in rows[hidden[rows]]:
            if side == 0:
                start = int(round(min(line[y], edge[y])))
                extra[y, start : int(edge[y])] = removed[y, start : int(edge[y])]
            else:
                end = int(round(max(line[y], edge[y])))
                extra[y, int(edge[y]) + 1 : end + 1] = removed[y, int(edge[y]) + 1 : end + 1]
    return extra


def _push_pull(rgb, known):
    """Colours for the unknown pixels, spread smoothly from the known ones (a pyramid fill)."""
    import numpy as np

    w = known.astype(np.float32)
    levels = [(rgb * w[..., None], w)]
    while min(levels[-1][1].shape) > 2:
        c, k = levels[-1]
        h, wd = (k.shape[0] + 1) // 2 * 2, (k.shape[1] + 1) // 2 * 2
        c = np.pad(c, ((0, h - c.shape[0]), (0, wd - c.shape[1]), (0, 0)))
        k = np.pad(k, ((0, h - k.shape[0]), (0, wd - k.shape[1])))
        c = c.reshape(h // 2, 2, wd // 2, 2, 3).sum(axis=(1, 3))
        k = k.reshape(h // 2, 2, wd // 2, 2).sum(axis=(1, 3))
        levels.append((c, k))
    colour = levels[-1][0] / np.maximum(levels[-1][1], 1e-6)[..., None]
    for c, k in reversed(levels[:-1]):
        up = np.repeat(np.repeat(colour, 2, axis=0), 2, axis=1)[: k.shape[0], : k.shape[1]]
        own = c / np.maximum(k, 1e-6)[..., None]
        blend = np.clip(k, 0, 1)[..., None]
        colour = own * blend + up * (1 - blend)
    return colour


def _fill_holes(image: Image.Image, most: float = 0.01) -> Image.Image:
    """
    image (RGBA) with the small holes inside it painted in from around them: the split leaves
    pinholes and slits in a garment where something lay over it (a hand at the jacket's hem),
    which show the background once that moves away. A hole bigger than most of the layer's area
    is a real opening and stays.
    """
    import numpy as np

    alpha = image.getchannel("A")
    solid = alpha.point(lambda v: 255 if v > 128 else 0)
    # Everything not reachable from the border through clear pixels is enclosed.
    padded = Image.new("L", (solid.width + 2, solid.height + 2), 0)
    padded.paste(solid, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128)
    inside = np.asarray(padded)[1:-1, 1:-1] == 0
    if not inside.any():
        return image
    area = float((np.asarray(solid) > 0).sum()) or 1.0
    holes = np.zeros_like(inside)
    marks = Image.fromarray(np.where(inside, 0, 255).astype(np.uint8), "L")
    ys, xs = np.nonzero(inside)
    for y, x in zip(ys.tolist(), xs.tolist()):
        if marks.getpixel((x, y)) != 0:
            continue
        ImageDraw.floodfill(marks, (x, y), 100)
        blob = np.asarray(marks) == 100
        if blob.sum() <= most * area:
            holes |= blob
        marks.paste(200, mask=Image.fromarray((blob * 255).astype(np.uint8), "L"))
    if not holes.any():
        return image
    rgb = np.asarray(image.convert("RGB")).astype(np.float32)
    filled = _push_pull(rgb, np.asarray(alpha) > 128)
    # Smoothed, so the fill shows no blocks from the pyramid.
    filled = np.asarray(Image.fromarray(filled.clip(0, 255).astype(np.uint8), "RGB").filter(ImageFilter.GaussianBlur(3))).astype(np.float32)
    out = rgb.copy()
    out[holes] = filled[holes]
    a = np.asarray(alpha).copy()
    a[holes] = 255
    result = Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")
    result.putalpha(Image.fromarray(a, "L"))
    return result


def _into_shoes(folder: pathlib.Path, entries: list[dict]) -> None:
    """
    The legwear (stockings, trousers) carried on down into the shoes: the split cuts it off where
    the shoe's top is, often a little above it, so a sliver of background or skin shows between
    the leg and the shoe, and more when the foot moves. Below its end, over the gap and behind
    the shoe, it's painted on from its own colours (the shoe is drawn over it). Rewrites the
    legwear textures in place.
    """
    import numpy as np

    def canvas(entry):
        image = Image.open(folder / entry["Texture"]).convert("RGBA")
        return image, (entry["X"], entry["Y"])

    shoes = [e for e in entries if e.get("Garment") == "footwear" and e.get("State") != "half"]
    legs = [e for e in entries if e.get("Garment") == "legwear" and e.get("State") != "half"]
    if not shoes or not legs:
        return
    left = min(e["X"] for e in shoes + legs)
    top = min(e["Y"] for e in shoes + legs)
    right = max(e["X"] + e["Width"] for e in shoes + legs)
    bottom = max(e["Y"] + e["Height"] for e in shoes + legs)
    size = (right - left, bottom - top)
    shoe = Image.new("L", size, 0)
    for entry in shoes:
        image, (x, y) = canvas(entry)
        shoe.paste(image.getchannel("A"), (x - left, y - top), image.getchannel("A"))
    shoe_a = np.asarray(shoe) > 128
    if not shoe_a.any():
        return
    shoe_top = np.where(shoe_a.any(axis=0), shoe_a.argmax(axis=0), -1)
    for entry in legs:
        image, (x, y) = canvas(entry)
        full = Image.new("RGBA", size, (0, 0, 0, 0))
        full.paste(image, (x - left, y - top))
        a = np.asarray(full.getchannel("A")) > 128
        if not a.any():
            continue
        has = a.any(axis=0)
        lowest = np.where(has, a.shape[0] - 1 - a[::-1].argmax(axis=0), -1)
        add = np.zeros_like(a)
        reach = max(6, int(size[1] * 0.04))
        for column in np.nonzero(has & (shoe_top >= 0))[0]:
            end, start = lowest[column], shoe_top[column]
            if end < 0 or start - end > reach:
                continue  # the leg doesn't end at the shoe here
            # Over the gap and on down behind the shoe, never into the background a heel's arch shows.
            below = np.nonzero(shoe_a[:, column])[0]
            add[end + 1 : start, column] = True
            add[start : below.max() + 1, column] = shoe_a[start : below.max() + 1, column]
        add &= ~a
        # Only behind the shoe or in the gap just above it, never out past it.
        grown = np.asarray(shoe.filter(ImageFilter.MaxFilter(2 * reach + 1))) > 0
        add &= grown
        if not add.any():
            continue
        rgb = np.asarray(full.convert("RGB")).astype(np.float32)
        filled = _push_pull(rgb, a)
        filled = np.asarray(Image.fromarray(filled.clip(0, 255).astype(np.uint8), "RGB").filter(ImageFilter.GaussianBlur(2))).astype(np.float32)
        out = rgb.copy()
        out[add] = filled[add]
        alpha = np.asarray(full.getchannel("A")).copy()
        alpha[add] = 255
        result = Image.fromarray(out.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")
        result.putalpha(Image.fromarray(alpha, "L"))
        bbox = result.getbbox()
        result = result.crop(bbox)
        result.save(folder / entry["Texture"])
        entry.update({"X": left + bbox[0], "Y": top + bbox[1], "Width": result.width, "Height": result.height})


def _fit_under_skirts(folder: pathlib.Path, entries: list[dict], skirts: dict, grown: dict) -> Image.Image | None:
    """
    The body, inner wear and legwear under a skirt are cut to the skirt's outline over its rows: the
    edits draw the hips a little wider than the skirt, which showed as slivers at its sides (and
    swung out when a leg moved). Off, the skirt then shows hips of its own width. Returns where
    the skirts cover (mode L, canvas size; None without a skirt) bar what hangs over their sides: no
    arm piece takes what's under a skirt there, or it would be drawn over the skirt.
    """
    import numpy as np

    skirt_entries = [e for e in entries if e.get("Garment") == "bottomwear" and e.get("State") != "half" and skirts.get(e.get("Switch") or e["Id"])]
    if not skirt_entries:
        return None
    size = next(iter(grown.values())).size
    keep = np.ones((size[1], size[0]), bool)
    band = max(8, size[0] // 80)
    # What hangs over the skirt's sides goes with the arms.
    arms = np.zeros((size[1], size[0]), bool)
    for group, mask in grown.items():
        if group.startswith("arm"):
            arms |= np.asarray(mask) > 0
    run = np.zeros((size[1], size[0]), bool)
    skirt_alpha = np.zeros((size[1], size[0]), bool)
    for entry in skirt_entries:
        layer = Image.open(folder / entry["Texture"]).getchannel("A")
        canvas = Image.new("L", size, 0)
        canvas.paste(layer, (entry["X"], entry["Y"]))
        skirt_alpha |= np.asarray(canvas) > 128
        alpha = (np.asarray(canvas) > 128) & ~arms
        counts = alpha.sum(axis=1)
        rows = np.nonzero(counts >= 0.4 * max(1, counts.max()))[0]
        if len(rows) < 4:
            continue
        middle = int(np.average(np.arange(size[0]), weights=alpha[rows].sum(axis=0) + 1e-6))
        for y in range(rows[0], rows[-1] + 1):
            row = alpha[y]
            if not row[middle]:
                continue
            # The skirt's own run through the middle (the layer can hold bits under the hands).
            gaps = np.nonzero(~row)[0]
            left = gaps[gaps < middle].max() + 1 if (gaps < middle).any() else 0
            right = gaps[gaps > middle].min() - 1 if (gaps > middle).any() else size[0] - 1
            # A band beside it: a hand hanging further out stays.
            keep[y, max(0, left - band) : max(0, left - 1)] = False
            keep[y, right + 2 : right + band] = False
            run[y, left : right + 1] = True
    for entry in entries:
        if not (entry["Role"] in ("nude_body", "inner") or entry.get("Garment") == "legwear"):
            continue
        path = folder / entry["Texture"]
        image = Image.open(path).convert("RGBA")
        box = (entry["X"], entry["Y"], entry["X"] + image.width, entry["Y"] + image.height)
        region = Image.fromarray((keep * 255).astype(np.uint8)).crop(box)
        image.putalpha(ImageChops.multiply(image.getchannel("A"), region))
        image.save(path)
    # Under a hand the skirt was painted in; the body's outline at its side is still the skirt's
    # (a band wider than its own run), the hand further out isn't.
    covered = Image.fromarray((run * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(2 * band + 1))
    return ImageChops.multiply(covered, Image.fromarray((skirt_alpha * 255).astype(np.uint8)))


def split_limbs(folder, entries: list[dict], masks: dict, rig: dict, overlap: int = 3, hands: dict | None = None) -> list[dict]:
    """
    Cut every body layer (body, clothes, arms) into a piece per limb it covers (masks from
    skeleton.limb_masks) plus the torso piece, each its own texture with "Piece" set to its group,
    so the player can draw an arm over the body when it swings across, and the legs under the hips.
    Neighbouring pieces overlap by a few pixels so no seam opens between them. The head's layers
    stay whole. Returns the new entries (rig["Cloth"] follows the pieces).
    """
    if not masks:
        return entries
    folder = pathlib.Path(folder)
    grown = {group: mask.filter(ImageFilter.MaxFilter(2 * overlap + 1)) for group, mask in masks.items()}
    cores = {group: mask.filter(ImageFilter.MinFilter(2 * overlap + 1)) for group, mask in masks.items()}
    result = []
    renamed: dict[str, list[str]] = {}
    skirts: dict[str, bool] = {}  # by switch: a half-off state is cut from the same garment
    for entry in entries:
        if entry.get("Garment") == "bottomwear" and entry.get("State") != "half" and entry["Role"] not in HEAD_ROLES:
            image = Image.open(folder / entry["Texture"]).convert("RGBA")
            box = (entry["X"], entry["Y"], entry["X"] + image.width, entry["Y"] + image.height)
            skirts[entry.get("Switch") or entry["Id"]] = _skirt(image.getchannel("A"), box, masks)
    _into_shoes(folder, entries)
    under_skirt = _fit_under_skirts(folder, entries, skirts, grown)
    for entry in entries:
        if entry["Role"] in HEAD_ROLES:
            result.append(entry)
            continue
        path = folder / entry["Texture"]
        image = Image.open(path).convert("RGBA")
        if entry.get("Garment"):
            image = _fill_holes(image)
        box = (entry["X"], entry["Y"], entry["X"] + image.width, entry["Y"] + image.height)
        alpha = image.getchannel("A")
        total = ImageStat.Stat(alpha).sum[0] or 1
        if entry["Role"] == "arm" and f"arm_{entry.get('Side')}" in grown:
            # An arm's own layer goes with its arm whole; what lies outside the arm is a stray bit of
            # the split under the sleeve.
            group = f"arm_{entry['Side']}"
            image.putalpha(ImageChops.multiply(alpha, grown[group].crop(box)))
            bbox = image.getchannel("A").getbbox()
            path.unlink()
            if bbox is None:
                renamed[entry["Id"]] = []
                continue
            piece_id = f"{entry['Id']}__{group}"
            image.crop(bbox).save(folder / "textures" / f"{piece_id}.png")
            result.append({**entry, "Id": piece_id, "Texture": f"textures/{piece_id}.png", "X": entry["X"] + bbox[0], "Y": entry["Y"] + bbox[1], "Width": bbox[2] - bbox[0], "Height": bbox[3] - bbox[1], "Piece": group})
            renamed[entry["Id"]] = [piece_id]
            continue
        limbs = []
        if entry["Role"] == "inner":
            # Inner wear doesn't reach down the legs: there it's stockings or shoes the edit kept,
            # which would stay on when the legwear comes off.
            for group in [g for g in cores if g.startswith("leg")]:
                alpha = ImageChops.multiply(alpha, ImageChops.invert(cores[group].crop(box)))
            # Nor is it on the hands: what the edit left around them is the hand redrawn, which
            # would stay on the hips when the arm moves.
            for hand in (hands or {}).values():
                alpha = ImageChops.multiply(alpha, ImageChops.invert(hand.filter(ImageFilter.MaxFilter(31)).crop(box)))
            image.putalpha(alpha)
            image.save(path)
        skirt = False
        if entry.get("Garment") == "bottomwear":
            key = entry.get("Switch") or entry["Id"]
            skirt = skirts[key] if key in skirts else _skirt(alpha, box, masks)
        if skirt or entry.get("Garment") == "outerwear":
            # Stray bits the split left far below the hem would stay behind when a leg moves.
            alpha = _trim_below_bulk(alpha)
            image.putalpha(alpha)
        for group, mask in grown.items():
            if group.startswith("leg") and skirt:
                # A skirt stays whole: the legs move under it.
                continue
            piece = ImageChops.multiply(alpha, mask.crop(box))
            if group.startswith("arm") and entry.get("Garment") in ("bottomwear", "legwear", "footwear"):
                # Hands hang over these: what's under a hand is mostly painted-in garment, which
                # stays; only what isn't the garment's colour (a cuff the split put in the layer)
                # goes with the arm.
                piece = ImageChops.multiply(piece, _unlike(image, alpha))
                hand = (hands or {}).get(group.split("_")[1])
                if hand is not None:
                    # The garment's own dark outline stays too, unless it's on the hand.
                    light = image.convert("L").point(lambda v: 255 if v > 80 else 0)
                    piece = ImageChops.multiply(piece, ImageChops.lighter(light, hand.filter(ImageFilter.MaxFilter(9)).crop(box)))
            elif group.startswith("arm") and under_skirt is not None and (entry["Role"] in ("nude_body", "inner") or entry.get("Garment") == "legwear"):
                # The body under a skirt isn't the arm's: drawn with the arm it would cover the skirt.
                piece = ImageChops.multiply(piece, ImageChops.invert(under_skirt.crop(box)))
            if ImageStat.Stat(piece).sum[0] > 0.01 * total:
                limbs.append((group, piece))
        if not limbs:
            # Still a torso piece: it follows the torso's bones and keeps its place in the drawing order.
            image.save(path)
            result.append({**entry, "Piece": "torso"})
            continue
        taken = Image.new("L", image.size, 0)
        for group, piece in limbs:
            # The legs take all of their side below the crotch, the strip between them too: a
            # sliver of torso left there would stay behind when a leg moves. A limb takes only
            # what its piece holds (on a skirt, just the bit on the hand).
            if group.startswith("leg"):
                region = grown[group].crop(box)
            else:
                # The overlap is kept only along the seam with the rest of the layer: along the
                # limb's own outline the torso would keep a sliver of it (specks of the sleeve's
                # outline hanging in the air once the arm moves).
                limb = masks[group].crop(box).point(lambda v: 255 if v > 0 else 0)
                rest = ImageChops.multiply(alpha.point(lambda v: 255 if v > 128 else 0), ImageChops.invert(limb))
                region = ImageChops.subtract(limb, rest.filter(ImageFilter.MaxFilter(2 * overlap + 1)))
            held = piece.point(lambda v: 255 if v > 0 else 0)
            taken = ImageChops.lighter(taken, ImageChops.multiply(region, held))
        torso_alpha = ImageChops.multiply(alpha, ImageChops.invert(taken))
        if any(group.startswith("arm") for group, _ in limbs):
            # Slivers of an arm's outline the arm's mask fell just short of, cut off from the rest:
            # left on the torso they'd hang in the air once the arm moves.
            from .outfits import _drop_small

            kept = _drop_small(torso_alpha.point(lambda v: 255 if v > 128 else 0), 0.012)
            torso_alpha = ImageChops.multiply(torso_alpha, kept.filter(ImageFilter.MaxFilter(3)))
        # The tops' sides run on behind the arms (the body and what's under stays as drawn: it's
        # covered, and drawn wider it would show past the clothes).
        sides = entry.get("Garment") in ("topwear", "outerwear")
        behind, torso_alpha = _fill_behind(image, alpha, torso_alpha, sides)
        pieces = [("torso", torso_alpha)] + limbs
        path.unlink()
        ids = []
        for group, piece_alpha in pieces:
            bbox = piece_alpha.getbbox()
            if bbox is None:
                continue
            piece = (behind if group == "torso" else image).copy()
            piece.putalpha(piece_alpha)
            piece = piece.crop(bbox)
            piece_id = f"{entry['Id']}__{group}"
            piece.save(folder / "textures" / f"{piece_id}.png")
            result.append(
                {
                    **entry,
                    "Id": piece_id,
                    "Texture": f"textures/{piece_id}.png",
                    "X": entry["X"] + bbox[0],
                    "Y": entry["Y"] + bbox[1],
                    "Width": piece.width,
                    "Height": piece.height,
                    "Piece": group,
                }
            )
            ids.append(piece_id)
        renamed[entry["Id"]] = ids
    cloth = []
    for item in rig.get("Cloth", []):
        cloth += [{**item, "Layer": new} for new in renamed.get(item["Layer"], [item["Layer"]])]
    if "Cloth" in rig:
        rig["Cloth"] = cloth
    result = armpit_shadows(folder, result, masks, rig)
    return shoes_over_legwear(result)


def armpit_shadows(folder, entries: list[dict], masks: dict, rig: dict, band: float = 0.1) -> list[dict]:
    """
    The shadow an arm casts on the jacket or top beside it, lifted onto its own layer: the picture
    was drawn with the arms down, so the cloth along the body's side is shaded dark there, and that
    shade would stay behind as a streak when the arm rises. As an artist parts a shadow out, the
    garment's torso piece gets the shade painted out (filled from the lit cloth around it) and a
    new layer over it carries the shade, its opacity tied to the arm (entry "ShadowOf": the upper
    arm's bone; the player fades it as that bone turns). Returns the entries with the shadows added.
    """
    import numpy as np

    folder = pathlib.Path(folder)
    result = []
    for entry in entries:
        result.append(entry)
        if entry.get("Piece") != "torso" or entry.get("Garment") not in ("outerwear", "topwear") or entry.get("State") == "half":
            continue
        path = folder / entry["Texture"]
        image = Image.open(path).convert("RGBA")
        box = (entry["X"], entry["Y"], entry["X"] + image.width, entry["Y"] + image.height)
        alpha = np.asarray(image.getchannel("A")) > 128
        if alpha.sum() < 400:
            continue
        rgb = np.asarray(image.convert("RGB")).astype(np.float32)
        lum = rgb @ np.array([0.299, 0.587, 0.114], dtype=np.float32)
        base = float(np.median(lum[alpha]))
        reach = max(12, int(band * image.width))  # band: share of the garment's width beside the arm
        for side in ("L", "R"):
            arm = masks.get(f"arm_{side}")
            if arm is None:
                continue
            arm = arm.crop(box)
            near = np.asarray(arm.filter(ImageFilter.MaxFilter(2 * min(reach, 40) + 1))) > 0
            if reach > 40:
                near = np.asarray(Image.fromarray(near.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(2 * (reach - 40) + 1))) > 0
            zone = near & ~(np.asarray(arm) > 127) & alpha
            if zone.sum() < 50:
                continue
            # How far into shadow each pixel there is, against the cloth's usual brightness.
            depth = np.clip((0.88 * base - lum) / max(1.0, 0.45 * base), 0, 1) * zone
            soft = np.asarray(Image.fromarray((depth * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2))).astype(np.float32) / 255
            soft = np.minimum(soft * zone, 1)
            if soft.sum() < 60:
                continue
            # Lit: the same cloth brightened back to its usual tone (folds and texture kept), the
            # colour taken from the lit cloth around it.
            gain = np.clip(0.88 * base / np.maximum(lum, 8.0), 1.0, 3.0)
            known = alpha & (soft < 0.05)
            tint = rgb[known].mean(axis=0) / max(1.0, float(lum[known].mean())) if known.any() else np.ones(3, np.float32)
            lit = (lum * gain)[..., None] * tint[None, None, :] * 0.6 + rgb * gain[..., None] * 0.4
            rgb = rgb * (1 - soft[..., None]) + lit * soft[..., None]
            shade = Image.fromarray(np.asarray(image.convert("RGB")), "RGB").convert("RGBA")
            shade.putalpha(Image.fromarray((soft * np.asarray(image.getchannel("A")).astype(np.float32)).clip(0, 255).astype(np.uint8)))
            bbox = shade.getchannel("A").getbbox()
            if bbox is None:
                continue
            shade_id = f"{entry['Id']}__shadow_{side}"
            shade.crop(bbox).save(folder / "textures" / f"{shade_id}.png")
            result.append(
                {
                    **entry,
                    "Id": shade_id,
                    "Texture": f"textures/{shade_id}.png",
                    "X": entry["X"] + bbox[0],
                    "Y": entry["Y"] + bbox[1],
                    "Width": bbox[2] - bbox[0],
                    "Height": bbox[3] - bbox[1],
                    "ShadowOf": f"UpperArm{side}",
                }
            )
            for item in list(rig.get("Cloth", [])):
                if item.get("Layer") == entry["Id"]:
                    rig["Cloth"].append({**item, "Layer": shade_id})
        lit_image = Image.fromarray(rgb.clip(0, 255).astype(np.uint8), "RGB").convert("RGBA")
        lit_image.putalpha(image.getchannel("A"))
        lit_image.save(path)
    return result


def shoes_over_legwear(entries: list[dict]) -> list[dict]:
    """
    The shoes drawn over the stockings: the split sometimes orders footwear under legwear, and the
    legwear carried down into the shoe (_into_shoes) then covers half the shoe. Each shoe moves to
    just after the last legwear layer of its state (the half-off states keep their own order).
    """
    result = list(entries)
    for state in {e.get("State") for e in result if e.get("Garment") == "footwear"}:
        shoes = [e for e in result if e.get("Garment") == "footwear" and e.get("State") == state]
        legs = [i for i, e in enumerate(result) if e.get("Garment") == "legwear" and e.get("State") == state]
        if not legs or min(result.index(s) for s in shoes) > max(legs):
            continue
        last = result[max(legs)]
        result = [e for e in result if e not in shoes]
        at = result.index(last) + 1
        result[at:at] = shoes
    return result


def write_outfits(folder, entries: list[dict]) -> list[dict]:
    """
    Outfit expressions (outfit_full, the half-off and off states the puppet's layers allow, down to
    outfit_nude), plus accessories_off / accessories_on when it has accessories, as expression list
    entries. The player keeps an outfit (and the accessories) on while the emotions change.
    """
    folder = pathlib.Path(folder)
    roles = {e["Role"] for e in entries}
    switches = {e.get("Switch") for e in entries if e.get("State") != "half"}
    has = {
        "body": "nude_body" in roles,
        "inner": "inner" in roles,
        "inner_split": {"ParamInnerTop", "ParamInnerBottom"} <= switches,
        "outer_split": "ParamClothesTop" in switches and bool({"ParamClothesBottom", "ParamClothesLegs"} & switches),
        "coat": "ParamClothesCoat" in switches,
    }
    has.update({f"{e['Switch']} half": True for e in entries if e.get("State") == "half" and e.get("Switch")})
    wanted: list[tuple[str, list[tuple[str, float]]]] = [
        (name, [(switch, float(values.get(switch, 1))) for switch in _SWITCHES])
        for name, (values, needs) in OUTFITS.items()
        if name != "outfit_full" and all(has.get(need) for need in needs)
    ]
    if wanted:  # something to switch: outfit_full puts everything back on
        wanted.insert(0, ("outfit_full", [(switch, 1.0) for switch in _SWITCHES]))
    if any(e.get("Accessory") for e in entries):
        wanted += [("accessories_off", [("ParamAccessories", 0.0)]), ("accessories_on", [("ParamAccessories", 1.0)])]
    if not wanted:
        return []
    (folder / model_files.EXPRESSIONS_DIR).mkdir(exist_ok=True)
    result = []
    for name, values in wanted:
        relative = f"{model_files.EXPRESSIONS_DIR}/{name}.exp3.json"
        data = {
            "Type": "Live2D Expression",
            "FadeInTime": 0.6,
            "FadeOutTime": 0.6,
            "Parameters": [{"Id": pid, "Value": value, "Blend": "Overwrite"} for pid, value in values],
        }
        (folder / relative).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        result.append({"Name": name, "File": relative})
    return result


def _solid_bbox(alpha: Image.Image):
    """
    The box of a layer's drawing without stray specks (a split can leave a few faint pixels in the
    canvas corners, which would make the layer, and with a face the head, as big as the canvas).
    Pixels outside it are cropped away. None when the layer is empty.
    """
    plain = alpha.getbbox()
    if plain is None:
        return None
    solid = alpha.point(lambda v: 255 if v > 24 else 0).filter(ImageFilter.MinFilter(5)).getbbox()
    if solid is None:
        return plain
    grow = 3
    return (max(plain[0], solid[0] - grow), max(plain[1], solid[1] - grow), min(plain[2], solid[2] + grow), min(plain[3], solid[3] + grow))


def _box(entry) -> tuple[int, int, int, int]:
    return entry["X"], entry["Y"], entry["X"] + entry["Width"], entry["Y"] + entry["Height"]


def build_rig(entries: list[dict], size: tuple[int, int]) -> dict:
    """The boxes and pivots the player deforms the layers around."""
    width, height = size

    def boxes(*roles, side=None):
        return [_box(e) for e in entries if e["Role"] in roles and (side is None or e["Side"] == side)]

    face = _union(boxes("face")) or _union(boxes("eye_white", "iris", "eyelash", "mouth", "nose", "brow"))
    if face is None:
        # No face: treat the top third of the character as the head.
        everything = _union([_box(e) for e in entries]) or (0, 0, width, height)
        face = (everything[0], everything[1], everything[2], everything[1] + (everything[3] - everything[1]) // 3)
    face_w, face_h = face[2] - face[0], face[3] - face[1]
    neck = _union(boxes("neck"))
    pivot_y = neck[1] + (neck[3] - neck[1]) * 0.35 if neck else face[3] - face_h * 0.05
    head = {
        "Box": list(face),
        "Center": [round((face[0] + face[2]) / 2, 1), round(face[1] + face_h * 0.55, 1)],
        "Pivot": [round((face[0] + face[2]) / 2, 1), round(pivot_y, 1)],
        "Radius": round(max(face_w, face_h) / 2, 1),
        "Depth": _depth(entries, "face"),
    }
    body_box = _union(boxes("body", "arm", "neck", "clothing", "nude_body", "inner"))
    if body_box is None:
        body_box = (face[0], face[3], face[2], height)
    body = {
        "Box": list(body_box),
        "Pivot": [round((body_box[0] + body_box[2]) / 2, 1), round(min(height, body_box[3]), 1)],
        "Chest": round(body_box[1] + (body_box[3] - body_box[1]) * 0.25, 1),
    }
    eyes = {}
    for side in ("L", "R"):
        box = _union(boxes("eye_white", "iris", "eyelash", side=side))
        if box is None:
            continue
        eye_h = box[3] - box[1]
        brow = _union(boxes("brow", side=side))
        eyes[side] = {
            "Box": list(box),
            "Lid": round(box[3] - eye_h * 0.28, 1),  # where the lids meet when the eye closes
            "Brow": list(brow) if brow else None,
        }
    if not eyes:
        box = _union(boxes("eyes"))
        if box:
            eyes["LR"] = {"Box": list(box), "Lid": round(box[3] - (box[3] - box[1]) * 0.28, 1), "Brow": None}
    mouth_box = _union(boxes("mouth"))
    mouth = None
    if mouth_box:
        open_box = _union(boxes("mouth_open"))
        mouth = {"Box": list(mouth_box), "Open": list(open_box) if open_box else None, "Center": [round((mouth_box[0] + mouth_box[2]) / 2, 1), round((mouth_box[1] + mouth_box[3]) / 2, 1)]}
    hair = []
    for entry in entries:
        if entry["Role"] in ("front_hair", "back_hair"):
            box = _box(entry)
            root = max(box[1], face[1] - face_h * 0.1) if entry["Role"] == "front_hair" else max(box[1], face[1])
            hair.append({"Layer": entry["Id"], "Root": round(root, 1), "Length": round(max(1, box[3] - root), 1)})
    rig = {
        "Head": head,
        "Body": body,
        "Eyes": eyes,
        "Mouth": mouth,
        "Hair": hair,
        "Strength": dict(STRENGTH),
        "Physics": json.loads(json.dumps(PHYSICS)),
    }
    rig.update(soft_body(entries, face, body_box))
    rig["Cloth"] = cloth(entries, body_box)
    rig["Arms"] = arms(entries, face)
    return rig


def arms(entries: list[dict], face=None) -> dict:
    """
    Each arm's joint for posing: {"L": {"Pivot", "Length", "Layers"}}. The joint is the point of the
    layer nearest the shoulder (beside the neck, under the chin), so a raised or bent arm turns at
    the shoulder and an arm layer that is only a hand (the sleeve in the clothes) turns at the
    wrist. Length is the farthest the layer reaches from it. An arm layer without a side counts for both.
    """
    neck = _union([_box(e) for e in entries if e["Role"] == "neck"])
    found = {}
    for entry in entries:
        if entry["Role"] != "arm":
            continue
        side = entry.get("Side") or "LR"
        left, top, right, bottom = _box(entry)
        width = right - left
        if face is not None:
            face_w, face_h = face[2] - face[0], face[3] - face[1]
            cx = (neck[0] + neck[2]) / 2 if neck else (face[0] + face[2]) / 2
            middle = (left + right) / 2
            sx = cx + (face_w * 0.95 if middle > cx else -face_w * 0.95)
            sy = face[3] + face_h * 0.45
            px, py = min(max(sx, left), right), min(max(sy, top), bottom)
        else:
            px, py = left + width / 2, top + min(width, bottom - top) * 0.3
        reach = max(((cx_ - px) ** 2 + (cy_ - py) ** 2) ** 0.5 for cx_ in (left, right) for cy_ in (top, bottom))
        found[side] = {"Pivot": [round(px, 1), round(py, 1)], "Length": round(max(1.0, reach), 1), "Layers": [entry["Id"]]}
    return found


def soft_body(entries: list[dict], face, body_box) -> dict:
    """
    Where the bust and hips are (centre and radii, canvas pixels), from the head size and anime
    proportions: the bust about one head below the chin, the hips about three. A region the body
    doesn't reach (a bust-up picture has no hips) is left out. Edit the numbers in the puppet file
    to fit a character better; a Radius of 0 turns a region off.
    """
    face_h = face[3] - face[1]
    neck = _union([_box(e) for e in entries if e["Role"] == "neck"])
    cx = (neck[0] + neck[2]) / 2 if neck else (face[0] + face[2]) / 2
    chin = face[3]
    soft = {}
    bust_y = chin + face_h * 1.15
    if body_box[3] > bust_y + face_h * 0.3 and body_box[1] < bust_y:
        offset = face_h * 0.4
        soft["Bust"] = {
            "Centers": [[round(cx + offset, 1), round(bust_y, 1)], [round(cx - offset, 1), round(bust_y, 1)]],
            "Radius": [round(face_h * 0.42, 1), round(face_h * 0.36, 1)],
        }
    hip_y = chin + face_h * 3.1
    if body_box[3] > hip_y + face_h * 0.3:
        soft["Hips"] = {
            "Centers": [[round(cx + face_h * 0.5, 1), round(hip_y, 1)], [round(cx - face_h * 0.5, 1), round(hip_y, 1)]],
            "Radius": [round(face_h * 0.6, 1), round(face_h * 0.55, 1)],
        }
    return soft


def cloth(entries: list[dict], body_box) -> list[dict]:
    """The garments that sway on their own: skirts and dresses from the waist down, ribbons and ties from their top."""
    result = []
    for entry in entries:
        garment = entry.get("Garment")
        box = _box(entry)
        if garment == "bottomwear":
            root = box[1] + (box[3] - box[1]) * 0.25
        elif garment == "neckwear":
            root = box[1] + (box[3] - box[1]) * 0.15
        else:
            continue
        result.append({"Layer": entry["Id"], "Root": round(root, 1), "Length": round(max(1, box[3] - root), 1)})
    return result


def cloth_sway(folder, entries: list[dict], items: list[dict]) -> None:
    """
    How freely each swaying garment swings ("Sway", 0.15..1), from its flare: a pencil skirt as wide
    at the hem as at the hips hugs the legs and barely moves, a skirt that flares out swings freely.
    """
    import numpy as np

    by_id = {e["Id"]: e for e in entries}
    for item in items:
        entry = by_id.get(item["Layer"])
        texture = pathlib.Path(folder) / entry["Texture"] if entry and entry.get("Texture") else None
        if texture is None or not texture.exists():
            continue  # nothing to measure: keep the full swing
        alpha = np.asarray(Image.open(texture).convert("RGBA").getchannel("A")) > 127
        widths = []
        for share in (0.0, 0.85):
            row = int(min(alpha.shape[0] - 1, max(0, item["Root"] - entry["Y"] + share * item["Length"])))
            xs = np.nonzero(alpha[max(0, row - 3) : row + 4].any(0))[0]
            widths.append(xs.max() - xs.min() + 1 if xs.size else 0)
        if widths[0] > 0 and widths[1] > 0:
            flare = widths[1] / widths[0]
            item["Sway"] = round(float(np.clip((flare - 1.0) / 0.35, 0.15, 1.0)), 2)


def _depth(entries, role):
    values = [e["Depth"] for e in entries if e["Role"] == role]
    return round(sum(values) / len(values), 4) if values else 0.5


def hit_areas(rig: dict, size, entries: list[dict] | None = None, fixed_pose: bool = False) -> list[dict]:
    """
    Where a tap lands, most specific first (the extension takes the first area it has a mapping
    for): the face (a boop), the top of the head (a pat), the bust, the hips, then the body. A
    fixed-pose puppet has the nose (a boop) and the cheeks (a poke) first, and no bust or hips.
    """
    head = [round(v, 1) for v in rig["Head"]["Box"]]
    body = rig["Body"]["Box"]
    face_h = head[3] - head[1]
    face_w = head[2] - head[0]
    face = [head[0] + face_w * 0.15, head[1] + face_h * 0.35, head[2] - face_w * 0.15, head[3]]
    areas = []
    if fixed_pose:
        nose = _union([_box(e) for e in entries or [] if e["Role"] == "nose"])
        cx, cy = (nose[0] + nose[2]) / 2 if nose else (head[0] + head[2]) / 2, (nose[1] + nose[3]) / 2 if nose else head[1] + face_h * 0.68
        r = face_w * 0.07
        areas.append({"Name": "Nose", "Id": "HitAreaNose", "Box": [round(cx - r, 1), round(cy - r, 1), round(cx + r, 1), round(cy + r, 1)]})
        top, bottom = head[1] + face_h * 0.6, head[1] + face_h * 0.88
        for side, (x0, x1) in (("R", (0.12, 0.34)), ("L", (0.66, 0.88))):
            areas.append({"Name": "Cheek", "Id": f"HitAreaCheek{side}", "Box": [round(head[0] + face_w * x0, 1), round(top, 1), round(head[0] + face_w * x1, 1), round(bottom, 1)]})
    areas += [
        {"Name": "Face", "Id": "HitAreaFace", "Box": [round(v, 1) for v in face]},
        {"Name": "Head", "Id": "HitAreaHead", "Box": head},
    ]
    for name, area in () if fixed_pose else (("Bust", "Chest"), ("Hips", "Hips")):
        region = rig.get(name)
        if region and region.get("Radius", [0])[0] > 0:
            rx, ry = region["Radius"]
            xs = [c[0] for c in region["Centers"]]
            ys = [c[1] for c in region["Centers"]]
            box = [min(xs) - rx, min(ys) - ry, max(xs) + rx, max(ys) + ry]
            areas.append({"Name": area, "Id": f"HitArea{area}", "Box": [round(v, 1) for v in box]})
    areas.append({"Name": "Body", "Id": "HitAreaBody", "Box": [body[0], max(body[1], head[3]), body[2], body[3]]})
    return areas


# How the character reacts to being touched: hit area (or "Drag" for a pull on the bust or hips)
# -> the emotion it shows, played as that emotion's expression and motion. The player falls back to
# these when nothing else handles the tap (and always for drags); the SillyTavern settings map the
# same reactions so they can be changed there.
REACTIONS = {
    "Face": "surprise",
    "Head": "joy",
    "Chest": "embarrassment",
    "Hips": "annoyance",
    "Body": "curiosity",
    "Drag": "embarrassment",
}


PREVIEW = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} puppet</title>
<style>
  :root {{ color-scheme: light dark; --bg: #f4f4f5; --fg: #18181b; --panel: #ffffffcc; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg: #18181b; --fg: #f4f4f5; --panel: #27272acc; }} }}
  html, body {{ margin: 0; height: 100%; background: var(--bg); color: var(--fg); font: 14px system-ui, sans-serif; }}
  #stage {{ position: fixed; inset: 0; }}
  #panel {{ position: fixed; top: 12px; left: 12px; max-height: calc(100% - 24px); overflow: auto; background: var(--panel);
           padding: 10px 12px; border-radius: 10px; backdrop-filter: blur(6px); width: min(260px, calc(100% - 48px)); }}
  select, button {{ width: 100%; margin: 4px 0; font: inherit; }}
  label {{ display: block; margin-top: 6px; }}
  [hidden] {{ display: none !important; }}
</style>
</head>
<body>
<div id="stage"></div>
<div id="panel">
  <strong>{name}</strong>
  <label>Expression <select id="expression"></select></label>
  <label>Motion <select id="motion"></select></label>
  <label id="outfit-row" hidden>Outfit <select id="outfit"></select></label>
  <div id="slots"></div>
  <label id="accessories-row" hidden><input type="checkbox" id="accessories" checked> Accessories</label>
  <div id="talk" hidden>
    <label>Say <input id="say-text" value="Hello! Nice to meet you, I'm glad you came." style="width:100%;box-sizing:border-box;font:inherit"></label>
    <button id="say">Speak</button>
    <label>Mouth shape <select id="viseme"></select></label>
  </div>
  <div id="vtuber">
    <label style="margin-top:10px"><strong>VTuber</strong></label>
    <button id="track">Track my face (webcam)</button>
    <button id="mic">Lip sync from the microphone</button>
    <label><input type="checkbox" id="mirror" checked> Mirror me</label>
    <button id="recenter" hidden>Recenter (sit as you'll stream, then press)</button>
    <p id="track-note" hidden style="margin:4px 0;opacity:.75"></p>
  </div>
  <label>Blush <input type="range" id="blush" min="0" max="1" step="0.05" value="0"></label>
  <label><input type="checkbox" id="follow" checked> Follow the cursor</label>
  <button id="reset-pose">Reset pose</button>
  <p style="margin:8px 0 0;opacity:.75">Drag the head, an arm or the torso to pose; drag the bust or hips to pull them; tap the head, face or body for a reaction.</p>
</div>
<video id="cam" playsinline muted hidden style="position:fixed;right:12px;bottom:12px;width:min(180px,30vw);border-radius:8px;opacity:.85"></video>
<p id="file-note" hidden style="position:fixed;bottom:12px;left:12px;right:12px;margin:0">
  Browsers don't load the puppet's files from a page opened from the disk. Open <b>play.html</b> instead
  (everything is packed in), or serve this folder: <code>python3 -m http.server</code> and open
  <code>http://localhost:8000/preview.html</code>.
</p>
<script>addEventListener("DOMContentLoaded", () => {{ if (location.protocol === "file:" && !window.AUTOEXPRESS_PUPPET_FILES) document.getElementById("file-note").hidden = false; }});</script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/pixi.js/6.5.2/browser/pixi.min.js"></script>
<script type="module">
import {{ PuppetModel }} from "./puppet.js";
const app = new PIXI.Application({{ resizeTo: window, backgroundAlpha: 0, antialias: true, resolution: window.devicePixelRatio || 1, autoDensity: true }});
document.getElementById("stage").appendChild(app.view);
window.__puppetRenderer = app.renderer;
const model = await PuppetModel.from("{name}{suffix}");
app.stage.addChild(model);
function fit() {{
  const scale = (innerHeight * 0.95) / model.internalModel.height;
  model.scale.set(scale);
  model.x = (innerWidth - model.width) / 2;
  model.y = innerHeight - model.height;
}}
fit();
addEventListener("resize", fit);
model.autoInteract = true;
document.getElementById("follow").onchange = (e) => (model.autoInteract = e.target.checked);
document.getElementById("reset-pose").onclick = () => model.resetPose();
const expressions = document.getElementById("expression");
const outfits = document.getElementById("outfit");
for (const item of model.internalModel.settings.expressions) {{
  if (item.Name.startsWith("outfit_")) outfits.append(new Option(item.Name.slice(7).replaceAll("_", " "), item.Name));
  else if (item.Name.startsWith("accessories_")) document.getElementById("accessories-row").hidden = false;
  else expressions.append(new Option(item.Name, item.Name));
}}
if (outfits.options.length) document.getElementById("outfit-row").hidden = false;
document.getElementById("accessories").onchange = (e) => model.expression(e.target.checked ? "accessories_on" : "accessories_off");
// One control per clothing slot (on, half off, off), like a Koikatsu character.
const SLOT_NAMES = {{ ParamClothesCoat: "Coat", ParamClothesTop: "Top", ParamClothesBottom: "Bottom", ParamClothesLegs: "Legwear", ParamInnerTop: "Inner top", ParamInnerBottom: "Inner bottom" }};
const hasBody = model.doc.Layers.some((e) => e.Role === "nude_body");
const slotControls = [];
for (const [id, label] of Object.entries(SLOT_NAMES)) {{
  const layers = model.doc.Layers.filter((e) => e.Switch === id);
  if (!layers.length || (!hasBody && id !== "ParamClothesCoat")) continue;
  const select = document.createElement("select");
  select.append(new Option("on", "1"));
  if (layers.some((e) => e.State === "half")) select.append(new Option("half off", "0.5"));
  select.append(new Option("off", "0"));
  select.onchange = () => model.internalModel.coreModel.setParameterValueById(id, Number(select.value));
  const row = document.createElement("label");
  row.append(label + " ", select);
  document.getElementById("slots").append(row);
  slotControls.push(select);
}}
outfits.addEventListener("change", () => slotControls.forEach((s) => {{ s.value = "1"; s.onchange(); }}));
outfits.onchange = () => model.expression(outfits.value);
document.getElementById("blush").oninput = (e) => model.internalModel.coreModel.setParameterValueById("ParamCheek", Number(e.target.value));
expressions.onchange = () => model.expression(expressions.value);
const motions = document.getElementById("motion");
for (const [group, list] of Object.entries(model.internalModel.settings.motions))
  list.forEach((_, index) => motions.append(new Option(`${{group}} ${{index}}`, `${{group}}|${{index}}`)));
motions.onchange = () => {{ const [group, index] = motions.value.split("|"); model.motion(group, Number(index)); }};
// Lip sync shapes, with the mouth in pieces (teeth and tongue on their own).
if (model.doc.Layers.some((e) => e.Role === "mouth_inside")) {{
  document.getElementById("talk").hidden = false;
  document.getElementById("say").onclick = () => model.speak(document.getElementById("say-text").value);
  const visemes = document.getElementById("viseme");
  for (const name of model.constructor.visemes) visemes.append(new Option(name, name));
  visemes.onchange = () => {{ model.viseme(visemes.value); model._speech.hold = 1500; }};
}}
// VTuber: the face from the webcam (MediaPipe's face tracker, loaded when asked) and the mouth from the microphone.
const MEDIAPIPE = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";
const FACE_MODEL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
const note = (text) => {{ const p = document.getElementById("track-note"); p.textContent = text; p.hidden = !text; }};
const mirror = document.getElementById("mirror");
const cam = document.getElementById("cam");
const mirrorCam = () => (cam.style.transform = mirror.checked ? "scaleX(-1)" : "");
mirror.onchange = mirrorCam;
mirrorCam();
let tracking = null;
const trackButton = document.getElementById("track");
trackButton.onclick = async () => {{
  if (tracking) {{ tracking.stop(); return; }}
  trackButton.disabled = true;
  note("Starting the webcam and the face tracker…");
  let stream = null;
  try {{
    stream = await navigator.mediaDevices.getUserMedia({{ video: {{ width: 640, height: 480, facingMode: "user" }} }});
    cam.srcObject = stream;
    await cam.play();
    cam.hidden = false;
    const vision = await import(MEDIAPIPE + "/vision_bundle.mjs");
    const files = await vision.FilesetResolver.forVisionTasks(MEDIAPIPE + "/wasm");
    const landmarker = await vision.FaceLandmarker.createFromOptions(files, {{
      baseOptions: {{ modelAssetPath: FACE_MODEL, delegate: "GPU" }}, runningMode: "VIDEO", numFaces: 1,
      outputFaceBlendshapes: true, outputFacialTransformationMatrixes: true,
    }});
    let running = true, seen = -1;
    const loop = () => {{
      if (!running) return;
      if (cam.currentTime !== seen && cam.readyState >= 2) {{
        seen = cam.currentTime;
        model.track(landmarker.detectForVideo(cam, performance.now()), {{ mirror: mirror.checked }});
      }}
      requestAnimationFrame(loop);
    }};
    loop();
    tracking = {{ stop() {{
      running = false;
      stream.getTracks().forEach((t) => t.stop());
      landmarker.close();
      cam.hidden = true;
      model.stopTracking();
      tracking = null;
      trackButton.textContent = "Track my face (webcam)";
      document.getElementById("recenter").hidden = true;
    }} }};
    trackButton.textContent = "Stop tracking";
    document.getElementById("recenter").hidden = false;
    note("");
  }} catch (err) {{
    if (stream) stream.getTracks().forEach((t) => t.stop());
    cam.hidden = true;
    note("Face tracking needs a webcam, and the internet once to load the tracker: " + err.message);
  }}
  trackButton.disabled = false;
}};
document.getElementById("recenter").onclick = () => model.recenter();
let stopMic = null;
const micButton = document.getElementById("mic");
micButton.onclick = async () => {{
  if (stopMic) {{ stopMic(); stopMic = null; micButton.textContent = "Lip sync from the microphone"; return; }}
  try {{
    const stream = await navigator.mediaDevices.getUserMedia({{ audio: {{ echoCancellation: true, noiseSuppression: true }} }});
    const stop = model.listen(stream);
    stopMic = () => {{ stop(); stream.getTracks().forEach((t) => t.stop()); }};
    micButton.textContent = "Stop the microphone";
  }} catch (err) {{
    note("The microphone: " + err.message);
  }}
}};
window.puppet = model;
</script>
</body>
</html>
"""


def write_preview(folder, name: str) -> None:
    """
    Pages that play the puppet in a browser: preview.html (served by a web server, loads the files
    next to it) and play.html (everything packed in, so it opens straight from the disk).
    """
    folder = pathlib.Path(folder)
    if PLAYER.exists():
        shutil.copyfile(PLAYER, folder / "puppet.js")
        if HUMANOID_IK.exists():
            shutil.copyfile(HUMANOID_IK, folder / "humanoid_ik.js")
    page = PREVIEW.format(name=name, suffix=SUFFIX)
    (folder / "preview.html").write_text(page, encoding="utf-8")
    if PLAYER.exists():
        (folder / "play.html").write_text(_packed_page(folder, page), encoding="utf-8")


def _packed_page(folder: pathlib.Path, page: str) -> str:
    """page with the player and every puppet file inlined (textures as data: URLs)."""
    files: dict = {}
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name in ("preview.html", "play.html", "puppet.js", "humanoid_ik.js"):
            continue
        relative = path.relative_to(folder).as_posix()
        if path.suffix == ".png":
            files[relative] = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        elif path.suffix == ".json":
            files[relative] = json.loads(path.read_text(encoding="utf-8"))
    data = json.dumps(files, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    player = PLAYER.read_text(encoding="utf-8").replace("import './humanoid_ik.js';", "")
    if HUMANOID_IK.exists():
        player = HUMANOID_IK.read_text(encoding="utf-8") + "\n" + player
    player = player.replace("</script", "<\\/script")
    page = page.replace('import { PuppetModel } from "./puppet.js";', player)
    return page.replace('<script type="module">', f"<script>window.AUTOEXPRESS_PUPPET_FILES = {data};</script>\n<script type=\"module\">", 1)


def is_puppet(path) -> bool:
    return str(path).lower().endswith(SUFFIX)


def load(path) -> dict:
    document = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    if document.get("Type") != FORMAT:
        raise ValueError(f"{path} is not an {FORMAT}.")
    return document


def texture_image(folder, entry) -> Image.Image:
    return Image.open(pathlib.Path(folder) / entry["Texture"])


def from_kit(kit_folder, output=None) -> pathlib.Path:
    """
    Make a puppet from a kit folder made earlier (its manifest.json and layers/), for kits made before
    puppets existed or after editing the layer PNGs. Returns the puppet folder (kit/puppet/<name> by default).
    """
    from .psd import Group, Layer

    kit_folder = pathlib.Path(kit_folder)
    manifest = json.loads((kit_folder / "manifest.json").read_text(encoding="utf-8"))
    name = manifest.get("name") or kit_folder.name
    size = tuple(manifest["canvas"])
    tree = []
    for group in manifest["groups"]:
        children = []
        for info in group["layers"]:
            path = kit_folder / "layers" / layers.layer_file(group["name"], info)
            if not path.exists():
                continue
            with Image.open(path) as image:
                children.append(Layer(info["name"], image.convert("RGBA"), 0, 0, visible=info.get("visible", True)))
        tree.append(Group(group["name"], children))
    groups = [{**group, "layers": [info for info in group["layers"] if any(layer.name == info["name"] for g in tree if g.name == group["name"] for layer in g.children)]} for group in manifest["groups"]]
    output = pathlib.Path(output) if output else kit_folder / "puppet" / name
    pose = kit_folder / POSE_FILE
    people = json.loads(pose.read_text(encoding="utf-8")).get("people") if pose.exists() else None
    sleeve_map = None
    if (kit_folder / SLEEVE_FILE).exists():
        with Image.open(kit_folder / SLEEVE_FILE) as image:
            sleeve_map = image.convert("RGB")
    build_puppet(
        tree,
        {**manifest, "groups": groups},
        size,
        output,
        name,
        neutral_pose=bool(manifest.get("neutral_pose")),
        depth_maps=load_depth(kit_folder / "depth") or None,
        people=people,
        sleeve_map=sleeve_map,
        fixed_pose=bool(manifest.get("fixed_pose")),
    )
    return output
