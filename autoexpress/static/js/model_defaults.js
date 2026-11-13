// Typical generation settings per model family, used when a value read from an image (or left over
// from another WebUI) isn't available on the connected one. Same table as frontend/lib/model-defaults.ts.

const FAMILY_DEFAULTS = {
    sd15: { label: 'SD 1.5', samplers: ['DPM++ 2M', 'Euler a', 'DPM++ 2M Karras', 'euler_ancestral'], schedulers: ['Karras', 'Automatic', 'karras', 'normal'], steps: 25, cfgScale: 7, clipSkip: 2 },
    sdxl: { label: 'SDXL', samplers: ['DPM++ 2M SDE', 'DPM++ 2M', 'Euler a', 'dpmpp_2m_sde', 'dpmpp_2m'], schedulers: ['Karras', 'Automatic', 'karras', 'normal'], steps: 30, cfgScale: 6, clipSkip: 1 },
    pony: { label: 'Pony', samplers: ['Euler a', 'DPM++ 2M SDE', 'euler_ancestral'], schedulers: ['Normal', 'Automatic', 'Karras', 'normal'], steps: 25, cfgScale: 7, clipSkip: 2 },
    illustrious: { label: 'Illustrious', samplers: ['Euler a', 'DPM++ 2M', 'euler_ancestral'], schedulers: ['Normal', 'Automatic', 'Karras', 'normal'], steps: 28, cfgScale: 5.5, clipSkip: 2 },
    flux: { label: 'Flux', samplers: ['Euler', 'euler', '[Forge] Flux Realistic'], schedulers: ['Simple', 'Beta', 'simple', 'beta', 'Automatic'], steps: 20, cfgScale: 1, clipSkip: 1 },
    sd3: { label: 'SD 3', samplers: ['Euler', 'DPM++ 2M', 'euler'], schedulers: ['SGM Uniform', 'Simple', 'sgm_uniform', 'Automatic'], steps: 28, cfgScale: 4.5, clipSkip: 1 },
};

// Checked in order, first match wins (Pony and Illustrious merges are SDXL too).
const FAMILY_PATTERNS = [
    ['flux', /flux|schnell/i],
    ['sd3', /sd3|sd_3|sd-3|stable.?diffusion.?3/i],
    ['pony', /pony|pdxl|autismmix|score_?9/i],
    ['illustrious', /illustrious|\billu|noob|\bwai[-_ ]|obsession/i],
    ['sdxl', /xl|sdxl|juggernaut|animagine|playground|realvis|dreamshaper.?xl|zavychroma|turbo|lightning/i],
];

function detectFamily(modelName) {
    if (!modelName) return 'sd15';
    const found = FAMILY_PATTERNS.find(([, pattern]) => pattern.test(modelName));
    return found ? found[0] : 'sd15';
}

function normalizeName(name) {
    return String(name).toLowerCase()
        .replace(/\s*\[[a-f0-9]+\]$/, '')
        .replace(/\.(safetensors|ckpt|pt|pth|gguf)$/, '')
        .replace(/[^a-z0-9]/g, '');
}

function findAvailable(wanted, available) {
    const key = normalizeName(wanted);
    return available.find(option => option === wanted) || available.find(option => normalizeName(option) === key);
}

function firstAvailable(preferred, available) {
    for (const name of preferred) {
        const match = findAvailable(name, available);
        if (match) return match;
    }
    return undefined;
}

// The installed checkpoint closest to `wanted`: same name first, then same family.
function closestModel(wanted, available) {
    if (!available.length) return undefined;
    const exact = findAvailable(wanted, available);
    if (exact) return exact;
    const key = normalizeName(wanted);
    const partial = key && available.find(option => normalizeName(option).includes(key) || key.includes(normalizeName(option)));
    if (partial) return partial;
    const family = detectFamily(wanted);
    return available.find(option => detectFamily(option) === family) || available[0];
}

