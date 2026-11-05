"""
Live2D Cubism 3/4 expression (.exp3.json) and motion (.motion3.json) files for the 28 emotions,
and wiring them into a model so the SillyTavern Live2D extension plays them.

attach_to_model() takes a rigged model folder (a .model3.json with its .moc3, as Cubism Editor
exports it), writes one expression and one short reaction motion per emotion plus a looping
idle, registers them in the .model3.json, and writes sillytavern_settings.json next to it. The
extension reads that file when the model is first picked for a character, so every emotion is
mapped without touching its menus.

The presets (resources/live2d.json) use Live2D's standard parameter ids. When the model has a
.cdi3.json (Cubism's parameter list), only parameters the model has are written.

Only the standard library is used.
"""

import json
import pathlib
import shutil
from functools import lru_cache

RESOURCE = pathlib.Path(__file__).resolve().parent.parent / "resources" / "live2d.json"

EMOTIONS = (
    "admiration", "amusement", "anger", "annoyance", "approval", "caring", "confusion", "curiosity",
    "desire", "disappointment", "disapproval", "disgust", "embarrassment", "excitement", "fear",
    "gratitude", "grief", "joy", "love", "nervousness", "neutral", "optimism", "pride", "realization",
    "relief", "remorse", "sadness", "surprise",
)
IDLE_GROUP = "Idle"
EXPRESSIONS_DIR = "expressions"
MOTIONS_DIR = "motions"
SETTINGS_FILE = "sillytavern_settings.json"
FPS = 30.0
FADE = 0.5
# A reaction is short: long fades would leave it no time at full strength.
MOTION_FADE_IN = 0.25
MOTION_FADE_OUT = 0.4


@lru_cache(maxsize=1)
def presets() -> dict:
    with open(RESOURCE, "r", encoding="utf-8") as handle:
        return json.load(handle)


def expression_parameters(emotion: str) -> dict[str, float]:
    """Parameter id -> value for an emotion, with the shorthand (EyeOpen, BrowY ...) spread over both sides."""
    data = presets()
    values = data["expressions"][emotion]
    result: dict[str, float] = {}
    for key, value in values.items():
        for parameter in data["sided"].get(key, [key]):
            result.setdefault(parameter, float(value))
    return result


def build_expression(emotion: str, parameters: set[str] | None = None) -> dict:
    """The .exp3.json content for an emotion. parameters limits it to ids the model has."""
    multiply = set(presets()["multiply"])
    items = []
    for parameter, value in expression_parameters(emotion).items():
        if parameters is not None and parameter not in parameters:
            continue
        items.append({"Id": parameter, "Value": round(value, 3), "Blend": "Multiply" if parameter in multiply else "Add"})
    return {"Type": "Live2D Expression", "FadeInTime": FADE, "FadeOutTime": FADE, "Parameters": items}


def _segments(keys: list[list[float]]) -> tuple[list[float], int, int]:
    """
    motion3 segment data for keyframes: eased (bezier) segments between consecutive keys.

    Returns (segments, segment count, point count).
    """
    keys = sorted(([float(t), float(v)] for t, v in keys), key=lambda key: key[0])
    data = [round(keys[0][0], 4), round(keys[0][1], 4)]
    for (t0, v0), (t1, v1) in zip(keys, keys[1:]):
        third = (t1 - t0) / 3
        # 1 = bezier: two control points then the end point. Flat handles ease in and out.
        data += [1, round(t0 + third, 4), round(v0, 4), round(t1 - third, 4), round(v1, 4), round(t1, 4), round(v1, 4)]
    count = len(keys) - 1
    return data, count, 1 + 3 * count


