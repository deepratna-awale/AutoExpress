// Generation options beyond the basic parameters: instruction edit wording, poses, expression
// intensity, background removal and animated sprites.

const POSE_KEY = 'autoexpress-pose';
const REMOVE_BACKGROUND_KEY = 'autoexpress-remove-background';
const ANIMATE_KEY = 'autoexpress-animate';
const FORMAT_LABELS = { webp: 'WebP', apng: 'APNG', gif: 'GIF' };

const photoToggle = document.getElementById('edit-style-toggle');
const poseToggle = document.getElementById('pose-toggle');
const intensitySlider = document.getElementById('intensity-slider');
const intensityInput = document.getElementById('intensity-input');
const removeBackgroundToggle = document.getElementById('remove-background-toggle');
const animateToggle = document.getElementById('animate-toggle');
const idleMotionInput = document.getElementById('idle-motion');

// Family defaults only fill in what the user hasn't chosen themselves.
const touched = { method: false, photoStyle: false };
let customIntensity = null;
let idleSource = 'card';

function selectedMethod() {
    return document.getElementById('edit-method-input').value || 'inpaint';
}

function posesAvailable() {
    return !!(AE.editMethods && AE.editMethods.some(m => m.id === 'instruct' && m.available));
}

// --- Method, wording and pose --------------------------------------------------------------------

function updateMethodOptions() {
    const instruct = selectedMethod() !== 'inpaint';
    document.getElementById('edit-style-row').hidden = !instruct;
    const method = AE.editMethods && AE.editMethods.find(m => m.id === selectedMethod());
    const note = document.getElementById('edit-method-note');
    note.textContent = instruct && method ? `${method.description} ${AE.vramNote || ''}` : '';
    note.hidden = !instruct;

    const available = posesAvailable();
    poseToggle.disabled = !available;
    poseToggle.checked = available && recall(POSE_KEY) === '1';
    document.getElementById('pose-note').textContent = available
        ? 'Adds a small sprite gesture to each expression (hands on the hips for anger, hands behind the back for curiosity) from the current pose. The outfit and background stay as they are.'
        : 'Needs Qwen-Image-Edit on a ComfyUI backend.';
}

document.getElementById('edit-method-input').addEventListener('change', (event) => {
    if (event.isTrusted) touched.method = true;
    updateMethodOptions();
    loadFamilyDefaults();
});
photoToggle.addEventListener('change', () => { touched.photoStyle = true; });
poseToggle.addEventListener('change', () => remember(POSE_KEY, poseToggle.checked ? '1' : '0'));

// --- Expression intensity ------------------------------------------------------------------------

function showIntensity() {
    const defaults = AE.familyDefaults;
    const value = customIntensity ?? (defaults ? defaults.intensity : 0.5);
    intensitySlider.value = value;
    intensityInput.value = value;
    const note = document.getElementById('intensity-note');
    const reset = document.getElementById('intensity-reset');
    if (customIntensity === null) {
        note.textContent = `Default for ${defaults ? defaults.family : 'this model'}. Realistic models start low; strong expressions look uncanny on real faces.`;
        reset.hidden = true;
    } else {
        note.textContent = 'Custom. ';
        reset.textContent = `Use the model default (${defaults ? defaults.intensity : 0.5})`;
        reset.hidden = false;
    }
}

function setIntensity(value) {
    customIntensity = value === null ? null : Math.min(Math.max(Math.round(Number(value) * 100) / 100, 0), 1);
    showIntensity();
}

intensitySlider.addEventListener('input', () => setIntensity(intensitySlider.value));
intensityInput.addEventListener('change', () => setIntensity(intensityInput.value));
document.getElementById('intensity-reset').addEventListener('click', () => setIntensity(null));

// Each model family has calibrated defaults: realistic models get much gentler expressions.
let defaultsRequest = 0;
async function loadFamilyDefaults() {
    const request = ++defaultsRequest;
    const checkpoint = document.getElementById('model-input').value;
    const family = document.getElementById('expression-family-input').value || 'auto';
    try {
        const result = await apiOptional(apiRequest(`/expression-defaults?checkpoint=${encodeURIComponent(checkpoint)}&family=${encodeURIComponent(family)}`));
        if (request !== defaultsRequest) return;
        AE.familyDefaults = result ? { family: result.family, ...result.defaults } : null;
        if (result && !touched.photoStyle) photoToggle.checked = result.defaults.edit_style === 'photo';
        if (result && !touched.method && AE.editMethods && AE.editMethods.some(m => m.id === result.defaults.method && m.available)) {
            const select = document.getElementById('edit-method-input');
            if (select.value !== result.defaults.method) {
                select.value = result.defaults.method;
                updateMethodOptions();
            }
        }
    } catch (error) {
        AE.familyDefaults = null;
    }
    showIntensity();
}

document.getElementById('model-input').addEventListener('change', loadFamilyDefaults);
document.getElementById('expression-family-input').addEventListener('change', loadFamilyDefaults);

// --- Background removal --------------------------------------------------------------------------

async function loadBackgroundRemoval() {
    const info = await apiOptional(apiRequest('/background-removal')).catch(() => null);
    AE.backgroundRemoval = info;
    const row = document.getElementById('remove-background-row');
    row.hidden = !info;
    if (!info) return;
    removeBackgroundToggle.disabled = !info.available;
    removeBackgroundToggle.checked = info.available && recall(REMOVE_BACKGROUND_KEY) === '1';
    document.getElementById('remove-background-note').textContent = info.available
        ? 'Saves each expression with a transparent background, only the character is kept.'
        : `Needs rembg on the AutoExpress server: ${info.install_command}`;
}

