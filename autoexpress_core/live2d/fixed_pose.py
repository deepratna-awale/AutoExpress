"""
The fixed-pose runtime: the 28 emotions and the touch reactions for a model that keeps the picture's pose.

A model built from the undress chain rests in the pose of the picture it came from, so nothing in
its runtime moves an arm, a hand or a leg: no ParamArm*, ParamHand*, ParamBone* or IK curves, only
the head, the body's lean and sway, breathing, the eyes, brows, mouth and the drawn pieces. It has

  * one expression per emotion (28, all different), set on the face's parameters,
  * a short head-and-body reaction motion per emotion, eased pose to pose,
  * two slow idle loops: breathing that alternates shallow and deep, a gentle sway and blinks,
  * four touch reactions with their own settled faces: a boop on the nose, a pat on the head, a poke
    on the cheek and a tap on the body (Boop, Pat, Poke, Tap), mapped to hit areas, and
  * a nod, a head shake and a head tilt for scripts.

write_runtime() writes them into a model or puppet folder (expressions/, motions/,
sillytavern_settings.json); model3_references() gives what a .model3.json lists. The cursor
follow (head, body and eyes), lip sync and the blink between motions come from the player.

Only the standard library is used.
"""

import json
import math
import pathlib
from itertools import pairwise

from .model_files import EMOTIONS, EXPRESSIONS_DIR, MOTIONS_DIR, SETTINGS_FILE, presets

IDLE_GROUP = "Idle"
# Parameters no fixed-pose motion may drive (the arms, hands and legs stay as drawn).
POSE_PREFIXES = ("ParamArm", "ParamHand", "ParamBone", "ParamLeg", "ParamIK", "ParamElbow", "ParamKnee", "ParamFoot", "ParamShoulder")

# Expressions ---------------------------------------------------------------------------------------
# Face parameters every emotion resets (so nothing one emotion set sticks into the next).
RESET = [
    "ParamBrowLY", "ParamBrowRY", "ParamBrowLX", "ParamBrowRX", "ParamBrowLAngle", "ParamBrowRAngle", "ParamBrowLForm", "ParamBrowRForm",
    "ParamEyeLSmile", "ParamEyeRSmile", "ParamEyeLWide", "ParamEyeRWide", "ParamEyeSparkle", "ParamBrowAngry",
    "ParamMouthForm", "ParamMouthGrin", "ParamMouthShout", "ParamCheek", "ParamTears", "ParamSweat", "ParamGloom",
]
MULTIPLY = {"ParamEyeLOpen", "ParamEyeROpen"}
ADD = {"ParamEyeBallX", "ParamEyeBallY", "ParamEyeBallForm", "ParamMouthOpenY", "ParamAngleX", "ParamAngleY", "ParamAngleZ", "ParamBodyAngleX", "ParamBodyAngleY", "ParamBodyAngleZ"}
# The same meaning under another id: puppets call the tears ParamTear.
ALSO = {"ParamTears": "ParamTear"}
_OVERRIDES = {"Sparkle": "ParamEyeSparkle", "BallForm": "ParamEyeBallForm"}


def face(brow=None, brow_l=None, brow_r=None, eye=None, eye_l=None, eye_r=None, gaze=None, mouth=None, head=None, **extra) -> dict:
    """
    Expression parameters: brow (Y, Angle, Form, X) for both sides, eye (Open, Smile, Wide), gaze
    (X, Y), mouth (Form, Open, Grin, Shout), head (X, Y, Z) angles; extra: Cheek, Tears, Sweat,
    Gloom, Sparkle, BrowAngry, BallForm. None leaves a value to the motion.
    """
    p = {}
    for side, b in (("L", brow_l or brow), ("R", brow_r or brow)):
        if b:
            for n, v in zip(("Y", "Angle", "Form", "X"), b):
                p[f"ParamBrow{side}{n}"] = v
    for side, e in (("L", eye_l or eye), ("R", eye_r or eye)):
        if e:
            for n, v in zip(("Open", "Smile", "Wide"), e):
                p[f"ParamEye{side}{n}"] = v
    if gaze:
        p["ParamEyeBallX"], p["ParamEyeBallY"] = gaze
    if mouth:
        for n, v in zip(("ParamMouthForm", "ParamMouthOpenY", "ParamMouthGrin", "ParamMouthShout"), mouth):
            p[n] = v
    if head:
        for n, v in zip("XYZ", head):
            p["ParamAngle" + n] = v
    for k, v in extra.items():
        p[_OVERRIDES.get(k, "Param" + k)] = v
    return p


