// The button's text node (it also holds an icon).
function setButtonText(button, text) {
    const node = Array.from(button.childNodes).find(n => n.nodeType === Node.TEXT_NODE && n.textContent.trim());
    if (node) {
        node.textContent = ' ' + text + ' ';
    }
}

// Follow a queued job until it finishes, showing progress on the generate button.
function followJob(jobId, button) {
    const label = 'Generate';
    const poll = () => {
        fetch(`/jobs/${jobId}`)
            .then(response => response.json())
            .then(job => {
                const p = job.progress || {};
                const text = job.status === 'queued' ? 'Queued' : `${p.done || 0}/${p.total || 0}`;
                setButtonText(button, text);
                button.setAttribute('title', p.current ? `Generating ${p.current}` : job.status);
                button.style.opacity = job.status === 'running' || job.status === 'queued' ? 0.6 : 1;
                if (p.done > 0 && typeof loadImages === 'function' && document.getElementById('output-directory').value) {
                    loadImages();
                }
                if (job.status === 'queued' || job.status === 'running') {
                    setTimeout(poll, 1500);
                    return;
                }
                setButtonText(button, label);
                button.removeAttribute('title');
                if (job.status === 'failed' && job.error) {
                    // e.g. ADetailer or the ComfyUI Impact Pack is missing on the selected WebUI
                    alert(job.error.message);
                }
            })
            .catch(error => {
                console.error('Lost track of the job:', error);
                setTimeout(poll, 5000);
            });
    };
    poll();
}

document.querySelector('.generate-button').addEventListener('click', function () {
    var button = this;
    // Create an XMLHttpRequest to send data
    var xhr = new XMLHttpRequest();

    xhr.open("POST", "/generate", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onreadystatechange = function () {
        if (xhr.readyState !== 4) {
            return;
        }
        var result = {};
        try {
            result = JSON.parse(xhr.responseText || '{}');
        } catch (e) {
            console.error('Unexpected response', xhr.responseText);
        }
        if (xhr.status === 202 && result.job_id) {
            followJob(result.job_id, button);
        } else if (result.status === 'Failed') {
            // Invalid input, or the WebUI is not ready
            alert(result.message);
        } else {
            console.log('Failed to send data');
        }
    };

    // Get the thumbnail element
    var thumbnailElement = document.querySelector('#drop-zone-thumbnail-image');
    // Get the base64 string of the image, or an empty string if no image uploaded
    var thumbnailSrc = thumbnailElement ? thumbnailElement.src : "";
    const loraInputElements = document.querySelectorAll('.multi-select-header-option-row');
    let loras = [];
    loras = Array.from(loraInputElements).map(loraElement => {
        const loraName = loraElement.querySelector('.lora-name').textContent;
        const loraStrength = loraElement.querySelector('.lora-strength').value;
        return { lora_name: loraName, lora_strength: loraStrength };
    }).filter(Boolean);


    console.log(loras);


    var data = JSON.stringify({
        init_images: thumbnailSrc,
        output_dir: document.getElementById('output-directory').value,
        wait: false,
        method: document.getElementById('edit-method-input').value,
        ad_scheduler: document.getElementById('scheduler-input').value,
        loras: loras,
        seed: document.getElementById('seed-input').value,
        ad_prompt: document.getElementById('prompt-textfield').value,
        ad_negative_prompt: document.getElementById('negative-prompt-textfield').value,
        ad_steps: document.getElementById('steps-input').value,
        ad_checkpoint: document.getElementById('model-input').value,
        ad_sampler: document.getElementById('sampler-input').value,
        ad_clip_skip: document.getElementById('clip-skip-input').value,
        ad_cfg_scale: document.getElementById('cfg-scale-input').value,
        ad_denoising_strength: document.getElementById('denoising-strength-input').value,
        // ad_inpaint_width: document.getElementById('width-input').value,
        // ad_inpaint_height: document.getElementById('height-input').value,
    });

    xhr.send(data);
});