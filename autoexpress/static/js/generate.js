// Generating a set (or one expression again), following the job, and the run's notes.

const JOB_POLL_MS = 1500;
const FOLDER_POLL_MS = 2500;
const generateButton = document.querySelector('.generate-button');
let pollTimer = null;
let generating = false;

function numberValue(id, fallback) {
    const value = parseFloat(document.getElementById(id).value);
    return Number.isFinite(value) ? value : fallback;
}

function loraTag(name) {
    const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    return new RegExp(`<lora:\\s*${escaped}\\s*:[^>]*>`, 'gi');
}

// LoRAs already written in the prompt (read from the input image) take the strength from the list
// instead of being added a second time.
function applyLoras(prompt, loras) {
    let adPrompt = prompt;
    const extra = [];
    loras.forEach(lora => {
        if (loraTag(lora.lora_name).test(adPrompt)) {
            adPrompt = adPrompt.replace(loraTag(lora.lora_name), `<lora:${lora.lora_name}:${lora.lora_strength}>`);
        } else {
            extra.push(lora);
        }
    });
    return { adPrompt, extra };
}

// The /generate body for the current inputs, the same for a whole set and for a retry.
function buildRequest() {
    if (!AE.imageDataUrl) return null;
    const { adPrompt, extra } = applyLoras(document.getElementById('prompt-textfield').value, selectedLoras());
    return {
        init_images: AE.imageDataUrl,
        output_dir: document.getElementById('output-directory').value,
        ad_scheduler: document.getElementById('scheduler-input').value,
        loras: extra,
        seed: numberValue('seed-input', -1),
        ad_prompt: adPrompt,
        ad_negative_prompt: document.getElementById('negative-prompt-textfield').value,
        ad_steps: numberValue('steps-input', 32),
        ad_checkpoint: document.getElementById('model-input').value,
        ad_sampler: document.getElementById('sampler-input').value,
        ad_clip_skip: numberValue('clip-skip-input', 2),
        ad_cfg_scale: numberValue('cfg-scale-input', 7),
        ad_denoising_strength: numberValue('denoising-strength-input', 0.5),
        ...generationOptions(),
    };
}

function setGenerating(value) {
    generating = value;
    generateButton.disabled = value;
    generateButton.querySelector('.generate-label').textContent = value ? 'Generating...' : 'Generate';
    setGeneratingOptions(value);
    const retry = document.getElementById('retry-button');
    if (retry) retry.disabled = value;
}

function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
}

function showProgress(job) {
    const box = document.getElementById('job-progress');
    const progress = job && job.progress;
    if (!job || !isActiveJob(job) || !progress || !progress.total) {
        box.hidden = true;
        return;
    }
    box.hidden = false;
    const fraction = (progress.done + ((progress.step && progress.step.fraction) || 0)) / progress.total;
    box.querySelector('.progress-fill').style.width = `${Math.round(fraction * 100)}%`;
    box.querySelector('.progress-text').textContent = job.status === 'queued'
        ? 'Queued...'
        : `${progress.done} of ${progress.total}${progress.current ? ` · ${expressionName(progress.current)}` : ''}${progress.step && progress.step.eta ? ` · ~${Math.ceil(progress.step.eta)}s` : ''}`;
}

// Notes from the last finished run, such as expression LoRAs the WebUI lacks.
function showNotes(job) {
    const bar = document.getElementById('job-notes');
    const notes = (job && job.notes) || [];
    if (!job || isActiveJob(job) || !notes.length || bar.dataset.dismissed === job.id) {
        bar.hidden = true;
        return;
    }
    const loras = notes.filter(note => note.kind === 'missing_lora').length;
    bar.querySelector('.notes-summary').textContent = loras === notes.length
        ? `${loras} expression ${loras === 1 ? 'LoRA' : 'LoRAs'} couldn't be installed`
        : `${notes.length} ${notes.length === 1 ? 'note' : 'notes'} from this run`;
    bar.dataset.job = job.id;
    bar.hidden = false;
    const list = document.getElementById('notes-list');
    list.replaceChildren(...notes.map(note => el('li', {},
        el('p', { class: 'note-title', text: note.title || note.name }),
        el('p', { class: 'muted', text: `${note.file_name || ''}${note.size_mb ? ` · ${note.size_mb.toFixed(note.size_mb < 10 ? 1 : 0)} MB` : ''}` }),
        note.message ? el('p', { text: note.message }) : null,
        note.url ? el('a', { href: note.url, target: '_blank', rel: 'noopener noreferrer', text: 'Download page' }) : null,
    )));
}

