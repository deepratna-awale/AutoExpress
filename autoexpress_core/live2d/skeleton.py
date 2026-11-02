"""
A full-body skeleton for puppets: bones from the hips up the spine to the head and down each arm
and leg, so the character can be posed like a 3D model instead of staying in the drawing's pose.

The joints come from a pose detector (DWPose / OpenPose body keypoints, see from_keypoints) or,
for a character drawn in the neutral A-pose the kit asks for, from anime proportions measured off
the face (from_proportions). bones() turns joints into the puppet's Rig.Skeleton: each bone turns
about its head joint by its own parameter (ParamBone<Name>, degrees, clockwise on screen) within
the joint's limits, and its children follow. The player binds every vertex of the body, clothes
and arms to its nearest bones, so they bend together.

L and R are the character's own left and right (L is on the right of the picture), like Live2D's
parameters and OpenPose's keypoints.
"""

import math

# OpenPose body keypoints (18), by index.
OPENPOSE = {
    "nose": 0, "neck": 1,
    "shoulder_R": 2, "elbow_R": 3, "wrist_R": 4,
    "shoulder_L": 5, "elbow_L": 6, "wrist_L": 7,
    "hip_R": 8, "knee_R": 9, "ankle_R": 10,
    "hip_L": 11, "knee_L": 12, "ankle_L": 13,
}

# name, parent, from joint, to joint, group, limits (degrees, clockwise on screen), thickness as a
# share of the face width. The limits keep to small, natural motion (a sway, a lean, an arm lifted a
# little): a single drawing has nothing drawn behind its arms, so bigger poses tear the clothes. Raising the left arm sideways turns it anticlockwise (towards the right
# of the picture), so its outward limit is the negative one; the right side is the mirror image.
BONES = (
    ("Hips", None, "pelvis", "spine", "torso", (-8, 8), None),
    ("Spine", "Hips", "spine", "chest", "torso", (-10, 10), None),
    ("Chest", "Spine", "chest", "neck", "torso", (-8, 8), None),
    ("Neck", "Chest", "neck", "chin", "torso", (-15, 15), 0.28),
    ("Head", "Neck", "chin", "crown", "head", (-20, 20), 0.6),
    ("UpperArmL", "Chest", "shoulder_L", "elbow_L", "arm_L", (-35, 12), 0.24),
    ("ForearmL", "UpperArmL", "elbow_L", "wrist_L", "arm_L", (-15, 40), 0.2),
    ("HandL", "ForearmL", "wrist_L", "hand_L", "arm_L", (-20, 20), 0.22),
    ("UpperArmR", "Chest", "shoulder_R", "elbow_R", "arm_R", (-12, 35), 0.24),
    ("ForearmR", "UpperArmR", "elbow_R", "wrist_R", "arm_R", (-40, 15), 0.2),
    ("HandR", "ForearmR", "wrist_R", "hand_R", "arm_R", (-20, 20), 0.22),
    ("ThighL", "Hips", "hip_L", "knee_L", "leg_L", (-8, 5), 0.36),
    ("ShinL", "ThighL", "knee_L", "ankle_L", "leg_L", (-8, 8), 0.26),
    ("FootL", "ShinL", "ankle_L", "foot_L", "leg_L", (-10, 10), 0.24),
    ("ThighR", "Hips", "hip_R", "knee_R", "leg_R", (-5, 8), 0.36),
    ("ShinR", "ThighR", "knee_R", "ankle_R", "leg_R", (-8, 8), 0.26),
    ("FootR", "ShinR", "ankle_R", "foot_R", "leg_R", (-10, 10), 0.24),
)

def _mid(a, b, t=0.5):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _extend(a, b, share):
    """The point past b along a -> b, share of its length further on."""
    return (b[0] + (b[0] - a[0]) * share, b[1] + (b[1] - a[1]) * share)


