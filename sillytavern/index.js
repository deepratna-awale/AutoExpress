/**
 * Emotica for SillyTavern.
 *
 * Makes a character's expression sprites from one image: the extension sends the
 * character's avatar (or another image) to the Emotica app, which repaints the
 * face on whatever WebUI it drives (A1111, Forge, SD.Next, ComfyUI, SwarmUI,
 * InvokeAI, local or remote), and uploads each finished expression into the
 * character's sprite folder as it arrives.
 *
 * Everything runs in the browser through the Emotica HTTP API, so the app must
 * allow SillyTavern's address (EMOTICA_CORS_ORIGINS, which includes
 * http://localhost:8000 and http://127.0.0.1:8000 by default).
 */

import { installPuppetLoader, livePuppets } from '../emotica_core/resources/puppet.js';

const MODULE = 'emotica';
const LOG_PREFIX = '[Emotica]';
const POLL_MS = 1500;

/** SillyTavern's built-in expression labels (the same 28 Emotica generates). */
const EXPRESSIONS = [
    'admiration', 'amusement', 'anger', 'annoyance', 'approval', 'caring', 'confusion',
    'curiosity', 'desire', 'disappointment', 'disapproval', 'disgust', 'embarrassment', 'excitement',
    'fear', 'gratitude', 'grief', 'joy', 'love', 'nervousness', 'neutral',
    'optimism', 'pride', 'realization', 'relief', 'remorse', 'sadness', 'surprise',
];

const DEFAULT_SETTINGS = Object.freeze({
    url: 'http://127.0.0.1:5000',
    family: 'auto',
    method: '',
    checkpoint: '',
    customIntensity: false,
    intensity: 0.5,
    removeBackground: false,
    pose: false,
    animate: false,
    prompt: '',
    onlyMissing: false,
    keepExisting: false,
    selected: [...EXPRESSIONS],
});

/** The job being generated, if any. One at a time, since the WebUI renders one image at a time anyway. */
let activeJob = null;
/** True while the dialog is loading or open, so a second click doesn't open another one. */
let dialogOpen = false;

function ctx() {
    return SillyTavern.getContext();
}

function settings() {
    const all = ctx().extensionSettings;
    all[MODULE] = Object.assign({}, structuredClone(DEFAULT_SETTINGS), all[MODULE] || all.autoexpress || {});  // autoexpress: settings saved under the former name
    return all[MODULE];
}

function save() {
    ctx().saveSettingsDebounced();
}

function escapeHtml(text) {
    return String(text ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', '\'': '&#39;' }[c]));
}

function titleCase(label) {
    return label.charAt(0).toUpperCase() + label.slice(1);
}

// Emotica API --------------------------------------------------------------

class EmoticaError extends Error {
    constructor(message, { status = 0, code = '', fix = null } = {}) {
        super(message);
        this.status = status;
        this.code = code;
        this.fix = fix;
    }
}

function serverUrl() {
    return String(settings().url || DEFAULT_SETTINGS.url).trim().replace(/\/+$/, '');
}

async function api(path, { method = 'GET', json, body, raw = false } = {}) {
    const init = { method, headers: {} };
    if (json !== undefined) {
        init.headers['Content-Type'] = 'application/json';
        init.body = JSON.stringify(json);
    } else if (body !== undefined) {
        init.body = body;
    }

    let response;
    try {
        response = await fetch(serverUrl() + path, init);
    } catch (error) {
        throw new EmoticaError(
            `Can't reach Emotica at ${serverUrl()}. Start it (python -m emotica, run.sh/run.bat or Docker) and check that it allows this page's address, ${location.origin}, in EMOTICA_CORS_ORIGINS.`,
            { code: 'unreachable' },
        );
    }
    if (raw) {
        if (!response.ok) throw new EmoticaError(`Emotica answered ${response.status} for ${path}.`, { status: response.status });
        return response;
    }

    let data = null;
    try {
        data = await response.json();
    } catch {
        data = null;
    }
    if (!response.ok) {
        const error = data?.error;
        const message = (typeof error === 'object' ? error?.message : error) || data?.message || `Emotica answered ${response.status} for ${path}.`;
        throw new EmoticaError(message, { status: response.status, code: error?.code || '', fix: error?.fix || null });
    }
    return data;
}

