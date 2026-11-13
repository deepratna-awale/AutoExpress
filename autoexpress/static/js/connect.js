var multiSelectElement = null;
let image_data = null;

const AUTH_ERROR = 'backend_auth';
const SETTINGS_KEY = 'autoexpress-classic-connection';
const connectButton = document.querySelector('.sd-connect');
const urlInput = document.querySelector('#ip-input');
const backendSelect = document.querySelector('#backend-input');

// The URL without a user:password@ part, so a password never lands in browser storage.
function stripCredentials(url) {
    return url.replace(/^([a-z][a-z0-9+.-]*:\/\/)?[^/@\s]*@/i, (_, scheme) => scheme || '');
}

// Show the selected WebUI's usual address as the URL placeholder. The WebUI can be anywhere:
// this machine, the LAN, or a hosted proxy URL with https and a sub-path.
var anyUrlPlaceholder = urlInput.placeholder;
function updateUrlPlaceholder() {
    var option = backendSelect.options[backendSelect.selectedIndex];
    var defaultUrl = option && option.dataset.defaultUrl;
    urlInput.placeholder = defaultUrl
        ? defaultUrl.replace(/127\.0\.0\.1/, 'host') + ' or an https proxy URL'
        : anyUrlPlaceholder;
}

function saveConnection() {
    remember(SETTINGS_KEY, JSON.stringify({ apiUrl: stripCredentials(urlInput.value), backend: backendSelect.value }));
}

backendSelect.addEventListener('change', function () {
    updateUrlPlaceholder();
    setConnectState('idle');
    document.getElementById('detected-backend').hidden = true;
    saveConnection();
});
urlInput.addEventListener('change', saveConnection);
updateUrlPlaceholder();

function setConnectState(state) {
    connectButton.classList.remove('connect-ok', 'connect-error', 'connect-busy');
    if (state === 'connected') connectButton.classList.add('connect-ok');
    if (state === 'error') connectButton.classList.add('connect-error');
    if (state === 'connecting') connectButton.classList.add('connect-busy');
    connectButton.disabled = state === 'connecting';
    AE.connected = state === 'connected';
}

// --- Login ---------------------------------------------------------------------------------------

const loginFields = {
    username: document.getElementById('login-username'),
    password: document.getElementById('login-password'),
    token: document.getElementById('login-token'),
    headers: document.getElementById('login-headers'),
};
const loginDetails = document.getElementById('login-details');
let loginTyped = {};

Object.entries(loginFields).forEach(([key, input]) => {
    input.addEventListener('input', () => { loginTyped[key] = true; });
});

function hasLogin(login) {
    return !!login && (!!login.username || login.password || login.token || (login.headers || []).length > 0);
}

// Show which login the server keeps for the WebUI. It never sends a secret back, only whether each is set.
function showLogin(login) {
    AE.login = login || null;
    const saved = hasLogin(login);
    document.getElementById('login-set').hidden = !saved;
    document.getElementById('login-forget').hidden = !saved;
    if (!loginTyped.username) loginFields.username.value = (login && login.username) || '';
    loginFields.password.placeholder = login && login.password ? 'Saved' : '';
    loginFields.token.placeholder = login && login.token ? "Saved (empty keeps it)" : "Bearer token, or SwarmUI's swarm_token";
    loginFields.headers.placeholder = login && login.headers && login.headers.length
        ? `Saved: ${login.headers.join(', ')}. Typing here replaces them.`
        : 'One per line, e.g.\nCF-Access-Client-Id: ...\nCF-Access-Client-Secret: ...';
}

function setLoginNeeded(needed) {
    document.getElementById('login-needed').hidden = !needed;
    if (needed) loginDetails.open = true;
}

// Login fields the user changed since the last connect. Empty secret fields keep the saved ones.
function loginInput() {
    const input = {};
    if (loginTyped.username) input.username = loginFields.username.value.trim();
    if (loginFields.password.value) input.password = loginFields.password.value;
    if (loginFields.token.value.trim()) input.token = loginFields.token.value.trim();
    if (loginFields.headers.value.trim()) input.headers = loginFields.headers.value;
    return input;
}

function clearLoginSecrets() {
    loginFields.password.value = '';
    loginFields.token.value = '';
    loginFields.headers.value = '';
    loginTyped = {};
}

document.getElementById('login-connect').addEventListener('click', () => connectWebUI(loginInput()));
document.getElementById('login-forget').addEventListener('click', () => connectWebUI({ forget_login: true }));

// --- LoRAs ----------------------------------------------------------------------------------------

