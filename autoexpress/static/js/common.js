// Shared helpers for the classic interface: API calls, notifications, small DOM builders.

class ApiError extends Error {
    constructor(message, status, body) {
        super(message);
        this.status = status;
        this.body = body;
    }

    get fix() {
        const error = this.body && this.body.error;
        return error && typeof error === 'object' && error.fix ? error.fix : null;
    }

    get code() {
        const error = this.body && this.body.error;
        return error && typeof error === 'object' && typeof error.code === 'string' ? error.code : '';
    }
}

function errorMessage(body) {
    if (!body || typeof body !== 'object') return '';
    if (typeof body.error === 'string') return body.error;
    if (body.error && typeof body.error.message === 'string') return body.error.message;
    return typeof body.message === 'string' ? body.message : '';
}

async function apiRequest(path, init) {
    const response = await fetch(path, init);
    let body = null;
    try {
        body = await response.json();
    } catch (e) {
        body = null;
    }
    if (!response.ok) {
        throw new ApiError(errorMessage(body) || `${response.status} ${response.statusText}`, response.status, body);
    }
    return body;
}

function apiPost(path, data, method = 'POST') {
    return apiRequest(path, {
        method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
    });
}

// null when the server is older and has no such endpoint.
async function apiOptional(promise) {
    try {
        return await promise;
    } catch (error) {
        if (error instanceof ApiError && (error.status === 404 || error.status === 405)) return null;
        throw error;
    }
}

function messageOf(error) {
    return error instanceof Error ? error.message : String(error);
}

function isActiveJob(job) {
    return !!job && (job.status === 'queued' || job.status === 'running');
}

function expressionName(file) {
    const name = String(file).replace(/\.[^.]+$/, '').replace(/_/g, ' ');
    return name.charAt(0).toUpperCase() + name.slice(1).toLowerCase();
}

// Same rule the /generate route uses to pick the output folder.
function resolveOutputDir(outputDirectory) {
    return String(outputDirectory || '').trim().replace(/\.[^.]*$/, '') || 'New_Character';
}

function encodePath(path) {
    return String(path).split('/').filter(Boolean).map(encodeURIComponent).join('/');
}

function remember(key, value) {
    try {
        localStorage.setItem(key, value);
    } catch (e) {
        // Storage can be blocked; the choice then lasts until reload.
    }
}

function recall(key) {
    try {
        return localStorage.getItem(key);
    } catch (e) {
        return null;
    }
}

function el(tag, attrs = {}, ...children) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
        if (value === undefined || value === null || value === false) continue;
        if (key === 'class') element.className = value;
        else if (key === 'text') element.textContent = value;
        else if (key.startsWith('on') && typeof value === 'function') element.addEventListener(key.slice(2), value);
        else if (value === true) element.setAttribute(key, '');
        else element.setAttribute(key, value);
    }
    for (const child of children.flat()) {
        if (child === null || child === undefined || child === false) continue;
        element.appendChild(typeof child === 'string' ? document.createTextNode(child) : child);
    }
    return element;
}

// Short notifications in the corner instead of alert(), which blocks the page.
function notify(message, kind = 'info', seconds = 5) {
    let area = document.getElementById('toasts');
    if (!area) {
        area = el('div', { id: 'toasts', class: 'toasts', role: 'status', 'aria-live': 'polite' });
        document.body.appendChild(area);
    }
    const toast = el('div', { class: `toast toast-${kind}` }, el('span', { text: message }));
    const close = el('button', { type: 'button', class: 'toast-close', 'aria-label': 'Dismiss', text: '×' });
    close.addEventListener('click', () => toast.remove());
    toast.appendChild(close);
    area.appendChild(toast);
    if (seconds) setTimeout(() => toast.remove(), seconds * 1000);
}

// A dialog built on <dialog>: openDialog(id) / closeDialog(id).
function openDialog(id) {
    const dialog = document.getElementById(id);
    if (dialog && !dialog.open) dialog.showModal();
}

function closeDialog(id) {
    const dialog = document.getElementById(id);
    if (dialog && dialog.open) dialog.close();
}

function readFileAsDataUrl(file) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result));
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });
}

// Close a <dialog> when its backdrop is clicked.
document.addEventListener('click', (event) => {
    if (event.target instanceof HTMLDialogElement && event.target.open) {
        const box = event.target.getBoundingClientRect();
        const inside = event.clientX >= box.left && event.clientX <= box.right && event.clientY >= box.top && event.clientY <= box.bottom;
        if (!inside) event.target.close();
    }
});

// Shared state the classic scripts read and write.
const AE = {
    imageDataUrl: null,
    character: null,
    job: null,
    galleryDir: '',
    images: [],
    currentIndex: 0,
    options: { models: [], samplers: [], schedulers: [], loras: [] },
    editMethods: null,
    familyDefaults: null,
    animationInfo: null,
    backgroundRemoval: null,
    login: null,
    connected: false,
};