document.getElementById('notes-details').addEventListener('click', () => openDialog('notes-dialog'));
document.getElementById('notes-dismiss').addEventListener('click', () => {
    const bar = document.getElementById('job-notes');
    bar.dataset.dismissed = bar.dataset.job || '';
    bar.hidden = true;
});

function finishJob(job) {
    stopPolling();
    AE.job = job;
    setGenerating(false);
    showProgress(null);
    showNotes(job);
    loadImages(job.output_dir, true);
    if (job.status === 'completed') {
        notify(`Finished generating expressions in Output/${job.output_dir}`, 'success');
        if ((job.notes || []).some(note => note.kind === 'missing_lora')) {
            notify('Some expression LoRAs were missing, see the note above the prompt.', 'warning');
        }
    } else if (job.status === 'cancelled') {
        notify(`Stopped after ${job.progress.done} of ${job.progress.total} expressions.`);
    } else {
        notify((job.error && job.error.message) || 'Generation failed', 'error', 10);
    }
}

// Follow a job until it ends, refreshing the gallery as expressions land.
function trackJob(started) {
    AE.job = started;
    setGenerating(true);
    showProgress(started);
    showNotes(null);
    loadImages(started.output_dir, true);
    stopPolling();
    let lastDone = started.progress.done;
    let busy = false;
    pollTimer = setInterval(async () => {
        if (busy) return;
        busy = true;
        try {
            const latest = await apiRequest(`/jobs/${encodeURIComponent(started.id)}`);
            AE.job = latest;
            showProgress(latest);
            if (latest.progress.done !== lastDone) {
                lastDone = latest.progress.done;
                loadImages(latest.output_dir, false);
            }
            if (!isActiveJob(latest)) finishJob(latest);
        } catch (e) {
            // Transient error; try again on the next tick
        } finally {
            busy = false;
        }
    }, JOB_POLL_MS);
}

async function startGeneration(request, dir) {
    setGenerating(true);
    AE.job = null;
    showNotes(null);
    stopPolling();
    // Older servers answer only when the whole set is done; watch the folder meanwhile.
    pollTimer = setInterval(() => loadImages(dir, false), FOLDER_POLL_MS);
    let tracking = false;
    try {
        const result = await apiPost('/generate', { ...request, wait: false });
        if (result.job && isActiveJob(result.job)) {
            tracking = true;
            trackJob(result.job);
        } else if (result.job) {
            tracking = true;
            finishJob(result.job);
        } else if (result.status === 'success') {
            notify(`Finished generating expressions in Output/${dir}`, 'success');
        } else {
            notify(result.message || 'Generation failed', 'error');
        }
    } catch (error) {
        // Point at the setup checklist: the fix for an unreachable WebUI, or what it is missing.
        if (error instanceof ApiError && error.fix) showConnectionError(error.body);
        else if (error instanceof ApiError && error.status === 409) checkCapabilities();
        notify(`Generation failed: ${messageOf(error)}`, 'error', 10);
    } finally {
        if (!tracking) {
            stopPolling();
            setGenerating(false);
            loadImages(dir, true);
        }
    }
}

async function generate() {
    const request = buildRequest();
    if (!request) {
        notify('Drop an input image first.', 'error');
        return;
    }
    await startGeneration(request, resolveOutputDir(request.output_dir));
}

// Make one expression again (a new seed), optionally with its own prompt and settings.
async function retryExpression(expression, override, rememberIt = false) {
    const request = buildRequest();
    if (!request) {
        notify("Drop the character's input image first, then retry.", 'error');
        return;
    }
    const dir = AE.galleryDir || resolveOutputDir(request.output_dir);
    const name = expression.toLowerCase();
    const hasOwn = override && (override.prompt || Object.keys(override.settings || {}).length > 0);
    await startGeneration({
        ...request,
        output_dir: dir,
        expressions: [name],
        // A new take unless the expression has a seed of its own.
        seed: -1,
        ...(hasOwn ? { overrides: { [name]: override }, save_overrides: rememberIt } : {}),
    }, dir);
}

async function interrupt() {
    try {
        if (isActiveJob(AE.job)) {
            await apiPost(`/jobs/${encodeURIComponent(AE.job.id)}/cancel`, {});
        } else {
            await apiPost('/interrupt', {});
        }
        notify('Stopping after the current expression.');
    } catch (error) {
        notify(`Could not interrupt: ${messageOf(error)}`, 'error');
    }
}

generateButton.addEventListener('click', generate);
document.querySelector('.interrupt-button').addEventListener('click', interrupt);

// Pick up a job that is still running, e.g. after a page reload.
apiOptional(apiRequest('/jobs')).then(result => {
    const active = result && (result.jobs || []).find(isActiveJob);
    if (active) {
        document.getElementById('output-directory').value = active.output_dir;
        trackJob(active);
    }
}).catch(() => {});
