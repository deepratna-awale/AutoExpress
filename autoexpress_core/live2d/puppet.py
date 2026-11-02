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

from PIL import Image

from . import layers, model_files

FORMAT = "AutoExpress Puppet"
VERSION = 1
SUFFIX = ".puppet.model.json"
PLAYER = pathlib.Path(__file__).resolve().parent.parent / "resources" / "puppet.js"

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

# Springs: hair, soft body (quick, bouncy, settles slowly) and cloth (slower, heavier).
PHYSICS = {
    "stiffness": 18.0,
    "damping": 5.5,
    "gravity": 0.0,
    "soft": {"stiffness": 75.0, "damping": 3.0},
    "cloth": {"stiffness": 12.0, "damping": 3.2},
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
HEAD_ROLES = ("face", "brow", "brow_angry", "nose", "eyewear", "eyes", "eyelash", "iris", "eye_white", "eye_closed", "eye_tears", "mouth", "mouth_open", "mouth_grin", "ear", "front_hair", "hair_under", "headwear", "back_hair")
# The eyes and mouth: small on the canvas, drawn large; their textures get upscaled.
FEATURE_ROLES = ("eyes", "eyelash", "iris", "eye_white", "eye_closed", "eye_tears", "brow", "brow_angry", "mouth", "mouth_open", "mouth_grin")
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


def grid_for(width: int, height: int, step: int = 28) -> list[int]:
    """Mesh columns and rows for a layer: about one vertex every step pixels, 2 to 40 per side."""
    return [max(2, min(40, round(width / step) + 1)), max(2, min(40, round(height / step) + 1))]


def build_puppet(tree: list, manifest: dict, size: tuple[int, int], folder, name: str, parts: list | None = None, enhance=None) -> dict:
    """
    Write a puppet for the kit's layer tree (top to bottom, as build_tree returns it) into folder.

    parts (the decomposition's layers) gives each layer's depth for the head-turn parallax; without
    it the depth follows the drawing order. enhance, when given, takes the eyes' and mouth's textures
    (RGBA) and returns sharper, larger copies (or None): those are small on the canvas and the
    player draws them biggest, so they get more pixels. Returns the puppet document.
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
            bbox = image.getchannel("A").getbbox()
            if bbox is None:
                continue
            pad = 2
            bbox = (max(0, bbox[0] - pad), max(0, bbox[1] - pad), min(image.width, bbox[2] + pad), min(image.height, bbox[3] + pad))
            image = image.crop(bbox)
            left, top = layer.left + bbox[0], layer.top + bbox[1]
            role, side = role_of(group.name, layer.name)
            file_id = _safe(f"{group.name}_{layer.name}")
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
    written = model_files.write_model_files(folder)
    outfits = write_outfits(folder, entries)
    written["Expressions"] = written["Expressions"] + outfits
    (folder / model_files.SETTINGS_FILE).write_text(
        json.dumps(
            model_files.sillytavern_settings(
                motions=set(written["Motions"]), parameters={p[0] for p in PARAMETERS}, reactions={k: v for k, v in REACTIONS.items() if k != "Drag"}
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    document = {
        "Type": FORMAT,
        "Version": VERSION,
        "Name": name,
        "Canvas": {"Width": size[0], "Height": size[1]},
        "Parameters": [{"Id": pid, "Min": low, "Max": high, "Default": default} for pid, low, high, default in PARAMETERS],
        "Layers": entries,
        "Rig": rig,
        "HitAreas": hit_areas(rig, size),
        "Reactions": dict(REACTIONS),
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


def _depth(entries, role):
    values = [e["Depth"] for e in entries if e["Role"] == role]
    return round(sum(values) / len(values), 4) if values else 0.5


def hit_areas(rig: dict, size) -> list[dict]:
    """
    Where a tap lands, most specific first (the extension takes the first area it has a mapping
    for): the face (a boop), the top of the head (a pat), the bust, the hips, then the body.
    """
    head = [round(v, 1) for v in rig["Head"]["Box"]]
    body = rig["Body"]["Box"]
    face_h = head[3] - head[1]
    face = [head[0] + (head[2] - head[0]) * 0.15, head[1] + face_h * 0.35, head[2] - (head[2] - head[0]) * 0.15, head[3]]
    areas = [
        {"Name": "Face", "Id": "HitAreaFace", "Box": [round(v, 1) for v in face]},
        {"Name": "Head", "Id": "HitAreaHead", "Box": head},
    ]
    for name, area in (("Bust", "Chest"), ("Hips", "Hips")):
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
  <label>Blush <input type="range" id="blush" min="0" max="1" step="0.05" value="0"></label>
  <label><input type="checkbox" id="follow" checked> Follow the cursor</label>
  <button id="reset-pose">Reset pose</button>
  <p style="margin:8px 0 0;opacity:.75">Drag the head, an arm or the torso to pose; drag the bust or hips to pull them; tap the head, face or body for a reaction.</p>
</div>
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
    page = PREVIEW.format(name=name, suffix=SUFFIX)
    (folder / "preview.html").write_text(page, encoding="utf-8")
    if PLAYER.exists():
        (folder / "play.html").write_text(_packed_page(folder, page), encoding="utf-8")


def _packed_page(folder: pathlib.Path, page: str) -> str:
    """page with the player and every puppet file inlined (textures as data: URLs)."""
    files: dict = {}
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.name in ("preview.html", "play.html", "puppet.js"):
            continue
        relative = path.relative_to(folder).as_posix()
        if path.suffix == ".png":
            files[relative] = "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        elif path.suffix == ".json":
            files[relative] = json.loads(path.read_text(encoding="utf-8"))
    data = json.dumps(files, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    player = PLAYER.read_text(encoding="utf-8").replace("</script", "<\\/script")
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
            safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in f"{group['name']} - {info['name']}")
            path = kit_folder / "layers" / f"{safe}.png"
            if not path.exists():
                continue
            with Image.open(path) as image:
                children.append(Layer(info["name"], image.convert("RGBA"), 0, 0, visible=info.get("visible", True)))
        tree.append(Group(group["name"], children))
    groups = [{**group, "layers": [info for info in group["layers"] if any(layer.name == info["name"] for g in tree if g.name == group["name"] for layer in g.children)]} for group in manifest["groups"]]
    output = pathlib.Path(output) if output else kit_folder / "puppet" / name
    build_puppet(tree, {**manifest, "groups": groups}, size, output, name)
    return output