# Rules from looking at the faces: an eye smile reads as a closed arc only at Smile 1 with Open 0; an
# open smile uses MouthGrin, a small "o" MouthShout, never both; MouthForm over 0.5 with the mouth open
# breaks the teeth.
EXPRESSIONS = {
    "neutral": face(),
    "admiration": face(brow=(0.8, 0.3, 0.4, 0), eye=(1, 0, 0.55), gaze=(0, 0.3), mouth=(0, 0.28, 0, 0), head=(5, 5, 8), Cheek=0.5, Sparkle=1, BallForm=1),
    "amusement": face(brow=(0.6, 0.35, 0.2, 0), eye_l=(0, 1, 0), eye_r=(0.8, 0.5, 0), mouth=(0, 0.3, 1, 0), head=(4, 5, -7), Cheek=0.35),
    "anger": face(brow=(-1, -1, -0.6, 0.4), eye=(0.7, 0, 0.3), gaze=(0, 0.15), mouth=(-1, 0.55, 0, 0), head=(3, -6, 0), BrowAngry=0),
    "annoyance": face(brow=(-0.8, -1, -0.3, 0.3), eye=(0.42, 0, 0), gaze=(0.65, 0.1), mouth=(-1, 0, 0, 0), head=(8, 2, -5), BrowAngry=0),
    "approval": face(brow=(0.4, 0.1, 0.3, 0), eye_l=(0, 1, 0), eye_r=(1, 0.3, 0), mouth=(1, 0, 0, 0), head=(-4, -2, 5), Cheek=0.2, Sparkle=1),
    "caring": face(brow=(0.25, 1, 0.2, -0.3), eye=(0.85, 0.3, 0), gaze=(0, -0.1), mouth=(0.5, 0, 0, 0), head=(6, -4, 11), Cheek=0.15),
    "confusion": face(brow_l=(-0.8, -0.7, 0, 0.2), brow_r=(1, 0.6, 0.6, 0), eye_l=(0.68, 0, 0), eye_r=(1, 0, 0.2), gaze=(0.5, 0.5), mouth=(-0.7, 0, 0, 0), head=(-5, 2, -11), Sweat=1),
    "curiosity": face(brow=(1, 0.2, 0.9, 0), eye=(1, 0, 0.45), gaze=(-0.25, 0.1), mouth=(0, 0, 0, 1), head=(7, 3, 12), Sparkle=1),
    "desire": face(brow=(-0.35, 0.25, 0.2, 0), eye=(0.45, 0, 0), gaze=(0, 0.25), mouth=(0.35, 0, 0, 0), head=(5, -7, -5), Cheek=1, Sparkle=1),
    "disappointment": face(brow=(-0.3, 0.7, -0.6, -0.3), eye=(0.4, 0, 0), gaze=(0.55, -0.7), mouth=(-0.8, 0, 0, 0), head=(4, -7, -6), Gloom=1),
    "disapproval": face(brow=(-0.6, -0.7, -0.4, 0.2), eye=(0, 0, 0), mouth=(-1, 0, 0, 0), head=(-11, 4, 5)),
    "disgust": face(brow_l=(0.4, 0.4, -0.3, 0), brow_r=(-0.9, -1, -0.6, 0), eye_l=(0.62, 0.3, 0), eye_r=(0.4, 0.3, 0), gaze=(0.6, 0), mouth=(-1, 0.3, 0, 0), head=(-14, 4, 7), Gloom=0.75),
    "embarrassment": face(brow=(0.35, 0.9, -0.3, 0), eye=(0.6, 0, 0), gaze=(-0.7, -0.6), mouth=(-0.45, 0, 0, 0), head=(-8, -8, 6), Cheek=1),
    "excitement": face(brow=(1, 0.3, 1, 0), eye=(1, 0, 0.8), gaze=(0, 0.1), mouth=(0, 0.5, 1, 0), head=(3, 4, -5), Cheek=0.6, Sparkle=1, BallForm=1),
    "fear": face(brow=(1, 1, -0.4, -0.7), eye=(1, 0, 1), gaze=(0.5, 0), mouth=(-1, 0.45, 0, 0), head=(-9, -4, -3), Sweat=1, Gloom=0.9, BallForm=-1),
    "gratitude": face(brow=(0.3, 0.75, 0.2, -0.2), eye=(0, 1, 0), mouth=(0.6, 0, 0, 0), head=(0, -8, -4), Cheek=0.9),
    "grief": face(brow=(0.8, 1, -0.6, -0.4), eye=(0, 0, 0), mouth=(-1, 0.6, 0, 0), head=(0, -8, 3), Tears=1, Cheek=0.4),
    "joy": face(brow=(0.6, 0.3, 0.3, 0), eye=(0, 1, 0), mouth=(0, 0.2, 1, 0), head=(0, 3, 6), Cheek=0.5),
    "love": face(brow=(0.3, 0.5, 0.5, 0), eye=(0.6, 0.45, 0), gaze=(0, 0.05), mouth=(1, 0, 0, 0), head=(-5, -2, -8), Cheek=1, Sparkle=1, BallForm=1),
    "nervousness": face(brow=(0.6, 0.9, -0.2, -0.4), eye=(1, 0, 0.5), gaze=(0.6, -0.15), mouth=(-0.8, 0.3, 0, 0), head=(6, -3, -6), Sweat=1),
    "optimism": face(brow=(0.85, -0.15, 0.5, 0), eye=(1, 0.4, 0.3), gaze=(0, 0.4), mouth=(1, 0, 0, 0), head=(-3, 8, -3), Sparkle=1, Cheek=0.3),
    "pride": face(brow_l=(-0.2, -0.4, 0.2, 0), brow_r=(0.6, -0.35, 0.2, 0), eye=(0.5, 0.35, 0), gaze=(0.35, -0.2), mouth=(1, 0, 0, 0), head=(6, 10, -6), Cheek=0.2),
    "realization": face(brow=(1, 0.1, 0.4, 0), eye=(1, 0, 0.6), gaze=(-0.3, 0.5), mouth=(0, 0.65, 0, 0), head=(-7, 8, -6), Sparkle=1),
    "relief": face(brow=(0.1, 0.7, 0.2, -0.2), eye=(0.33, 0, 0), gaze=(0, -0.3), mouth=(0, 0.4, 0, 0), head=(0, -4, 4), Sweat=1, Cheek=0.2),
    "remorse": face(brow=(0.6, 1, -0.6, -0.4), eye=(0.3, 0, 0), gaze=(-0.3, -0.8), mouth=(-0.6, 0, 0, 0), head=(-4, -12, 6), Tears=0.5, Cheek=0.25),
    "sadness": face(brow=(0.6, 1, -0.6, -0.4), eye=(0.58, 0, 0), gaze=(0, -0.7), mouth=(-1, 0, 0, 0), head=(4, -10, 5), Sparkle=1, Tears=0.25),
    "surprise": face(brow=(1, 0.3, 1, 0), eye=(1, 0, 1), mouth=(-0.5, 0, 0, 1), head=(0, 9, 2), BallForm=-1),
}
# The settled face after a touch. The shape switches (eye smile and wide, grin, "o") are left to the
# touch's motion, so it can startle, close the eyes happily or giggle and then hand back to this face.
FREE = {"ParamEyeLSmile", "ParamEyeRSmile", "ParamEyeLWide", "ParamEyeRWide", "ParamMouthGrin", "ParamMouthShout"}
TOUCH_EXPRESSIONS = {
    "Pat": face(brow=(0.3, 0.5, 0.3, 0), eye=(0.8, None, None), gaze=(0, -0.15), mouth=(0.8, 0, None, None), head=(0, -3, 4), Cheek=0.85, Sparkle=1),
    "Boop": face(brow=(0.5, 0.6, 0.2, 0), eye=(1, None, None), gaze=(0, -0.2), mouth=(-0.5, 0, None, None), head=(0, 2, -3), Cheek=0.7, Sparkle=1),
    "Poke": face(brow_l=(-0.6, -0.8, -0.2, 0.2), brow_r=(0.2, -0.3, 0, 0), eye_l=(0.55, None, None), eye_r=(0.9, None, None), gaze=(-0.5, 0.1), mouth=(-1, 0, None, None), head=(7, 0, -6), Cheek=0.55),
    "Tap": face(brow=(0.5, 0.9, -0.3, -0.2), eye=(0.75, None, None), gaze=(0.6, -0.4), mouth=(-0.4, 0, None, None), head=(7, -4, -4), Cheek=1, Sweat=1),
}
# Hit area -> touch reaction (expression and motion group of the same name). Most specific first.
HIT_AREAS = {"Nose": "Boop", "Cheek": "Poke", "Face": "Boop", "Head": "Pat", "Body": "Tap"}
# Old expression names some characters' settings use.
LEGACY = {
    "Neutral": "neutral", "Smile": "joy", "Laugh": "amusement", "Warm": "love", "Shy": "embarrassment", "Sad": "sadness", "Cry": "grief",
    "Angry": "anger", "Disgust": "disgust", "Surprised": "surprise", "Scared": "fear", "Puzzled": "confusion", "Smug": "pride",
}


