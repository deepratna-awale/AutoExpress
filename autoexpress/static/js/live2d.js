// Live2D model kit: pictures in, a ready-to-play puppet and a layered Cubism-ready PSD out.

const MAX_LIVE2D_PICTURES = 8;
const L2 = { info: null, pictures: [], reports: [], best: 0, chosen: null, loras: null, lora: null, job: null, busy: false };

function l2(id) {
    return document.getElementById(`l2-${id}`);
}

function l2Busy(text) {
    L2.busy = !!text;
    l2('busy').textContent = text ? `${text}...` : '';
    l2Update();
}

function l2Error(text) {
    l2('error').textContent = text || '';
    l2('error').hidden = !text;
}

async function openLive2D() {
    openDialog('live2d-dialog');
    l2Error('');
    try {
        L2.info = await apiOptional(apiRequest('/live2d'));
    } catch (error) {
        l2Error(messageOf(error));
    }
    const info = L2.info;
    const warning = l2('not-ready');
    warning.hidden = !info || info.ready;
    if (info && !info.ready) {
        warning.replaceChildren(...[
            el('p', { class: 'strong', text: info.message }),
            info.fix && info.fix.commands && info.fix.commands.length ? el('pre', { text: info.fix.commands.join('\n') }) : null,
            el('p', { class: 'muted', text: info.vram_note }),
        ].filter(Boolean));
    }
    if (info) {
        l2('resolution').value = String(info.defaults.resolution);
        const advice = info.advice;
        l2('advice').replaceChildren(
            el('summary', { text: advice.title }),
            el('ul', {}, ...advice.best.map(line => el('li', { text: line }))),
            el('p', { class: 'strong', text: 'Helps even more' }),
            el('ul', {}, ...advice.extras.map(line => el('li', { text: line }))),
            el('p', { class: 'strong', text: 'Avoid' }),
            el('ul', {}, ...advice.avoid.map(line => el('li', { text: line }))),
        );
        l2('advice').hidden = false;
    }
    l2Update();
}

async function addLive2DFiles(files) {
    l2Error('');
    const images = Array.from(files).filter(file => file.type.startsWith('image/'));
    const added = await Promise.all(images.map(async file => ({ name: file.name, dataUrl: await readFileAsDataUrl(file) })));
    L2.pictures = [...L2.pictures, ...added].slice(0, MAX_LIVE2D_PICTURES);
    L2.chosen = null;
    if (!l2('name').value && added[0]) l2('name').value = added[0].name.replace(/\.[^.]+$/, '');
    renderLive2DPictures();
    if (!L2.pictures.length) return;
    l2Busy('Checking the pictures');
    try {
        const result = await apiPost('/live2d/check', { images: L2.pictures.map(p => p.dataUrl) });
        L2.reports = result.reports;
        L2.best = result.best;
    } catch (error) {
        l2Error(messageOf(error));
    } finally {
        l2Busy(null);
        renderLive2DPictures();
    }
}

function renderLive2DPictures() {
    const grid = l2('pictures');
    const picked = L2.chosen ?? L2.best;
    if (!L2.pictures.length) {
        grid.replaceChildren(el('p', { class: 'muted l2-empty', text: 'Drop pictures here' }));
    } else {
        grid.replaceChildren(...L2.pictures.map((picture, index) => {
            const report = L2.reports[index];
            const remove = el('span', { class: 'l2-remove', role: 'button', tabindex: '0', 'aria-label': 'Remove', text: '×' });
            remove.addEventListener('click', (event) => {
                event.stopPropagation();
                L2.pictures.splice(index, 1);
                L2.reports.splice(index, 1);
                L2.chosen = null;
                L2.best = 0;
                renderLive2DPictures();
            });
            const card = el('button', { type: 'button', class: `l2-picture${index === picked ? ' l2-picked' : ''}` },
                el('img', { src: picture.dataUrl, alt: picture.name }),
                remove,
                report ? el('span', { class: 'muted', text: `Score ${report.score}${index === picked ? ' · used' : ''}` }) : null);
            card.addEventListener('click', () => {
                L2.chosen = index;
                renderLive2DPictures();
            });
            return card;
        }));
    }
    const report = L2.reports[picked];
    l2('checks').replaceChildren(...(report ? report.checks.map(check => el('li', { class: check.ok ? 'check-ok' : `check-${check.level}` },
        el('span', { class: 'check-mark', text: check.ok ? '✓' : '!' }), el('span', { text: check.message }))) : []));
    l2('add').disabled = L2.pictures.length >= MAX_LIVE2D_PICTURES;
    l2Update();
}