/** Steps from a WebUI capability "fix", as HTML. */
function fixHtml(fix) {
    if (!fix) return '';
    const steps = (fix.steps || []).map((step) => `<li>${escapeHtml(step)}</li>`).join('');
    const commands = (fix.commands || []).map((command) => `<code>${escapeHtml(command)}</code>`).join('<br>');
    const links = (fix.links || []).map((link) => `<a href="${escapeHtml(link.url)}" target="_blank" rel="noopener">${escapeHtml(link.label)}</a>`).join(' · ');
    return `${steps ? `<ol>${steps}</ol>` : ''}${commands ? `<div>${commands}</div>` : ''}${links ? `<div>${links}</div>` : ''}`;
}

function showError(error, title = 'Emotica') {
    console.error(LOG_PREFIX, error);
    const message = escapeHtml(error?.message || String(error));
    toastr.error(`${message}${fixHtml(error?.fix)}`, title, { escapeHtml: false, timeOut: 15000, extendedTimeOut: 30000 });
}

// SillyTavern side ------------------------------------------------------------

/** Characters to offer: the current chat's character(s) first, then everyone else. */
function characterChoices() {
    const context = ctx();
    const characters = context.characters || [];
    let current = [];
    if (context.groupId) {
        const group = (context.groups || []).find((g) => g.id === context.groupId);
        current = (group?.members || []).map((avatar) => characters.findIndex((c) => c.avatar === avatar)).filter((i) => i >= 0);
    } else if (context.characterId !== undefined && context.characterId !== null && characters[context.characterId]) {
        current = [Number(context.characterId)];
    }
    const rest = characters.map((_, i) => i).filter((i) => !current.includes(i));
    return { current, order: [...current, ...rest] };
}

/**
 * The sprite folder SillyTavern reads a character's expressions from: its folder
 * override (Character Expressions → "Override folder name") or else its name.
 */
function spriteFolder(character) {
    const avatarKey = String(character.avatar || '').replace(/\.[^/.]+$/, '');
    const override = (ctx().extensionSettings.expressionOverrides || []).find((o) => o.name === avatarKey);
    return override?.path ? override.path : character.name;
}

async function existingSprites(folder) {
    try {
        const response = await fetch(`/api/sprites/get?name=${encodeURIComponent(folder)}`, { headers: ctx().getRequestHeaders() });
        if (!response.ok) return [];
        return await response.json();
    } catch {
        return [];
    }
}

async function avatarBlob(character) {
    const response = await fetch(`/characters/${encodeURIComponent(character.avatar)}`, { cache: 'no-cache' });
    if (!response.ok) throw new Error(`Couldn't load ${character.name}'s avatar (${response.status}).`);
    return await response.blob();
}

function blobToDataUrl(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
    });
}

/**
 * Put one sprite into the character's folder. Uses the Character Expressions
 * extension's own upload (which also refreshes its sprite list) when it is loaded.
 */
async function uploadSprite(character, folder, label, spriteName, blob, extension = 'png') {
    const command = ctx().SlashCommandParser?.commands?.['expression-upload'];
    // The slash command saves every upload as .png, so animated sprites go straight to the upload API to keep .webp.
    if (command?.callback && extension === 'png') {
        const url = URL.createObjectURL(blob);
        try {
            const name = await command.callback({ name: character.avatar, label, folder, spriteName }, url);
            if (name) return;
        } finally {
            URL.revokeObjectURL(url);
        }
        throw new Error(`SillyTavern didn't accept the ${label} sprite.`);
    }

    const form = new FormData();
    form.append('name', folder);
    form.append('label', label);
    form.append('spriteName', spriteName);
    form.append('avatar', new File([blob], `${spriteName}.${extension}`, { type: blob.type || `image/${extension}` }));
    const response = await fetch('/api/sprites/upload', {
        method: 'POST',
        headers: ctx().getRequestHeaders({ omitContentType: true }),
        body: form,
    });
    if (!response.ok) throw new Error(`SillyTavern didn't accept the ${label} sprite (${response.status}).`);
}

// Connection status -------------------------------------------------------------

