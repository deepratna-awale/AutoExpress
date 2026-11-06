"""The humanoid IK (resources/humanoid_ik.js), run under Node."""
import json
import pathlib
import shutil
import subprocess

import pytest

IK = pathlib.Path(__file__).resolve().parents[1] / "autoexpress_core" / "resources" / "humanoid_ik.js"
T_POSE = {"nose": [996, 246], "neck": [1023, 423], "r_sho": [866, 416], "r_elb": [631, 460], "r_wri": [382, 460],
          "l_sho": [1181, 431], "l_elb": [1423, 467], "l_wri": [1673, 463], "r_hip": [910, 984], "r_knee": [884, 1429],
          "r_ank": [848, 1852], "l_hip": [1127, 988], "l_knee": [1145, 1429], "l_ank": [1185, 1852]}

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")


def run(script: str):
    code = f"const IK = require({json.dumps(str(IK))}); const sk = IK.skeletonFromJoints({json.dumps(T_POSE)});\n{script}"
    return json.loads(subprocess.run(["node", "-e", code], check=True, capture_output=True, text=True).stdout)


def test_skeleton_has_every_humanoid_joint_down_to_the_fingers():
    names = run("console.log(JSON.stringify(sk.joints.map(j => j.name)))")
    for side in "LR":
        for joint in ("clavicle", "upperArm", "forearm", "hand", "thumbCmc", "thumbTip", "indexMcp", "indexPip", "indexDip", "pinkyTip", "thigh", "shin", "foot", "toe"):
            assert joint + side in names
    assert {"pelvis", "spine", "chest", "neck", "head"} <= set(names)


def test_arm_reaches_a_goal_and_the_elbow_bends_toward_its_pole():
    r = run("""const r = sk.solve({handR: {x: 850, y: 850, pole: {x: 600, y: 650}}});
console.log(JSON.stringify({hand: r.handR.pos, elbow: r.forearmR.pos}))""")
    assert abs(r["hand"][0] - 850) < 1 and abs(r["hand"][1] - 850) < 1
    assert r["elbow"][0] < 866  # out to the character's right (picture left), toward the pole


def test_a_goal_out_of_reach_straightens_the_arm_without_breaking_it():
    r = run("""const r = sk.solve({handR: {x: -3000, y: 460}, reach: false});
const d = (a, b) => Math.hypot(a[0]-b[0], a[1]-b[1], a[2]-b[2]);
console.log(JSON.stringify({upper: d(r.upperArmR.pos, r.forearmR.pos), lower: d(r.forearmR.pos, r.handR.pos)}))""")
    assert abs(r["upper"] - 239) < 2 and abs(r["lower"] - 249.5) < 2


def test_a_hand_crossing_the_body_comes_out_in_front_of_it():
    r = run("console.log(JSON.stringify(sk.solve({handR: {x: 1020, y: 700}}).handR))")
    assert r["depth"] > 20 and abs(r["pos"][0] - 1020) < 1


def test_elbow_hinge_never_bends_backwards_or_past_its_limit():
    r = run("""const out = [];
for (const [x, y] of [[700, 300], [866, 500], [1000, 420], [500, 800]]) {
  const r = sk.solve({handR: {x, y}}); const u = IK.util;
  const a = [0,1,2].map(i => r.forearmR.pos[i] - r.upperArmR.pos[i]), b = [0,1,2].map(i => r.handR.pos[i] - r.forearmR.pos[i]);
  out.push(u.angle(a, b) * 180 / Math.PI);
}
console.log(JSON.stringify(out))""")
    assert all(0 <= bend <= 151 for bend in r)


def test_hand_poses_curl_the_fingers_and_report_a_view():
    r = run("""const open = sk.solve({handR: {x: 600, y: 200, grip: 'open'}});
const fist = sk.solve({handR: {x: 600, y: 200, grip: 'fist'}});
const d = (a, b) => Math.hypot(a[0]-b[0], a[1]-b[1], a[2]-b[2]);
console.log(JSON.stringify({open: d(open.indexTipR.pos, open.handR.pos), fist: d(fist.indexTipR.pos, fist.handR.pos), view: fist.handR.view, poses: Object.keys(IK.HAND_POSES)}))""")
    assert r["fist"] < r["open"] * 0.8
    assert 0 <= r["view"]["index"] < 24 and r["view"]["yaw"] % 45 == 0
    assert {"open", "relaxed", "fist", "point", "peace", "thumbsUp", "ok"} <= set(r["poses"])


def test_look_at_shares_the_turn_between_neck_head_and_eyes():
    r = run("console.log(JSON.stringify(sk.solve({look: {x: 2500, y: 300, z: 600}}).head))")
    assert r["lookX"] > 20 and r["eyes"] >= 0


def test_parameters_from_a_mapping():
    r = run("""const rep = sk.solve({handR: {x: 400, y: 900}});
console.log(JSON.stringify(IK.toParameters(rep, {ParamArmRA: {joint: 'upperArmR', field: 'turn', min: -90, max: 150}, ParamHandView: {joint: 'handR', field: 'view.index'}})))""")
    assert -90 <= r["ParamArmRA"] < -10 and isinstance(r["ParamHandView"], int)
