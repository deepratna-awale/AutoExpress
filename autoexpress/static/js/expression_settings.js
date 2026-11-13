// Advanced: each expression's own prompt and settings, saved with the character
// (Output/<name>/autoexpress_overrides.json) and used on every run, plus a retry of one expression.

const SEED_FIELD = { key: 'seed', label: 'Seed', step: 1, min: -1 };
const INTENSITY_FIELD = { key: 'expression_intensity', label: 'Intensity', step: 0.05, min: 0, max: 1 };
const INPAINT_FIELDS = [
    SEED_FIELD,
    INTENSITY_FIELD,
    { key: 'ad_denoising_strength', label: 'Denoising', step: 0.05, min: 0, max: 1 },
    { key: 'ad_steps', label: 'Steps', step: 1, min: 1, max: 150 },
    { key: 'ad_cfg_scale', label: 'CFG scale', step: 0.5, min: 0, max: 30 },
];
const EDIT_FIELDS = [
    SEED_FIELD,
    INTENSITY_FIELD,
    { key: 'edit_steps', label: 'Edit steps', step: 1, min: 1, max: 100 },
    { key: 'edit_cfg_scale', label: 'Edit CFG', step: 0.5, min: 0, max: 20 },
];

const ES = { dir: '', instruct: false, defaults: {}, drafts: {}, saved: {}, selected: '' };

function toDraft(override, defaultPrompt) {
    const settings = (override && override.settings) || {};
    const numbers = {};
    Object.entries(settings).forEach(([key, value]) => {
        if (key !== 'ad_negative_prompt' && typeof value === 'number') numbers[key] = String(value);
    });
    return { prompt: (override && override.prompt) || defaultPrompt, negative: settings.ad_negative_prompt || '', numbers };
}

// The default wording left as is isn't stored, so it keeps following the intensity.
function fromDraft(draft, defaultPrompt) {
    const settings = {};
    Object.entries(draft.numbers).forEach(([key, text]) => {
        const value = parseFloat(text);
        if (String(text || '').trim() && Number.isFinite(value)) settings[key] = value;
    });
    if (draft.negative.trim()) settings.ad_negative_prompt = draft.negative.trim();
    const prompt = draft.prompt.trim();
    return {
        ...(prompt && prompt !== defaultPrompt.trim() ? { prompt } : {}),
        ...(Object.keys(settings).length ? { settings } : {}),
    };
}

function isEmptyOverride(override) {
    return !override.prompt && !Object.keys(override.settings || {}).length;
}

function currentOverrides() {
    const all = {};
    Object.entries(ES.drafts).forEach(([name, draft]) => {
        const override = fromDraft(draft, ES.defaults[name] || '');
        if (!isEmptyOverride(override)) all[name] = override;
    });
    return all;
}

function isDirty() {
    return JSON.stringify(currentOverrides()) !== JSON.stringify(ES.saved);
}

function sharedValues() {
    const defaults = AE.familyDefaults;
    const intensity = document.getElementById('intensity-reset').hidden ? null : document.getElementById('intensity-input').value;
    return {
        seed: document.getElementById('seed-input').value,
        expression_intensity: intensity ?? (defaults ? String(defaults.intensity) : 'default'),
        ad_denoising_strength: document.getElementById('denoising-strength-input').value,
        ad_steps: document.getElementById('steps-input').value,
        ad_cfg_scale: document.getElementById('cfg-scale-input').value,
        edit_steps: 'default',
        edit_cfg_scale: 'default',
    };
}

function renderExpressionList() {
    const list = document.getElementById('es-list');
    const overrides = currentOverrides();
    list.replaceChildren(...Object.keys(ES.defaults).map(name => {
        const button = el('button', { type: 'button', class: `es-item${name === ES.selected ? ' es-selected' : ''}` },
            el('span', { text: expressionName(name) }),
            overrides[name] ? el('span', { class: 'es-dot', 'aria-label': 'has its own settings' }) : null);
        button.addEventListener('click', () => {
            ES.selected = name;
            renderExpressionSettings();
        });
        return el('li', {}, button);
    }));
}