def complete(joints: dict, face) -> dict:
    """
    The joints the bones need, derived from the detected ones: pelvis (between the hips), spine and
    chest (up the torso), chin and crown (from the face box), hands and feet (past the wrists and
    ankles). Joints that can't be had are left out.
    """
    j = dict(joints)
    left, top, right, bottom = face
    face_h = bottom - top
    j.setdefault("chin", ((left + right) / 2, bottom))
    j.setdefault("crown", ((left + right) / 2, top - face_h * 0.15))
    if "neck" not in j and "shoulder_L" in j and "shoulder_R" in j:
        j["neck"] = _mid(j["shoulder_L"], j["shoulder_R"])
    if "pelvis" not in j and "hip_L" in j and "hip_R" in j:
        j["pelvis"] = _mid(j["hip_L"], j["hip_R"])
    if "pelvis" in j and "neck" in j:
        j.setdefault("spine", _mid(j["pelvis"], j["neck"], 0.4))
        j.setdefault("chest", _mid(j["pelvis"], j["neck"], 0.75))
    for side in ("L", "R"):
        if f"elbow_{side}" in j and f"wrist_{side}" in j:
            j.setdefault(f"hand_{side}", _extend(j[f"elbow_{side}"], j[f"wrist_{side}"], 0.4))
        if f"ankle_{side}" in j:
            j.setdefault(f"foot_{side}", (j[f"ankle_{side}"][0], j[f"ankle_{side}"][1] + face_h * 0.35))
    return j


def from_keypoints(people: list, face, size) -> dict | None:
    """
    Joints (canvas pixels) from a pose detector's OpenPose JSON (the "people" list: pose_keypoints_2d
    as x, y, confidence triples, in pixels or normalised to 0-1), for the person whose head is
    nearest the face box. None when nobody was found.
    """
    width, height = size
    cx, cy = (face[0] + face[2]) / 2, (face[1] + face[3]) / 2
    best, best_d = None, math.inf
    for person in people or []:
        flat = person.get("pose_keypoints_2d") or []
        points = [flat[i:i + 3] for i in range(0, len(flat) - 2, 3)]
        if len(points) < 14:
            continue
        normalised = all(0 <= p[0] <= 1.01 and 0 <= p[1] <= 1.01 for p in points if p[2] > 0)
        scale = (width, height) if normalised else (1, 1)
        found = {name: (points[i][0] * scale[0], points[i][1] * scale[1]) for name, i in OPENPOSE.items() if points[i][2] > 0.3}
        anchor = found.get("nose") or found.get("neck")
        if not anchor:
            continue
        d = math.hypot(anchor[0] - cx, anchor[1] - cy)
        if d < best_d:
            best, best_d = found, d
    if not best:
        return None
    best.pop("nose", None)
    return best


def from_proportions(face, body_box) -> dict:
    """
    Joints for a character standing in the neutral A-pose (arms straight down, a little away from
    the body; legs straight, a little apart), from anime proportions measured off the face, cut off
    where the body ends (a bust-up picture has no legs).
    """
    left, top, right, bottom = face
    face_w, face_h = right - left, bottom - top
    cx = (left + right) / 2
    chin = bottom
    j = {"neck": (cx, chin + face_h * 0.3)}
    shoulder_y = chin + face_h * 0.45
    tilt = math.radians(18)  # how far the arms hang away from the body
    upper, fore = face_h * 1.3, face_h * 1.15
    for side, sign in (("L", 1), ("R", -1)):
        shoulder = (cx + sign * face_w * 0.95, shoulder_y)
        elbow = (shoulder[0] + sign * math.sin(tilt) * upper, shoulder[1] + math.cos(tilt) * upper)
        wrist = (elbow[0] + sign * math.sin(tilt) * fore, elbow[1] + math.cos(tilt) * fore)
        j.update({f"shoulder_{side}": shoulder, f"elbow_{side}": elbow, f"wrist_{side}": wrist})
        hip = (cx + sign * face_w * 0.5, chin + face_h * 2.75)
        knee = (cx + sign * face_w * 0.55, chin + face_h * 4.75)
        ankle = (cx + sign * face_w * 0.6, chin + face_h * 6.7)
        j.update({f"hip_{side}": hip, f"knee_{side}": knee, f"ankle_{side}": ankle})
    end = body_box[3] if body_box else math.inf
    for name in [n for n in j if n.split("_")[0] in ("knee", "ankle", "elbow", "wrist")]:
        if j[name][1] > end + face_h * 0.1:
            del j[name]
    # The hips stay, at the bottom of a bust-up picture, so the torso can still lean.
    for side in ("L", "R"):
        x, y = j[f"hip_{side}"]
        j[f"hip_{side}"] = (x, min(y, max(j["neck"][1] + face_h * 0.6, end)))
    return j


