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
    const fileName = file.name;
    const outputDir = document.getElementById('output-directory');
    outputDir.value = fileName.trim().split('.').slice(0, -1).join('.');
    formData.append('file', file);

    fetch('/upload', {
        method: 'POST',
        body: formData,
    })
        .then(response => response.json())
        .then(data => {
            console.log('Upload successful. Recieved metadata for the image:', data)
            const uncleaned_data = data.uncleaned_data;
            const image_data = data.cleaned_data;
            createInfoAlert(uncleaned_data);
            createImageHoverTooltip(uncleaned_data);
            updateUI(data);
        })
        .catch(error => console.error('Error uploading file:', error));
}


function createInfoAlert(uncleaned_data) {
    const element = document.getElementById("info-icon");

    // Show uncleaned data in an alert on click
    element.addEventListener('click', () => {
        alert(uncleaned_data);
    });
}


function createImageHoverTooltip(data) {
    const element = document.getElementById('drop-zone-thumbnail-image');

    // Show uncleaned data on hover
    element.addEventListener('mouseenter', () => {
        element.title = data; // Use title attribute to show data as tooltip
    });

    // Remove tooltip on mouse leave
    element.addEventListener('mouseleave', () => {
        element.removeAttribute('title');
    });
} 

function updateUI(data) {

    if (data.cleaned_data === null) {
        console.log("No data received from the server. Falling back to pillow metadata.");
        document.getElementById('width-input').value = data.width;
        document.getElementById('height-input').value = data.height;
        return;
    }
    data = data.cleaned_data;
    setDropdownValue('model-input', data.ad_checkpoint);
    setDropdownValue('sampler-input', data.ad_sampler);
    setDropdownValue('scheduler-input', data.ad_scheduler);

    
    document.getElementById('clip-skip-input').value = data.ad_clip_skip;
    document.getElementById('seed-input').value = data.seed;
    
    document.getElementById('steps-input').value = data.ad_steps;

    document.getElementById('width-input').value = data.width;
    document.getElementById('height-input').value = data.height;
    document.getElementById('cfg-scale-input').value = data.ad_cfg_scale;
    document.getElementById('denoising-strength-input').value = data.denoising_strength;
    
    document.getElementById('prompt-textfield').value = data.prompt;
    document.getElementById('negative-prompt-textfield').value = data.negative_prompt;
    
    // const multiSelectElement = document.querySelector('multi-select');
    // multiSelectElement.addLorawithStrength('vomcum', 0.7);
}


function setDropdownValue(elementId, dataValue) {
    const dropdown = document.getElementById(elementId);

    // Check if the dropdown exists
    if (!dropdown) {
        console.warn(`Dropdown with id "${elementId}" not found.`);
        return;
    }

    // Check if the option already exists in the dropdown
    let optionExists = Array.from(dropdown.options).some(option => option.value === dataValue);

    // If the option doesn't exist, add it to the dropdown
    if (!optionExists) {
        let newOption = new Option(dataValue, dataValue);
        dropdown.add(newOption);
    }

    // Set the dropdown value
    dropdown.value = dataValue;
}