def build_expression(values: dict, free=(), parameters: set[str] | None = None) -> dict:
    """The .exp3.json for expression values (face()), resetting the face parameters it leaves out."""
    items = []
    for key, value in values.items():
        if value is None:
            continue
        blend = "Multiply" if key in MULTIPLY else "Add" if key in ADD else "Overwrite"
        for pid in (key, ALSO.get(key)):
            if pid and (parameters is None or pid in parameters):
                items.append({"Id": pid, "Value": float(value), "Blend": blend})
    for key in RESET:
        if key in values or key in free:
            continue
        for pid in (key, ALSO.get(key)):
            if pid and (parameters is None or pid in parameters):
                items.append({"Id": pid, "Value": 0.0, "Blend": "Overwrite"})
    return {"Type": "Live2D Expression", "FadeInTime": 0.25, "FadeOutTime": 0.3, "Parameters": items}


# Motions -------------------------------------------------------------------------------------------
HEAD_BODY = ["ParamAngleX", "ParamAngleY", "ParamAngleZ", "ParamBodyAngleX", "ParamBodyAngleY", "ParamBodyAngleZ", "ParamBodyLean", "ParamBreath", "ParamEyeLOpen", "ParamEyeROpen", "ParamEyeBallX", "ParamEyeBallY"]
REST = {"ParamEyeLOpen": 1.0, "ParamEyeROpen": 1.0}
# Ranges the art takes without tearing, in the parameters' units.
LIMIT = {"ParamBodyAngleX": 2.5, "ParamBodyAngleZ": 4.0, "ParamBodyAngleY": 6.0, "ParamAngleX": 22, "ParamAngleY": 18, "ParamAngleZ": 14}
ALIAS = {
    "hx": "ParamAngleX", "hy": "ParamAngleY", "hz": "ParamAngleZ", "bx": "ParamBodyAngleX", "by": "ParamBodyAngleY", "bz": "ParamBodyAngleZ",
    "lean": "ParamBodyLean", "br": "ParamBreath", "ex": "ParamEyeBallX", "ey": "ParamEyeBallY", "eoL": "ParamEyeLOpen", "eoR": "ParamEyeROpen",
    "grin": "ParamMouthGrin", "shout": "ParamMouthShout", "mform": "ParamMouthForm", "cheek": "ParamCheek",
}
PAIRS = {"eo": ["ParamEyeLOpen", "ParamEyeROpen"], "smile": ["ParamEyeLSmile", "ParamEyeRSmile"], "wide": ["ParamEyeLWide", "ParamEyeRWide"]}
FADE_OUT = 0.15


def _ease(keys):
    """Pose to pose: every key a stop (flat handles), eased in and out."""
    data, segments, points = [keys[0][0], keys[0][1]], 0, 1
    for (t0, v0), (t1, v1) in pairwise(keys):
        if abs(v1 - v0) < 1e-9:
            data += [0, t1, v1]
            points += 1
        else:
            d = t1 - t0
            data += [1, t0 + d / 3, v0, t0 + 2 * d / 3, v1, t1, v1]
            points += 3
        segments += 1
    return data, segments, points


def _smooth(keys, loop):
    """Catmull-Rom through sampled keys (the idle's continuous curves)."""
    n = len(keys)

    def tangent(i):
        if loop:
            a = keys[(i - 1) % (n - 1)] if i > 0 else keys[n - 2]
            b = keys[(i + 1) % (n - 1)] if i < n - 1 else keys[1]
            dt = (keys[min(i + 1, n - 1)][0] - keys[max(i - 1, 0)][0]) if 0 < i < n - 1 else 2 * (keys[1][0] - keys[0][0])
            return (b[1] - a[1]) / dt
        if i in (0, n - 1):
            return 0.0
        return (keys[i + 1][1] - keys[i - 1][1]) / (keys[i + 1][0] - keys[i - 1][0])

    data, segments, points = [keys[0][0], keys[0][1]], 0, 1
    for i in range(n - 1):
        (t0, v0), (t1, v1) = keys[i], keys[i + 1]
        d = t1 - t0
        data += [1, t0 + d / 3, v0 + tangent(i) * d / 3, t0 + 2 * d / 3, v1 - tangent(i + 1) * d / 3, t1, v1]
        segments += 1
        points += 3
    return data, segments, points