def build_motion(curves: dict[str, list[list[float]]], loop: bool = False, duration: float | None = None, parameters: set[str] | None = None) -> dict:
    """The .motion3.json content for keyframed parameters ({id: [[seconds, value], ...]})."""
    items = []
    segment_total = point_total = 0
    end = 0.0
    for parameter, keys in curves.items():
        if parameters is not None and parameter not in parameters:
            continue
        if len(keys) < 2:
            continue
        segments, segment_count, point_count = _segments(keys)
        items.append({"Target": "Parameter", "Id": parameter, "Segments": segments})
        segment_total += segment_count
        point_total += point_count
        end = max(end, max(float(t) for t, _ in keys))
    duration = float(duration if duration is not None else end) or 1.0
    return {
        "Version": 3,
        "Meta": {
            "Duration": round(duration, 4),
            "Fps": FPS,
            "Loop": loop,
            "AreBeziersRestricted": True,
            "FadeInTime": MOTION_FADE_IN,
            "FadeOutTime": MOTION_FADE_OUT,
            "CurveCount": len(items),
            "TotalSegmentCount": segment_total,
            "TotalPointCount": point_total,
            "UserDataCount": 0,
            "TotalUserDataSize": 0,
        },
        "Curves": items,
    }


def reaction_motion(emotion: str, parameters: set[str] | None = None) -> dict | None:
    """The short reaction motion for an emotion, or None (neutral just idles)."""
    data = presets()
    name = data["motions"].get(emotion)
    if not name:
        return None
    curves = dict(data["reactions"][name])
    gesture = data.get("gestures", {}).get(data.get("gesture_for", {}).get(emotion, ""))
    if gesture:
        curves.update(gesture_curves(gesture, max(k[0] for keys in curves.values() for k in keys)))
    return build_motion(curves, parameters=parameters)


def gesture_curves(gesture: dict, length: float) -> dict[str, list[list[float]]]:
    """
    Keyframes for an arm gesture during a reaction: into the pose, held (with its back-and-forth),
    and back out, over at least 2.4 seconds so the fades leave it time to show.
    """
    end = max(2.4, length)
    into, out = 0.45, end - 0.55
    wiggle = {name: amount for name, amount in gesture.get("wiggle", [])}
    curves = {}
    for parameter, value in gesture["pose"].items():
        keys = [[0.0, 0.0], [into, float(value)]]
        if parameter in wiggle:
            t, sign = into + 0.25, 1
            while t < out - 0.2:
                keys.append([round(t, 3), float(value) + sign * wiggle[parameter]])
                t, sign = t + 0.25, -sign
        keys += [[round(out, 3), float(value)], [round(end, 3), 0.0]]
        curves[parameter] = keys
    return curves


def idle_motion(parameters: set[str] | None = None) -> dict:
    idle = presets()["idle"]
    return build_motion(idle["keys"], loop=True, duration=idle["duration"], parameters=parameters)


def motion_value(emotion: str) -> str:
    """How the extension names a motion: <group>_id=<index>."""
    return f"{emotion}_id=0"


def sillytavern_settings(emotions=EMOTIONS, motions: set[str] | None = None, parameters: set[str] | None = None, reactions: dict | None = None) -> dict:
    """
    The extension's per-model settings, with every emotion mapped to its expression and motion,
    and each hit area in reactions (area -> emotion) mapped to that emotion's expression and motion.

    The extension replaces its defaults with this file as a whole, so every key it reads is here.
    """
    def has(parameter: str) -> bool:
        return parameters is None or parameter in parameters

    motions = set(emotions) if motions is None else motions
    cursor = {key: (value if has(value) else "none") for key, value in presets()["cursor_parameters"].items()}
    return {
        "scale": 1.0,
        "x": 0.0,
        "y": 0.0,
        "eye": 45,
        "cursor_param": cursor,
        "param_mouth_open_y_id": "ParamMouthOpenY" if has("ParamMouthOpenY") else "none",
        "mouth_open_speed": 1.0,
        "mouth_time_per_character": 30,
        "animation_starter": {"expression": "neutral" if "neutral" in emotions else "none", "motion": "none", "delay": 0},
        "animation_default": {"expression": "neutral" if "neutral" in emotions else "none", "motion": "none"},
        "animation_click": {"expression": "none", "motion": "none", "message": ""},
        "hit_areas": {
            area: {
                "expression": emotion if emotion in emotions else "none",
                "motion": motion_value(emotion) if emotion in motions else "none",
                "message": "",
            }
            for area, emotion in (reactions or {}).items()
        },
        "classify_mapping": {
            emotion: {"expression": emotion, "motion": motion_value(emotion) if emotion in motions else "none"} for emotion in EMOTIONS if emotion in emotions
        },
    }