async function checkConnection({ quiet = false } = {}) {
    const status = $('#emotica_status');
    status.removeClass('ok warn error').html('<i class="fa-solid fa-spinner fa-spin"></i> Checking…');
    try {
        await api('/health');
    } catch (error) {
        status.addClass('error').html(`<i class="fa-solid fa-circle-xmark"></i> ${escapeHtml(error.message)}`);
        if (!quiet) showError(error);
        return null;
    }
    let report;
    try {
        report = await api('/backend/capabilities');
    } catch (error) {
        status.addClass('error').html(`<i class="fa-solid fa-circle-xmark"></i> Emotica is running, but: ${escapeHtml(error.message)}`);
        return null;
    }
    const where = `${escapeHtml(report.name)} at ${escapeHtml(report.url)}`;
    if (report.ready) {
        status.addClass('ok').html(`<i class="fa-solid fa-circle-check"></i> Connected to ${where}.`);
    } else {
        const missing = (report.items || []).filter((item) => item.required && !item.ok);
        const details = missing.map((item) => `<li><b>${escapeHtml(item.label)}</b>: ${escapeHtml(item.detail)}${fixHtml(item.fix)}</li>`).join('');
        const message = report.error?.message ? escapeHtml(report.error.message) : `missing ${escapeHtml((report.missing || []).join(', '))}`;
        status.addClass('warn').html(`<i class="fa-solid fa-triangle-exclamation"></i> ${where}: ${message}<ul>${details}</ul>`);
    }
    return report;
}

async function connectWebUI() {
    const webuiUrl = String($('#emotica_webui_url').val() || '').trim();
    if (!webuiUrl) {
        return checkConnection();
    }
    try {
        const result = await api('/receive_data', { method: 'POST', json: { text: webuiUrl, backend: 'auto' } });
        toastr.success(`Emotica now uses ${result.name} at ${result.url}.`, 'Emotica');
        $('#emotica_webui_url').val('');
    } catch (error) {
        showError(error, 'Connecting the WebUI');
    }
    return checkConnection({ quiet: true });
}

// Generate dialog -------------------------------------------------------------------

async function loadOptions() {
    const [families, methods, models, background, animation] = await Promise.all([
        api('/expression-families').catch(() => null),
        api('/edit-methods').catch(() => null),
        api('/get-models').catch(() => []),
        api('/background-removal').catch(() => null),
        api('/animation').catch(() => null),
    ]);
    return {
        families: families?.families || [],
        methods: (methods?.methods || []).filter((m) => m.available),
        models: Array.isArray(models) ? models.map((m) => (typeof m === 'string' ? m : m?.title || m?.model_name || m?.name)).filter(Boolean) : [],
        background: background?.available === true,
        animation: animation?.available === true,
    };
}