def _rows(mask):
    """{y: (centre x, half width)} of each row of a mask (a 2D numpy bool array) that has any of it."""
    import numpy as np

    found = {}
    ys = np.nonzero(mask.any(axis=1))[0]
    for y in ys:
        xs = np.nonzero(mask[y])[0]
        found[int(y)] = (float(xs.mean()), (float(xs.max()) - float(xs.min()) + 1) / 2)
    return found


def _at(rows: dict, y: float, span: int = 6):
    """The centre and half width around row y (averaged over a few rows), or None."""
    near = []
    while not near and span <= 48:
        near = [rows[r] for r in range(int(y) - span, int(y) + span + 1) if r in rows]
        span *= 2
    if not near:
        return None
    return sum(c for c, _ in near) / len(near), sum(w for _, w in near) / len(near)


def _outer_run(row, sign):
    """The outermost run of a mask row (numpy bool) on one side: (start, end) x, or None."""
    import numpy as np

    xs = np.nonzero(row)[0]
    if not len(xs):
        return None
    if sign < 0:
        xs = xs[::-1]
    end = xs[-1]
    start = end
    for x in xs[::-1][1:]:
        if abs(int(x) - int(start)) > 2:
            break
        start = x
    return (min(start, end), max(start, end))


def fit_to_layers(joints: dict, face, arms: dict | None = None, silhouette=None) -> tuple[dict, dict]:
    """
    Joints and bone thicknesses fitted to the drawing: anime proportions only guess where the arms
    hang and how far apart the legs stand, so each arm's joints are moved onto its own layer (arms
    maps "L"/"R" to its alpha, mode L, canvas size: the split paints the whole arm, under the sleeves
    too) and the knees and ankles onto the legs of silhouette (the whole body's alpha). Returns
    (joints, radii) for bones().
    """
    import numpy as np

    j = dict(joints)
    radii: dict = {}
    face_h = face[3] - face[1]
    cx = (face[0] + face[2]) / 2
    face_w = face[2] - face[0]
    whole = np.asarray(silhouette) > 128 if silhouette is not None else None
    for side, image in (arms or {}).items():
        sign = 1 if side == "L" else -1
        # The split paints the hands reliably (the rest of an arm under a sleeve comes out in bits):
        # the hand is the arm layer's lowest solid blob.
        from PIL import ImageFilter

        solid = np.asarray(image.point(lambda v: 255 if v > 128 else 0).filter(ImageFilter.MinFilter(5)).filter(ImageFilter.MaxFilter(5))) > 0
        rows = _rows(solid)
        if not rows or f"shoulder_{side}" not in j:
            continue
        bottom = max(rows)
        hand_rows = {y: v for y, v in rows.items() if y >= bottom - face_h * 0.75}
        top = min(hand_rows)
        if bottom - top < face_h * 0.2:
            continue
        wrist = (_at(hand_rows, top + (bottom - top) * 0.12)[0], top + (bottom - top) * 0.12)
        tip = (_at(hand_rows, bottom - 3)[0], bottom - (bottom - top) * 0.1)
        shoulder_y = j[f"shoulder_{side}"][1]
        shoulder_x = j[f"shoulder_{side}"][0]
        upper_r = face_w * 0.3
        if whole is not None:
            # The outer edge of the sleeve at the shoulder, and its width halfway down the arm.
            line = np.nonzero(whole[int(shoulder_y)])[0]
            if len(line):
                edge = float(line.max() if sign > 0 else line.min())
                mid_y = int((shoulder_y + wrist[1]) / 2)
                run = _outer_run(whole[mid_y], sign)
                if run and run[1] - run[0] < face_w * 0.6:
                    upper_r = (run[1] - run[0]) / 2 * 1.1
                shoulder_x = edge - sign * upper_r
        shoulder = (shoulder_x, shoulder_y)
        j[f"shoulder_{side}"] = shoulder
        j[f"elbow_{side}"] = _mid(shoulder, wrist, 0.52)
        j[f"wrist_{side}"] = wrist
        j[f"hand_{side}"] = tip
        hand_r = (max(v[1] for v in hand_rows.values())) * 1.15
        radii[f"UpperArm{side}"] = round(upper_r * 1.1, 1)
        radii[f"Forearm{side}"] = round(max(upper_r * 0.95, hand_r * 0.9), 1)
        radii[f"Hand{side}"] = round(hand_r, 1)
    if silhouette is not None and "hip_L" in j and "hip_R" in j:
        whole = np.asarray(silhouette) > 128
        hip_y = (j["hip_L"][1] + j["hip_R"][1]) / 2
        for side, sign in (("L", 1), ("R", -1)):
            half = whole.copy()
            if sign > 0:
                half[:, : int(cx)] = False
            else:
                half[:, int(cx) + 1:] = False
            # Arms hanging beside the legs would pull the legs' centre out: only rows below the hands.
            hands = [j[f"hand_{s}"][1] for s in ("L", "R") if f"hand_{s}" in j]
            rows = _rows(half)
            start = max([hip_y] + hands)
            legs = {y: v for y, v in rows.items() if y > start}
            if len(legs) < face_h:
                continue
            ankle_y = max(legs) - face_h * 0.55
            knee_y = (hip_y + ankle_y) / 2
            ankle, knee = _at(legs, ankle_y), _at(legs, max(knee_y, start + 6))
            if ankle is None or knee is None:
                continue
            j[f"ankle_{side}"] = (ankle[0], ankle_y)
            j[f"knee_{side}"] = (knee[0], knee_y)
            j[f"hip_{side}"] = (j[f"hip_{side}"][0] * 0.5 + knee[0] * 0.5, j[f"hip_{side}"][1])
            radii[f"Shin{side}"] = round(max(face_h * 0.12, knee[1] * 1.2), 1)
    return j, radii


