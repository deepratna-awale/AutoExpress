// The gallery of a character's expressions: the animated sprite when there is one, else the PNG.

const SPRITE_RANK = ['.webp', '.apng', '.gif', '.png'];
let galleryVersion = 0;

function loadImagesInput(event) {
    if (event.key === 'Enter') loadImages();
}

// One file per expression, the animated one first.
function spriteFiles(files) {
    const byStem = new Map();
    const rank = name => SPRITE_RANK.indexOf(name.slice(name.lastIndexOf('.')).toLowerCase());
    files.forEach(file => {
        if (typeof file !== 'string' || rank(file) < 0) return;
        const stem = file.replace(/\.[^.]+$/, '');
        const current = byStem.get(stem);
        if (!current || rank(file) < rank(current)) byStem.set(stem, file);
    });
    return [...byStem.values()].sort();
}

async function loadImages(dir, refresh = true) {
    const target = resolveOutputDir(dir === undefined ? document.getElementById('output-directory').value : dir);
    const keep = AE.images[AE.currentIndex];
    try {
        let files = [];
        try {
            files = await apiRequest(`/images/${encodePath(target)}`);
        } catch (error) {
            if (!(error instanceof ApiError && error.status === 404)) throw error;
        }
        const changedDir = target !== AE.galleryDir;
        AE.galleryDir = target;
        AE.images = spriteFiles(Array.isArray(files) ? files : []);
        // Expressions overwrite files with the same names, so bust the browser cache.
        if (refresh) galleryVersion = Date.now();
        const stay = changedDir ? -1 : AE.images.indexOf(keep);
        AE.currentIndex = stay >= 0 ? stay : 0;
        document.getElementById('gallery-dir').textContent = `Output/${target}`;
        displayImage(AE.currentIndex);
    } catch (error) {
        notify(`Failed to load images: ${messageOf(error)}`, 'error');
    }
}

function navigate(direction) {
    if (!AE.images.length) return;
    AE.currentIndex = (AE.currentIndex + direction + AE.images.length) % AE.images.length;
    displayImage(AE.currentIndex);
}

function currentExpression() {
    const file = AE.images[AE.currentIndex];
    return file ? file.replace(/\.[^.]+$/, '') : null;
}

function displayImage(index) {
    const image = document.getElementById('image-display');
    const name = document.getElementById('expression-image-name');
    const count = document.getElementById('gallery-count');
    const retry = document.getElementById('retry-button');
    if (!AE.images.length) {
        image.removeAttribute('src');
        image.style.display = 'none';
        name.textContent = generating
            ? 'Waiting for the first expression...'
            : AE.galleryDir ? `No images found in Output/${AE.galleryDir}.` : '';
        count.textContent = '0 images';
        retry.hidden = true;
        return;
    }
    const file = AE.images[index];
    image.src = `/image/${encodePath(AE.galleryDir)}/${encodeURIComponent(file)}${galleryVersion ? `?v=${galleryVersion}` : ''}`;
    image.alt = expressionName(file);
    name.textContent = expressionName(file);
    count.textContent = `${index + 1} of ${AE.images.length}`;
    retry.hidden = false;
    retry.title = `Retry ${expressionName(file)}, optionally with its own prompt and settings`;
    retry.setAttribute('aria-label', `Retry ${expressionName(file)}`);
}

document.querySelector('.nav-left').addEventListener('click', () => navigate(-1));
document.querySelector('.nav-right').addEventListener('click', () => navigate(1));
document.querySelector('.load-images').addEventListener('click', () => loadImages());
document.querySelector('#output-directory').addEventListener('change', () => loadImages());
document.getElementById('retry-button').addEventListener('click', () => openExpressionSettings(currentExpression()));

document.addEventListener('keydown', (event) => {
    if (isTyping(event.target) || document.querySelector('dialog[open]')) return;
    if (event.key === 'ArrowLeft') navigate(-1);
    else if (event.key === 'ArrowRight') navigate(1);
});
