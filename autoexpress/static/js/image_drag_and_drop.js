document.querySelectorAll("#drop-zone-input-field").forEach((inputElement) => {
    const dropZoneElement = inputElement.closest(".drop-zone");

    dropZoneElement.addEventListener("click", (e) => {
        inputElement.click();
    });

    inputElement.addEventListener("change", (e) => {
        if (inputElement.files.length) {
            updateThumbnail(dropZoneElement, inputElement.files[0]);
        }
    });

    dropZoneElement.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropZoneElement.classList.add("drop-zone--over");
    });

    ["dragleave", "dragend"].forEach((type) => {
        dropZoneElement.addEventListener(type, (e) => {
            dropZoneElement.classList.remove("drop-zone--over");
        });
    });

    dropZoneElement.addEventListener("drop", (e) => {
        e.preventDefault();

        if (e.dataTransfer.files.length) {
            inputElement.files = e.dataTransfer.files;
            updateThumbnail(dropZoneElement, e.dataTransfer.files[0]);
        }

        dropZoneElement.classList.remove("drop-zone--over");
    });
});

function updateThumbnail(dropZoneElement, file) {
    let thumbnailElement = dropZoneElement.querySelector("#drop-zone-thumbnail-image");

    // First time - remove the prompt
    if (dropZoneElement.querySelector("#upload-file-drop-zone")) {
        dropZoneElement.querySelector(".drop-zone-prompt").remove();
    }

    // First time - there is no thumbnail element, so let's create it
    if (!thumbnailElement) {
        thumbnailElement = document.createElement("img");
        thumbnailElement.id = "drop-zone-thumbnail-image";
        dropZoneElement.appendChild(thumbnailElement);
    }

    thumbnailElement.dataset.label = file.name;

    // Show thumbnail for image files
    if (file.type.startsWith("image/")) {
        const reader = new FileReader();

        reader.readAsDataURL(file);
        reader.onload = () => {
            thumbnailElement.src = reader.result;
            uploadImage(file);  // Call upload function after setting the src
        };
    } else {
        thumbnailElement.src = ""; // Clear the source if it's not an image
    }
}

function uploadImage(file) {
    const formData = new FormData();
    formData.append('file', file);

    fetch('/upload', {
        method: 'POST',
        body: formData,
    })
        .then(response => response.json())
        .then(data => {
            console.log('Upload successful. Recieved metadata for the image:', data)
            image_data = data;
            updateUI(data);
        })
        .catch(error => console.error('Error uploading file:', error));
}


function updateUI(data) {
    document.getElementById('lora-input').value = data.lora;
    document.getElementById('seed-input').value = data.seed;

    document.getElementById('prompt').value = data.ad_prompt;
    document.getElementById('negative_prompt').value = data.ad_negative_prompt;
    document.getElementById('model-input').value = data.ad_checkpoint;
    document.getElementById('sampler-input').value = data.ad_sampler;
    document.getElementById('clip-skip-input').value = data.ad_clip_skip;
    document.getElementById('width-input').value = data.ad_inpaint_width;
    document.getElementById('height-input').value = data.ad_inpaint_height;
    document.getElementById('cfg-scale-input').value = data.ad_cfg_scale;
    document.getElementById('denoising-strength-input').value = data.ad_denoising_strength;

}