def bones(joints: dict, face, radii: dict | None = None) -> dict | None:
    """
    Rig.Skeleton for the puppet: {"Bones": [...], parents first}, each {"Name", "Parent", "Head",
    "Tail", "Radius", "Group", "Param", "Min", "Max"}. The torso's thickness is half the shoulders'
    (or hips') width; a limb's is a share of the face width. Bones whose joints are missing are
    left out, with everything hanging from them. radii ({bone name: pixels}) overrides a bone's
    thickness, measured off the drawing by fit_to_layers. None without a torso.
    """
    j = complete(joints, face)
    face_w = face[2] - face[0]
    shoulders = abs(j["shoulder_L"][0] - j["shoulder_R"][0]) if "shoulder_L" in j and "shoulder_R" in j else face_w * 1.9
    hips = abs(j["hip_L"][0] - j["hip_R"][0]) if "hip_L" in j and "hip_R" in j else shoulders * 0.6
    result = []
    names = set()
    for name, parent, a, b, group, (low, high), thick in BONES:
        if a not in j or b not in j or (parent and parent not in names):
            continue
        if radii and name in radii:
            radius = radii[name]
        elif name == "Hips":
            radius = hips * 0.75
        elif name in ("Spine", "Chest"):
            radius = shoulders * (0.4 if name == "Chest" else 0.42)
        else:
            radius = face_w * thick
        result.append(
            {
                "Name": name,
                "Parent": parent,
                "Head": [round(j[a][0], 1), round(j[a][1], 1)],
                "Tail": [round(j[b][0], 1), round(j[b][1], 1)],
                "Radius": round(radius, 1),
                "Group": group,
                "Param": f"ParamBone{name}",
                "Min": low,
                "Max": high,
            }
        )
        names.add(name)
    if "Hips" not in names or "Chest" not in names:
        return None
    return {"Bones": result}


def parameters(skeleton: dict | None) -> list[tuple[str, float, float, float]]:
    """The puppet parameters for a skeleton's bones: (id, min, max, default)."""
    return [(b["Param"], b["Min"], b["Max"], 0) for b in (skeleton or {}).get("Bones", [])]


def _segment_distance(x, y, a, b) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    t = 0.0 if length <= 1e-9 else min(1.0, max(0.0, ((x - a[0]) * dx + (y - a[1]) * dy) / length))
    return math.hypot(x - (a[0] + dx * t), y - (a[1] + dy * t))