function dialogHtml(options, choices) {
    const characters = ctx().characters;
    const characterOptions = choices.order.map((i) => {
        const c = characters[i];
        const tag = choices.current.includes(i) ? ' (this chat)' : '';
        return `<option value="${i}">${escapeHtml(c.name)}${tag}</option>`;
    }).join('');
    const familyOptions = ['<option value="auto">Auto (from the checkpoint name)</option>',
        ...options.families.map((f) => `<option value="${escapeHtml(f.id)}" title="${escapeHtml(f.description)}">${escapeHtml(f.name)}</option>`)].join('');
    const methodOptions = ['<option value="">The model\'s default</option>',
        ...options.methods.map((m) => `<option value="${escapeHtml(m.id)}" title="${escapeHtml(m.description)}">${escapeHtml(m.name)}</option>`)].join('');
    const modelOptions = ['<option value="">From the image, else the WebUI\'s current model</option>',
        ...options.models.map((m) => `<option value="${escapeHtml(m)}">${escapeHtml(m)}</option>`)].join('');
    const instruct = options.methods.some((m) => m.id === 'instruct');
    const expressionBoxes = EXPRESSIONS.map((e) => `
        <label class="checkbox_label emotica-expression">
            <input type="checkbox" name="emotica_expression" value="${e}"> <span>${titleCase(e)}</span>
        </label>`).join('');

    return `
    <div class="emotica-dialog">
        <h3>Generate expression sprites</h3>
        <div class="emotica-columns">
            <div class="emotica-source">
                <img id="emotica_preview" alt="Input image">
                <label for="emotica_character">Character</label>
                <select id="emotica_character" class="text_pole">${characterOptions}</select>
                <small id="emotica_folder_note"></small>
                <label class="checkbox_label"><input type="radio" name="emotica_source" value="avatar" checked> Use the avatar</label>
                <label class="checkbox_label"><input type="radio" name="emotica_source" value="file"> Use another image</label>
                <input id="emotica_file" type="file" accept="image/png,image/jpeg,image/webp" hidden>
                <small>A larger, uncropped image of the character (with its generation settings, if it has them) gives better sprites than a small avatar.</small>
            </div>
            <div class="emotica-options">
                <label for="emotica_checkpoint">Checkpoint</label>
                <select id="emotica_checkpoint" class="text_pole">${modelOptions}</select>
                <label for="emotica_family">Prompt style</label>
                <select id="emotica_family" class="text_pole">${familyOptions}</select>
                <label for="emotica_method">Method</label>
                <select id="emotica_method" class="text_pole">${methodOptions}</select>
                <label class="checkbox_label"><input id="emotica_custom_intensity" type="checkbox"> Expression intensity <span id="emotica_intensity_value"></span></label>
                <input id="emotica_intensity" type="range" min="0" max="1" step="0.05">
                <label for="emotica_prompt">Character prompt <small>(optional, read from the image when it has one)</small></label>
                <textarea id="emotica_prompt" class="text_pole" rows="2" placeholder="1girl, long silver hair, blue eyes, ..."></textarea>
                <label class="checkbox_label ${options.background ? '' : 'disabled'}" title="${options.background ? 'Cut every sprite out of its background (rembg on the Emotica server).' : 'Needs rembg on the Emotica server.'}">
                    <input id="emotica_remove_background" type="checkbox" ${options.background ? '' : 'disabled'}> Remove background
                </label>
                <label class="checkbox_label ${instruct ? '' : 'disabled'}" title="${instruct ? 'Also change the pose a little with each expression, keeping the outfit and background.' : 'Needs Qwen-Image-Edit on ComfyUI.'}">
                    <input id="emotica_pose" type="checkbox" ${instruct ? '' : 'disabled'}> Change the pose too
                </label>
                <label class="checkbox_label ${options.animation ? '' : 'disabled'}" title="${options.animation ? 'Turn every sprite into a short looping animation (animated WebP, Wan 2.2). Neutral becomes the idle animation, made from the character card. Transparent with Remove background on.' : 'Needs Wan 2.2 on a ComfyUI backend.'}">
                    <input id="emotica_animate" type="checkbox" ${options.animation ? '' : 'disabled'}> Animate (idle from the character card)
                </label>
                <label class="checkbox_label" title="Upload each new sprite next to the existing one (joy-emotica.png) instead of replacing it. Turn on 'Allow multiple sprites' in Character Expressions to use both.">
                    <input id="emotica_keep_existing" type="checkbox"> Keep existing sprites (add as alternates)
                </label>
            </div>
        </div>
        <div class="emotica-expressions-header">
            <b>Expressions</b>
            <span class="menu_button" data-emotica-select="all">All</span>
            <span class="menu_button" data-emotica-select="none">None</span>
            <span class="menu_button" data-emotica-select="missing" title="Only the expressions this character has no sprite for yet">Missing</span>
            <small id="emotica_count"></small>
        </div>
        <div class="emotica-expressions">${expressionBoxes}</div>
    </div>`;
}

/** Open the dialog, then start a job with what was picked. */
async function openDialog() {
    if (dialogOpen) return;
    dialogOpen = true;
    try {
        await showDialog();
    } finally {
        dialogOpen = false;
    }
}

