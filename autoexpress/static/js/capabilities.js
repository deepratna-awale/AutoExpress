// What the connected WebUI has for AutoExpress, and step-by-step fixes for what's missing.

function capabilityElement(tag, className, text) {
    const element = document.createElement(tag);
    if (className) {
        element.className = className;
    }
    if (text !== undefined) {
        element.textContent = text;
    }
    return element;
}

function renderFix(fix) {
    const box = capabilityElement('div', 'capability-fix');
    if (fix.steps && fix.steps.length) {
        const steps = capabilityElement('ol');
        fix.steps.forEach(step => steps.appendChild(capabilityElement('li', '', step)));
        box.appendChild(steps);
    }
    (fix.commands || []).forEach(command => {
        const row = capabilityElement('div', 'capability-command');
        row.appendChild(capabilityElement('code', '', command));
        const copy = capabilityElement('button', '', 'Copy');
        copy.type = 'button';
        copy.addEventListener('click', () => {
            navigator.clipboard.writeText(command).then(() => {
                copy.textContent = 'Copied';
                setTimeout(() => { copy.textContent = 'Copy'; }, 1500);
            });
        });
        row.appendChild(copy);
        box.appendChild(row);
    });
    (fix.links || []).forEach(link => {
        const anchor = capabilityElement('a', 'capability-link', link.label);
        anchor.href = link.url;
        anchor.target = '_blank';
        anchor.rel = 'noopener noreferrer';
        box.appendChild(anchor);
    });
    return box;
}

function renderCapabilities(report, detectedName) {
    const panel = document.getElementById('capabilities');
    const list = document.getElementById('capabilities-list');
    const title = document.getElementById('capabilities-title');
    list.replaceChildren();

    let heading = report.name || 'WebUI';
    if (detectedName) {
        heading = 'Detected ' + detectedName;
    }
    title.textContent = heading + (report.ready ? ': ready' : ': needs setup');
    panel.classList.toggle('capabilities-ready', !!report.ready);

    (report.items || []).forEach(item => {
        const state = item.ok ? 'ok' : (item.required ? 'missing' : 'optional');
        const row = capabilityElement('li', 'capability capability-' + state);
        const summary = capabilityElement('div', 'capability-summary');
        summary.appendChild(capabilityElement('span', 'capability-mark', item.ok ? '✓' : (item.required ? '✗' : '!')));
        summary.appendChild(capabilityElement('span', 'capability-label', item.label));
        row.appendChild(summary);
        if (item.detail) {
            row.appendChild(capabilityElement('div', 'capability-detail', item.detail));
        }
        if (!item.ok && item.fix) {
            row.appendChild(renderFix(item.fix));
        }
        list.appendChild(row);
    });
    panel.hidden = false;
}

function checkCapabilities(detectedName) {
    const title = document.getElementById('capabilities-title');
    title.textContent = 'Checking the WebUI...';
    document.getElementById('capabilities').hidden = false;
    fetch('/backend/capabilities')
        .then(response => response.json())
        .then(report => renderCapabilities(report, detectedName))
        .catch(error => {
            console.error('Capability check failed:', error);
            title.textContent = 'Could not check the WebUI.';
        });
}

// Errors from connecting (unreachable, login refused, not a supported WebUI) as one capability row.
function showConnectionError(result) {
    const error = result.error || {};
    renderCapabilities({
        name: 'WebUI',
        ready: false,
        items: [{
            label: 'Connection',
            ok: false,
            required: true,
            detail: error.message || result.message || 'Could not connect.',
            fix: error.fix || null,
        }],
    });
}

document.getElementById('capabilities-recheck').addEventListener('click', () => checkCapabilities());