async function findCharacterLora() {
    const name = l2('name').value.trim();
    if (!name) return;
    l2Busy('Looking for a character LoRA on Civitai');
    l2Error('');
    try {
        const result = await apiPost('/live2d/character-lora', { name });
        L2.loras = result.results;
        L2.lora = result.results.find(r => r.installed_name) || null;
    } catch (error) {
        l2Error(messageOf(error));
    } finally {
        l2Busy(null);
        renderCharacterLoras();
    }
}

function renderCharacterLoras() {
    const box = l2('loras');
    if (!L2.loras) {
        box.replaceChildren();
        return;
    }
    if (!L2.loras.length) {
        box.replaceChildren(el('p', { class: 'muted', text: 'No character LoRA found. The edits work from the pictures alone.' }));
        return;
    }
    box.replaceChildren(...L2.loras.map(result => {
        const using = L2.lora && L2.lora.entry.name === result.entry.name;
        const use = el('button', { type: 'button', class: using ? 'primary-button' : '', disabled: !result.installed_name, text: using ? 'Using' : 'Use' });
        use.addEventListener('click', () => {
            L2.lora = using ? null : result;
            renderCharacterLoras();
        });
        return el('div', { class: 'l2-lora' },
            el('div', {},
                el('a', { href: result.page, target: '_blank', rel: 'noreferrer', text: result.entry.title }),
                el('span', { class: 'muted', text: ` ${result.entry.base_model || ''}` }),
                el('p', { class: 'muted', text: result.installed_name ? `On the WebUI as ${result.installed_name}` : (result.install && result.install.message) || '' })),
            use);
    }));
}

function l2Checked(id) {
    return l2(id).checked;
}

// Switches that depend on others, and whether the kit can be built.
function l2Update() {
    const undress = l2Checked('undress');
    const outfits = l2Checked('outfits');
    l2('neutral-pose').disabled = undress;
    if (undress) l2('neutral-pose').checked = false;
    l2('outfits').disabled = undress;
    if (undress) l2('outfits').checked = false;
    l2('expression-art').disabled = !l2Checked('variants');
    l2('outer-row').hidden = !l2Checked('clothing-slots');
    l2('adult-box').hidden = !(outfits || undress);
    l2('inner-row').hidden = !outfits;
    const running = isActiveJob(L2.job);
    l2('build').disabled = !L2.pictures.length || L2.busy || running || (L2.info !== null && !L2.info.ready) || (outfits && !l2Checked('adult'));
    l2('cancel').hidden = !running;
}

['undress', 'outfits', 'variants', 'clothing-slots', 'adult'].forEach(id => l2(id).addEventListener('change', l2Update));

async function buildLive2DKit() {
    l2Error('');
    l2Busy('Starting');
    const outfits = l2Checked('outfits');
    const undress = l2Checked('undress');
    const description = l2('description').value.trim();
    const innerWear = l2('inner').value.trim();
    const outfit = l2('outfit').value.trim();
    const outer = l2('outer').value.trim();
    try {
        const response = await apiPost('/live2d', {
            images: L2.pictures.map(p => p.dataUrl),
            name: l2('name').value.trim() || 'character',
            wait: false,
            settings: {
                resolution: Number(l2('resolution').value),
                low_vram: l2Checked('low-vram'),
                variants: l2Checked('variants') ? 'auto' : 'none',
                outfit_layers: outfits,
                undress_chain: undress,
                adult_confirmed: (outfits || undress) && l2Checked('adult'),
                ...((outfits || undress) && description ? { character_description: description } : {}),
                ...(outfits && innerWear ? { inner_wear: innerWear } : {}),
                ...(outfit ? { outfit_prompt: outfit } : {}),
                ...(l2Checked('clothing-slots') && outer ? { outer_garment: outer } : {}),
                use_prompt_data: l2Checked('prompt-data'),
                clothing_slots: l2Checked('clothing-slots'),
                expression_art: l2Checked('expression-art') && l2Checked('variants'),
                neutral_pose: l2Checked('neutral-pose') && !undress,
                ...(L2.chosen !== null ? { base_index: L2.chosen } : {}),
            },
            character_lora: L2.lora ? { entry: L2.lora.entry, installed_name: L2.lora.installed_name } : null,
        });
        if (response.job) followLive2DJob(response.job);
    } catch (error) {
        l2Error(messageOf(error));
    } finally {
        l2Busy(null);
    }
}