async function showDialog() {
    if (activeJob) {
        toastr.info('Emotica is already generating sprites. Cancel it in the Emotica settings first.', 'Emotica');
        return;
    }
    const context = ctx();
    if (!context.characters?.length) {
        toastr.warning('Create or import a character first.', 'Emotica');
        return;
    }
    try {
        await api('/health');
    } catch (error) {
        showError(error);
        return;
    }

    const loading = toastr.info('Asking Emotica for the WebUI\'s models and options…', 'Emotica', { timeOut: 0, extendedTimeOut: 0 });
    let options;
    try {
        options = await loadOptions();
    } finally {
        toastr.clear(loading);
    }
    const choices = characterChoices();
    const s = settings();
    const root = $(dialogHtml(options, choices));
    let pickedFile = null;
    let spritesByFolder = {};

    const character = () => context.characters[Number(root.find('#emotica_character').val())];
    const selected = () => root.find('input[name="emotica_expression"]:checked').map((_, el) => el.value).get();
    const updateCount = () => root.find('#emotica_count').text(`${selected().length} of ${EXPRESSIONS.length}`);
    const updateIntensity = () => {
        const on = root.find('#emotica_custom_intensity').prop('checked');
        root.find('#emotica_intensity').prop('disabled', !on);
        root.find('#emotica_intensity_value').text(on ? Number(root.find('#emotica_intensity').val()).toFixed(2) : '(the model\'s default)');
    };
    const updatePreview = async () => {
        const c = character();
        if (!c) return;
        const folder = spriteFolder(c);
        if (!(folder in spritesByFolder)) spritesByFolder[folder] = await existingSprites(folder);
        const count = new Set(spritesByFolder[folder].map((x) => x.label)).size;
        root.find('#emotica_folder_note').text(`Sprites go to characters/${folder}/ (${count} expression${count === 1 ? '' : 's'} there now).`);
        const useFile = root.find('input[name="emotica_source"]:checked').val() === 'file' && pickedFile;
        root.find('#emotica_preview').attr('src', useFile ? URL.createObjectURL(pickedFile) : `/characters/${encodeURIComponent(c.avatar)}`);
    };

    root.find('#emotica_checkpoint').val(options.models.includes(s.checkpoint) ? s.checkpoint : '');
    root.find('#emotica_family').val(options.families.some((f) => f.id === s.family) ? s.family : 'auto');
    root.find('#emotica_method').val(options.methods.some((m) => m.id === s.method) ? s.method : '');
    root.find('#emotica_custom_intensity').prop('checked', s.customIntensity);
    root.find('#emotica_intensity').val(s.intensity);
    root.find('#emotica_prompt').val(s.prompt);
    root.find('#emotica_remove_background').prop('checked', options.background && s.removeBackground);
    root.find('#emotica_pose').prop('checked', !root.find('#emotica_pose').prop('disabled') && s.pose);
    root.find('#emotica_animate').prop('checked', options.animation && s.animate);
    root.find('#emotica_keep_existing').prop('checked', s.keepExisting);
    root.find('input[name="emotica_expression"]').each((_, el) => { el.checked = s.selected.includes(el.value); });

    root.on('change', 'input[name="emotica_expression"]', updateCount);
    root.on('input change', '#emotica_custom_intensity, #emotica_intensity', updateIntensity);
    root.on('change', '#emotica_character', () => { pickedFile = null; root.find('input[name="emotica_source"][value="avatar"]').prop('checked', true); updatePreview(); });
    root.on('change', 'input[name="emotica_source"]', function () {
        if (this.value === 'file' && !pickedFile) root.find('#emotica_file').trigger('click');
        updatePreview();
    });
    root.on('change', '#emotica_file', function () {
        pickedFile = this.files?.[0] || null;
        root.find(`input[name="emotica_source"][value="${pickedFile ? 'file' : 'avatar'}"]`).prop('checked', true);
        updatePreview();
    });
    root.on('click', '[data-emotica-select]', async function () {
        const mode = this.dataset.emoticaSelect;
        const folder = spriteFolder(character());
        const have = new Set((spritesByFolder[folder] || []).map((x) => x.label));
        root.find('input[name="emotica_expression"]').each((_, el) => {
            el.checked = mode === 'all' || (mode === 'missing' && !have.has(el.value));
        });
        updateCount();
    });

    updateCount();
    updateIntensity();
    await updatePreview();

    const popup = new context.Popup(root[0], context.POPUP_TYPE.CONFIRM, '', {
        okButton: 'Generate',
        cancelButton: 'Cancel',
        wide: true,
        allowVerticalScrolling: true,
        onClosing: (p) => {
            if (p.result === context.POPUP_RESULT.AFFIRMATIVE && selected().length === 0) {
                toastr.warning('Pick at least one expression.', 'Emotica');
                return false;
            }
            return true;
        },
    });
    const result = await popup.show();
    if (result !== context.POPUP_RESULT.AFFIRMATIVE) return;

    Object.assign(s, {
        checkpoint: String(root.find('#emotica_checkpoint').val() || ''),
        family: String(root.find('#emotica_family').val() || 'auto'),
        method: String(root.find('#emotica_method').val() || ''),
        customIntensity: root.find('#emotica_custom_intensity').prop('checked'),
        intensity: Number(root.find('#emotica_intensity').val()),
        prompt: String(root.find('#emotica_prompt').val() || '').trim(),
        removeBackground: root.find('#emotica_remove_background').prop('checked'),
        pose: root.find('#emotica_pose').prop('checked'),
        animate: root.find('#emotica_animate').prop('checked'),
        keepExisting: root.find('#emotica_keep_existing').prop('checked'),
        selected: selected(),
    });
    save();

    const useFile = root.find('input[name="emotica_source"]:checked').val() === 'file' && pickedFile;
    generate({ character: character(), file: useFile ? pickedFile : null, expressions: selected() });
}

