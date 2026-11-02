/**
 * AutoExpress puppet player.
 *
 * Plays an AutoExpress puppet (a "<name>.puppet.model.json" made by the Live2D model kit) with
 * PixiJS 6 meshes. The puppet stands in for a Live2D model: it has the parts of
 * pixi-live2d-display's Live2DModel that the SillyTavern Live2D extension uses (parameters,
 * expressions, motions, hit areas, lip sync, cursor following), so that extension plays puppets
 * without any change once installPuppetLoader() has hooked Live2DModel.from().
 *
 * The rig is procedural: each layer has a role (face, iris, eyelash, front hair ...) and the
 * puppet file gives the boxes and pivots to deform it around. Every frame the parameters are
 * worked out (defaults, then motions, expressions and the outfit, eased by a spring so changes
 * glide, then blinking and breathing, cursor, lip sync, values set by hand) and every layer's
 * mesh is bent from them: head turn with depth parallax, features, hair and cloth sway, soft
 * body jiggle (bust and hips) and the pull of the mouse when cloth, hair or a soft part is dragged.
 *
 * Needs window.PIXI (v6). Nothing else.
 */

const FORMAT = 'AutoExpress Puppet';
const SUFFIX = '.puppet.model.json';
const LOG = '[AutoExpress puppet]';

// How far in front of the face each role sits, for the head-turn parallax (face = 0).
const ROLE_DEPTH = {
    front_hair: 0.75, hair_under: 0.75, headwear: 0.65, nose: 0.6, eyewear: 0.6, brow: 0.45, brow_angry: 0.45, mouth: 0.45, mouth_open: 0.45,
    mouth_grin: 0.45, eyelash: 0.4, eye_closed: 0.4, eye_tears: 0.39, eyes: 0.4, iris: 0.35, eye_white: 0.35, cheek: 0.25, face: 0,
    ear: -0.3, back_hair: -0.45,
};
const HEAD_ROLES = new Set(Object.keys(ROLE_DEPTH));
const EYE_ROLES = new Set(['eye_white', 'iris', 'eyelash', 'eyes']);
// Layers of the body under the head: they jiggle with the soft parts and follow the mouse's pull.
const SOFT_ROLES = new Set(['body', 'clothing', 'nude_body', 'inner']);
// The outer clothes, hidden by ParamClothesOuter when there is a body layer under them.
const OUTER_ROLES = new Set(['clothing', 'arm']);
// Expressions whose names start with these stay on (each in its own slot) while emotions change.
const PERSISTENT_SLOTS = ['outfit_', 'accessories_'];
// How long parameter changes take to settle (seconds): expressions glide instead of snapping.
const EASE_TIME = 0.16;
const CURSOR_DEFAULTS = {
    idParamAngleX: 'ParamAngleX',
    idParamAngleY: 'ParamAngleY',
    idParamAngleZ: 'ParamAngleZ',
    idParamBodyAngleX: 'ParamBodyAngleX',
    idParamBreath: 'ParamBreath',
    idParamEyeBallX: 'ParamEyeBallX',
    idParamEyeBallY: 'ParamEyeBallY',
};

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const lerp = (a, b, t) => a + (b - a) * t;
function smoothstep(edge0, edge1, x) {
    const t = clamp((x - edge0) / (edge1 - edge0), 0, 1);
    return t * t * (3 - 2 * t);
}