def build_motion(duration: float, spec: dict, loop: bool = False, fade_in: float = 0.2, fade_out: float = FADE_OUT, smooth=(), parameters: set[str] | None = None) -> dict:
    """
    A .motion3.json from spec ({parameter or alias: [(t, value), ...]}). A one-shot motion starts and
    ends at rest and is back at rest before its fade-out (a fading motion can't finish a move).
    Every head, body and face parameter gets a curve, so nothing an interrupted motion drove sticks.
    """
    wanted = {}
    for key, keys in spec.items():
        for pid in PAIRS.get(key, [ALIAS.get(key, key)]):
            wanted[pid] = list(keys)
    curves, segment_total, point_total = [], 0, 0
    for pid in HEAD_BODY + RESET:
        if pid.startswith(POSE_PREFIXES):
            raise ValueError(f"{pid} moves the pose")
        rest = REST.get(pid, 0.0)
        keys = sorted(wanted.get(pid, []))
        if not loop:
            if not keys or keys[0][0] > 1e-6:
                keys = [(0.0, rest), *keys]
            if keys[-1][0] < duration - fade_out - 0.05:
                keys = [*keys, (duration - fade_out, rest)]
            if keys[-1][0] < duration - 1e-6:
                keys = [*keys, (duration, rest)]
        elif not keys:
            keys = [(0.0, rest), (duration, rest)]
        if any(b[0] <= a[0] for a, b in pairwise(keys)):
            raise ValueError(f"{pid}: keys out of order")
        limit = LIMIT.get(pid)
        if limit is not None and max(abs(v) for _, v in keys) > limit + 1e-6:
            raise ValueError(f"{pid} goes past {limit}")
        keys = [(round(t, 4), round(v, 4)) for t, v in keys]
        data, segments, points = _smooth(keys, loop) if pid in smooth else _ease(keys)
        if parameters is not None and pid not in parameters:
            continue
        curves.append({"Target": "Parameter", "Id": pid, "Segments": [round(x, 4) if isinstance(x, float) else x for x in data]})
        segment_total += segments
        point_total += points
    return {
        "Version": 3,
        "Meta": {
            "Duration": duration, "Fps": 30.0, "Loop": loop, "AreBeziersRestricted": True, "FadeInTime": fade_in, "FadeOutTime": fade_out,
            "CurveCount": len(curves), "TotalSegmentCount": segment_total, "TotalPointCount": point_total, "UserDataCount": 0, "TotalUserDataSize": 0,
        },
        "Curves": curves,
    }


def blink(t, hold=0.04, close=0.07, opening=0.13, base=1.0, depth=0.0):
    return [(t, base), (t + close, depth), (t + close + hold, depth), (t + close + hold + opening, base)]


def pulses(t0, n, period, amp, base=0.0, up=0.4):
    out = []
    for i in range(n):
        a = amp * (1 - 0.18 * i)
        out += [(t0 + i * period + period * up, base + a), (t0 + (i + 1) * period, base)]
    return out


def tremble(t0, t1, hz, amp):
    n = int((t1 - t0) * hz * 2)
    return [(t0 + (i + 1) * (t1 - t0) / (n + 1), amp * (1 if i % 2 else -1) * (1 - i / (n + 2))) for i in range(n)]


def switch(t0, t1):
    """A shape switch on and off fast (these parameters cross-fade art, so no slow ramps)."""
    return [(t0, 0.0), (t0 + 0.05, 1.0), (t1, 1.0), (t1 + 0.07, 0.0)]


def happy_eyes(t0, t1):
    """The eyes close first, the smile switch fades in only while the lids are shut, then they reopen."""
    return {"eo": [(t0, 1.0), (t0 + 0.09, 0.0), (t1, 0.0), (t1 + 0.16, 1.0)], "smile": [(t0 + 0.09, 0.0), (t0 + 0.15, 1.0), (t1 - 0.08, 1.0), (t1, 0.0)]}


