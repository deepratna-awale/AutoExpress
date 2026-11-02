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
 * worked out (defaults, then motions, expressions, blinking and breathing, cursor, lip sync,
 * values set by hand) and every layer's mesh is bent from them.
 *
 * Needs window.PIXI (v6). Nothing else.
 */

const FORMAT = 'AutoExpress Puppet';
const SUFFIX = '.puppet.model.json';
const LOG = '[AutoExpress puppet]';

// How far in front of the face each role sits, for the head-turn parallax (face = 0).
const ROLE_DEPTH = {
    front_hair: 0.75, headwear: 0.65, nose: 0.6, eyewear: 0.6, brow: 0.45, mouth: 0.45, mouth_open: 0.45,
    eyelash: 0.4, eye_closed: 0.4, eyes: 0.4, iris: 0.35, eye_white: 0.35, cheek: 0.25, face: 0,
    ear: -0.3, back_hair: -0.45,
};
const HEAD_ROLES = new Set(Object.keys(ROLE_DEPTH));
const EYE_ROLES = new Set(['eye_white', 'iris', 'eyelash', 'eyes']);
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

function definePuppetClass(PIXI) {
    class Puppet extends PIXI.Container {
        static async from(source) {
            const url = new URL(source, document.baseURI).href;
            const response = await fetch(url);
            if (!response.ok) throw new Error(`${LOG} can't load ${source}: ${response.status}`);
            const document_ = await response.json();
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
            this.on('pointertap', (event) => {
                const hits = this.hitTest(event.data.global.x, event.data.global.y);
                if (hits.length) this.emit('hit', hits);
            });

            this._ticker = PIXI.Ticker.shared;
            this._ticker.add(this._tick, this);
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
                const texture = await PIXI.Texture.fromURL(this.base + entry.Texture);
                this.layers.push(this._makeLayer(entry, texture));
                if (index === cheekAfter) {
                    for (const side of Object.keys(rig.Eyes || {})) this.layers.push(this._makeCheek(side));
                }
                index += 1;
            }
            for (const layer of this.layers) this.addChild(layer.mesh);
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
            return {
                entry,
                role: entry.Role,
                side: entry.Side,
                mesh,
                rest,
                out: mesh.vertices,
                hair,
                dz: ROLE_DEPTH[entry.Role] ?? 0,
                head: HEAD_ROLES.has(entry.Role) || entry.Role === 'neck',
            };
        }

        _makeCheek(side) {
            const eye = this.doc.Rig.Eyes[side];
            const [l, t, r, b] = eye.Box;
            const w = (r - l) * 1.15;
            const h = (b - t) * 0.55;
            const canvas = document.createElement('canvas');
            canvas.width = 128;
            canvas.height = 64;
            const g = canvas.getContext('2d');
            const gradient = g.createRadialGradient(64, 32, 2, 64, 32, 62);
            gradient.addColorStop(0, 'rgba(255,110,130,0.85)');
            gradient.addColorStop(1, 'rgba(255,110,130,0)');
            g.setTransform(1, 0, 0, 0.5, 0, 16);
            g.fillStyle = gradient;
            g.fillRect(0, 0, 128, 128);
            const entry = {
                Id: `cheek_${side}`, Role: 'cheek', Side: side,
                X: (l + r) / 2 - w / 2, Y: b + (b - t) * 0.15, Width: w, Height: h, Grid: [2, 2],
            };
            const layer = this._makeLayer(entry, PIXI.Texture.from(canvas));
            layer.mesh.alpha = 0;
            return layer;
        }

        async _loadJson(relative) {
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
            for (const active of this._expressions) if (active.fadeOutStart === undefined) active.fadeOutStart = this._time;
            this._expressions.push({ expression, start: this._time, name: item.Name });
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
            const dt = Math.min(0.1, this._ticker.deltaMS / 1000);
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
            if (idle && idle.length && !this._motions.some(m => m.group === 'Idle' && m.fadeOutStart === undefined) && !this._idleLoading) {
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
            for (const active of this._motions) {
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

        _hairSwing(key, target, dt) {
            const physics = this.doc.Rig.Physics || {};
            const k = physics.stiffness ?? 18;
            const d = physics.damping ?? 5.5;
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

            for (const layer of this.layers) {
                const { role, side, rest, out } = layer;
                const eyeKey = side && rig.Eyes[side] ? side : (rig.Eyes.LR ? 'LR' : side);
                const eye = rig.Eyes[eyeKey];
                const eyeOpen = eyeKey === 'LR' ? (P('ParamEyeLOpen') + P('ParamEyeROpen')) / 2 : P(`ParamEye${side}Open`);
                const eyeSmile = eyeKey === 'LR' ? (P('ParamEyeLSmile') + P('ParamEyeRSmile')) / 2 : P(`ParamEye${side}Smile`);
                const hasClosed = closedSides.has(side || 'LR') || closedSides.has('LR');

                // Opacity from the switches.
                let alpha = 1;
                if (role === 'eye_closed') alpha = 1 - smoothstep(0.12, 0.45, eyeOpen);
                else if (role === 'eye_white' || role === 'iris') alpha = hasClosed ? smoothstep(0.08, 0.4, eyeOpen) : smoothstep(0.02, 0.2, eyeOpen);
                else if (role === 'eyelash' || role === 'eyes') alpha = hasClosed ? smoothstep(0.12, 0.45, eyeOpen) : 1;
                else if (role === 'mouth') alpha = hasMouthOpen ? 1 - smoothstep(0.15, 0.55, mouthOpen) : 1;
                else if (role === 'mouth_open') alpha = smoothstep(0.15, 0.55, mouthOpen);
                else if (role === 'cheek') alpha = clamp(P('ParamCheek'), 0, 1) * 0.55;
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
                        const scale = eyeOpen <= 1 ? 0.1 + 0.9 * eyeOpen : eyeOpen;
                        y = eye.Lid + (y - eye.Lid) * scale;
                        y -= eyeSmile * 0.35 * eh * clamp((rest[k + 1] - et) / Math.max(1, eh), 0, 1);
                        if (role === 'iris') {
                            x += P('ParamEyeBallX') * (S.eyeball ?? 0.14) * (er - el);
                            y -= P('ParamEyeBallY') * (S.eyeball ?? 0.14) * 0.8 * eh;
                        }
                    } else if (role === 'brow' && eye) {
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

                    // Hair sway --------------------------------------------------------
                    if (layer.hair) {
                        const t = clamp((rest[k + 1] - layer.hair.Root) / layer.hair.Length, 0, 1);
                        x += hairSwing[role] * hairReach * t * t;
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

                    // Body: lean, turn and breathing ------------------------------------
                    const up = clamp((bpy - rest[k + 1]) / bodyH, 0, 1);
                    x += bx * 0.025 * bodyH * up;
                    y += by * 0.012 * bodyH * up;
                    y -= breath * (S.breath ?? 0.012) * bodyH * clamp((bpy - rest[k + 1]) / Math.max(1, bpy - chest), 0, 1);
                    if (bodyTilt) {
                        const dx = x - bpx, dy = y - bpy;
                        x = bpx + dx * cosB - dy * sinB;
                        y = bpy + dx * sinB + dy * cosB;
                    }
                    out[k] = x;
                    out[k + 1] = y;
                }
            }
        }

        destroy(options) {
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