removeBackgroundToggle.addEventListener('change', () => remember(REMOVE_BACKGROUND_KEY, removeBackgroundToggle.checked ? '1' : '0'));

// --- Animated sprites ----------------------------------------------------------------------------

async function loadAnimationInfo() {
    const info = await apiOptional(apiRequest('/animation')).catch(() => null);
    AE.animationInfo = info;
    const row = document.getElementById('animation-row');
    row.hidden = !info;
    if (!info) return;
    animateToggle.disabled = !info.available;
    animateToggle.checked = info.available && recall(ANIMATE_KEY) === '1';
    document.getElementById('animation-note').textContent = info.available
        ? 'Turns each expression into a short looping clip with Wan 2.2 image to video. Neutral becomes the character\'s idle animation. With Remove background on, the clips are transparent too.'
        : 'Needs a ComfyUI backend with Wan 2.2 image to video.';
    const formats = document.getElementById('animation-formats');
    const checked = new Set(Array.from(formats.querySelectorAll('input:checked')).map(input => input.value));
    if (!checked.size) checked.add('webp');
    formats.replaceChildren(el('span', { class: 'muted', text: 'Save as' }));
    info.formats.forEach(format => {
        formats.appendChild(el('label', { class: 'inline-check' },
            el('input', { type: 'checkbox', value: format, checked: checked.has(format) }),
            FORMAT_LABELS[format] || format));
    });
    const llm = document.querySelector('[data-idle-source="llm"]');
    llm.title = info.llm.configured ? '' : 'Set AUTOEXPRESS_LLM_URL (any OpenAI compatible endpoint) to use an LLM.';
    document.getElementById('animation-vram').textContent = info.vram_note;
    updateAnimationPanel();
}

function updateAnimationPanel() {
    const info = AE.animationInfo;
    const on = !!info && info.available && animateToggle.checked;
    document.getElementById('animation-settings').hidden = !on;
    document.getElementById('idle-label').textContent = `Idle animation${AE.character ? ` for ${AE.character.name}` : ''}`;
    idleMotionInput.placeholder = AE.character
        ? 'Filled in from the character card.'
        : 'How the character idles, e.g. sways playfully and winks. Left empty, it comes from the character card.';
    document.querySelectorAll('[data-idle-source]').forEach(button => {
        button.disabled = !AE.imageDataUrl || (button.dataset.idleSource === 'llm' && !(info && info.llm.configured));
    });
}

document.getElementById('animation-formats').addEventListener('change', (event) => {
    // Keep at least one format.
    if (!document.querySelector('#animation-formats input:checked')) event.target.checked = true;
});

animateToggle.addEventListener('change', () => {
    remember(ANIMATE_KEY, animateToggle.checked ? '1' : '0');
    updateAnimationPanel();
});

async function suggestIdleMotion(source) {
    if (!AE.imageDataUrl) return;
    const spinner = document.getElementById('idle-busy');
    spinner.hidden = false;
    try {
        const result = await apiOptional(apiPost('/character-card', { image: AE.imageDataUrl, idle_source: source }));
        if (result) {
            idleMotionInput.value = result.idle_motion;
            idleSource = source;
            if (source !== 'card' && result.idle_source === 'card') notify('Nothing more found, so the idle comes from the card.');
        }
    } catch (error) {
        notify(`Could not describe the idle motion: ${messageOf(error)}`, 'error');
    } finally {
        spinner.hidden = true;
    }
}

document.querySelectorAll('[data-idle-source]').forEach(button => {
    button.addEventListener('click', () => suggestIdleMotion(button.dataset.idleSource));
});

// A new input image: forget the old idle motion, and read the new card's.
function onCharacterChanged() {
    idleMotionInput.value = '';
    idleSource = 'card';
    updateAnimationPanel();
    if (AE.character) suggestIdleMotion('card');
}

// --- What the WebUI can do -----------------------------------------------------------------------

function loadFeatureInfo() {
    loadBackgroundRemoval();
    loadAnimationInfo();
    loadFamilyDefaults();
}

// The settings these options add to a /generate request.
function generationOptions() {
    const options = {};
    const instruct = selectedMethod() !== 'inpaint';
    if (AE.editMethods) options.method = selectedMethod();
    if (instruct) options.edit_style = photoToggle.checked ? 'photo' : 'illustration';
    if (customIntensity !== null) options.expression_intensity = customIntensity;
    if (removeBackgroundToggle.checked && AE.backgroundRemoval && AE.backgroundRemoval.available) options.remove_background = true;
    if (poseToggle.checked && posesAvailable()) options.pose = true;
    if (animateToggle.checked && AE.animationInfo && AE.animationInfo.available) {
        const formats = Array.from(document.querySelectorAll('#animation-formats input:checked')).map(input => input.value);
        const idle = idleMotionInput.value.trim();
        options.animate = true;
        options.animation = {
            formats: formats.length ? formats : ['webp'],
            lightning: document.getElementById('animation-fast').checked,
            ...(idle ? { idle_motion: idle } : { idle_source: idleSource }),
        };
    }
    return options;
}

function setGeneratingOptions(generating) {
    const inputs = [removeBackgroundToggle, animateToggle, idleMotionInput, document.getElementById('animation-fast')];
    inputs.forEach(input => { input.disabled = generating; });
    document.querySelectorAll('#animation-formats input').forEach(input => { input.disabled = generating; });
    if (!generating) {
        idleMotionInput.disabled = false;
        loadBackgroundRemoval();
        loadAnimationInfo();
    }
}

loadFeatureInfo();
showIntensity();