function renderExpressionSettings() {
    renderExpressionList();
    const draft = ES.drafts[ES.selected];
    const editor = document.getElementById('es-editor');
    if (!draft) {
        editor.replaceChildren();
        return;
    }
    const defaultPrompt = ES.defaults[ES.selected] || '';
    const prompt = el('textarea', { id: 'es-prompt', rows: ES.instruct ? 5 : 3, class: 'mono' });
    prompt.value = draft.prompt;
    const reset = el('button', { type: 'button', class: 'link-button', text: 'Reset to default', hidden: draft.prompt.trim() === defaultPrompt.trim() });
    prompt.addEventListener('input', () => {
        draft.prompt = prompt.value;
        reset.hidden = draft.prompt.trim() === defaultPrompt.trim();
        afterEdit();
    });
    reset.addEventListener('click', () => {
        draft.prompt = defaultPrompt;
        prompt.value = defaultPrompt;
        reset.hidden = true;
        afterEdit();
    });

    const shared = sharedValues();
    const fields = (ES.instruct ? EDIT_FIELDS : INPAINT_FIELDS).map(field => {
        const input = el('input', { type: 'number', id: `es-${field.key}`, step: field.step, min: field.min, max: field.max, placeholder: shared[field.key] });
        input.value = draft.numbers[field.key] || '';
        input.addEventListener('input', () => {
            draft.numbers[field.key] = input.value;
            afterEdit();
        });
        return el('div', { class: 'es-field' }, el('label', { for: `es-${field.key}`, text: field.label }), input);
    });

    let negative = null;
    if (!ES.instruct) {
        const input = el('input', { type: 'text', id: 'es-negative', placeholder: 'The shared negative prompt' });
        input.value = draft.negative;
        input.addEventListener('input', () => {
            draft.negative = input.value;
            afterEdit();
        });
        negative = el('div', { class: 'es-field es-wide' }, el('label', { for: 'es-negative', text: 'Negative prompt' }), input);
    }

    editor.replaceChildren(
        el('div', { class: 'es-prompt-head' }, el('label', { for: 'es-prompt', text: ES.instruct ? 'Edit instruction' : 'Expression prompt' }), reset),
        prompt,
        el('p', { class: 'muted', text: ES.instruct
            ? 'Sent to Qwen-Image-Edit as the whole instruction for this expression.'
            : "Replaces this expression's tags; your character prompt, quality tags and LoRAs are still added." }),
        el('div', { class: 'es-fields' }, ...fields, negative),
    );
    afterEdit();
}

// Refresh the dots, the Save button and the Retry label after an edit or a selection.
function afterEdit() {
    const overrides = currentOverrides();
    document.querySelectorAll('#es-list .es-item').forEach((button, i) => {
        const name = Object.keys(ES.defaults)[i];
        const dot = button.querySelector('.es-dot');
        if (overrides[name] && !dot) button.appendChild(el('span', { class: 'es-dot', 'aria-label': 'has its own settings' }));
        if (!overrides[name] && dot) dot.remove();
    });
    document.getElementById('es-save').disabled = !isDirty();
    const hasImage = AE.images.some(file => file.replace(/\.[^.]+$/, '').toLowerCase() === ES.selected);
    const retry = document.getElementById('es-retry');
    retry.textContent = `${hasImage ? 'Retry' : 'Generate'} ${expressionName(ES.selected)}`;
    retry.disabled = generating || !AE.imageDataUrl;
    retry.title = AE.imageDataUrl ? '' : "Drop the character's input image first.";
}