export function isPuppetPath(source) {
    return typeof source === 'string' && source.split(/[?#]/)[0].toLowerCase().endsWith(SUFFIX);
}

// Parameters ----------------------------------------------------------------------------
/** The parameter store, shaped like Cubism's core model as pixi-live2d-display exposes it. */
class PuppetCore {
    constructor(parameters) {
        this.ids = parameters.map(p => p.Id);
        this.index = new Map(this.ids.map((id, i) => [id, i]));
        const n = this.ids.length;
        this.defaults = Float32Array.from(parameters, p => p.Default ?? 0);
        this.mins = Float32Array.from(parameters, p => p.Min ?? -1);
        this.maxs = Float32Array.from(parameters, p => p.Max ?? 1);
        this.values = Float32Array.from(this.defaults);
        this.overrides = new Map(); // index -> value set by hand (kept until reset to the default)
        this.adds = new Map(); // index -> {value, time}: short-lived offsets (lip sync)
        this._model = {
            parameters: {
                ids: this.ids,
                defaultValues: this.defaults,
                minimumValues: this.mins,
                maximumValues: this.maxs,
                values: this.values,
                count: n,
            },
        };
    }

    getParameterIndex(id) {
        return this.index.has(id) ? this.index.get(id) : -1;
    }

    getParameterValueById(id) {
        const i = this.getParameterIndex(id);
        return i < 0 ? 0 : this.values[i];
    }

    getParameterValueByIndex(i) {
        return this.values[i] ?? 0;
    }

    setParameterValueById(id, value, weight = 1) {
        this.setParameterValueByIndex(this.getParameterIndex(id), value, weight);
    }

    setParameterValueByIndex(i, value, weight = 1) {
        if (i < 0 || i >= this.ids.length) return;
        const target = weight >= 1 ? value : lerp(this.values[i], value, weight);
        // Setting a parameter back to its default hands it back to the animation.
        if (Math.abs(target - this.defaults[i]) < 1e-6) this.overrides.delete(i);
        else this.overrides.set(i, target);
        this.values[i] = clamp(target, this.mins[i], this.maxs[i]);
    }

    addParameterValueById(id, value, weight = 1) {
        const i = this.getParameterIndex(id);
        if (i < 0) return;
        this.adds.set(i, { value: value * weight, time: performance.now() });
    }

    multiplyParameterValueById(id, value, weight = 1) {
        const i = this.getParameterIndex(id);
        if (i >= 0) this.values[i] *= lerp(1, value, weight);
    }
}

// Motions ---------------------------------------------------------------------------------
/** A parsed .motion3.json: curves that give each parameter's value at a time. */
class Motion {
    constructor(json, entry = {}) {
        const meta = json.Meta || {};
        this.duration = meta.Duration || 1;
        this.loop = !!meta.Loop;
        this.fadeIn = entry.FadeInTime ?? meta.FadeInTime ?? 0.5;
        this.fadeOut = entry.FadeOutTime ?? meta.FadeOutTime ?? 0.5;
        this.curves = [];
        for (const curve of json.Curves || []) {
            if (curve.Target !== 'Parameter') continue;
            this.curves.push({ id: curve.Id, segments: Motion.parse(curve.Segments || []), fadeIn: curve.FadeInTime, fadeOut: curve.FadeOutTime });
        }
    }

    static parse(data) {
        const segments = [];
        if (data.length < 2) return segments;
        let last = [data[0], data[1]];
        let pos = 2;
        while (pos < data.length) {
            const type = data[pos];
            if (type === 1) {
                const points = [last, [data[pos + 1], data[pos + 2]], [data[pos + 3], data[pos + 4]], [data[pos + 5], data[pos + 6]]];
                segments.push({ type, points });
                last = points[3];
                pos += 7;
            } else {
                const end = [data[pos + 1], data[pos + 2]];
                segments.push({ type, points: [last, end] });
                last = end;
                pos += 3;
            }
        }
        return segments;
    }

    static evaluate(segments, time) {
        if (!segments.length) return 0;
        let segment = segments[segments.length - 1];
        for (const s of segments) {
            if (time <= s.points[s.points.length - 1][0]) {
                segment = s;
                break;
            }
        }
        const p = segment.points;
        const start = p[0];
        const end = p[p.length - 1];
        if (time <= start[0]) return start[1];
        if (time >= end[0]) return end[1];
        switch (segment.type) {
        case 2: return start[1]; // stepped
        case 3: return end[1]; // inverse stepped
        case 1: { // bezier: find u with x(u) = time, then y(u)
            const bez = (a, b, c, d, u) => {
                const v = 1 - u;
                return v * v * v * a + 3 * v * v * u * b + 3 * v * u * u * c + u * u * u * d;
            };
            let lo = 0, hi = 1, u = 0.5;
            for (let k = 0; k < 20; k++) {
                u = (lo + hi) / 2;
                if (bez(p[0][0], p[1][0], p[2][0], p[3][0], u) < time) lo = u;
                else hi = u;
            }
            return bez(p[0][1], p[1][1], p[2][1], p[3][1], u);
        }
        default: return lerp(start[1], end[1], (time - start[0]) / (end[0] - start[0]));
        }
    }
}

/** A parsed .exp3.json. */
class Expression {
    constructor(json) {
        this.fadeIn = json.FadeInTime ?? 0.5;
        this.fadeOut = json.FadeOutTime ?? 0.5;
        this.parameters = (json.Parameters || []).map(p => ({ id: p.Id, value: p.Value ?? 0, blend: p.Blend || 'Add' }));
    }
}

// The model ---------------------------------------------------------------------------------
let PuppetClass = null;
// Puppets that are playing (the SillyTavern extension looks up a character's puppet here).
const LIVE = new Set();

/** The puppets on screen now. */
export function livePuppets() {
    return [...LIVE];
}

/**
 * A file of a puppet packed into the page (play.html sets window.AUTOEXPRESS_PUPPET_FILES: path ->
 * parsed JSON, or a data: URL for a texture), so it plays when opened straight from the disk,
 * where browsers block fetch().
 */
function bundled(path) {
    const files = typeof window !== 'undefined' && window.AUTOEXPRESS_PUPPET_FILES;
    return files && Object.prototype.hasOwnProperty.call(files, path) ? files[path] : null;
}

function definePuppetClass(PIXI) {
    class Puppet extends PIXI.Container {
        static async from(source) {
            const url = new URL(source, document.baseURI).href;
            let document_ = bundled(source);
            if (!document_) {
                const response = await fetch(url);
                if (!response.ok) throw new Error(`${LOG} can't load ${source}: ${response.status}`);
                document_ = await response.json();
            }
            if (document_.Type !== FORMAT) throw new Error(`${LOG} ${source} is not an ${FORMAT}`);
            const puppet = new Puppet(document_, url);
            await puppet._loadTextures();
            return puppet;
        }

        constructor(doc, url) {
            super();
            this.doc = doc;
            this.url = url;
            this.base = url.substring(0, url.lastIndexOf('/') + 1);
            this.tag = doc.Name || 'puppet';
            const width = doc.Canvas.Width;
            const height = doc.Canvas.Height;
            this.core = new PuppetCore(doc.Parameters);
            const references = doc.FileReferences || {};
            this._motionCache = new Map();
            this._expressionCache = new Map();
            this._motions = []; // active motions: {motion, group, start, fadeOutStart?}
            this._expressions = []; // active expressions: {expression, start, fadeOutStart?}
            this._time = 0;
            this._blink = { next: 2 + Math.random() * 3, phase: -1 };
            this._focus = { x: 0, y: 0, tx: 0, ty: 0 };
            this._hair = {};
            this._soft = {};
            this._drag = { active: false, sx: 0, sy: 0, tx: 0, ty: 0, x: 0, y: 0, vx: 0, vy: 0, moved: 0, start: 0, soft: null };
            // Expressions that stay on while the emotions change, one per slot (outfit_*, accessories_*):
            // slot -> { now: {expression, start}, old: the one it fades from }.
            this._slots = {};
            this._pose = new Map(); // parameter id -> offset the user posed
            this._eased = null;
            this._easedVelocity = null;
            // Drag anywhere to pull (the preview page); in SillyTavern only cloth, hair and soft parts,
            // so dragging elsewhere still moves the model.
            this.grabAnywhere = false;
            // Dragging the head, an arm or the torso poses the skeleton (off: only the bust and hips pull).
            this.poseable = true;
            this._autoInteract = false;
            this._onPointerMove = (event) => this._pointerMoved(event);

            const self = this;
            const hitAreas = {};
            (doc.HitAreas || []).forEach((area, index) => {
                hitAreas[area.Name] = { id: area.Id || area.Name, name: area.Name, index };
            });
            this.internalModel = {
                coreModel: this.core,
                settings: {
                    url,
                    name: this.tag,
                    expressions: references.Expressions || [],
                    motions: references.Motions || {},
                    hitAreas: doc.HitAreas || [],
                },
                hitAreas,
                width,
                height,
                originalWidth: width,
                originalHeight: height,
                motionManager: {
                    get playing() {
                        return self._motions.some(m => m.group !== 'Idle' && m.fadeOutStart === undefined);
                    },
                    stopAllMotions: () => {
                        this._motions = [];
                    },
                },
                ...CURSOR_DEFAULTS,
            };

            this.interactive = true;
            this.buttonMode = false;
            this.hitArea = new PIXI.Rectangle(0, 0, width, height);
            this._wrapped = new Map();
            super.on('pointerdown', (event) => this._grabStart(event));
            super.on('pointermove', (event) => this._grabMove(event));
            super.on('pointerup', () => this._grabEnd());
            super.on('pointerupoutside', () => this._grabEnd());
            super.on('pointertap', (event) => {
                if (this._drag.moved > 6) return; // that was a drag, not a tap
                const hits = this.hitTest(event.data.global.x, event.data.global.y);
                if (!hits.length) return;
                // The SillyTavern Live2D extension plays its mapping for a hit; with nobody listening
                // (the preview page), the puppet reacts by itself.
                if (this.listenerCount('hit')) this.emit('hit', hits);
                else this.react(hits[0]);
            });

            this._ticker = PIXI.Ticker.shared;
            this._ticker.add(this._tick, this);
            LIVE.add(this);
        }

        // Size: like Live2DModel, the size is the canvas size times the scale.
        get width() {
            return Math.abs(this.scale.x) * this.internalModel.width;
        }

        set width(value) {
            this.scale.x = value / this.internalModel.width;
        }

        get height() {
            return Math.abs(this.scale.y) * this.internalModel.height;
        }

        set height(value) {
            this.scale.y = value / this.internalModel.height;
        }

        get autoInteract() {
            return this._autoInteract;
        }

        set autoInteract(value) {
            this._autoInteract = !!value;
            window.removeEventListener('pointermove', this._onPointerMove);
            if (this._autoInteract) window.addEventListener('pointermove', this._onPointerMove);
            else {
                this._focus.tx = 0;
                this._focus.ty = 0;
            }
        }

        _pointerMoved(event) {
            this.focus(event.clientX, event.clientY);
        }

        /** Look towards a point (in the page's pixels, like the pointer). */
        focus(x, y) {
            const renderer = this._renderer();
            const view = renderer?.view;
            let sx = x, sy = y;
            if (view && view.getBoundingClientRect) {
                const rect = view.getBoundingClientRect();
                sx = (x - rect.left) * (renderer.screen.width / Math.max(1, rect.width));
                sy = (y - rect.top) * (renderer.screen.height / Math.max(1, rect.height));
            }
            const point = this.toLocal(new PIXI.Point(sx, sy));
            const head = this.doc.Rig.Head;
            const reach = Math.max(this.internalModel.width, this.internalModel.height) * 0.6;
            this._focus.tx = clamp((point.x - head.Center[0]) / reach, -1, 1);
            this._focus.ty = clamp((head.Center[1] - point.y) / reach, -1, 1);
        }

        _view() {
            return this._renderer()?.view || null;
        }

        // Mouse pulls ---------------------------------------------------------------------------
        // Listeners others add for pointermove (the Live2D extension drags the model with it) are
        // paused while the puppet's cloth, hair or body is being pulled.
        on(event, fn, context) {
            if (event !== 'pointermove' || typeof fn !== 'function') return super.on(event, fn, context);
            const wrapped = (...args) => {
                if (!this._drag.active) fn.apply(context ?? this, args);
            };
            this._wrapped.set(fn, wrapped);
            return super.on(event, wrapped, context);
        }

        off(event, fn, context) {
            if (event === 'pointermove' && this._wrapped?.has(fn)) {
                const wrapped = this._wrapped.get(fn);
                this._wrapped.delete(fn);
                return super.off(event, wrapped, context);
            }
            return super.off(event, fn, context);
        }

        /** Which soft region ('Bust', 'Hips') a point on the canvas is over, or null. */
        _softAt(x, y, grow = 1) {
            const rig = this.doc.Rig;
            for (const name of ['Bust', 'Hips']) {
                const region = rig[name];
                if (!region || !(region.Radius?.[0] > 0)) continue;
                for (const [cx, cy] of region.Centers) {
                    const dx = (x - cx) / (region.Radius[0] * grow);
                    const dy = (y - cy) / (region.Radius[1] * grow);
                    if (dx * dx + dy * dy <= 1) return name;
                }
            }
            return null;
        }

        /**
         * What a press at a canvas point grabs: 'body' on the bust or hips (pulled, springs back),
         * or a joint of the skeleton to pose ('head', 'arm L' / 'arm R', 'torso'), or null.
         */
        _grabbable(x, y) {
            if (this._softAt(x, y, 1.15)) return 'body';
            if (!this.poseable) return null;
            const rig = this.doc.Rig;
            const [hl, ht, hr, hb] = rig.Head.Box;
            if (x >= hl && x <= hr && y >= ht && y <= hb) return 'head';
            for (const [side, arm] of Object.entries(rig.Arms || {})) {
                const entry = this.doc.Layers.find(e => e.Id === arm.Layers[0]);
                // Anywhere on the arm away from its joint (near the joint is the body's).
                if (entry && x >= entry.X && x <= entry.X + entry.Width && y >= entry.Y && y <= entry.Y + entry.Height
                    && Math.hypot(x - arm.Pivot[0], y - arm.Pivot[1]) >= arm.Length * 0.3) return `arm ${side}`;
            }
            const [bl, bt, br, bb] = rig.Body.Box;
            if (x >= bl && x <= br && y >= hb && y <= bt + (bb - bt) * 0.55) return 'torso';
            return null;
        }

        /**
         * Pose the skeleton from a drag: the head turns and nods, an arm swings at the shoulder, the
         * torso leans. Every joint stops at its limit (the parameters' ranges), and the pose stays.
         */
        _poseMove(d, point) {
            const rig = this.doc.Rig;
            const [hl, ht, hr, hb] = rig.Head.Box;
            const dx = point.x - d.sx;
            const dy = point.y - d.sy;
            const set = (id, value) => {
                const i = this.core.getParameterIndex(id);
                if (i < 0) return;
                const lo = this.core.mins[i], hi = this.core.maxs[i];
                // The offset stops where the joint does (the parameter's range, from its default).
                this._pose.set(id, clamp(value, lo - this.core.defaults[i], hi - this.core.defaults[i]));
            };
            const start = (id) => d.poseStart.get(id) || 0;
            if (d.pose === 'head') {
                set('ParamAngleX', start('ParamAngleX') + dx / Math.max(1, hr - hl) * 50);
                set('ParamAngleY', start('ParamAngleY') - dy / Math.max(1, hb - ht) * 50);
            } else if (d.pose === 'torso') {
                // The torso leans the way it is pulled: around the hips, like the arms at the shoulder.
                const [bl, bt, br, bb] = rig.Body.Box;
                const hx = (bl + br) / 2, hy = bt + (bb - bt) * 0.75;
                const lean = (Math.atan2(point.x - hx, hy - point.y) - Math.atan2(d.sx - hx, hy - d.sy)) * 180 / Math.PI;
                set('ParamBodyAngleZ', start('ParamBodyAngleZ') + lean);
                set('ParamBodyAngleX', start('ParamBodyAngleX') + dx / Math.max(1, br - bl) * 20);
            } else if (d.pose.startsWith('arm ')) {
                const side = d.pose.slice(4);
                const arm = rig.Arms[side];
                const [px, py] = arm.Pivot;
                const from = Math.atan2(d.sy - py, d.sx - px);
                const to = Math.atan2(point.y - py, point.x - px);
                const degrees = (to - from) * 180 / Math.PI;
                for (const s of side === 'LR' ? ['L', 'R'] : [side]) set(`ParamArm${s}A`, start(`ParamArm${s}A`) + degrees);
            }
        }

        /** Put the skeleton back in the drawing's pose. */
        resetPose() {
            this._pose.clear();
        }

        _grabStart(event) {
            const point = this.toLocal(event.data.global);
            const d = this._drag;
            d.moved = 0;
            const kind = this._grabbable(point.x, point.y);
            d.reacted = false;
            if (!kind) return;
            d.kind = kind;
            d.active = true;
            d.sx = point.x;
            d.sy = point.y;
            d.tx = 0;
            d.ty = 0;
            d.start = this._time;
            d.soft = this._softAt(point.x, point.y, 1.15);
            d.pose = kind === 'body' ? null : kind;
            d.poseStart = new Map(this._pose);
        }

        _grabMove(event) {
            const d = this._drag;
            if (!d.active) return;
            const point = this.toLocal(event.data.global);
            if (d.pose) {
                d.moved = Math.max(d.moved, Math.hypot(point.x - d.sx, point.y - d.sy) * Math.abs(this.scale.x || 1));
                this._poseMove(d, point);
                return;
            }
            // Skin and cloth only stretch so far: the pull is limited to a share of the soft part's
            // size (a little more sideways than up and down), and gives way gradually towards it.
            const region = this.doc.Rig[d.soft] || null;
            const gain = (this.doc.Rig.Strength || {}).drag ?? 1;
            const head = this.doc.Rig.Head;
            const [rx, ry] = region?.Radius || [(head.Box[3] - head.Box[1]) * 0.4, (head.Box[3] - head.Box[1]) * 0.4];
            const limitX = rx * 0.32 * gain;
            const limitY = ry * 0.24 * gain;
            let dx = point.x - d.sx;
            let dy = point.y - d.sy;
            d.moved = Math.max(d.moved, Math.hypot(dx, dy) * Math.abs(this.scale.x || 1));
            dx = limitX * Math.tanh(dx / Math.max(1, limitX * 1.6));
            dy = limitY * Math.tanh(dy / Math.max(1, limitY * 1.6));
            d.tx = dx;
            d.ty = dy;
            if (!d.reacted && d.moved > 24) {
                d.reacted = true;
                this.react('Drag');
            }
        }

        _grabEnd() {
            const d = this._drag;
            if (!d.active) return;
            d.active = false;
            d.tx = 0;
            d.ty = 0;
            // A quick tap on a soft part pokes it: it bounces.
            if (d.soft && d.moved <= 6) this.poke(d.sx, d.sy);
        }

        /**
         * React to a touch: show the emotion the puppet's Reactions give the hit area ("Drag" for a
         * pull), with its motion, for a few seconds, then go back to the emotion from before.
         */
        react(area, seconds = 4) {
            const emotion = (this.doc.Reactions || {})[area];
            const names = this.internalModel.settings.expressions.map(e => e.Name);
            if (!emotion || !names.includes(emotion)) return false;
            const token = (this._reaction = {});
            const before = this._emotion;
            this.expression(emotion).then(() => (this._emotion = before));
            if (this.internalModel.settings.motions[emotion]) this.motion(emotion);
            setTimeout(() => {
                if (this._reaction !== token || this._emotion !== before) return; // something newer took over
                if (before) this.expression(before);
                else for (const active of this._expressions) if (active.fadeOutStart === undefined) active.fadeOutStart = this._time;
            }, seconds * 1000);
            return true;
        }

        /** Poke the puppet at a point on the canvas: a soft part there bounces. */
        poke(x, y, strength = 1) {
            const name = this._softAt(x, y, 1.3);
            if (!name) return false;
            const region = this.doc.Rig[name];
            region.Centers.forEach((_, index) => {
                const state = this._soft[`${name}${index}`];
                if (!state) return;
                state.vy += region.Radius[1] * 2.2 * strength;
                state.vx += (x - region.Centers[index][0]) * 1.5 * strength;
            });
            return true;
        }

        _renderer() {
            let node = this;
            while (node.parent) node = node.parent;
            return node._puppetRenderer || window.__puppetRenderer || null;
        }

        /** Names of the hit areas under a point on the screen (global stage coordinates). */
        hitTest(x, y) {
            const point = this.toLocal(new PIXI.Point(x, y));
            return (this.doc.HitAreas || [])
                .filter(area => point.x >= area.Box[0] && point.x <= area.Box[2] && point.y >= area.Box[1] && point.y <= area.Box[3])
                .map(area => area.Name);
        }

        // Loading -------------------------------------------------------------------------
        async _loadTextures() {
            const rig = this.doc.Rig;
            this.layers = [];
            const cheekAfter = this.doc.Layers.findIndex(l => l.Role === 'face');
            let index = 0;
            for (const entry of this.doc.Layers) {
                const texture = await PIXI.Texture.fromURL(bundled(entry.Texture) || this.base + entry.Texture);
                this.layers.push(this._makeLayer(entry, texture));
                if (index === cheekAfter) {
                    for (const side of Object.keys(rig.Eyes || {})) {
                        this.layers.push(this._makeCheek(side, false));
                        this.layers.push(this._makeCheek(side, true));
                    }
                }
                index += 1;
            }
            for (const layer of this.layers) this.addChild(layer.mesh);
            this._hasBody = this.layers.some(l => l.role === 'nude_body');
            this._halfSwitches = new Set(this.doc.Layers.filter(e => e.State === 'half' && e.Switch).map(e => e.Switch));
            this._update(0);
        }

        _makeLayer(entry, texture) {
            const [cols, rows] = entry.Grid || [2, 2];
            const count = cols * rows;
            const rest = new Float32Array(count * 2);
            const uvs = new Float32Array(count * 2);
            for (let r = 0; r < rows; r++) {
                for (let c = 0; c < cols; c++) {
                    const k = (r * cols + c) * 2;
                    const u = c / (cols - 1);
                    const v = r / (rows - 1);
                    uvs[k] = u;
                    uvs[k + 1] = v;
                    rest[k] = entry.X + u * entry.Width;
                    rest[k + 1] = entry.Y + v * entry.Height;
                }
            }
            const indices = new Uint16Array((cols - 1) * (rows - 1) * 6);
            let i = 0;
            for (let r = 0; r < rows - 1; r++) {
                for (let c = 0; c < cols - 1; c++) {
                    const a = r * cols + c;
                    const b = a + 1;
                    const d = a + cols;
                    const e = d + 1;
                    indices.set([a, b, d, b, e, d], i);
                    i += 6;
                }
            }
            const mesh = new PIXI.SimpleMesh(texture, Float32Array.from(rest), uvs, indices, PIXI.DRAW_MODES.TRIANGLES);
            mesh.autoUpdate = true;
            const hair = (this.doc.Rig.Hair || []).find(h => h.Layer === entry.Id);
            const cloth = (this.doc.Rig.Cloth || []).find(c => c.Layer === entry.Id);
            return {
                entry,
                role: entry.Role,
                side: entry.Side,
                mesh,
                rest,
                out: mesh.vertices,
                hair,
                cloth,
                dz: ROLE_DEPTH[entry.Role] ?? 0,
                head: HEAD_ROLES.has(entry.Role) || entry.Role === 'neck',
            };
        }

        /**
         * A blush for one cheek: a soft pink multiplied over the skin (so it takes the skin's tone),
         * or, with hatch, the anime blush strokes drawn over it when the blush is strong.
         */
        _makeCheek(side, hatch) {
            const eye = this.doc.Rig.Eyes[side];
            const [l, t, r, b] = eye.Box;
            const w = (r - l) * 1.5;
            const h = (b - t) * 0.85;
            const canvas = document.createElement('canvas');
            canvas.width = 256;
            canvas.height = 128;
            const g = canvas.getContext('2d');
            if (!hatch) {
                // Feathered: strongest in the middle and fading out smoothly (no visible rim).
                const gradient = g.createRadialGradient(128, 64, 0, 128, 64, 126);
                const stops = 12;
                for (let i = 0; i <= stops; i++) {
                    const f = i / stops;
                    const a = Math.pow(Math.cos(f * Math.PI / 2), 2.2);
                    gradient.addColorStop(f, `rgba(255,${Math.round(125 + 45 * f)},${Math.round(138 + 40 * f)},${a.toFixed(3)})`);
                }
                g.filter = 'blur(3px)';
                g.setTransform(1, 0, 0, 0.5, 0, 32);
                g.fillStyle = gradient;
                g.fillRect(0, 0, 256, 256);
            } else {
                // Short parallel strokes leaning outwards, thick in the middle, fading at the ends.
                const lean = (side === 'R') === (this.doc.Rig.Head.Center[0] > (l + r) / 2) ? 1 : -1;
                g.lineCap = 'round';
                g.filter = 'blur(1.2px)';
                for (let i = 0; i < 4; i++) {
                    const x = 70 + i * 36;
                    const grad = g.createLinearGradient(x, 30, x + 18 * lean, 98);
                    grad.addColorStop(0, 'rgba(225,70,95,0)');
                    grad.addColorStop(0.5, 'rgba(225,70,95,0.7)');
                    grad.addColorStop(1, 'rgba(225,70,95,0)');
                    g.strokeStyle = grad;
                    g.lineWidth = 5;
                    g.beginPath();
                    g.moveTo(x - 9 * lean, 34);
                    g.lineTo(x + 9 * lean, 94);
                    g.stroke();
                }
            }
            const entry = {
                Id: `cheek_${side}${hatch ? '_hatch' : ''}`, Role: hatch ? 'cheek_hatch' : 'cheek', Side: side,
                X: (l + r) / 2 - w / 2, Y: b + (b - t) * 0.05, Width: w, Height: h, Grid: [2, 2],
            };
            const layer = this._makeLayer(entry, PIXI.Texture.from(canvas));
            // Line the blush up with the eyes: a drawn head is often tilted already, and the blush
            // should sit along the face, not level with the screen. Head tilt then turns it further.
            const angle = this._eyeLineAngle();
            if (angle) {
                const ox = entry.X + w / 2, oy = entry.Y + h / 2;
                const c = Math.cos(angle), s = Math.sin(angle);
                for (let k = 0; k < layer.rest.length; k += 2) {
                    const dx = layer.rest[k] - ox, dy = layer.rest[k + 1] - oy;
                    layer.rest[k] = ox + dx * c - dy * s;
                    layer.rest[k + 1] = oy + dx * s + dy * c;
                }
                layer.out.set(layer.rest);
            }
            layer.dz = ROLE_DEPTH.cheek;
            layer.head = true;
            if (!hatch && PIXI.BLEND_MODES?.MULTIPLY !== undefined) layer.mesh.blendMode = PIXI.BLEND_MODES.MULTIPLY;
            layer.mesh.alpha = 0;
            return layer;
        }

        /** The slant of the line through both eyes in the drawing (radians, 0 with one eye box). */
        _eyeLineAngle() {
            const eyes = this.doc.Rig.Eyes || {};
            if (!eyes.L || !eyes.R) return 0;
            const centre = (box) => [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
            let [ax, ay] = centre(eyes.L.Box);
            let [bx, by] = centre(eyes.R.Box);
            if (ax > bx) [ax, ay, bx, by] = [bx, by, ax, ay];
            const angle = Math.atan2(by - ay, Math.max(1, bx - ax));
            return clamp(angle, -0.6, 0.6);
        }

        async _loadJson(relative) {
            const inline = bundled(relative);
            if (inline) return inline;
            const response = await fetch(this.base + relative);
            if (!response.ok) throw new Error(`${LOG} can't load ${relative}`);
            return response.json();
        }

        // Expressions and motions (the Live2DModel calls the extension makes) ---------------
        async expression(id) {
            const list = this.internalModel.settings.expressions;
            if (!list.length) return false;
            let item;
            if (id === undefined) item = list[Math.floor(Math.random() * list.length)];
            else if (typeof id === 'number') item = list[id];
            else item = list.find(e => e.Name === id) ?? list[Number(id)];
            if (!item) return false;
            let expression = this._expressionCache.get(item.File);
            if (!expression) {
                expression = new Expression(await this._loadJson(item.File));
                this._expressionCache.set(item.File, expression);
            }
            const slot = PERSISTENT_SLOTS.find(prefix => String(item.Name).startsWith(prefix));
            if (slot) {
                // Outfits and accessories stay on while the emotions change.
                const state = this._slots[slot] || (this._slots[slot] = { now: null, old: null });
                state.old = state.now;
                state.now = { expression, start: this._time, name: item.Name };
                return true;
            }
            for (const active of this._expressions) if (active.fadeOutStart === undefined) active.fadeOutStart = this._time;
            this._expressions.push({ expression, start: this._time, name: item.Name });
            this._emotion = item.Name;
            return true;
        }

        async motion(group, index, priority) {
            const list = this.internalModel.settings.motions[group];
            if (!list || !list.length) return false;
            let i = index === undefined || index === null || index === 'random' ? Math.floor(Math.random() * list.length) : Number(index);
            if (!(i >= 0 && i < list.length)) i = 0;
            const entry = list[i];
            let motion = this._motionCache.get(entry.File);
            if (!motion) {
                motion = new Motion(await this._loadJson(entry.File), entry);
                this._motionCache.set(entry.File, motion);
            }
            for (const active of this._motions) {
                if (active.fadeOutStart === undefined && (group !== 'Idle' || active.group === 'Idle')) active.fadeOutStart = this._time;
            }
            this._motions.push({ motion, group, start: this._time });
            return true;
        }

        // Every frame -------------------------------------------------------------------------
        _tick() {
            if (!this.layers) return;
            // Real time, so a slow frame rate never slows blinks and motions down (the springs
            // sub-step); only a long pause (a hidden tab) is cut short.
            const dt = Math.min(0.5, this._ticker.deltaMS / 1000);
            this._update(dt);
        }

        _update(dt) {
            this._time += dt;
            this._computeParameters(dt);
            this._deform(dt);
        }

        _computeParameters(dt) {
            const core = this.core;
            const values = core.values;
            values.set(core.defaults);
            const touched = new Set();
            const now = this._time;

            // Idle in the background when nothing else plays.
            const idle = this.internalModel.settings.motions.Idle;
            const reacting = this._motions.some(m => m.group !== 'Idle' && m.fadeOutStart === undefined);
            if (idle && idle.length && !reacting && !this._motions.some(m => m.group === 'Idle' && m.fadeOutStart === undefined) && !this._idleLoading) {
                this._idleLoading = true;
                this.motion('Idle').finally(() => (this._idleLoading = false));
            }

            // Motions, oldest first, each blended over what came before.
            this._motions = this._motions.filter(active => {
                const m = active.motion;
                const t = now - active.start;
                if (!m.loop && t > m.duration) return false;
                if (active.fadeOutStart !== undefined && now - active.fadeOutStart > m.fadeOut) return false;
                return true;
            });
            // The idle loop goes underneath whatever else plays.
            const ordered = [...this._motions.filter(a => a.group === 'Idle'), ...this._motions.filter(a => a.group !== 'Idle')];
            for (const active of ordered) {
                const m = active.motion;
                const t = now - active.start;
                const local = m.loop ? t % m.duration : t;
                let weight = m.fadeIn > 0 ? clamp(t / m.fadeIn, 0, 1) : 1;
                if (!m.loop && m.fadeOut > 0) weight *= clamp((m.duration - t) / m.fadeOut, 0, 1);
                if (active.fadeOutStart !== undefined) weight *= m.fadeOut > 0 ? clamp(1 - (now - active.fadeOutStart) / m.fadeOut, 0, 1) : 0;
                weight = smoothstep(0, 1, weight);
                for (const curve of m.curves) {
                    const i = core.getParameterIndex(curve.id);
                    if (i < 0) continue;
                    values[i] = lerp(values[i], Motion.evaluate(curve.segments, local), weight);
                    touched.add(i);
                }
            }

            // Expressions on top: the newest fades in while the older ones fade out.
            this._expressions = this._expressions.filter(active => active.fadeOutStart === undefined || now - active.fadeOutStart < active.expression.fadeOut);
            for (const active of this._expressions) {
                const e = active.expression;
                let weight = e.fadeIn > 0 ? clamp((now - active.start) / e.fadeIn, 0, 1) : 1;
                if (active.fadeOutStart !== undefined) weight *= e.fadeOut > 0 ? clamp(1 - (now - active.fadeOutStart) / e.fadeOut, 0, 1) : 0;
                weight = smoothstep(0, 1, weight);
                for (const p of e.parameters) {
                    const i = core.getParameterIndex(p.id);
                    if (i < 0) continue;
                    if (p.blend === 'Multiply') values[i] *= lerp(1, p.value, weight);
                    else if (p.blend === 'Overwrite') values[i] = lerp(values[i], p.value, weight);
                    else values[i] += p.value * weight;
                    touched.add(i);
                }
            }

            // The outfit, over everything (Overwrite), cross-fading from the one before.
            const applyOutfit = (active, weight) => {
                for (const p of active.expression.parameters) {
                    const i = core.getParameterIndex(p.id);
                    if (i >= 0) values[i] = lerp(values[i], p.value, weight);
                }
            };
            for (const state of Object.values(this._slots)) {
                if (!state.now) continue;
                const e = state.now.expression;
                const weight = smoothstep(0, 1, e.fadeIn > 0 ? clamp((now - state.now.start) / e.fadeIn, 0, 1) : 1);
                if (state.old && weight < 1) applyOutfit(state.old, 1);
                else state.old = null;
                applyOutfit(state.now, weight);
            }

            // Ease every value towards where the motions and expressions put it (a critically damped
            // spring), so expression changes glide and overlapping fades never jump.
            if (!this._eased || this._eased.length !== values.length || dt <= 0) {
                this._eased = Float32Array.from(values);
                this._easedVelocity = new Float32Array(values.length);
            } else {
                const omega = 2 / EASE_TIME;
                const f = 1 + 2 * dt * omega;
                const oo = omega * omega;
                const hoo = dt * oo;
                const hhoo = dt * hoo;
                const inv = 1 / (f + hhoo);
                const x = this._eased, v = this._easedVelocity;
                for (let i = 0; i < values.length; i++) {
                    const target = values[i];
                    const nx = (f * x[i] + dt * v[i] + hhoo * target) * inv;
                    v[i] = (v[i] + hoo * (target - x[i])) * inv;
                    x[i] = nx;
                    values[i] = nx;
                }
            }

            // Blinking and breathing.
            const blink = this._autoBlink(dt);
            for (const id of ['ParamEyeLOpen', 'ParamEyeROpen']) {
                const i = core.getParameterIndex(id);
                if (i >= 0) values[i] *= blink;
            }
            const breath = core.getParameterIndex(this.internalModel.idParamBreath || 'ParamBreath');
            if (breath >= 0 && !touched.has(breath)) values[breath] = 0.5 + 0.5 * Math.sin(now * (2 * Math.PI / 3.6));

            // Cursor.
            const f = this._focus;
            const ease = 1 - Math.exp(-dt * 6);
            f.x += (f.tx - f.x) * ease;
            f.y += (f.ty - f.y) * ease;
            const im = this.internalModel;
            const addFocus = (id, amount) => {
                if (!id || id === 'none') return;
                const i = core.getParameterIndex(id);
                if (i >= 0) values[i] += amount;
            };
            addFocus(im.idParamAngleX, f.x * 30);
            addFocus(im.idParamAngleY, f.y * 30);
            addFocus(im.idParamAngleZ, f.x * f.y * -30);
            addFocus(im.idParamBodyAngleX, f.x * 10);
            addFocus(im.idParamEyeBallX, f.x);
            addFocus(im.idParamEyeBallY, f.y);

            // Lip sync and other short offsets, then values set by hand.
            const wall = performance.now();
            for (const [i, add] of core.adds) {
                if (wall - add.time > 160) core.adds.delete(i);
                else values[i] += add.value;
            }
            for (const [i, value] of core.overrides) values[i] = value;
            // The pose the user dragged the skeleton into, on top of whatever plays.
            for (const [id, offset] of this._pose) {
                const i = core.getParameterIndex(id);
                if (i >= 0) values[i] += offset;
            }
            for (let i = 0; i < values.length; i++) values[i] = clamp(values[i], core.mins[i], core.maxs[i]);
        }

        _autoBlink(dt) {
            const b = this._blink;
            if (b.phase < 0) {
                b.next -= dt;
                if (b.next <= 0) b.phase = 0;
                return 1;
            }
            b.phase += dt;
            const closing = 0.08, closed = 0.05, opening = 0.12;
            let open;
            if (b.phase < closing) open = 1 - b.phase / closing;
            else if (b.phase < closing + closed) open = 0;
            else if (b.phase < closing + closed + opening) open = (b.phase - closing - closed) / opening;
            else {
                b.phase = -1;
                b.next = 2.5 + Math.random() * 4 + (Math.random() < 0.15 ? -2.2 : 0); // now and then a quick double blink
                open = 1;
            }
            return open;
        }

        _hairSwing(key, target, dt, spring) {
            const physics = this.doc.Rig.Physics || {};
            const k = spring?.stiffness ?? physics.stiffness ?? 18;
            const d = spring?.damping ?? physics.damping ?? 5.5;
            const state = this._hair[key] || (this._hair[key] = { x: target, v: 0 });
            const steps = Math.max(1, Math.ceil(dt / 0.008));
            const h = dt / steps;
            for (let s = 0; s < steps; s++) {
                const a = k * (target - state.x) - d * state.v;
                state.v += a * h;
                state.x += state.v * h;
            }
            return state.x;
        }

        /** A 2D spring that follows (ax, ay) with a lag: returns the lag (how far the soft part trails). */
        _softSpring(key, ax, ay, dt, k, d) {
            const state = this._soft[key] || (this._soft[key] = { x: ax, y: ay, vx: 0, vy: 0 });
            const steps = Math.max(1, Math.ceil(dt / 0.006));
            const h = dt / steps;
            for (let s = 0; s < steps; s++) {
                state.vx += (k * (ax - state.x) - d * state.vx) * h;
                state.vy += (k * (ay - state.y) - d * state.vy) * h;
                state.x += state.vx * h;
                state.y += state.vy * h;
            }
            return [state.x - ax, state.y - ay];
        }

        /** The mouse's pull: follows the pointer while dragging, springs back (and wobbles) after. */
        _dragStep(dt) {
            const d = this._drag;
            const spring = (this.doc.Rig.Physics || {}).drag || {};
            const k = d.active ? 260 : (spring.stiffness ?? 110);
            const c = d.active ? 32 : (spring.damping ?? 5);
            const steps = Math.max(1, Math.ceil(dt / 0.006));
            const h = dt / steps;
            for (let s = 0; s < steps; s++) {
                d.vx += (k * (d.tx - d.x) - c * d.vx) * h;
                d.vy += (k * (d.ty - d.y) - c * d.vy) * h;
                d.x += d.vx * h;
                d.y += d.vy * h;
            }
            return Math.abs(d.x) + Math.abs(d.y) + Math.abs(d.vx) + Math.abs(d.vy) > 0.05;
        }

        _deform(dt) {
            const P = (id) => this.core.getParameterValueById(id);
            const rig = this.doc.Rig;
            const S = rig.Strength || {};
            const head = rig.Head;
            const body = rig.Body;
            const [fl, ft, fr, fb] = head.Box;
            const faceW = fr - fl;
            const faceH = fb - ft;
            const [cx, cy] = head.Center;
            const [px, py] = head.Pivot;
            const r = Math.max(1, head.Radius);
            const ax = P('ParamAngleX') / 30;
            const ay = P('ParamAngleY') / 30;
            const tilt = (P('ParamAngleZ') * (S.tilt ?? 0.35)) * Math.PI / 180;
            const bodyTilt = (P('ParamBodyAngleZ') * (S.body ?? 0.35)) * Math.PI / 180;
            const bx = P('ParamBodyAngleX') / 10;
            const by = P('ParamBodyAngleY') / 10;
            const breath = P('ParamBreath');
            const [bpx, bpy] = body.Pivot;
            const top = Math.min(ft, body.Box[1]);
            const bodyH = Math.max(1, bpy - top);
            const chest = body.Chest ?? (body.Box[1] + (body.Box[3] - body.Box[1]) * 0.25);
            const turn = (S.turn ?? 0.1) * faceW;
            const nod = (S.nod ?? 0.07) * faceH;
            const parallax = S.parallax ?? 0.9;
            const cosT = Math.cos(tilt), sinT = Math.sin(tilt);
            const cosB = Math.cos(bodyTilt), sinB = Math.sin(bodyTilt);
            const hairSwing = {
                front_hair: this._hairSwing('front', -ax * 0.7 - P('ParamAngleZ') / 30 * 0.9 - bx * 0.3 + P('ParamHairFront') + 0.12 * Math.sin(this._time * 1.3), dt),
                back_hair: this._hairSwing('back', -ax * 0.9 - P('ParamAngleZ') / 30 * 1.1 - bx * 0.5 + P('ParamHairBack') + 0.15 * Math.sin(this._time * 1.1 + 1), dt),
            };
            const hairReach = (S.hair ?? 0.06) * faceW;
            const mouth = rig.Mouth;
            const mouthOpen = P('ParamMouthOpenY');
            const mouthForm = P('ParamMouthForm');
            const hasMouthOpen = this.layers.some(l => l.role === 'mouth_open');
            const closedSides = new Set(this.layers.filter(l => l.role === 'eye_closed').map(l => l.side || 'LR'));
            // Drawn pieces for the strongest emotions: angry brows, a grin, tears (each over what it replaces).
            const hasArt = (role) => this.layers.some(l => l.role === role);
            const angry = hasArt('brow_angry') ? smoothstep(0.1, 0.7, P('ParamBrowAngry')) : 0;
            const grin = hasArt('mouth_grin') ? smoothstep(0.1, 0.7, P('ParamMouthGrin')) : 0;
            const tears = smoothstep(0.05, 0.6, P('ParamTear'));
            const outer = this._hasBody ? P('ParamClothesOuter') : 1;
            const inner = P('ParamClothesInner');

            // Where the body moves a point to (lean, turn, breathing, tilt): used for the vertices and
            // to drive the soft parts, which trail behind that movement.
            const bodyMove = (rx, ry, x, y) => {
                const up = clamp((bpy - ry) / bodyH, 0, 1);
                x += bx * 0.025 * bodyH * up;
                y += by * 0.012 * bodyH * up;
                y -= breath * (S.breath ?? 0.012) * bodyH * clamp((bpy - ry) / Math.max(1, bpy - chest), 0, 1);
                if (bodyTilt) {
                    const dx = x - bpx, dy = y - bpy;
                    x = bpx + dx * cosB - dy * sinB;
                    y = bpy + dx * sinB + dy * cosB;
                }
                return [x, y];
            };

            // Soft body: each bust and hip centre trails the body's movement on a bouncy spring.
            const softPhysics = (rig.Physics || {}).soft || {};
            const softRegions = [];
            for (const name of ['Bust', 'Hips']) {
                const region = rig[name];
                const gain = name === 'Bust' ? (S.bust ?? 1) : (S.hips ?? 1);
                if (!region || !(region.Radius?.[0] > 0) || gain <= 0) continue;
                const [rx, ry] = region.Radius;
                const param = name === 'Bust' ? ['ParamBustX', 'ParamBustY'] : ['ParamHipX', 'ParamHipY'];
                region.Centers.forEach(([cx0, cy0], index) => {
                    const [ax, ay] = bodyMove(cx0, cy0, cx0, cy0);
                    // Breathing lifts the bust a touch more, so it never sits perfectly still.
                    const lift = name === 'Bust' ? -breath * ry * 0.04 : 0;
                    const k = (softPhysics.stiffness ?? 75) * (name === 'Hips' ? 0.7 : 1) * (index ? 1.06 : 1);
                    const c = (softPhysics.damping ?? 3) * (name === 'Hips' ? 1.2 : 1);
                    let [ox, oy] = this._softSpring(`${name}${index}`, ax, ay + lift, dt, k, c);
                    ox = clamp(ox * 3 * gain, -rx * 0.3, rx * 0.3) + P(param[0]) * rx * 0.18;
                    oy = clamp(oy * 3 * gain, -ry * 0.3, ry * 0.3) - P(param[1]) * ry * 0.18;
                    softRegions.push({ cx: cx0, cy: cy0, rx, ry, ox, oy });
                });
            }

            // Cloth: skirt hems and ribbons swing behind the body like hair, a little heavier.
            const bodyW = Math.max(1, body.Box[2] - body.Box[0]);
            const clothSwing = (rig.Cloth || []).length
                ? this._hairSwing('cloth', -bx * 0.9 - P('ParamBodyAngleZ') / 10 * 0.7 + 0.08 * Math.sin(this._time * 0.9), dt, (rig.Physics || {}).cloth)
                : 0;
            const clothReach = (S.cloth ?? 0.05) * bodyW;

            // The mouse's pull, strongest where the drag started.
            const dragging = this._dragStep(dt);
            const drag = this._drag;
            const sigma = faceH * (drag.soft ? 0.4 : 0.32);
            const twoSigma2 = 2 * sigma * sigma;

            for (const layer of this.layers) {
                const { role, side, rest, out } = layer;
                const eyeKey = side && rig.Eyes[side] ? side : (rig.Eyes.LR ? 'LR' : side);
                const eye = rig.Eyes[eyeKey];
                const rawOpen = eyeKey === 'LR' ? (P('ParamEyeLOpen') + P('ParamEyeROpen')) / 2 : P(`ParamEye${side}Open`);
                const eyeSmile = clamp(eyeKey === 'LR' ? (P('ParamEyeLSmile') + P('ParamEyeRSmile')) / 2 : P(`ParamEye${side}Smile`), 0, 1);
                const hasClosed = closedSides.has(side || 'LR') || closedSides.has('LR');
                // With closed-eye art, a smile closes the eyes into arcs (^ ^) instead of squashing
                // the open eye, which smears its lashes.
                const eyeOpen = hasClosed ? Math.min(rawOpen, 1) * (1 - 0.92 * eyeSmile) + Math.max(0, rawOpen - 1) : rawOpen;

                // Opacity from the switches.
                let alpha = 1;
                // A quick cross-fade between the open eye and the closed art (a blink lasts a tenth of a
                // second, so the swap reads as the lid closing).
                if (role === 'eye_closed') alpha = 1 - smoothstep(0.2, 0.42, eyeOpen);
                else if (role === 'eye_white' || role === 'iris') alpha = hasClosed ? smoothstep(0.22, 0.4, eyeOpen) : smoothstep(0.02, 0.2, eyeOpen);
                else if (role === 'eyelash' || role === 'eyes') alpha = hasClosed ? smoothstep(0.2, 0.42, eyeOpen) : 1;
                else if (role === 'mouth') alpha = (hasMouthOpen ? 1 - smoothstep(0.15, 0.55, mouthOpen) : 1) * (1 - grin);
                else if (role === 'mouth_open') alpha = smoothstep(0.15, 0.55, mouthOpen);
                else if (role === 'mouth_grin') alpha = grin * (hasMouthOpen ? 1 - smoothstep(0.15, 0.55, mouthOpen) : 1);
                else if (role === 'brow') alpha = 1 - angry;
                else if (role === 'brow_angry') alpha = angry;
                else if (role === 'eye_tears') alpha = tears * (hasClosed ? smoothstep(0.2, 0.42, eyeOpen) : smoothstep(0.02, 0.2, eyeOpen));
                else if (role === 'cheek') alpha = clamp(P('ParamCheek'), 0, 1) * 0.85;
                else if (role === 'cheek_hatch') alpha = smoothstep(0.35, 0.85, P('ParamCheek')) * 0.8;
                else if (OUTER_ROLES.has(role)) alpha = clamp(outer, 0, 1);
                else if (role === 'inner') alpha = clamp(inner, 0, 1);
                // One piece of the clothes on its own (half off), and the accessories.
                // Koikatsu-style slots: 1 on, 0.5 half off (with half-off art), 0 off. Without a body
                // layer only the coat can come off (the clothes under it are drawn).
                const sw = layer.entry.Switch;
                if (sw && (this._hasBody || sw === 'ParamClothesCoat')) {
                    const v = P(sw);
                    if (layer.entry.State === 'half') alpha *= smoothstep(0.1, 0.35, v) * (1 - smoothstep(0.65, 0.9, v));
                    else if (this._halfSwitches.has(sw)) alpha *= smoothstep(0.65, 0.9, v);
                    else alpha *= clamp(v, 0, 1);
                } else if (layer.entry.State === 'half') alpha = 0;
                if (layer.entry.Accessory) alpha *= clamp(P('ParamAccessories'), 0, 1);
                layer.mesh.alpha = alpha;
                layer.mesh.visible = alpha > 0.003;
                if (!layer.mesh.visible) continue;

                for (let k = 0; k < rest.length; k += 2) {
                    let x = rest[k];
                    let y = rest[k + 1];

                    // Features ---------------------------------------------------------
                    if (eye && EYE_ROLES.has(role)) {
                        const [el, et, er, eb] = eye.Box;
                        const eh = eb - et;
                        // The lid comes down a little before the swap to the closed art; without that
                        // art the eye has to close by squashing.
                        const scale = eyeOpen <= 1 ? (hasClosed ? 0.55 + 0.45 * eyeOpen : 0.1 + 0.9 * eyeOpen) : eyeOpen;
                        y = eye.Lid + (y - eye.Lid) * scale;
                        if (!hasClosed) y -= eyeSmile * 0.35 * eh * clamp((rest[k + 1] - et) / Math.max(1, eh), 0, 1);
                        if (role === 'iris') {
                            x += P('ParamEyeBallX') * (S.eyeball ?? 0.14) * (er - el);
                            y -= P('ParamEyeBallY') * (S.eyeball ?? 0.14) * 0.8 * eh;
                        }
                    } else if (role === 'eye_closed' && eye && eyeSmile > 0) {
                        // A smile bends the closed lid into an arc, highest in the middle.
                        const [el, et, er, eb] = eye.Box;
                        const n = clamp((x - (el + er) / 2) / Math.max(1, (er - el) / 2), -1, 1);
                        y -= eyeSmile * 0.3 * (eb - et) * (1 - n * n);
                    } else if ((role === 'brow' || role === 'brow_angry') && eye) {
                        const [el, et, er, eb] = eye.Box;
                        const eh = eb - et;
                        const brow = eye.Brow || eye.Box;
                        const bw = Math.max(1, brow[2] - brow[0]);
                        // +1 at the inner end (towards the middle of the face), -1 at the outer end.
                        const inner = clamp(((x - (brow[0] + brow[2]) / 2) / (bw / 2)) * Math.sign(cx - (brow[0] + brow[2]) / 2 || 1), -1, 1);
                        const n = clamp((x - (brow[0] + brow[2]) / 2) / (bw / 2), -1, 1);
                        y -= P(`ParamBrow${side}Y`) * (S.brow ?? 0.35) * eh;
                        y += P(`ParamBrow${side}Angle`) * 0.22 * eh * inner;
                        y -= P(`ParamBrow${side}Form`) * 0.15 * eh * (1 - n * n);
                    } else if ((role === 'mouth' || role === 'mouth_open') && mouth) {
                        const [ml, mt, mr, mb] = mouth.Box;
                        const mw = Math.max(1, mr - ml);
                        const [mcx, mcy] = mouth.Center;
                        const n = clamp((x - mcx) / (mw / 2), -1.2, 1.2);
                        if (role === 'mouth') y = mcy + (y - mcy) * (1 + (hasMouthOpen ? 1.5 : 4) * mouthOpen);
                        else y = mcy + (y - mcy) * (0.3 + 0.7 * mouthOpen);
                        y -= mouthForm * (S.mouth_form ?? 0.35) * mw * 0.3 * (n * n - 0.35);
                    }

                    // Hair and cloth sway ----------------------------------------------
                    let sway = 1;
                    if (layer.hair) {
                        const t = clamp((rest[k + 1] - layer.hair.Root) / layer.hair.Length, 0, 1);
                        x += hairSwing[role] * hairReach * t * t;
                        sway = t;
                    }
                    if (layer.cloth) {
                        const t = clamp((rest[k + 1] - layer.cloth.Root) / layer.cloth.Length, 0, 1);
                        x += clothSwing * clothReach * t * t;
                    }

                    // Soft body jiggle ------------------------------------------------------
                    const soft = SOFT_ROLES.has(role);
                    if (soft) {
                        for (const region of softRegions) {
                            const dx = (rest[k] - region.cx) / region.rx;
                            const dy = (rest[k + 1] - region.cy) / region.ry;
                            const d2 = dx * dx + dy * dy;
                            if (d2 >= 1) continue;
                            const w = (1 - d2) * (1 - d2);
                            x += region.ox * w;
                            // Bouncing up stretches it a little, landing squashes it.
                            y += region.oy * w + (rest[k + 1] - region.cy) * (region.oy / region.ry) * 0.25 * w;
                        }
                    }

                    // The mouse's pull ---------------------------------------------------------
                    if (dragging && soft) {
                        const ddx = rest[k] - drag.sx;
                        const ddy = rest[k + 1] - drag.sy;
                        const w = Math.exp(-(ddx * ddx + ddy * ddy) / twoSigma2) * (layer.hair ? sway : 1);
                        x += drag.x * w;
                        y += drag.y * w;
                    }

                    // Head turn, nod and tilt -------------------------------------------
                    if (layer.head) {
                        let w = 1;
                        if (role === 'neck') w = clamp(1 - (rest[k + 1] - (py - r * 0.2)) / Math.max(1, r * 0.8), 0, 1) * 0.6;
                        else if (role === 'back_hair' || role === 'front_hair') w = rest[k + 1] <= py ? 1 : lerp(1, role === 'back_hair' ? 0.25 : 0.5, smoothstep(py, py + r * 1.5, rest[k + 1]));
                        const nx = clamp((rest[k] - cx) / r, -1, 1);
                        const ny = clamp((rest[k + 1] - cy) / r, -1, 1);
                        const depth = 1 + parallax * layer.dz;
                        x += ax * turn * (1 - 0.5 * nx * nx) * depth * w;
                        y -= ay * nod * (1 - 0.5 * ny * ny) * depth * w;
                        if (tilt) {
                            const dx = x - px, dy = y - py;
                            const c = lerp(1, cosT, w), s = sinT * w;
                            x = px + dx * c - dy * s;
                            y = py + dx * s + dy * c;
                        }
                    }

                    // Posed arms: turn at the shoulder, the upper end staying attached ----
                    if (role === 'arm' && rig.Arms) {
                        const arm = rig.Arms[side] || rig.Arms.LR;
                        const degrees = arm ? P(`ParamArm${side || 'L'}A`) : 0;
                        if (degrees) {
                            const [ax0, ay0] = arm.Pivot;
                            const w = smoothstep(arm.Length * 0.04, arm.Length * 0.25, Math.hypot(rest[k] - ax0, rest[k + 1] - ay0));
                            const angle = degrees * Math.PI / 180 * w;
                            const ddx = x - ax0, ddy = y - ay0;
                            x = ax0 + ddx * Math.cos(angle) - ddy * Math.sin(angle);
                            y = ay0 + ddx * Math.sin(angle) + ddy * Math.cos(angle);
                        }
                    }

                    // Body: lean, turn and breathing ------------------------------------
                    [x, y] = bodyMove(rest[k], rest[k + 1], x, y);
                    out[k] = x;
                    out[k + 1] = y;
                }
            }
        }

        destroy(options) {
            LIVE.delete(this);
            this._ticker?.remove(this._tick, this);
            window.removeEventListener('pointermove', this._onPointerMove);
            super.destroy(options);
            this.layers = null;
            this.internalModel = undefined;
        }
    }
    return Puppet;
}

function puppetClass() {
    if (!PuppetClass) {
        if (!window.PIXI) throw new Error(`${LOG} PixiJS isn't loaded`);
        PuppetClass = definePuppetClass(window.PIXI);
    }
    return PuppetClass;
}

/** Load a puppet: `await PuppetModel.from(url)`. */
export const PuppetModel = {
    from: (source) => puppetClass().from(source),
};

/**
 * Make Live2DModel.from() load puppets too, so the SillyTavern Live2D extension plays them.
 * Waits for the extension's PixiJS and Live2D libraries, which may load after this script.
 */
export function installPuppetLoader({ timeout = 300000 } = {}) {
    const started = Date.now();
    const hook = () => {
        const Live2DModel = window.PIXI?.live2d?.Live2DModel;
        if (!Live2DModel) {
            if (Date.now() - started < timeout) setTimeout(hook, 250);
            return;
        }
        if (Live2DModel.from.__autoexpressPuppet) return;
        const original = Live2DModel.from.bind(Live2DModel);
        const from = function (source, ...rest) {
            if (isPuppetPath(source)) return puppetClass().from(source);
            return original(source, ...rest);
        };
        from.__autoexpressPuppet = true;
        Live2DModel.from = from;
        // The puppet looks up the renderer to follow the cursor on the right canvas.
        const Application = window.PIXI.Application;
        if (Application && !Application.prototype.__autoexpressPuppet) {
            const render = Application.prototype.render;
            Application.prototype.render = function (...args) {
                this.stage._puppetRenderer = this.renderer;
                return render.apply(this, args);
            };
            Application.prototype.__autoexpressPuppet = true;
        }
        console.log(LOG, 'Live2D models can now be AutoExpress puppets.');
    };
    hook();
}