# Emotion -> (seconds, spec): head and body only.
REACTIONS = {
    "admiration": (2.0, {"hy": [(0.5, 5), (1.3, 4)], "hz": [(0.6, 3), (1.4, 2)], "by": [(0.6, 2.5), (1.4, 2)], "lean": [(0.7, -2), (1.4, -1.5)], "br": [(0.6, 0.45), (1.5, 0.1)], "eo": blink(1.05, hold=0.06), "ey": [(0.5, 0.2), (1.3, 0.2)]}),
    "amusement": (2.0, {"by": pulses(0.1, 4, 0.36, 2.8), "hy": pulses(0.12, 4, 0.36, 4.0), "hz": [(0.3, -4), (0.9, 4), (1.5, -2)], "bz": [(0.4, 1.2), (1.1, -1.2)], "br": pulses(0.1, 4, 0.36, 0.4)}),
    "anger": (1.6, {"hy": [(0.12, -7), (0.9, -5)], "hx": [(0.12, 3), *tremble(0.25, 0.85, 6, 2.2)], "by": [(0.14, -2.5), (1.0, -1.5)], "lean": [(0.15, -3), (1.0, -2)], "br": [(0.15, 0.5), (1.0, 0.4)], "bz": tremble(0.2, 0.8, 6, 0.6)}),
    "annoyance": (1.7, {"hx": [(0.25, 9), (1.0, 8)], "hz": [(0.3, -4), (1.0, -3)], "hy": [(0.2, 3), (0.7, -2), (1.1, -1)], "ey": [(0.25, 0.6), (0.6, 0.6), (0.85, 0)], "ex": [(0.3, 0.3), (0.8, 0.3)], "br": [(0.3, 0.45), (1.1, 0.0)], "by": [(0.3, 1.5), (1.1, -1.5)]}),
    "approval": (1.5, {"hy": [(0.2, 3), (0.42, -10), (0.66, 1), (0.9, -7), (1.15, 0.5)], "by": [(0.45, -1.8), (0.68, 0), (0.92, -1.2), (1.15, 0)], "hz": [(0.4, 2), (1.1, 1)]}),
    "caring": (2.2, {"hz": [(0.6, 6), (1.5, 5)], "hx": [(0.6, 3), (1.5, 2)], "hy": [(0.5, -2), (0.95, -6), (1.35, -2)], "by": [(0.6, 1.5), (1.5, 1.2)], "lean": [(0.7, -2.5), (1.5, -2)], "br": [(0.6, 0.35), (1.6, 0.05)], "eo": blink(1.0, hold=0.08, close=0.1, opening=0.18)}),
    "confusion": (2.2, {"hz": [(0.35, -8), (1.0, -7), (1.35, 6), (1.8, 4)], "hx": [(0.35, -3), (1.35, 4), (1.8, 2)], "ex": [(0.3, 0.5), (0.9, 0.5), (1.2, -0.5), (1.7, -0.4)], "ey": [(0.3, 0.4), (1.7, 0.3)], "eo": blink(0.55) + blink(0.85), "bz": [(0.4, -1.5), (1.4, 1.5)]}),
    "curiosity": (1.8, {"by": [(0.4, 3), (1.3, 2.5)], "lean": [(0.45, -3.5), (1.3, -3)], "hz": [(0.4, 7), (1.3, 6)], "hx": [(0.45, 6), (1.3, 5)], "hy": [(0.4, 3), (1.3, 2)], "eo": blink(0.75), "br": [(0.4, 0.4), (1.3, 0.2)]}),
    "desire": (2.4, {"hy": [(0.8, -5), (1.8, -4)], "hz": [(0.9, -4), (1.8, -3)], "hx": [(0.8, 3), (1.8, 3)], "lean": [(0.9, -3), (1.8, -2.5)], "by": [(0.9, 2), (1.8, 1.5)], "br": [(0.8, 0.5), (1.9, 0.0)], "eo": blink(1.0, hold=0.22, close=0.16, opening=0.3), "bz": [(0.9, -1.5), (1.8, -1)]}),
    "disappointment": (2.3, {"br": [(0.4, 0.5), (1.5, 0.0)], "by": [(0.4, 1.5), (1.4, -3.5), (1.9, -2.5)], "hy": [(0.4, 2), (1.4, -10), (1.9, -8)], "hz": [(1.4, -4), (1.9, -3)], "hx": tremble(1.3, 2.0, 1.6, 2.5), "eo": blink(1.1, hold=0.2, close=0.14, opening=0.25)}),
    "disapproval": (1.9, {"hx": [(0.25, -8), (0.6, 7), (0.95, -6), (1.3, 4), (1.6, -1)], "hz": [(0.3, 2), (1.3, 1.5)], "hy": [(0.3, 2), (1.4, 1)], "bz": [(0.3, -0.8), (0.65, 0.8), (1.0, -0.6), (1.35, 0.4)]}),
    "disgust": (1.7, {"hx": [(0.15, -10), (1.0, -8)], "hy": [(0.15, 4), (1.0, 3)], "hz": tremble(0.25, 0.75, 7, 2.2), "by": [(0.15, -2.5), (1.0, -1.5)], "lean": [(0.18, 2), (1.0, 1.5)], "bx": [(0.2, -1.5), (1.0, -1)], "br": [(0.15, 0.3), (0.5, 0.0)]}),
    "embarrassment": (2.1, {"hy": [(0.35, -8), (1.5, -6)], "hx": [(0.35, -7), (1.5, -5)], "hz": [(0.35, 3), (0.65, -3), (0.95, 3), (1.25, -2), (1.55, 1.5)], "bz": [(0.4, 1.5), (0.7, -1.5), (1.0, 1.2), (1.3, -1)], "ex": [(0.3, -0.4), (0.8, 0.4), (1.2, -0.4), (1.6, 0)], "eo": blink(0.5) + blink(1.3), "by": [(0.4, -1.5), (1.5, -1)]}),
    "excitement": (1.8, {"by": pulses(0.05, 3, 0.42, 4.5, up=0.45), "hy": pulses(0.08, 3, 0.42, 5), "hz": [(0.25, 4), (0.67, -4), (1.1, 3)], "br": pulses(0.05, 3, 0.42, 0.45), "bz": [(0.25, 1), (0.67, -1), (1.1, 0.8)]}),
    "fear": (1.9, {"hy": [(0.1, 5), (1.2, 3)], "hx": [(0.1, -8), (1.2, -6)], "by": [(0.1, -3), (1.2, -2.5)], "lean": [(0.12, 2), (1.2, 1.5)], "hz": tremble(0.2, 1.25, 9, 1.4), "bz": tremble(0.22, 1.2, 9, 0.5), "br": [(0.1, 0.5), (1.2, 0.45)], "ex": [(0.3, 0.4), (0.6, -0.4), (0.9, 0.3), (1.2, 0)]}),
    "gratitude": (2.1, {"hy": [(0.2, 2), (0.65, -15), (1.2, -15), (1.7, -1)], "by": [(0.65, -4), (1.2, -4), (1.7, 0)], "lean": [(0.65, -4), (1.2, -4), (1.7, 0)], "hz": [(0.65, -2), (1.2, -2)], "br": [(0.25, 0.4), (1.2, 0.1)]}),
    "grief": (2.4, {"hy": [(0.5, -9), (1.9, -8)], "hz": [(0.6, 3), (1.9, 2)], "by": [(0.4, -2), *pulses(0.6, 4, 0.32, 1.6, base=-2), (1.95, -1.8)], "br": pulses(0.6, 4, 0.32, 0.45), "hx": tremble(0.6, 1.9, 1.6, 1.5)}),
    "joy": (1.7, {"hz": [(0.3, 8), (0.75, -6), (1.2, 3)], "by": pulses(0.05, 2, 0.45, 3.5), "hy": [(0.25, 4), (0.5, 1), (0.75, 4), (1.2, 1)], "bz": [(0.3, 2), (0.75, -1.8), (1.2, 0.8)], "br": [(0.3, 0.4), (1.0, 0.1)]}),
    "love": (2.3, {"hz": [(0.6, 6), (1.3, -5), (1.9, 2)], "bz": [(0.65, 2), (1.35, -2), (1.95, 0.6)], "hx": [(0.6, 3), (1.3, -2)], "lean": [(0.8, -2.5), (1.7, -2)], "by": [(0.8, 1.5), (1.7, 1)], "br": [(0.7, 0.5), (1.8, 0.05)], "eo": blink(1.05, hold=0.18, close=0.14, opening=0.26, depth=0.25)}),
    "nervousness": (2.1, {"ex": [(0.2, -0.6), (0.55, 0.5), (0.85, -0.5), (1.2, 0.4), (1.5, -0.2)], "hx": [(0.25, -4), (0.6, 3), (0.9, -3), (1.25, 2)], "bx": [(0.4, -1.2), (1.0, 1.2), (1.5, -0.5)], "bz": [(0.4, 1), (1.0, -1)], "br": pulses(0.1, 5, 0.34, 0.3), "by": pulses(0.1, 5, 0.34, 0.8), "eo": blink(0.4) + blink(0.72) + blink(1.4), "hy": [(0.3, -2), (1.5, -1.5)]}),
    "optimism": (1.7, {"hy": [(0.35, 8), (0.7, 6), (0.92, -3), (1.2, 4)], "by": [(0.35, 2.5), (0.92, 0), (1.2, 1.5)], "br": [(0.35, 0.5), (1.2, 0.15)], "hz": [(0.4, -2), (1.2, -1)], "ey": [(0.35, 0.3), (0.8, 0.3)]}),
    "pride": (1.9, {"hy": [(0.4, 9), (1.3, 8)], "hz": [(0.45, -4), (1.3, -3)], "hx": [(0.45, 4), (1.3, 3)], "by": [(0.4, 3), (1.3, 2.5)], "br": [(0.4, 0.5), (1.3, 0.45)], "eo": blink(0.55, hold=0.4, close=0.12, opening=0.22, depth=0.4), "lean": [(0.45, 1.5), (1.3, 1.2)]}),
    "realization": (1.5, {"hy": [(0.12, 9), (0.5, 7), (0.75, -4), (1.0, 2)], "by": [(0.12, 4), (0.4, 1.5), (0.75, -1), (1.0, 0.5)], "br": [(0.12, 0.5), (0.8, 0.1)], "ey": [(0.12, 0.4), (0.55, 0.4)], "eo": blink(0.55)}),
    "relief": (2.3, {"br": [(0.5, 0.5), (1.7, 0.0)], "by": [(0.5, 2.5), (1.6, -3), (2.0, -1.5)], "hy": [(0.5, 5), (1.6, -6), (2.0, -3)], "hz": [(1.5, 3), (2.0, 2)], "eo": [(0.45, 1.0), (0.6, 0.0), (1.45, 0.0), (1.7, 1.0)]}),
    "remorse": (2.3, {"hy": [(0.8, -13), (1.6, -13), (2.0, -6)], "by": [(0.8, -3), (1.6, -3)], "lean": [(0.8, -3), (1.6, -3)], "hz": [(0.8, 3), (1.6, 3)], "hx": tremble(0.9, 1.6, 2, 1.8), "eo": blink(0.7, hold=0.5, close=0.14, opening=0.3), "br": [(0.3, 0.3), (1.4, 0.0)]}),
    "sadness": (2.3, {"hy": [(0.9, -9), (1.8, -8)], "hz": [(0.9, -4), (1.8, -3)], "by": [(0.4, 1), (1.3, -2.5), (1.8, -2)], "br": [(0.4, 0.45), (1.5, 0.0)], "eo": blink(1.15, hold=0.16, close=0.14, opening=0.26), "ey": [(0.9, -0.3), (1.8, -0.2)]}),
    "surprise": (1.3, {"hy": [(0.09, 10), (0.3, 6), (0.55, 7.5), (0.9, 5)], "by": [(0.09, 5), (0.3, 1.5), (0.55, 2.5), (0.9, 1)], "lean": [(0.1, 2), (0.6, 1)], "br": [(0.09, 0.5), (0.9, 0.3)], "eo": blink(0.5) + blink(0.75)}),
    "neutral": (1.5, {"br": [(0.35, 0.3), (1.1, 0.0)], "by": [(0.35, 1), (1.1, -0.6)], "hy": [(0.4, 1.5), (0.85, -2.5), (1.2, 0)], "eo": blink(0.8)}),
}
# Head gestures for scripts.
GESTURES = {
    "Nod": [(1.3, {"hy": [(0.15, 3), (0.38, -11), (0.62, 1), (0.85, -8), (1.08, 0.5)], "by": [(0.4, -2), (0.63, 0), (0.87, -1.4), (1.08, 0)]})],
    "Shake": [(1.6, {"hx": [(0.2, -12), (0.5, 12), (0.8, -10), (1.1, 8), (1.35, -2)], "hz": [(0.2, 1.5), (0.5, -1.5), (0.8, 1.2), (1.1, -1)], "bz": [(0.25, -0.8), (0.55, 0.8), (0.85, -0.6)]})],
    "HeadTilt": [(2.0, {"hz": [(0.45, 11), (1.4, 10)], "hx": [(0.45, 4), (1.4, 3)], "bz": [(0.5, 1.5), (1.4, 1.2)], "eo": blink(0.9)})],
}
# Touch reactions: a startle with the shape switches, then the motion hands back to the touch's face.
TOUCHES = {
    "Pat": [
        (2.3, {"hy": [(0.18, -7), (0.42, -4.5), (0.66, -8), (0.9, -5), (1.14, -8), (1.5, -5)], "hz": [(0.3, 4), (1.5, 5)], "by": [(0.18, -1.8), (0.42, -1), (0.66, -2), (0.9, -1), (1.14, -2), (1.5, -1)],
               "br": [(0.5, 0.3), (1.6, 0.05)], "bz": [(0.4, 1), (1.5, 1.2)], **happy_eyes(0.12, 1.65)}),
        (2.4, {"hy": [(0.2, -6), (0.5, -3.5), (0.8, -7), (1.1, -4), (1.6, -3)], "hz": [(0.35, -6), (0.95, -7), (1.7, -4)], "hx": [(0.4, -4), (1.6, -3)], "by": [(0.2, -1.5), (0.5, -0.8), (0.8, -1.8), (1.1, -0.8)],
               "lean": [(0.5, -2), (1.6, -1.5)], "br": [(0.5, 0.35), (1.7, 0.05)], **happy_eyes(0.14, 1.75)}),
    ],
    "Boop": [
        (2.2, {"hy": [(0.08, 9), (0.3, 5), (0.7, -2), (1.5, -3)], "hx": [(0.7, 8), (1.5, 9)], "hz": [(0.08, -2), (0.7, -5), (1.5, -5)], "by": [(0.08, 3.5), (0.3, 1), (0.7, -1), (1.5, -1)],
               "wide": switch(0.0, 0.42), "shout": switch(0.0, 0.4), "eo": blink(0.16, hold=0.03, close=0.06, opening=0.08) + blink(0.36, hold=0.1, close=0.06, opening=0.1) + [(0.75, 0.62), (1.55, 0.62)],
               "ex": [(0.7, 0.5), (1.5, 0.5)], "br": [(0.08, 0.5), (0.7, 0.4), (1.5, 0.1)], "bz": [(0.7, -1.2), (1.5, -1)]}),
        (2.3, {"hy": [(0.08, 9), (0.3, 5), *pulses(0.55, 4, 0.3, 3.5, base=2)], "hz": [(0.08, 2), (0.6, 6), (1.2, 3), (1.8, 5)], "by": [(0.08, 3.5), (0.3, 1), *pulses(0.55, 4, 0.3, 2.2, base=0.5)],
               "wide": switch(0.0, 0.56), "shout": switch(0.0, 0.4), "grin": switch(0.52, 1.75), "br": [(0.08, 0.5), (0.5, 0.2), *pulses(0.55, 4, 0.3, 0.35)],
               "eo": blink(0.16, hold=0.03, close=0.06, opening=0.08) + [(0.47, 1.0), (0.56, 0.0), (1.8, 0.0), (1.96, 1.0)], "smile": [(0.56, 0.0), (0.62, 1.0), (1.72, 1.0), (1.8, 0.0)]}),
    ],
    "Poke": [
        (2.1, {"hx": [(0.08, 9), (0.3, -3), (0.55, 3), (1.4, 4)], "hz": [(0.08, -9), (0.3, 3), (0.55, -3), (1.4, -4)], "hy": [(0.1, -2), (0.6, 2), (1.4, 2)], "bz": [(0.1, -2), (0.35, 0.8), (0.6, -0.5)], "bx": [(0.1, 1.5), (0.4, -0.5)],
               "eoL": [(0.0, 1.0), (0.06, 0.0), (0.4, 0.0), (0.55, 1.0)], "eoR": [(0.0, 1.0), (0.06, 0.45), (0.4, 0.45), (0.55, 1.0)], "shout": switch(0.0, 0.3),
               "ex": [(0.6, -0.4), (1.4, -0.4)], "by": [(0.08, -1.5), (0.6, 1.5), (0.85, 0.3), (1.1, 1.5), (1.4, 0.5)], "br": [(0.6, 0.5), (1.4, 0.45)]}),
    ],
    "Tap": [
        (2.3, {"by": [(0.08, 5.5), (0.28, -1), (0.45, 1), (0.9, -2.5), (1.7, -2)], "hy": [(0.08, 9), (0.35, 4), (0.9, -5), (1.7, -5)], "hx": [(0.9, 6), (1.7, 6)], "hz": [(0.9, -3), (1.25, 2), (1.6, -2)],
               "lean": [(0.1, 2), (0.9, 1)], "bz": [(0.9, -1.5), (1.25, 1.2), (1.6, -1)], "wide": switch(0.0, 0.56), "shout": switch(0.0, 0.5), "br": [(0.08, 0.5), (0.9, 0.35), (1.7, 0.1)],
               "eo": blink(0.5, hold=0.1, close=0.06, opening=0.1) + blink(0.82, hold=0.03, close=0.06, opening=0.1), "ex": [(0.9, 0.3), (1.2, -0.3), (1.6, 0.3)]}),
    ],
}
# The idle: a slow sway loop. The player's own breathing adds 0..0.5 on ParamBreath every 3.2345 s; the
# idle adds a slower swell at half that rate, so breaths alternate shallow and deep, and the body rises with it.
BREATH_PERIOD = 3.2345
IDLE_LENGTH = 4 * BREATH_PERIOD


