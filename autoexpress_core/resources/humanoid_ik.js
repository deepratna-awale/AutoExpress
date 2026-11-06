/*
 * Humanoid IK for 2D puppets (Live2D models and AutoExpress puppets).
 *
 * The skeleton lives in the picture's space: x right, y down, z toward the viewer, in canvas pixels. Every joint has
 * a rest position (the drawn pose), a parent and a constraint; the solver works in 3D and reports, per joint, its
 * world position, its turn in the picture's plane (what a 2D rotation deformer can show) and its depth (what decides
 * whether a hand is drawn in front of the body). Hands also report which way the palm faces, so a player can pick
 * the matching drawn hand view.
 *
 * Solvers:
 *  - limbs (arm, leg): analytic two-bone IK in 3D, the elbow or knee bending toward a pole point;
 *  - chains (spine, fingers): FABRIK, each joint projected back into its constraint after every pass;
 *  - look-at: head and eyes share the turn, each within its own limits;
 *  - body: a hand never ends inside the torso or head (capsules); it is pushed out to the surface and solved again;
 *  - reach: a goal beyond the arm bends the spine toward it, up to the spine's limits.
 *
 * Constraints: "hinge" (one axis, min..max degrees: elbows, knees, finger joints), "cone" (swing within a cone of
 * max degrees about the rest direction, with twist limits: shoulders, hips, wrists, thumb base), "fixed".
 *
 * Works in a browser (window.HumanoidIK) and in Node (module.exports).
 */