// The LoRAs picked in the list, with their strengths.
function selectedLoras() {
    return Array.from(document.querySelectorAll('.multi-select-header-option-row')).map(row => ({
        lora_name: row.querySelector('.lora-name').textContent,
        lora_strength: row.querySelector('.lora-strength').value,
    }));
}

// (Re)build the LoRA list: the WebUI's LoRAs plus any picked ones it doesn't list.
function buildLoraSelect(names, selections) {
    const all = names.slice();
    selections.forEach(lora => { if (!all.includes(lora.lora_name)) all.push(lora.lora_name); });
    let target = document.getElementById('lora-input');
    if (!target && multiSelectElement) {
        target = el('select', { id: 'lora-input', class: 'dropdown', name: 'lora-input' });
        multiSelectElement.element.replaceWith(target);
    }
    multiSelectElement = new MultiSelect(target, {
        data: all.map(name => ({ value: name, text: name })),
        placeholder: 'Select Lora(s)',
        selectAll: false,
        search: true,
        listAll: false,
    });
    selections.forEach(lora => multiSelectElement.addLoraWithStrength(lora.lora_name, lora.lora_strength));
}

// --- Connecting ----------------------------------------------------------------------------------

function fillDropdown(dropdownId, values) {
    const dropdown = document.getElementById(dropdownId);
    const current = dropdown.value;
    dropdown.replaceChildren(new Option('', ''));
    values.forEach(value => dropdown.add(new Option(value, value)));
    if (current) setSelectValue(dropdownId, current);
}

async function stringList(path) {
    const data = await apiRequest(path);
    return Array.isArray(data) ? data.filter(item => typeof item === 'string') : [];
}

async function loadListings() {
    const [models, samplers, schedulers, loras] = await Promise.all([
        stringList('/get-models'),
        stringList('/get-samplers'),
        stringList('/get-schedulers'),
        stringList('/get-loras'),
    ]);
    AE.options = { models, samplers, schedulers, loras };
    fillDropdown('model-input', models);
    fillDropdown('sampler-input', samplers);
    fillDropdown('scheduler-input', schedulers);

    buildLoraSelect(loras, selectedLoras());
    return models;
}

async function connectWebUI(login) {
    setConnectState('connecting');
    try {
        const result = await apiPost('/receive_data', { text: urlInput.value.trim(), backend: backendSelect.value, ...(login || {}) });
        if (result.login) showLogin(result.login);
        clearLoginSecrets();
        setLoginNeeded(false);
        if (result.url) urlInput.value = result.url;
        saveConnection();
        const detected = document.getElementById('detected-backend');
        detected.hidden = !(result.detected && result.name);
        detected.querySelector('b').textContent = result.name || '';

        const models = await loadListings();
        reconcileWithWebUI();
        loadEditMethods();
        loadFeatureInfo();
        if (models.length === 0) {
            setConnectState('error');
            notify('Connected, but the WebUI returned no models. Is it running with its API enabled?', 'error');
        } else {
            setConnectState('connected');
            notify(`Connected${result.detected && result.name ? ' to ' + result.name : ''}: ${models.length} models, ${AE.options.loras.length} LoRAs`, 'success');
        }
        checkCapabilities(result.detected ? result.name : null);
        if (globalThis.image_data) updateUI(globalThis.image_data);
        return true;
    } catch (error) {
        setConnectState('error');
        document.getElementById('detected-backend').hidden = true;
        if (error instanceof ApiError) {
            showConnectionError(error.body || { message: error.message });
            if (error.code === AUTH_ERROR) setLoginNeeded(true);
        }
        notify(`Could not connect: ${messageOf(error)}`, 'error');
        return false;
    }
}

connectButton.addEventListener('click', () => connectWebUI(loginInput()));
urlInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') connectWebUI(loginInput());
});

// Restore the last address, then what the server is already connected to.
(function restoreConnection() {
    try {
        const saved = JSON.parse(recall(SETTINGS_KEY) || 'null');
        if (saved && saved.apiUrl) urlInput.value = stripCredentials(saved.apiUrl);
        if (saved && saved.backend && Array.from(backendSelect.options).some(o => o.value === saved.backend)) {
            backendSelect.value = saved.backend;
            updateUrlPlaceholder();
        }
    } catch (e) {
        // Storage unavailable
    }
    apiOptional(apiRequest('/backends')).then(data => {
        if (!data) return;
        if (data.login) showLogin(data.login);
        if (data.url && !urlInput.value) urlInput.value = data.url;
    }).catch(() => {});
})();