def idle(variant: int, parameters: set[str] | None = None) -> dict:
    n = 26
    times = [IDLE_LENGTH * i / n for i in range(n + 1)]
    w = 2 * math.pi / IDLE_LENGTH
    s, ph = (-1, 1.3) if variant else (1, 0.0)
    curves = {
        "ParamBreath": lambda t: 0.225 * (1 - math.cos(2 * w * t)),
        "ParamBodyAngleY": lambda t: 0.9 * (1 - math.cos(2 * w * t)) - 0.9 + 0.35 * math.sin(w * t + ph),
        "ParamAngleY": lambda t: 0.7 * (1 - math.cos(2 * w * t - 0.5)) - 0.7 + 0.8 * math.sin(w * t + 0.9 + ph),
        "ParamAngleX": lambda t: s * (2.6 * math.sin(w * t + ph) + 0.9 * math.sin(3 * w * t + 0.7)),
        "ParamAngleZ": lambda t: s * (1.7 * math.sin(w * t + 1.1 + ph) + 0.6 * math.sin(2 * w * t + 2.0)),
        "ParamBodyAngleZ": lambda t: s * 1.1 * math.sin(w * t + 0.5 + ph),
        "ParamBodyAngleX": lambda t: s * 0.6 * math.sin(w * t + 2.2 + ph),
    }
    spec = {pid: [(t, fn(t)) for t in times] for pid, fn in curves.items()}
    if not variant:
        spec["eo"] = [(0.0, 1.0), *blink(2.1), *blink(6.3), *blink(6.62), *blink(10.4), (IDLE_LENGTH, 1.0)]
        spec["ex"] = [(0.0, 0.0), (3.9, 0.0), (4.02, 0.38), (5.5, 0.38), (5.64, 0.0), (IDLE_LENGTH, 0.0)]
        spec["ey"] = [(0.0, 0.0), (3.9, 0.0), (4.02, -0.12), (5.5, -0.12), (5.64, 0.0), (IDLE_LENGTH, 0.0)]
    else:
        spec["eo"] = [(0.0, 1.0), *blink(1.6), *blink(4.9), *blink(8.6, hold=0.07), *blink(11.5), (IDLE_LENGTH, 1.0)]
        spec["ex"] = [(0.0, 0.0), (7.0, 0.0), (7.12, -0.42), (8.5, -0.42), (8.85, 0.0), (IDLE_LENGTH, 0.0)]
        spec["ey"] = [(0.0, 0.0), (7.0, 0.0), (7.12, 0.25), (8.5, 0.25), (8.85, 0.0), (IDLE_LENGTH, 0.0)]
    return build_motion(round(IDLE_LENGTH, 4), spec, loop=True, fade_in=0.8, fade_out=0.4, smooth=set(curves), parameters=parameters)