// Generation ------------------------------------------------------------------------

/** Generation settings read from the image's metadata, mapped onto /generate fields. */
function metadataFields(cleaned) {
    if (!cleaned) return {};
    const fields = {};
    const copy = ['ad_sampler', 'ad_scheduler', 'ad_prompt', 'ad_negative_prompt', 'ad_checkpoint'];
    for (const key of copy) if (cleaned[key]) fields[key] = cleaned[key];
    const numbers = ['seed', 'ad_steps', 'ad_cfg_scale', 'ad_clip_skip'];
    for (const key of numbers) {
        const value = Number(cleaned[key]);
        if (cleaned[key] !== null && cleaned[key] !== '' && Number.isFinite(value)) fields[key] = value;
    }
    if (Array.isArray(cleaned.loras)) fields.loras = cleaned.loras;
    return fields;
}

async function generate({ character, file, expressions }) {
    const s = settings();
    const folder = spriteFolder(character);
    const job = { id: null, character, folder, uploaded: new Set(), total: expressions.length };
    activeJob = job;
    renderProgress({ text: `Preparing ${character.name}…`, fraction: 0 });

    try {
        const blob = file || await avatarBlob(character);
        const image = await blobToDataUrl(blob);

        // Read the generation settings (prompt, checkpoint, seed, ...) the image was made with, if any.
        const form = new FormData();
        form.append('file', new File([blob], file?.name || character.avatar || 'character.png', { type: blob.type || 'image/png' }));
        const parsed = await api('/upload', { method: 'POST', body: form }).catch(() => null);

        await api('/expression-family', { method: 'POST', json: { family: s.family } });

        const body = {
            ...metadataFields(parsed?.cleaned_data),
            init_images: image,
            output_dir: folder,
            expressions,
            wait: false,
        };
        // Redoing a sprite the character already has: a new seed, or the image's seed would draw the same face again.
        // Prompts and settings saved per expression in Emotica (Output/<folder>) still apply, seeds included.
        const have = new Set((await existingSprites(folder)).map((x) => x.label));
        if (expressions.some((name) => have.has(name))) body.seed = -1;
        if (s.prompt) body.ad_prompt = s.prompt;
        if (s.checkpoint) body.ad_checkpoint = s.checkpoint;
        if (s.method) body.method = s.method;
        if (s.customIntensity) body.expression_intensity = s.intensity;
        if (s.removeBackground) body.remove_background = true;
        if (s.pose) body.pose = true;
        // The idle (neutral) animation's motion comes from the card in the avatar PNG.
        if (s.animate) {
            body.animate = true;
            body.animation = { formats: ['webp'], idle_source: 'web' };
        }

        const queued = await api('/generate', { method: 'POST', json: body });
        job.id = queued.job_id;
        toastr.info(`Generating ${expressions.length} sprite${expressions.length === 1 ? '' : 's'} for ${character.name}. They appear in Character Expressions as they finish.`, 'Emotica');
        await follow(job, queued.job);
    } catch (error) {
        showError(error, `Emotica: ${character.name}`);
        renderProgress(null);
    } finally {
        activeJob = null;
    }
}

