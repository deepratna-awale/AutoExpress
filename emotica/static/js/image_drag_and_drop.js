var data = null;
let uncleaned_data = null;

const ACCEPTED_TYPES = ['image/png', 'image/jpeg', 'image/gif'];
const MAX_SIZE = 25 * 1024 * 1024;
const dropZoneElement = document.querySelector('.drop-zone');
const dropZoneInput = document.getElementById('drop-zone-input-field');

dropZoneElement.addEventListener('click', () => dropZoneInput.click());

dropZoneInput.addEventListener('change', () => {
    if (dropZoneInput.files.length) acceptFile(dropZoneInput.files[0]);
    dropZoneInput.value = '';
});

dropZoneElement.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZoneElement.classList.add('drop-zone--over');
});

['dragleave', 'dragend'].forEach((type) => {
    dropZoneElement.addEventListener(type, () => dropZoneElement.classList.remove('drop-zone--over'));
});

dropZoneElement.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZoneElement.classList.remove('drop-zone--over');
    if (e.dataTransfer.files.length) acceptFile(e.dataTransfer.files[0]);
});

function isTyping(target) {
    return target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName));
}

// Paste an image from the clipboard anywhere outside a text field.
document.addEventListener('paste', (event) => {
    if (isTyping(event.target) || document.querySelector('dialog[open]')) return;
    const item = Array.from((event.clipboardData && event.clipboardData.files) || []).find(f => f.type.startsWith('image/'));
    if (!item) return;
    event.preventDefault();
    const extension = item.type.split('/')[1].replace('jpeg', 'jpg');
    const named = item.name && item.name !== 'image.png' ? item : new File([item], `Pasted_Character.${extension}`, { type: item.type });
    if (acceptFile(named)) notify('Image pasted', 'success', 2);
});

// Show the raw generation data the image carries.
document.getElementById('info-icon').addEventListener('click', (event) => {
    event.stopPropagation();
    document.getElementById('metadata-text').textContent = globalThis.uncleaned_data || 'This image has no generation data.';
    openDialog('metadata-dialog');
});

document.getElementById('image-remove').addEventListener('click', (event) => {
    event.stopPropagation();
    clearImage();
});

function formatBytes(bytes) {
    return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
}

function acceptFile(file) {
    if (!ACCEPTED_TYPES.includes(file.type)) {
        notify(`${file.name} isn't a PNG, JPG or GIF.`, 'error');
        return false;
    }
    if (file.size > MAX_SIZE) {
        notify(`${file.name} is ${formatBytes(file.size)}; the limit is ${formatBytes(MAX_SIZE)}.`, 'error');
        return false;
    }
    updateThumbnail(file);
    return true;
}

function clearImage() {
    AE.imageDataUrl = null;
    AE.character = null;
    globalThis.image_data = null;
    globalThis.uncleaned_data = null;
    const thumbnail = document.getElementById('drop-zone-thumbnail-image');
    if (thumbnail) thumbnail.remove();
    document.querySelector('.drop-zone-prompt').hidden = false;
    document.getElementById('image-file-info').hidden = true;
    document.getElementById('image-remove').hidden = true;
    onCharacterChanged();
}

function updateThumbnail(file) {
    let thumbnailElement = document.getElementById('drop-zone-thumbnail-image');
    document.querySelector('.drop-zone-prompt').hidden = true;
    if (!thumbnailElement) {
        thumbnailElement = document.createElement('img');
        thumbnailElement.id = 'drop-zone-thumbnail-image';
        dropZoneElement.appendChild(thumbnailElement);
    }
    thumbnailElement.dataset.label = file.name;
    readFileAsDataUrl(file).then(dataUrl => {
        thumbnailElement.src = dataUrl;
        AE.imageDataUrl = dataUrl;
        thumbnailElement.onload = () => {
            const info = document.getElementById('image-file-info');
            info.textContent = `${file.name} · ${formatBytes(file.size)} · ${thumbnailElement.naturalWidth}×${thumbnailElement.naturalHeight}`;
            info.hidden = false;
        };
        document.getElementById('image-remove').hidden = false;
        uploadImage(file);
    });
}

async function uploadImage(file) {
    const outputDir = document.getElementById('output-directory');
    outputDir.value = file.name.trim().split('.').slice(0, -1).join('.') || file.name;
    AE.character = null;
    globalThis.uncleaned_data = null;
    const formData = new FormData();
    formData.append('file', file);
    try {
        const result = await apiRequest('/upload', { method: 'POST', body: formData });
        globalThis.image_data = result;
        globalThis.uncleaned_data = result.uncleaned_data && result.uncleaned_data !== 'None' ? result.uncleaned_data : null;
        const thumbnail = document.getElementById('drop-zone-thumbnail-image');
        if (thumbnail) thumbnail.title = globalThis.uncleaned_data || '';
        updateUI(result);
        if (result.character) {
            AE.character = result.character;
            outputDir.value = result.character.name;
        }
    } catch (error) {
        notify(`Could not read image metadata: ${messageOf(error)}`, 'error');
    }
    onCharacterChanged();
}

function updateUI(result) {
    const cleaned = result.cleaned_data;
    if (!cleaned) {
        notify("No generation parameters found in this image, so the model's usual settings are used.", 'info');
        if (result.width) setNumber('width', result.width);
        if (result.height) setNumber('height', result.height);
        reconcileWithWebUI();
        return;
    }
    if (cleaned.ad_checkpoint) setSelectValue('model-input', cleaned.ad_checkpoint);
    if (cleaned.ad_sampler) setSelectValue('sampler-input', cleaned.ad_sampler);
    if (cleaned.ad_scheduler) setSelectValue('scheduler-input', cleaned.ad_scheduler);
    document.getElementById('clip-skip-input').value = cleaned.ad_clip_skip;
    document.getElementById('seed-input').value = cleaned.seed;
    setNumber('steps', cleaned.ad_steps);
    setNumber('width', cleaned.width || result.width);
    setNumber('height', cleaned.height || result.height);
    setNumber('cfg-scale', cleaned.ad_cfg_scale);
    setNumber('denoising-strength', cleaned.ad_denoising_strength);
    document.getElementById('prompt-textfield').value = cleaned.ad_prompt || '';
    document.getElementById('negative-prompt-textfield').value = cleaned.ad_negative_prompt || '';
    const loras = Array.isArray(cleaned.loras) ? cleaned.loras.filter(l => l && typeof l.lora_name === 'string') : [];
    buildLoraSelect(AE.options.loras, loras.map(l => ({ lora_name: l.lora_name.trim(), lora_strength: l.lora_strength })));
    reconcileWithWebUI();
}