# Writing it -------------------------------------------------------------------------------------------
def motion_value(group: str, count: int) -> str:
    return f"{group}_id=random" if count > 1 else f"{group}_id=0"


def sillytavern_settings(motions: dict, parameters: set[str] | None = None, hit_areas=None) -> dict:
    """The Live2D extension's settings: every emotion mapped, each hit area to its touch reaction."""
    def has(pid):
        return parameters is None or pid in parameters

    cursor = {key: (value if has(value) else "none") for key, value in presets()["cursor_parameters"].items()}
    areas = HIT_AREAS if hit_areas is None else {name: HIT_AREAS.get(name, "Tap") for name in hit_areas}
    return {
        "scale": 1.0, "x": 0.0, "y": 0.0, "eye": 45,
        "cursor_param": cursor,
        "param_mouth_open_y_id": "ParamMouthOpenY" if has("ParamMouthOpenY") else "none",
        "mouth_open_speed": 1.0, "mouth_time_per_character": 30,
        "animation_starter": {"expression": "neutral", "motion": "none", "delay": 0},
        "animation_default": {"expression": "neutral", "motion": "none"},
        "animation_click": {"expression": "none", "motion": "none", "message": ""},
        "hit_areas": {area: {"expression": touch, "motion": motion_value(touch, len(motions.get(touch, []))) if touch in motions else "none", "message": ""} for area, touch in areas.items()},
        "classify_mapping": {e: {"expression": e, "motion": motion_value(e, len(motions[e])) if e in motions else "none"} for e in EMOTIONS},
    }


