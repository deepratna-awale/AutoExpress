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
    ("ParamBodyAngleX", -10, 10, 0),
    ("ParamBodyAngleY", -10, 10, 0),
    ("ParamBodyAngleZ", -10, 10, 0),
    ("ParamBreath", 0, 1, 0),
    ("ParamHairFront", -1, 1, 0),
    ("ParamHairSide", -1, 1, 0),
    ("ParamHairBack", -1, 1, 0),
]

# How far things move at the ends of each parameter, as fractions of the face (head) or canvas.
STRENGTH = {
    "turn": 0.10,  # head turn: shift of the face centre at AngleX = 30, in face widths
    "nod": 0.07,  # head nod: shift at AngleY = 30, in face heights
    "tilt": 0.35,  # degrees of head roll per degree of AngleZ
    "parallax": 0.9,  # how much more the nearest layers move than the face (and the back hair less)
    "body": 0.35,  # degrees of body lean per degree of BodyAngleX
    "breath": 0.012,  # chest rise at Breath = 1, in body heights
    "eyeball": 0.14,  # iris travel at EyeBall = 1, in eye widths
    "brow": 0.35,  # brow travel at BrowY = 1, in eye heights
    "mouth_form": 0.35,  # mouth corner travel at MouthForm = 1, in mouth widths
    "hair": 0.06,  # hair tip sway at full swing, in face widths
}

PHYSICS = {"stiffness": 18.0, "damping": 5.5, "gravity": 0.0}

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
_BODY_ROLES = {"Neck": "neck", "Arm": "arm", "Arms": "arm"}
HEAD_ROLES = ("face", "brow", "nose", "eyewear", "eyes", "eyelash", "iris", "eye_white", "eye_closed", "mouth", "mouth_open", "ear", "front_hair", "headwear", "back_hair")


def role_of(group: str, layer_name: str) -> tuple[str, str | None]:
    """(role, side) for a layer of the kit's tree."""
    side = None
    words = layer_name.split()
    if words and words[-1] in ("L", "R"):
        side = words[-1]
    if layer_name.endswith("closed"):
        return "eye_closed", (group.split()[-1] if group.startswith("Eye ") else None)
    if layer_name == "Mouth open":
        return "mouth_open", None
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
    """Mesh columns and rows for a layer: about one vertex every step pixels, 2 to 24 per side."""
    return [max(2, min(24, round(width / step) + 1)), max(2, min(24, round(height / step) + 1))]


def build_puppet(tree: list, manifest: dict, size: tuple[int, int], folder, name: str, parts: list | None = None) -> dict:
    """
    Write a puppet for the kit's layer tree (top to bottom, as build_tree returns it) into folder.

    parts (the decomposition's layers) gives each layer's depth for the head-turn parallax; without
    it the depth follows the drawing order. Returns the puppet document.
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
            depth = depths.get(info.get("tag") or "", None)
            if depth is None:
                depth = 1.0 - order / max(1, total - 1)
            entries.append(
                {
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
            )
            order += 1

    rig = build_rig(entries, size)
    written = model_files.write_model_files(folder)
    (folder / model_files.SETTINGS_FILE).write_text(
        json.dumps(model_files.sillytavern_settings(motions=set(written["Motions"]), parameters={p[0] for p in PARAMETERS}), indent=2) + "\n",
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
        "FileReferences": {"Expressions": written["Expressions"], "Motions": written["Motions"]},
        "Groups": [
            {"Target": "Parameter", "Name": "EyeBlink", "Ids": ["ParamEyeLOpen", "ParamEyeROpen"]},
            {"Target": "Parameter", "Name": "LipSync", "Ids": ["ParamMouthOpenY"]},
        ],
    }
    (folder / f"{name}{SUFFIX}").write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_preview(folder, name)
    return document


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
    body_box = _union(boxes("body", "arm", "neck"))
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
    return {
        "Head": head,
        "Body": body,
        "Eyes": eyes,
        "Mouth": mouth,
        "Hair": hair,
        "Strength": dict(STRENGTH),
        "Physics": dict(PHYSICS),
    }


def _depth(entries, role):
    values = [e["Depth"] for e in entries if e["Role"] == role]
    return round(sum(values) / len(values), 4) if values else 0.5


def hit_areas(rig: dict, size) -> list[dict]:
    head = rig["Head"]["Box"]
    body = rig["Body"]["Box"]
    return [
        {"Name": "Head", "Id": "HitAreaHead", "Box": head},
        {"Name": "Body", "Id": "HitAreaBody", "Box": [body[0], max(body[1], head[3]), body[2], body[3]]},
    ]


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
</style>
</head>
<body>
<div id="stage"></div>
<div id="panel">
  <strong>{name}</strong>
  <label>Expression <select id="expression"></select></label>
  <label>Motion <select id="motion"></select></label>
  <label><input type="checkbox" id="follow" checked> Follow the cursor</label>
</div>
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
const expressions = document.getElementById("expression");
for (const item of model.internalModel.settings.expressions) expressions.append(new Option(item.Name, item.Name));
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
    """A page that plays the puppet in a browser (open it through a web server: browsers block file:// fetches)."""
    folder = pathlib.Path(folder)
    if PLAYER.exists():
        shutil.copyfile(PLAYER, folder / "puppet.js")
    (folder / "preview.html").write_text(PREVIEW.format(name=name, suffix=SUFFIX), encoding="utf-8")


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