async function follow(job, state) {
    const s = settings();
    const seenNotes = new Set();
    while (true) {
        for (const note of state.notes || []) {
            const key = `${note.kind}:${note.message}`;
            if (seenNotes.has(key)) continue;
            seenNotes.add(key);
            toastr.warning(note.message, note.title || 'Emotica', { timeOut: 15000 });
        }

        for (const image of state.images || []) {
            const label = image.expression;
            if (job.uploaded.has(label)) continue;
            job.uploaded.add(label);
            try {
                const file = image.animation ? image.animation.split('/').pop() : `${label}.png`;
                const path = state.output_dir ? `/image/${encodeURIComponent(state.output_dir)}/${encodeURIComponent(file)}` : (image.animation || image.url);
                const response = await api(`${path}?t=${Date.now()}`, { raw: true });
                const blob = await response.blob();
                const extension = file.includes('.') ? file.split('.').pop() : 'png';
                await uploadSprite(job.character, job.folder, label, s.keepExisting ? `${label}-emotica` : label, blob, extension);
            } catch (error) {
                showError(error, `Emotica: ${label}`);
            }
        }

        const progress = state.progress || {};
        const current = progress.current ? ` · ${titleCase(progress.current)}` : '';
        renderProgress({
            text: `${job.character.name}: ${progress.done ?? job.uploaded.size} of ${progress.total ?? job.total}${current}`,
            fraction: progress.fraction ?? 0,
        });

        if (['completed', 'failed', 'cancelled'].includes(state.status)) break;
        await new Promise((resolve) => setTimeout(resolve, POLL_MS));
        state = await api(`/jobs/${encodeURIComponent(job.id)}`);
    }

    renderProgress(null);
    const count = job.uploaded.size;
    if (state.status === 'completed') {
        toastr.success(`Added ${count} sprite${count === 1 ? '' : 's'} to ${job.character.name}.`, 'Emotica');
    } else if (state.status === 'cancelled') {
        toastr.info(`Stopped. ${count} sprite${count === 1 ? ' was' : 's were'} added to ${job.character.name}.`, 'Emotica');
    } else {
        const error = new EmoticaError(state.error?.message || 'Generation failed.', { code: state.error?.code, fix: state.error?.fix });
        showError(error, `Emotica: ${job.character.name}`);
    }
}

async function cancelJob() {
    if (!activeJob?.id) return;
    try {
        await api(`/jobs/${encodeURIComponent(activeJob.id)}/cancel`, { method: 'POST' });
    } catch (error) {
        showError(error);
    }
}

function renderProgress(state) {
    const box = $('#emotica_progress');
    if (!state) {
        box.prop('hidden', true);
        return;
    }
    box.prop('hidden', false);
    box.find('.emotica-progress-text').text(state.text);
    box.find('.emotica-progress-bar > div').css('width', `${Math.round((state.fraction || 0) * 100)}%`);
}

// Setup ---------------------------------------------------------------------------------

function settingsHtml() {
    return `
    <div class="emotica-settings">
        <div class="inline-drawer">
            <div class="inline-drawer-toggle inline-drawer-header">
                <b>Emotica</b>
                <div class="inline-drawer-icon fa-solid fa-circle-chevron-down down"></div>
            </div>
            <div class="inline-drawer-content">
                <small>Makes expression sprites for a character from one image, with the WebUI you already use. Needs the <a href="https://github.com/deepratna-awale/Emotica/blob/main/docs/sillytavern.md" target="_blank" rel="noopener">Emotica app</a> running.</small>
                <label for="emotica_url">Emotica address</label>
                <div class="flex-container">
                    <input id="emotica_url" class="text_pole flex1" type="text" placeholder="${DEFAULT_SETTINGS.url}">
                </div>
                <label for="emotica_webui_url">WebUI address <small>(optional: point Emotica at a WebUI, e.g. a RunPod URL; it detects which one)</small></label>
                <div class="flex-container">
                    <input id="emotica_webui_url" class="text_pole flex1" type="text" placeholder="http://127.0.0.1:7860">
                    <div id="emotica_connect" class="menu_button menu_button_icon"><i class="fa-solid fa-plug"></i> Connect</div>
                </div>
                <div id="emotica_status" class="emotica-status"></div>
                <div id="emotica_open" class="menu_button menu_button_icon"><i class="fa-solid fa-face-smile"></i> Generate expression sprites</div>
                <div id="emotica_progress" class="emotica-progress" hidden>
                    <div class="emotica-progress-text"></div>
                    <div class="emotica-progress-bar"><div></div></div>
                    <div id="emotica_cancel" class="menu_button menu_button_icon"><i class="fa-solid fa-stop"></i> Cancel</div>
                </div>
            </div>
        </div>
    </div>`;
}

function addWandButton() {
    const button = $(`
        <div id="emotica_wand" class="list-group-item flex-container flexGap5" title="Make expression sprites for a character with Emotica">
            <div class="fa-solid fa-face-smile extensionsMenuExtensionButton"></div>
            <span>Generate expression sprites</span>
        </div>`);
    button.on('click', openDialog);
    $('#extensionsMenu').append(button);
}