def model_parameters(folder: pathlib.Path, model3: dict) -> set[str] | None:
    """The model's parameter ids from its .cdi3.json, or None when there isn't one."""
    name = (model3.get("FileReferences") or {}).get("DisplayInfo")
    candidates = [folder / name] if name else []
    candidates += sorted(folder.glob("*.cdi3.json"))
    for path in candidates:
        if path.is_file():
            try:
                info = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            ids = {item.get("Id") for item in info.get("Parameters", []) if item.get("Id")}
            if ids:
                return ids
    return None


def find_model3(folder: pathlib.Path) -> pathlib.Path:
    matches = sorted(pathlib.Path(folder).glob("*.model3.json"))
    if not matches:
        raise FileNotFoundError(f"No .model3.json in {folder}. Export the model from Cubism Editor (File > Export For Runtime) first.")
    return matches[0]


def write_model_files(folder: pathlib.Path, parameters: set[str] | None = None) -> dict:
    """Write expressions/<emotion>.exp3.json, motions/<emotion>.motion3.json and motions/idle.motion3.json into folder."""
    folder = pathlib.Path(folder)
    (folder / EXPRESSIONS_DIR).mkdir(parents=True, exist_ok=True)
    (folder / MOTIONS_DIR).mkdir(parents=True, exist_ok=True)
    expressions, motions = [], {}
    for emotion in EMOTIONS:
        relative = f"{EXPRESSIONS_DIR}/{emotion}.exp3.json"
        _write_json(folder / relative, build_expression(emotion, parameters))
        expressions.append({"Name": emotion, "File": relative})
        motion = reaction_motion(emotion, parameters)
        if motion and motion["Curves"]:
            relative = f"{MOTIONS_DIR}/{emotion}.motion3.json"
            _write_json(folder / relative, motion)
            motions[emotion] = [{"File": relative, "FadeInTime": MOTION_FADE_IN, "FadeOutTime": MOTION_FADE_OUT}]
    idle = idle_motion(parameters)
    if idle["Curves"]:
        relative = f"{MOTIONS_DIR}/idle.motion3.json"
        _write_json(folder / relative, idle)
        motions[IDLE_GROUP] = [{"File": relative, "FadeInTime": 1.0, "FadeOutTime": 1.0}]
    return {"Expressions": expressions, "Motions": motions}


def attach_to_model(folder, backup: bool = True) -> dict:
    """
    Add the 28 emotions to a rigged model folder and map them for the SillyTavern Live2D extension.

    Existing expressions and motions with other names are kept; ours replace ones with the same name.
    Returns a summary: model file, number of expressions and motions, parameters used.
    """
    folder = pathlib.Path(folder)
    model_path = find_model3(folder)
    model3 = json.loads(model_path.read_text(encoding="utf-8"))
    parameters = model_parameters(folder, model3)
    written = write_model_files(folder, parameters)

    references = model3.setdefault("FileReferences", {})
    ours = {item["Name"] for item in written["Expressions"]}
    references["Expressions"] = [item for item in references.get("Expressions", []) if item.get("Name") not in ours] + written["Expressions"]
    motions = references.setdefault("Motions", {})
    for group, items in written["Motions"].items():
        motions[group] = items

    groups = model3.setdefault("Groups", [])
    names = {group.get("Name") for group in groups}

    def add_group(name: str, ids: list[str]) -> None:
        ids = [i for i in ids if parameters is None or i in parameters]
        if name not in names and ids:
            groups.append({"Target": "Parameter", "Name": name, "Ids": ids})

    add_group("EyeBlink", ["ParamEyeLOpen", "ParamEyeROpen"])
    add_group("LipSync", ["ParamMouthOpenY"])

    if backup:
        backup_path = model_path.with_name(model_path.name + ".bak")
        if not backup_path.exists():
            shutil.copy2(model_path, backup_path)
    _write_json(model_path, model3)
    settings = sillytavern_settings(motions=set(written["Motions"]), parameters=parameters)
    _write_json(folder / SETTINGS_FILE, settings)
    return {
        "model": model_path.name,
        "expressions": len(written["Expressions"]),
        "motions": len(written["Motions"]),
        "parameters": "from the model's .cdi3.json" if parameters is not None else "Live2D standard ids (no .cdi3.json found)",
        "settings": SETTINGS_FILE,
    }


def _write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