def limb_of(x: float, y: float, bones_list: list) -> str:
    """
    Which limb group a canvas point is drawn with ("arm_L", "leg_R" ...), or "torso": a limb's only
    well inside it (within 90% of its thickness, and clearly nearer it than any other bone), so
    what lies under the clothes near the body never comes over them. The player binds vertices
    with the same scores.
    """
    best, best_score, second_score = None, 0.0, 0.0
    for bone in bones_list:
        if bone["Name"] == "Head":
            continue
        d = _segment_distance(x, y, bone["Head"], bone["Tail"])
        q = d / max(1.0, bone["Radius"])
        score = math.exp(-3 * q * q)
        if score > best_score:
            best, best_score, second_score = (bone, d), score, best_score
        elif score > second_score:
            second_score = score
    if best is None:
        return "torso"
    bone, d = best
    group = bone.get("Group") or "torso"
    if group.startswith("arm"):
        # A sleeve is often wider than the arm's measured thickness: the arm takes everything that's
        # relatively nearer to it than to the body.
        return group if d < bone["Radius"] * 1.8 else "torso"
    share = best_score / (best_score + second_score) if best_score + second_score > 0 else 1.0
    return group if group != "torso" and d < bone["Radius"] * 0.9 and share > 0.85 else "torso"


def limb_masks(skeleton_doc: dict, size, step: int = 8, arms: dict | None = None) -> dict:
    """
    {group: mask} (mode L, canvas size) of where each limb is drawn, from limb_of on a grid every
    step pixels, smoothed. Groups with no area are left out; "torso" is everything else. arms
    ({"L"/"R": alpha}) adds each arm's own layer to its mask, so the whole arm comes off the body.
    """
    from PIL import Image

    bones_list = skeleton_doc.get("Bones", [])
    width, height = size
    cols, rows = max(1, width // step + 1), max(1, height // step + 1)
    by_name = {b["Name"]: b for b in bones_list}
    crotch = mid = None
    if "Hips" in by_name and "ThighL" in by_name and "ThighR" in by_name:
        # Standing, the legs part below the crotch: everything there is the leg on its side of the
        # middle (unless it's a hand hanging beside it), and nothing above it is a leg.
        hip_y = (by_name["ThighL"]["Head"][1] + by_name["ThighR"]["Head"][1]) / 2
        knee_y = (by_name["ThighL"]["Tail"][1] + by_name["ThighR"]["Tail"][1]) / 2
        crotch = hip_y + (knee_y - hip_y) * 0.3
        mid = by_name["Hips"]["Head"][0]

    def label(x, y):
        found = limb_of(x, y, bones_list)
        if crotch is None or found.startswith("arm"):
            return found
        if y < crotch:
            return "torso" if found.startswith("leg") else found
        # Below it, the leg whose bones are nearer: where the legs touch, the line between them
        # isn't the body's middle.
        near = {side: min(_segment_distance(x, y, by_name[n]["Head"], by_name[n]["Tail"]) for n in (f"Thigh{side}", f"Shin{side}", f"Foot{side}") if n in by_name) for side in "LR"}
        if near["L"] != near["R"]:
            return "leg_L" if near["L"] < near["R"] else "leg_R"
        return "leg_L" if x >= mid else "leg_R"

    labels = [label(c * step, r * step) for r in range(rows) for c in range(cols)]
    masks = {}
    for group in sorted(set(labels) - {"torso"}):
        small = Image.new("L", (cols, rows))
        small.putdata([255 if label == group else 0 for label in labels])
        from PIL import ImageFilter

        mask = small.resize((cols * step, rows * step), Image.Resampling.BILINEAR).crop((0, 0, width, height))
        # Smooth the grid's steps out of the cut.
        mask = mask.filter(ImageFilter.GaussianBlur(step * 0.75))
        masks[group] = mask.point(lambda v: 255 if v >= 128 else 0)
    from PIL import ImageChops

    for side, alpha in (arms or {}).items():
        own = alpha.point(lambda v: 255 if v > 128 else 0)
        masks[f"arm_{side}"] = ImageChops.lighter(masks[f"arm_{side}"], own) if f"arm_{side}" in masks else own
    return masks