function followLive2DJob(job) {
    L2.job = job;
    renderLive2DJob();
    if (!isActiveJob(job)) return;
    setTimeout(async () => {
        try {
            followLive2DJob(await apiRequest(`/jobs/${encodeURIComponent(job.id)}`));
        } catch (error) {
            l2Error(messageOf(error));
            setTimeout(() => followLive2DJob(job), 4000);
        }
    }, 2000);
}

function renderLive2DJob() {
    const job = L2.job;
    const running = isActiveJob(job);
    l2('progress').hidden = !running;
    if (running) {
        l2('progress').querySelector('.progress-fill').style.width = `${Math.round((job.progress.fraction || 0) * 100)}%`;
        l2('progress').querySelector('.progress-text').textContent = job.progress.current || job.status;
    }
    if (job && job.status === 'failed') l2Error(job.error && job.error.message);
    const kit = job && job.live2d;
    const result = l2('result');
    result.hidden = !kit;
    if (kit) {
        const link = (href, text, primary, download = true) => el('a', { class: `button-link${primary ? ' primary-button' : ''}`, href, download, target: download ? null : '_blank', rel: 'noreferrer', text });
        result.replaceChildren(...[
            el('div', { class: 'l2-downloads' },
                kit.puppet_zip ? link(kit.puppet_zip, 'Puppet (.zip)', true) : null,
                kit.puppet_preview ? link(kit.puppet_preview, 'Try the puppet', false, false) : null,
                link(kit.zip, 'Kit (.zip)', !kit.puppet_zip),
                link(kit.psd, 'Cubism PSD'),
                link(kit.seethrough_psd, 'See-through PSD')),
            kit.puppet_zip ? el('p', { class: 'muted', text: 'The puppet plays right away in SillyTavern: unzip it into assets/live2d and pick its .puppet.model.json in the Live2D extension (the AutoExpress extension must be installed too). The kit is for making a full Live2D model in Cubism Editor.' }) : null,
            el('p', { text: `${kit.layers} layers in ${kit.groups.length} parts: ${kit.groups.join(', ')}.${kit.switches.length ? ` Hidden for blinking and talking: ${kit.switches.map(s => s.layer).join(', ')}.` : ''}` }),
            ...[...kit.missing.map(m => m.message), ...kit.notes].map(line => el('p', { class: 'check-warning', text: `! ${line}` })),
            el('div', { class: 'l2-previews' },
                el('img', { src: kit.preview, alt: 'Reassembled layers', class: 'checkerboard' }),
                el('img', { src: kit.sheet, alt: 'Every layer' })),
            el('p', { class: 'muted', text: 'Open the PSD in Live2D Cubism Editor to rig it (the README in the kit walks through it), or drop the See-through PSD into StretchyStudio for an instant rig. After exporting from Cubism, add the 28 emotions with python -m autoexpress_core.live2d attach <model folder>.' }),
        ].filter(Boolean));
    }
    l2Update();
}

l2('add').addEventListener('click', () => l2('files').click());
l2('files').addEventListener('change', (event) => {
    addLive2DFiles(event.target.files);
    event.target.value = '';
});
l2('pictures').addEventListener('dragover', (event) => event.preventDefault());
l2('pictures').addEventListener('drop', (event) => {
    event.preventDefault();
    addLive2DFiles(event.dataTransfer.files);
});
l2('find-lora').addEventListener('click', findCharacterLora);
l2('build').addEventListener('click', buildLive2DKit);
l2('cancel').addEventListener('click', async () => {
    if (!L2.job) return;
    try {
        await apiPost(`/jobs/${encodeURIComponent(L2.job.id)}/cancel`, {});
        L2.job = await apiRequest(`/jobs/${encodeURIComponent(L2.job.id)}`);
        renderLive2DJob();
    } catch (error) {
        l2Error(messageOf(error));
    }
});
l2('close').addEventListener('click', () => closeDialog('live2d-dialog'));
document.getElementById('live2d-open').addEventListener('click', openLive2D);
renderLive2DPictures();