// Swaps values the connected WebUI doesn't offer for the closest match or the family's usual setting.
function reconcileSelections(current, options) {
    const result = { model: current.model, sampler: current.sampler, scheduler: current.scheduler, adjustments: {} };

    if (current.model && options.models.length) {
        const match = closestModel(current.model, options.models);
        if (match && match !== current.model) {
            if (normalizeName(match) !== normalizeName(current.model)) {
                result.adjustments.model = {
                    from: current.model,
                    reason: `not installed, using the closest ${FAMILY_DEFAULTS[detectFamily(current.model)].label} checkpoint`,
                };
            }
            result.model = match;
        }
    }

    const family = FAMILY_DEFAULTS[detectFamily(result.model || current.model)];
    let sampler = current.sampler;
    let scheduler = current.scheduler;

    // Older A1111 names put the schedule in the sampler: "DPM++ 2M Karras".
    if (sampler && options.samplers.length && !findAvailable(sampler, options.samplers)) {
        const split = sampler.match(/^(.*)\s+(Karras|Exponential|SGM Uniform|Simple|Beta|Normal)$/i);
        if (split && findAvailable(split[1], options.samplers)) {
            sampler = split[1];
            if (!scheduler || scheduler === 'Automatic') scheduler = split[2];
        }
    }

    if (options.samplers.length) {
        const match = sampler ? findAvailable(sampler, options.samplers) : undefined;
        if (match) {
            result.sampler = match;
        } else if (sampler) {
            result.adjustments.sampler = { from: sampler, reason: `not available, using the ${family.label} default` };
            result.sampler = firstAvailable(family.samplers, options.samplers) || options.samplers[0];
        } else {
            result.sampler = firstAvailable(family.samplers, options.samplers) || options.samplers[0];
        }
    }

    if (options.schedulers.length) {
        const match = scheduler ? findAvailable(scheduler, options.schedulers) : undefined;
        if (match) {
            result.scheduler = match;
        } else if (scheduler) {
            result.adjustments.scheduler = { from: scheduler, reason: `not available, using the ${family.label} default` };
            result.scheduler = firstAvailable(family.schedulers, options.schedulers) || options.schedulers[0];
        } else {
            result.scheduler = firstAvailable(family.schedulers, options.schedulers) || options.schedulers[0];
        }
    }

    return result;
}

function setSelectValue(id, value) {
    const select = document.getElementById(id);
    if (!select || value === undefined || value === null) return;
    if (value && !Array.from(select.options).some(option => option.value === value)) {
        select.add(new Option(value, value));
    }
    select.value = value;
}

function showAdjustment(key, adjustment) {
    const note = document.getElementById(`${key}-adjustment`);
    if (!note) return;
    note.textContent = adjustment ? `${adjustment.from} ${adjustment.reason}.` : '';
    note.hidden = !adjustment;
}

// Fit the model, sampler and scheduler to what the connected WebUI lists, with a note for each swap.
function reconcileWithWebUI() {
    const options = AE.options;
    if (!options.models.length && !options.samplers.length) return;
    const current = {
        model: document.getElementById('model-input').value,
        sampler: document.getElementById('sampler-input').value,
        scheduler: document.getElementById('scheduler-input').value,
    };
    const result = reconcileSelections(current, options);
    setSelectValue('model-input', result.model);
    setSelectValue('sampler-input', result.sampler);
    setSelectValue('scheduler-input', result.scheduler);
    ['model', 'sampler', 'scheduler'].forEach(key => showAdjustment(key, result.adjustments[key]));
    updateModelDefaultsLink();
}

function setNumber(name, value) {
    const input = document.getElementById(`${name}-input`);
    const slider = document.getElementById(`${name}-slider`);
    if (input) input.value = value;
    if (slider) slider.value = value;
}

// Sampler, scheduler, steps, CFG and clip skip that the selected model's family usually uses.
function applyModelDefaults() {
    const family = FAMILY_DEFAULTS[detectFamily(document.getElementById('model-input').value)];
    const pick = (preferred, available, current) => (available.length ? firstAvailable(preferred, available) || current : current);
    setSelectValue('sampler-input', pick(family.samplers, AE.options.samplers, document.getElementById('sampler-input').value));
    setSelectValue('scheduler-input', pick(family.schedulers, AE.options.schedulers, document.getElementById('scheduler-input').value));
    setNumber('steps', family.steps);
    setNumber('cfg-scale', family.cfgScale);
    document.getElementById('clip-skip-input').value = family.clipSkip;
    ['model', 'sampler', 'scheduler'].forEach(key => showAdjustment(key, null));
    notify(`Applied ${family.label} defaults`, 'success');
}

function updateModelDefaultsLink() {
    const link = document.getElementById('model-defaults');
    if (!link) return;
    const model = document.getElementById('model-input').value;
    const family = FAMILY_DEFAULTS[detectFamily(model)];
    link.hidden = !model;
    link.textContent = `Use ${family.label} defaults`;
    link.title = `Sampler, scheduler, steps, CFG and clip skip that ${family.label} models usually use`;
}

document.getElementById('model-defaults').addEventListener('click', applyModelDefaults);
['model', 'sampler', 'scheduler'].forEach(key => {
    document.getElementById(`${key}-input`).addEventListener('change', () => {
        showAdjustment(key, null);
        if (key === 'model') updateModelDefaultsLink();
    });
});