def write_runtime(folder, parameters: set[str] | None = None, hit_areas=None, settings: bool = True) -> dict:
    """
    Write the fixed-pose runtime into folder: expressions/, motions/ and (settings) the SillyTavern
    settings. parameters limits every file to the ids the model has. Returns {"Expressions": [...],
    "Motions": {group: [...]}} for a model file's FileReferences.
    """
    folder = pathlib.Path(folder)
    (folder / EXPRESSIONS_DIR).mkdir(parents=True, exist_ok=True)
    (folder / MOTIONS_DIR).mkdir(parents=True, exist_ok=True)

    def dump(data, relative):
        (folder / relative).write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")

    expressions = []
    for emotion in EMOTIONS:
        relative = f"{EXPRESSIONS_DIR}/{emotion}.exp3.json"
        dump(build_expression(EXPRESSIONS[emotion], parameters=parameters), relative)
        expressions.append({"Name": emotion, "File": relative})
    for name, values in TOUCH_EXPRESSIONS.items():
        relative = f"{EXPRESSIONS_DIR}/{name}.exp3.json"
        dump(build_expression(values, FREE, parameters), relative)
        expressions.append({"Name": name, "File": relative})
    motions: dict[str, list] = {IDLE_GROUP: []}
    for variant in (0, 1):
        relative = f"{MOTIONS_DIR}/idle_{variant}.motion3.json"
        dump(idle(variant, parameters), relative)
        motions[IDLE_GROUP].append({"File": relative, "FadeInTime": 0.8, "FadeOutTime": 0.4})

    def add(group, items, stem):
        motions[group] = []
        for index, (duration, spec) in enumerate(items):
            relative = f"{MOTIONS_DIR}/{stem}{'_' + str(index) if len(items) > 1 else ''}.motion3.json"
            dump(build_motion(duration, spec, parameters=parameters), relative)
            motions[group].append({"File": relative, "FadeInTime": 0.2, "FadeOutTime": FADE_OUT})

    for emotion in EMOTIONS:
        add(emotion, [REACTIONS[emotion]], f"react_{emotion}")
    for group, items in TOUCHES.items():
        add(group, items, f"touch_{group.lower()}")
    for group, items in GESTURES.items():
        add(group, items, f"gesture_{group.lower()}")
    if settings:
        dump(sillytavern_settings(motions, parameters, hit_areas), SETTINGS_FILE)
    return {"Expressions": expressions, "Motions": motions}


def legacy_expressions() -> list[dict]:
    """Old expression names pointing at the new files, for characters set up with them."""
    return [{"Name": name, "File": f"{EXPRESSIONS_DIR}/{emotion}.exp3.json"} for name, emotion in LEGACY.items()]
