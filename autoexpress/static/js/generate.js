document.querySelector('.generate-button').addEventListener('click', function () {
    // Create an XMLHttpRequest to send data
    var xhr = new XMLHttpRequest();

    xhr.open("POST", "/generate", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onreadystatechange = function () {

        if (xhr.readyState === 4 && xhr.status === 200) {
            console.log('Data sent successfully');
        } else if (xhr.readyState === 4) {
            console.log('Failed to send data');
        }
    };

    // Get the thumbnail element
    var thumbnailElement = document.querySelector('#drop-zone-thumbnail-image');
    // Get the base64 string of the image, or an empty string if no image uploaded
    var thumbnailSrc = thumbnailElement ? thumbnailElement.src : "";

    var data = JSON.stringify({
        init_images: thumbnailSrc,
        output_dir: document.getElementById('output-directory').value,
        ad_inpaint_width: document.getElementById('width-input').value,
        ad_inpaint_height: document.getElementById('height-input').value,
        lora: document.getElementById('lora-input').value,
        seed: document.getElementById('seed-input').value,
        ad_prompt: document.getElementById('prompt_textfield').value,
        ad_negative_prompt: document.getElementById('negative_prompt_textfield').value,
        ad_steps: document.getElementById('steps-input').value,
        ad_checkpoint: document.getElementById('model-input').value,
        ad_sampler: document.getElementById('sampler-input').value,
        ad_clip_skip: document.getElementById('clip-skip-input').value,
        ad_cfg_scale: document.getElementById('cfg-scale-input').value,
        ad_denoising_strength: document.getElementById('denoising-strength-input').value,
    });

    xhr.send(data);
});