(function (root, factory) {
    if (typeof module === 'object' && module.exports) module.exports = factory();
    else root.HumanoidIK = factory();
})(typeof self !== 'undefined' ? self : this, function () {
    'use strict';
    const DEG = Math.PI / 180;
    const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
    const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
    const mul = (a, s) => [a[0] * s, a[1] * s, a[2] * s];
    const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    const cross = (a, b) => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
    const len = a => Math.hypot(a[0], a[1], a[2]);
    const norm = a => { const l = len(a) || 1e-9; return [a[0] / l, a[1] / l, a[2] / l]; };
    const lerp = (a, b, t) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
    const angle = (a, b) => Math.acos(clamp(dot(norm(a), norm(b)), -1, 1));
    /** v turned about unit axis k by t radians (Rodrigues). */
    const rotate = (v, k, t) => {
        const c = Math.cos(t), s = Math.sin(t);
        return add(add(mul(v, c), mul(cross(k, v), s)), mul(k, dot(k, v) * (1 - c)));
    };
    /** The direction d kept within a cone of half angle max about axis (both unit). */
    const intoCone = (d, axis, max) => {
        const a = angle(d, axis);
        if (a <= max) return d;
        let k = cross(axis, d);
        if (len(k) < 1e-9) k = Math.abs(axis[0]) < 0.9 ? cross(axis, [1, 0, 0]) : cross(axis, [0, 1, 0]);
        return norm(rotate(axis, norm(k), max));
    };

    /**
     * The standard humanoid joints, from drawn joint positions ({name: [x, y]} or [x, y, z]): DWPose-style names
     * (r_sho, r_elb, r_wri, l_..., r_hip, r_knee, r_ank, neck, nose) and optional hand keypoints
     * (hands: {l: [[x,y] x 21], r: [...]}, OpenPose hand order). Missing joints get human proportions.
     * Left/right are the character's own sides (character-left is picture-right).
     */
    function skeletonFromJoints(J, opts = {}) {
        // A third value is a depth only when opts.depth says so (DWPose's third value is its confidence).
        const P = k => J[k] ? [J[k][0], J[k][1], opts.depth && J[k].length > 2 ? J[k][2] : 0] : null;
        const rs = P('r_sho'), ls = P('l_sho');
        const shoulderW = rs && ls ? len(sub(ls, rs)) : 300;
        const neck = P('neck') || (rs && ls ? lerp(rs, ls, 0.5) : [0, 0, 0]);
        const rh = P('r_hip') || add(neck, [-shoulderW * 0.3, shoulderW * 1.5, 0]);
        const lh = P('l_hip') || add(neck, [shoulderW * 0.3, shoulderW * 1.5, 0]);
        const pelvis = lerp(rh, lh, 0.5);
        const chest = lerp(neck, pelvis, 0.3);
        const spine = lerp(neck, pelvis, 0.65);
        const head = P('nose') ? lerp(neck, P('nose'), 0.6) : add(neck, [0, -shoulderW * 0.45, 0]);
        const joints = [];
        const j = (name, parent, pos, constraint) => joints.push({ name, parent, rest: pos, constraint: constraint || { type: 'ball' } });
        j('pelvis', null, pelvis, { type: 'fixed' });
        j('spine', 'pelvis', spine, { type: 'cone', max: 20, twist: 15 });
        j('chest', 'spine', chest, { type: 'cone', max: 15, twist: 15 });
        j('neck', 'chest', neck, { type: 'cone', max: 25, twist: 30 });
        j('head', 'neck', head, { type: 'cone', max: 30, twist: 45 });
        for (const [s, k, out] of [['R', 'r', -1], ['L', 'l', 1]]) {
            const sho = P(`${k}_sho`) || add(neck, [out * shoulderW / 2, shoulderW * 0.05, 0]);
            const clav = lerp(neck, sho, 0.25);
            const elb = P(`${k}_elb`) || add(sho, [0, shoulderW * 0.9, 0]);
            const wri = P(`${k}_wri`) || add(elb, sub(elb, sho));
            j(`clavicle${s}`, 'chest', clav, { type: 'cone', max: 12, twist: 5 });
            // Shoulder: a wide cone about the arm hanging down, the bend of the elbow a hinge.
            j(`upperArm${s}`, `clavicle${s}`, sho, { type: 'cone', max: 170, twist: 90, axis: [0, 1, 0] });
            j(`forearm${s}`, `upperArm${s}`, elb, { type: 'hinge', min: 0, max: 150 });
            j(`hand${s}`, `forearm${s}`, wri, { type: 'cone', max: 80, twist: 85 });
            const handLen = len(sub(wri, elb)) * 0.42;
            const hp = J.hands && J.hands[k];
            const dir = norm(sub(wri, elb));
            // OpenPose hand: 0 wrist, thumb 1-4, index 5-8, middle 9-12, ring 13-16, pinky 17-20.
            const fingers = { Thumb: [1, 2, 3, 4], Index: [5, 6, 7, 8], Middle: [9, 10, 11, 12], Ring: [13, 14, 15, 16], Pinky: [17, 18, 19, 20] };
            const spreadAt = { Thumb: -0.55, Index: -0.25, Middle: 0, Ring: 0.22, Pinky: 0.42 };
            for (const [f, ids] of Object.entries(fingers)) {
                let pts;
                if (hp && hp.length >= 21) pts = ids.map(i => [hp[i][0], hp[i][1], 0]);
                else {
                    const side = norm(cross(dir, [0, 0, out]));
                    const base = add(add(wri, mul(dir, handLen * (f === 'Thumb' ? 0.25 : 0.55))), mul(side, spreadAt[f] * handLen * 0.6));
                    const seg = handLen * (f === 'Thumb' ? 0.28 : f === 'Pinky' ? 0.22 : 0.3);
                    const fd = norm(add(dir, mul(side, spreadAt[f] * 0.5)));
                    pts = [0, 1, 2, 3].map(t => add(base, mul(fd, seg * t)));
                }
                const names = f === 'Thumb' ? ['Cmc', 'Mcp', 'Ip', 'Tip'] : ['Mcp', 'Pip', 'Dip', 'Tip'];
                names.forEach((n, i) => j(`${f.toLowerCase()}${n}${s}`, i ? `${f.toLowerCase()}${names[i - 1]}${s}` : `hand${s}`, pts[i],
                    n === 'Tip' ? { type: 'fixed' } : i === 0 ? { type: 'cone', max: f === 'Thumb' ? 50 : 20, twist: 10 } : { type: 'hinge', min: f === 'Thumb' ? -10 : -5, max: f === 'Thumb' ? 80 : 100 }));
            }
            const hip = s === 'R' ? rh : lh;
            const knee = P(`${k}_knee`) || add(hip, [0, shoulderW * 1.3, 0]);
            const ank = P(`${k}_ank`) || add(knee, [0, shoulderW * 1.3, 0]);
            j(`thigh${s}`, 'pelvis', hip, { type: 'cone', max: 110, twist: 40, axis: [0, 1, 0] });
            j(`shin${s}`, `thigh${s}`, knee, { type: 'hinge', min: 0, max: 150 });
            j(`foot${s}`, `shin${s}`, ank, { type: 'cone', max: 40, twist: 20 });
            j(`toe${s}`, `foot${s}`, add(ank, [out * shoulderW * 0.05, shoulderW * 0.05, shoulderW * 0.35]), { type: 'fixed' });
        }
        return new Skeleton(joints, opts);
    }

    class Skeleton {
        constructor(joints, opts = {}) {
            this.joints = joints;
            this.byName = Object.fromEntries(joints.map((jt, i) => [jt.name, i]));
            this.children = joints.map(() => []);
            joints.forEach((jt, i) => { if (jt.parent) this.children[this.byName[jt.parent]].push(i); });
            // Body capsules a hand may not enter: torso (neck to pelvis) and head, radii from the shoulder width.
            const sw = this.has('upperArmR') && this.has('upperArmL') ? len(sub(this.rest('upperArmL'), this.rest('upperArmR'))) : 300;
            this.capsules = opts.capsules || [
                { a: 'chest', b: 'pelvis', r: sw * 0.42, depth: sw * 0.22 },
                { a: 'neck', b: 'head', r: sw * 0.33, depth: sw * 0.3 },
            ];
            this.reset();
        }
        has(name) { return name in this.byName; }
        rest(name) { return this.joints[this.byName[name]].rest; }
        reset() { this.pos = this.joints.map(jt => jt.rest.slice()); return this; }
        get(name) { return this.pos[this.byName[name]]; }
        /** Move a joint and carry its whole subtree with it (a rigid move). */
        _moveSubtree(i, delta) {
            const stack = [i];
            while (stack.length) { const k = stack.pop(); this.pos[k] = add(this.pos[k], delta); stack.push(...this.children[k]); }
        }
        /** Turn the subtree under joint i about joint i's position (axis unit, t radians). */
        _rotateSubtree(i, axis, t) {
            const o = this.pos[i];
            const stack = [...this.children[i]];
            while (stack.length) { const k = stack.pop(); this.pos[k] = add(o, rotate(sub(this.pos[k], o), axis, t)); stack.push(...this.children[k]); }
        }
        /** Aim the bone from joint i to its child c at point goal (turning i's subtree). */
        _aim(i, c, goal) {
            const from = sub(this.pos[c], this.pos[i]), to = sub(goal, this.pos[i]);
            const t = angle(from, to);
            if (t < 1e-6) return;
            let k = cross(from, to);
            if (len(k) < 1e-9) k = [0, 0, 1];
            this._rotateSubtree(i, norm(k), t);
        }
        _restDir(i, c) { return norm(sub(this.joints[c].rest, this.joints[i].rest)); }
        _parentTurn(i) {
            // How the parent bone turned from rest: rest directions are carried by it (a cone is about the rotated axis).
            const p = this.joints[i].parent; if (!p) return null;
            const pi = this.byName[p];
            const restD = this._restDir(pi, i), nowD = norm(sub(this.pos[i], this.pos[pi]));
            const t = angle(restD, nowD);
            if (t < 1e-6) return null;
            return { axis: norm(cross(restD, nowD)), t };
        }
        /** The direction of bone i->c clamped into joint i's cone (about its rest direction carried by the parent). */
        _limitCone(i, c) {
            const cn = this.joints[i].constraint;
            if (!cn || cn.type !== 'cone') return;
            let axis = cn.axis ? norm(cn.axis) : this._restDir(i, c);
            const pt = this._parentTurn(i);
            if (pt) axis = rotate(axis, pt.axis, pt.t);
            const dir = norm(sub(this.pos[c], this.pos[i]));
            const ok = intoCone(dir, axis, (cn.max || 180) * DEG);
            if (ok !== dir) this._aim(i, c, add(this.pos[i], mul(ok, len(sub(this.pos[c], this.pos[i])))));
        }

        /**
         * Two-bone IK: joint a (shoulder/hip) -> b (elbow/knee) -> c (wrist/ankle) reaches goal; b bends toward pole.
         * The hinge at b is kept within its limits, the cone at a within its cone.
         */
        twoBone(a, b, c, goal, pole) {
            const ia = this.byName[a], ib = this.byName[b], ic = this.byName[c];
            const A = this.pos[ia];
            const l1 = len(sub(this.joints[ib].rest, this.joints[ia].rest)), l2 = len(sub(this.joints[ic].rest, this.joints[ib].rest));
            const hinge = this.joints[ib].constraint;
            const minBend = (hinge.min || 0) * DEG, maxBend = (hinge.max || 180) * DEG;
            // The reach the hinge allows: straightest at minBend, most folded at maxBend.
            const far = Math.sqrt(l1 * l1 + l2 * l2 + 2 * l1 * l2 * Math.cos(minBend));
            const near = Math.sqrt(l1 * l1 + l2 * l2 + 2 * l1 * l2 * Math.cos(maxBend));
            let v = sub(goal, A); const d0 = len(v) || 1e-6; const n = norm(v);
            const d = clamp(d0, near + 1e-3, far * 0.9999);
            const T = add(A, mul(n, d));
            if (!pole) pole = add(this.pos[ib], [0, 0, -l1]);
            const h = sub(pole, A);
            let p = sub(h, mul(n, dot(h, n)));
            if (len(p) < 1e-6) p = Math.abs(n[2]) < 0.9 ? cross(n, [0, 0, 1]) : cross(n, [1, 0, 0]);
            p = norm(p);
            const x = (l1 * l1 - l2 * l2 + d * d) / (2 * d);
            const y = Math.sqrt(Math.max(0, l1 * l1 - x * x));
            const B = add(add(A, mul(n, x)), mul(p, y));
            this._aim(ia, ib, B);
            this._limitCone(ia, ib);
            this._aim(ib, ic, T);
            return len(sub(this.pos[ic], goal));
        }

        /** FABRIK over a chain of joint names (root fixed) so its last joint reaches goal; hinges keep their range. */
        chain(names, goal, iterations = 12, tolerance = 0.5) {
            const ids = names.map(n => this.byName[n]);
            const lens = ids.slice(1).map((id, k) => len(sub(this.joints[id].rest, this.joints[ids[k]].rest)));
            const root = this.pos[ids[0]].slice();
            let pts = ids.map(id => this.pos[id].slice());
            for (let it = 0; it < iterations; it++) {
                pts[pts.length - 1] = goal.slice();
                for (let k = pts.length - 2; k >= 0; k--) pts[k] = add(pts[k + 1], mul(norm(sub(pts[k], pts[k + 1])), lens[k]));
                pts[0] = root.slice();
                for (let k = 1; k < pts.length; k++) pts[k] = add(pts[k - 1], mul(norm(sub(pts[k], pts[k - 1])), lens[k - 1]));
                if (len(sub(pts[pts.length - 1], goal)) < tolerance) break;
            }
            // Apply as rotations (so subtrees follow), then limit each joint.
            for (let k = 0; k < ids.length - 1; k++) {
                this._aim(ids[k], ids[k + 1], pts[k + 1]);
                this._limitHinge(ids[k], ids[k + 1]);
                this._limitCone(ids[k], ids[k + 1]);
            }
            return len(sub(this.pos[ids[ids.length - 1]], goal));
        }
        /** A hinge joint i (child c) kept within [min, max] degrees of bend from its rest line. */
        _limitHinge(i, c) {
            const cn = this.joints[i].constraint;
            if (!cn || cn.type !== 'hinge') return;
            const p = this.joints[i].parent; if (!p) return;
            const pi = this.byName[p];
            const parentDir = norm(sub(this.pos[i], this.pos[pi]));
            const dir = norm(sub(this.pos[c], this.pos[i]));
            const restBend = angle(this._restDir(pi, i), this._restDir(i, c));
            const bend = angle(parentDir, dir) - restBend;
            const target = clamp(bend, (cn.min || 0) * DEG, (cn.max || 180) * DEG);
            if (Math.abs(target - bend) < 1e-4) return;
            let k = cross(parentDir, dir);
            if (len(k) < 1e-9) k = [0, 0, 1];
            this._rotateSubtree(i, norm(k), target - bend);
        }

        /** Curl a finger: 0 straight (as drawn) .. 1 fully bent, spread in degrees at its base. */
        curl(finger, side, amount, spread = 0) {
            const f = finger.toLowerCase();
            const names = f === 'thumb' ? ['Cmc', 'Mcp', 'Ip', 'Tip'] : ['Mcp', 'Pip', 'Dip', 'Tip'];
            const ids = names.map(n => this.byName[`${f}${n}${side}`]);
            if (ids.some(x => x === undefined)) return;
            const palm = this.palmNormal(side);
            const axis0 = norm(cross(sub(this.pos[ids[1]], this.pos[ids[0]]), palm));
            if (spread) this._rotateSubtree(ids[0], palm, spread * DEG);
            const share = f === 'thumb' ? [0.25, 0.4, 0.35] : [0.35, 0.4, 0.25];
            const maxes = ids.slice(0, 3).map(id => (this.joints[id].constraint.max || 90) * DEG);
            for (let k = 0; k < 3; k++) this._rotateSubtree(ids[k], axis0, amount * Math.min(maxes[k], share[k] * 2.6));
        }
        /** Which way the palm faces (unit, world): toward the viewer is z > 0. */
        palmNormal(side) {
            const w = this.get(`hand${side}`), i = this.get(`indexMcp${side}`), p = this.get(`pinkyMcp${side}`);
            if (!w || !i || !p) return [0, 0, 1];
            const n = norm(cross(sub(i, w), sub(p, w)));
            return side === 'L' ? n : mul(n, -1);
        }

        /** Push a hand out of the body capsules; returns true when it moved. */
        _keepOut(point) {
            let moved = null;
            for (const cap of this.capsules) {
                const A = this.get(cap.a), B = this.get(cap.b);
                if (!A || !B) continue;
                const ab = sub(B, A), t = clamp(dot(sub(point, A), ab) / (dot(ab, ab) || 1), 0, 1);
                const q = add(A, mul(ab, t));
                // An ellipse across x/z: the body is wide in the picture and shallow in depth.
                const dx = point[0] - q[0], dz = point[2] - q[2];
                const e = Math.hypot(dx / cap.r, dz / cap.depth);
                if (Math.abs(point[1] - q[1]) <= cap.r && e < 1) {
                    // In front of the body is the natural way out for a hand crossing it.
                    // Out the front: the hand keeps its place in the picture and comes forward to the surface.
                    const fx = clamp(dx / cap.r, -1, 1);
                    const out = [point[0], point[1], q[2] + cap.depth * Math.sqrt(1 - fx * fx) + 1];
                    moved = out; point = out;
                }
            }
            return moved;
        }

        /**
         * Solve a whole pose. goals: {
         *   handL/handR: {x, y, z?, pole?: {x,y,z}, palm?: 'in'|'out'|'down'|'up'|'side', grip?: pose name or {finger: curl}},
         *   footL/footR: {x, y, z?, pole?}, look: {x, y, z?}, lean: degrees (spine bend toward the side), reach: true
         * }
         */
        solve(goals = {}) {
            this.reset();
            if (goals.lean) {
                const s = this.byName.spine;
                if (s !== undefined) this._rotateSubtree(s, [0, 0, 1], clamp(goals.lean, -20, 20) * DEG);
            }
            const vec = g => [g.x, g.y, g.z !== undefined ? g.z : null];
            for (const side of ['L', 'R']) {
                const g = goals[`hand${side}`];
                if (!g || !this.has(`upperArm${side}`)) continue;
                let T = vec(g);
                const sh = this.get(`upperArm${side}`);
                if (T[2] === null) T[2] = sh[2];
                const out = this._keepOut(T); if (out) T = out;
                // A goal beyond the arm bends the spine toward it (within the spine's cone).
                const arm = len(sub(this.rest(`forearm${side}`), this.rest(`upperArm${side}`))) + len(sub(this.rest(`hand${side}`), this.rest(`forearm${side}`)));
                const gap = len(sub(T, sh)) - arm * 0.98;
                if (gap > 0 && goals.reach !== false && this.has('spine') && this.has('chest')) {
                    const s = this.byName.spine, c = this.byName.chest;
                    const toward = sub(T, this.pos[s]);
                    const k = norm(cross(sub(this.pos[c], this.pos[s]), toward));
                    const t = Math.min(20 * DEG, gap / (len(sub(sh, this.pos[s])) || 1));
                    this._rotateSubtree(s, k, t);
                }
                const pole = g.pole ? [g.pole.x, g.pole.y, g.pole.z !== undefined ? g.pole.z : this.get(`forearm${side}`)[2] - 50]
                    : add(this.get(`forearm${side}`), [side === 'L' ? 80 : -80, 40, -80]);
                this.twoBone(`upperArm${side}`, `forearm${side}`, `hand${side}`, T, pole);
                this._orientHand(side, g.palm);
                if (g.grip) this.grip(side, g.grip);
            }
            for (const side of ['L', 'R']) {
                const g = goals[`foot${side}`];
                if (!g || !this.has(`thigh${side}`)) continue;
                const T = vec(g); if (T[2] === null) T[2] = this.get(`thigh${side}`)[2];
                const pole = g.pole ? [g.pole.x, g.pole.y, g.pole.z !== undefined ? g.pole.z : 200] : add(this.get(`shin${side}`), [0, 0, 200]);
                this.twoBone(`thigh${side}`, `shin${side}`, `foot${side}`, T, pole);
                // The foot stays level: its toe points where it pointed at rest.
                const f = this.byName[`foot${side}`], t = this.byName[`toe${side}`];
                this._aim(f, t, add(this.pos[f], sub(this.joints[t].rest, this.joints[f].rest)));
            }
            if (goals.look) this.lookAt([goals.look.x, goals.look.y, goals.look.z !== undefined ? goals.look.z : 600]);
            return this.report();
        }

        /** Turn the wrist so the palm faces a way: 'in' (toward the body), 'out', 'down', 'up', 'side' (thumb up), 'viewer', 'away'. */
        _orientHand(side, palm) {
            if (!palm) return;
            const h = this.byName[`hand${side}`];
            const fore = norm(sub(this.pos[h], this.get(`forearm${side}`)));
            const inward = side === 'L' ? [-1, 0, 0] : [1, 0, 0];
            const want = { in: inward, out: mul(inward, -1), down: [0, 1, 0], up: [0, -1, 0], viewer: [0, 0, 1], away: [0, 0, -1], side: norm(cross(fore, [0, 0, 1])) }[palm];
            if (!want) return;
            // Twist about the forearm until the palm normal lies closest to want (limited by the wrist's twist).
            const n0 = this.palmNormal(side);
            const proj = v => norm(sub(v, mul(fore, dot(v, fore))));
            const a = proj(n0), b = proj(want);
            let t = angle(a, b);
            if (dot(cross(a, b), fore) < 0) t = -t;
            const lim = (this.joints[h].constraint.twist || 90) * DEG;
            this._rotateSubtree(this.byName[`forearm${side}`], fore, clamp(t, -lim * 1.6, lim * 1.6));
        }

        /** Shape a hand: a named pose (open, relaxed, fist, point, peace, thumbsUp, ok, grip) or {finger: curl}. */
        grip(side, pose) {
            const curls = typeof pose === 'string' ? HAND_POSES[pose] : pose;
            if (!curls) return;
            for (const [f, c] of Object.entries(curls)) {
                const [amount, spread] = Array.isArray(c) ? c : [c, 0];
                this.curl(f, side, amount, spread);
            }
        }

        /** Head and eyes look at a point: the neck takes 40%, the head 60%, each within its cone; eyes take the rest. */
        lookAt(point) {
            const n = this.byName.neck, h = this.byName.head;
            if (n === undefined || h === undefined) return null;
            const head = this.pos[h];
            const want = norm(sub(point, head));
            const face = [0, 0, 1];
            const total = angle(face, want);
            let k = cross(face, want); if (len(k) < 1e-9) return null; k = norm(k);
            const neckMax = this.joints[n].constraint.max * DEG, headMax = this.joints[h].constraint.max * DEG;
            const tn = Math.min(total * 0.4, neckMax), th = Math.min(total - tn, headMax);
            this._rotateSubtree(n, k, tn);
            this._headTurn = rotate(face, k, tn + th);
            this._eyeTurn = Math.max(0, total - tn - th);
            this._lookDir = want;
            return this._headTurn;
        }

        /**
         * Per joint: world position, the turn of its bone in the picture's plane (degrees, from its drawn direction,
         * positive = clockwise on screen), its swing out of the plane (degrees, toward the viewer positive) and depth.
         * Hands add palm (normal) and view (the nearest of 8 yaw x 3 pitch drawn views). The head adds its look angles.
         */
        report() {
            const out = {};
            this.joints.forEach((jt, i) => {
                const kids = this.children[i];
                const r = { pos: this.pos[i].slice(), depth: this.pos[i][2] };
                if (kids.length) {
                    const c = kids[0];
                    const rd = this._restDir(i, c), nd = norm(sub(this.pos[c], this.pos[i]));
                    r.turn = (Math.atan2(nd[1], nd[0]) - Math.atan2(rd[1], rd[0])) / DEG;
                    r.turn = ((r.turn + 540) % 360) - 180;
                    r.swing = (Math.asin(clamp(nd[2], -1, 1)) - Math.asin(clamp(rd[2], -1, 1))) / DEG;
                    // How long the bone looks on screen (foreshortening) compared with its drawing.
                    const rl = Math.hypot(rd[0], rd[1]) || 1e-6;
                    r.scale = Math.hypot(nd[0], nd[1]) / rl;
                }
                out[jt.name] = r;
            });
            for (const side of ['L', 'R']) {
                if (!this.has(`hand${side}`)) continue;
                const n = this.palmNormal(side);
                const yaw = Math.atan2(n[0] * (side === 'L' ? 1 : -1), n[2]) / DEG;
                const pitch = Math.asin(clamp(-n[1], -1, 1)) / DEG;
                out[`hand${side}`].palm = n;
                out[`hand${side}`].view = handView(yaw, pitch);
            }
            if (this._headTurn) {
                const d = this._headTurn;
                out.head.lookX = Math.atan2(d[0], d[2]) / DEG;
                out.head.lookY = Math.atan2(-d[1], d[2]) / DEG;
                out.head.eyes = this._eyeTurn / DEG;
            }
            return out;
        }
    }

    /** The drawn hand view nearest to a palm yaw/pitch: yaw in 45 degree steps (0 = palm to the viewer), pitch -45/0/45. */
    function handView(yaw, pitch) {
        const y = ((Math.round(yaw / 45) * 45) + 360) % 360;
        const p = pitch > 22.5 ? 45 : pitch < -22.5 ? -45 : 0;
        return { yaw: y, pitch: p, index: (y / 45) + 8 * (p === -45 ? 0 : p === 0 ? 1 : 2) };
    }

    /** Finger curls (0 straight .. 1 fully bent), optionally [curl, spread degrees]. */
    const HAND_POSES = {
        open: { thumb: [0, -12], index: [0, -6], middle: 0, ring: [0, 5], pinky: [0, 10] },
        relaxed: { thumb: 0.2, index: 0.25, middle: 0.32, ring: 0.38, pinky: 0.42 },
        fist: { thumb: 0.7, index: 1, middle: 1, ring: 1, pinky: 1 },
        point: { thumb: 0.6, index: 0, middle: 1, ring: 1, pinky: 1 },
        peace: { thumb: 0.6, index: [0, -8], middle: [0, 8], ring: 1, pinky: 1 },
        thumbsUp: { thumb: 0, index: 1, middle: 1, ring: 1, pinky: 1 },
        ok: { thumb: 0.55, index: 0.7, middle: [0, 2], ring: [0.05, 6], pinky: [0.1, 12] },
        grip: { thumb: 0.5, index: 0.65, middle: 0.7, ring: 0.72, pinky: 0.75 },
    };

    /**
     * Turn a solved report into model parameters with a mapping {param: {joint, field ('turn'|'swing'|'scale'|
     * 'view.index'|'lookX'...), scale?, offset?, min?, max?}}. A Live2D rig's arm angles are the bones' turns in the
     * picture's plane, with the rig's own sign per side.
     */
    function toParameters(report, mapping) {
        const out = {};
        for (const [param, m] of Object.entries(mapping)) {
            const r = report[m.joint]; if (!r) continue;
            let v = m.field.split('.').reduce((o, k) => (o == null ? o : o[k]), r);
            if (typeof v !== 'number') continue;
            v = v * (m.scale ?? 1) + (m.offset ?? 0);
            if (m.min !== undefined) v = Math.max(m.min, v);
            if (m.max !== undefined) v = Math.min(m.max, v);
            out[param] = v;
        }
        return out;
    }

    return { Skeleton, skeletonFromJoints, toParameters, handView, HAND_POSES, util: { rotate, angle, norm, intoCone } };
});