async function openExpressionSettings(expression) {
    ES.dir = AE.galleryDir || resolveOutputDir(document.getElementById('output-directory').value);
    ES.instruct = selectedMethod() !== 'inpaint';
    document.getElementById('es-dir').textContent = `Output/${ES.dir}`;
    document.getElementById('es-export').href = `/expression-overrides?output_dir=${encodeURIComponent(ES.dir)}&download=1`;
    document.getElementById('es-editor').replaceChildren(el('p', { class: 'muted', text: 'Loading...' }));
    openDialog('expression-settings-dialog');
    try {
        const options = generationOptions();
        const [prompts, stored] = await Promise.all([
            apiOptional(apiPost('/expression-prompt', {
                method: ES.instruct ? selectedMethod() : 'inpaint',
                ad_checkpoint: document.getElementById('model-input').value,
                family: document.getElementById('expression-family-input').value || 'auto',
                ...(options.expression_intensity !== undefined ? { expression_intensity: options.expression_intensity } : {}),
                ...(options.edit_style ? { edit_style: options.edit_style } : {}),
                ...(options.pose ? { pose: true } : {}),
            })),
            apiOptional(apiRequest(`/expression-overrides?output_dir=${encodeURIComponent(ES.dir)}`)),
        ]);
        if (!prompts || !stored) {
            notify('This AutoExpress server has no per-expression settings. Update it.', 'error');
            closeDialog('expression-settings-dialog');
            return;
        }
        ES.defaults = prompts.prompts;
        ES.saved = stored.expressions || {};
        ES.drafts = {};
        Object.entries(ES.defaults).forEach(([name, text]) => { ES.drafts[name] = toDraft(ES.saved[name], text); });
        const wanted = expression && expression.toLowerCase();
        ES.selected = wanted && wanted in ES.defaults ? wanted : (ES.selected in ES.defaults ? ES.selected : Object.keys(ES.defaults)[0] || '');
        renderExpressionSettings();
    } catch (error) {
        notify(`Could not load the expression settings: ${messageOf(error)}`, 'error');
        closeDialog('expression-settings-dialog');
    }
}

async function saveExpressionSettings(next = currentOverrides(), quiet = false) {
    try {
        const result = await apiPost('/expression-overrides', { output_dir: ES.dir, expressions: next }, 'PUT');
        ES.saved = result.expressions;
        afterEdit();
        if (!quiet) notify(`Saved per-expression settings for Output/${ES.dir}.`, 'success');
        return true;
    } catch (error) {
        notify(`Could not save: ${messageOf(error)}`, 'error');
        return false;
    }
}

document.getElementById('es-save').addEventListener('click', () => saveExpressionSettings());
document.getElementById('es-close').addEventListener('click', () => closeDialog('expression-settings-dialog'));
document.getElementById('es-import').addEventListener('click', () => document.getElementById('es-import-file').click());
document.getElementById('es-import-file').addEventListener('change', async (event) => {
    const file = event.target.files[0];
    event.target.value = '';
    if (!file) return;
    try {
        const data = JSON.parse(await file.text());
        const imported = (data && data.expressions) || data;
        if (!imported || typeof imported !== 'object') throw new Error('not an AutoExpress settings file');
        if (await saveExpressionSettings(imported, true)) {
            Object.keys(ES.defaults).forEach(name => { ES.drafts[name] = toDraft(imported[name], ES.defaults[name]); });
            renderExpressionSettings();
            notify(`Imported settings for ${Object.keys(imported).length} expressions into Output/${ES.dir}.`, 'success');
        }
    } catch (error) {
        notify(`Could not import ${file.name}: ${messageOf(error)}`, 'error');
    }
});
document.getElementById('es-retry').addEventListener('click', async () => {
    const override = fromDraft(ES.drafts[ES.selected], ES.defaults[ES.selected] || '');
    // Keep the edits of the other expressions too, so a retry never drops them.
    if (document.getElementById('es-remember').checked && isDirty()) {
        if (!(await saveExpressionSettings(currentOverrides(), true))) return;
    }
    closeDialog('expression-settings-dialog');
    await retryExpression(ES.selected, override, false);
});
document.getElementById('per-expression-open').addEventListener('click', () => openExpressionSettings(null));