/** A button next to "Upload sprite pack" in the Character Expressions settings, when that panel exists. */
function addExpressionsButton() {
    if ($('#emotica_expressions_button').length) return;
    const anchor = $('#expression_upload_pack_button');
    if (!anchor.length) return;
    const button = $(`
        <div id="emotica_expressions_button" class="menu_button menu_button_icon" title="Make this character's sprites with Emotica">
            <i class="fa-solid fa-wand-magic-sparkles"></i><span>Generate with Emotica</span>
        </div>`);
    button.on('click', openDialog);
    anchor.after(button);
}

function registerCommand() {
    const context = ctx();
    if (!context.SlashCommandParser || !context.SlashCommand) return;
    context.SlashCommandParser.addCommandObject(context.SlashCommand.fromProps({
        name: 'emotica',
        callback: async () => {
            await openDialog();
            return '';
        },
        helpString: 'Open Emotica to generate expression sprites for a character.',
    }));
}

// Let the Live2D extension play Emotica puppets (*.puppet.model.json) as if they were Live2D models.
installPuppetLoader();

/**
 * The emotion of a message, as Character Expressions classifies it (with whichever API it is set
 * to: local, Extras, LLM or WebLLM). The Live2D extension only asks the local and Extras
 * classifiers, so with an LLM classifier every message would fall back to neutral.
 * Waits briefly for Character Expressions' own result for the message, then asks it directly.
 */
async function messageEmotion(name, text) {
    let expressions;
    try {
        expressions = await import('/scripts/extensions/expressions/index.js');
    } catch (error) {
        return null;
    }
    const before = expressions.lastExpression?.[name];
    for (let waited = 0; waited < 6000; waited += 250) {
        await new Promise(resolve => setTimeout(resolve, 250));
        const now = expressions.lastExpression?.[name];
        if (now && now !== before) return now;
    }
    try {
        return (await expressions.getExpressionLabel?.(text)) || null;
    } catch (error) {
        console.warn(LOG_PREFIX, 'Could not classify the message for the puppet:', error);
        return null;
    }
}

/** Play the emotion of a new message on the character's puppet, with the Live2D extension's mapping. */
async function playPuppetEmotion(messageId) {
    const context = ctx();
    const message = context.chat?.[messageId];
    if (!message || message.is_user || message.is_system) return;
    const puppets = livePuppets().filter(puppet => puppet.st_character === message.name);
    if (!puppets.length) return;
    const emotion = await messageEmotion(message.name, message.mes);
    if (!emotion) return;
    for (const puppet of puppets) {
        const mapping = context.extensionSettings?.live2d?.characterModelsSettings?.[message.name]?.[puppet.st_model_path]?.classify_mapping?.[emotion];
        const names = puppet.internalModel.settings.expressions.map(item => item.Name);
        const expression = mapping?.expression && mapping.expression !== 'none' ? mapping.expression : (names.includes(emotion) ? emotion : null);
        if (expression) puppet.expression(expression);
        const motion = mapping?.motion && mapping.motion !== 'none' ? mapping.motion : `${emotion}_id=random`;
        const [group, index] = motion.split('_id=');
        if (puppet.internalModel.settings.motions[group]) puppet.motion(group, index === 'random' ? undefined : index);
    }
}

jQuery(async () => {
    settings();
    $('#extensions_settings2').append(settingsHtml());
    $('#emotica_url').val(settings().url).on('change', function () {
        settings().url = String($(this).val() || '').trim() || DEFAULT_SETTINGS.url;
        $(this).val(settings().url);
        save();
        checkConnection({ quiet: true });
    });
    $('#emotica_connect').on('click', connectWebUI);
    $('#emotica_open').on('click', openDialog);
    $('#emotica_cancel').on('click', cancelJob);

    addWandButton();
    registerCommand();
    // Character Expressions may load after this extension.
    addExpressionsButton();
    setTimeout(addExpressionsButton, 2000);
    const { eventSource, eventTypes } = ctx();
    eventSource?.on(eventTypes?.APP_READY, addExpressionsButton);
    eventSource?.on(eventTypes?.MESSAGE_RECEIVED, (messageId) => playPuppetEmotion(messageId));

    checkConnection({ quiet: true });
});
