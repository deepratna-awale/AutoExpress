document.querySelector('.sd-connect').addEventListener('click', function () {
    var inputText = document.querySelector('#ip-input').value;  // Get the input value
    var button = this;

    // Create an XMLHttpRequest to send data
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/receive_data", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
            if (xhr.status === 200) {
                console.log('Data sent successfully');
                button.style.backgroundColor = 'grey';  // Set button background to grey
            } else {
                console.log('Failed to send data');
                button.style.backgroundColor = 'red';  // Set button background to red
            }
        }
    };
    var data = JSON.stringify({ text: inputText });
    xhr.send(data);

    // Function to handle empty dropdown data and clear previous options
    function handleEmptyData(models, dropdownId) {
        const dropdown = document.getElementById(dropdownId);
        // Clear existing options first
        while (dropdown.firstChild) {
            dropdown.removeChild(dropdown.firstChild);
        }
        // Set the button to red if no models are fetched
        if (models.length === 0) {
            button.style.backgroundColor = 'red';  // Set button background to red
        }
        
        // Populate dropdown with new data
        models.forEach(model => {
            const option = document.createElement('option');
            option.value = model;
            option.textContent = model;
            dropdown.appendChild(option);
        });
    }

    // Fetch models and populate dropdown
    fetch('/get-models')
        .then(response => response.json())
        .then(models => {
            handleEmptyData(models, 'model-input');
        })
        .catch(error => {
            console.error('Error loading models:', error);
            button.style.backgroundColor = 'red';  // Set button background to red
        });

    // Fetch samplers and populate dropdown
    fetch('/get-samplers')
        .then(response => response.json())
        .then(models => {
            handleEmptyData(models, 'sampler-input');
            button.style.backgroundColor = 'green';
        })
        .catch(error => {
            console.error('Error loading models:', error);
            button.style.backgroundColor = 'red';  // Set button background to red
        });

    // Fetch LORAs and populate dropdown
    fetch('/get-loras')
        .then(response => response.json())
        .then(models => {
            handleEmptyData(models, 'lora-input');
        })
        .catch(error => {
            console.error('Error loading models:', error);
            button.style.backgroundColor = 'red';  // Set button background to red
        });
});



document.querySelectorAll(".drop-zone__input").forEach((inputElement) => {
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
    let thumbnailElement = dropZoneElement.querySelector(".drop-zone__thumb");

    // First time - remove the prompt
    if (dropZoneElement.querySelector(".drop-zone__prompt")) {
        dropZoneElement.querySelector(".drop-zone__prompt").remove();
    }

    // First time - there is no thumbnail element, so let's create it
    if (!thumbnailElement) {
        thumbnailElement = document.createElement("img");
        thumbnailElement.classList.add("drop-zone__thumb");
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
            updateUI(data);
        })
        .catch(error => console.error('Error uploading file:', error));
}


function updateUI(data){
    document.getElementById('prompt').value = data.prompt;
    document.getElementById('negative_prompt').value = data.negative_prompt;
    document.getElementById('model-input').value = data.model;
    document.getElementById('lora-input').value = data.lora;
    document.getElementById('sampler-input').value = data.sampler;
    document.getElementById('seed-input').value = data.seed;
    document.getElementById('clip-skip-input').value = data.clip_skip;
    document.getElementById('width-input').value = data.width;
    document.getElementById('height-input').value = data.height;
    document.getElementById('cfg-scale-input').value = data.cfg_scale;
    document.getElementById('denoising-strength-input').value = data.denoising_strength;

}

// Function to update input value when slider changes
function updateInput(inputId) {
    const slider = document.getElementById(`${inputId}-slider`);
    const input = document.getElementById(`${inputId}-input`);
    input.value = slider.value;
}

// Function to update slider value when input changes
function updateSlider(inputId) {
    const slider = document.getElementById(`${inputId}-slider`);
    const input = document.getElementById(`${inputId}-input`);
    slider.value = input.value;
}

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
    var thumbnailElement = document.querySelector('.drop-zone__thumb');
    // Get the base64 string of the image, or an empty string if no image uploaded
    var thumbnailSrc = thumbnailElement ? thumbnailElement.src : "";

    var data = JSON.stringify({
        init_images: thumbnailSrc,
        prompt: document.getElementById('prompt').value,
        negative_prompt: document.getElementById('negative_prompt').value,
        steps: document.getElementById('steps-input').value,
        lora: document.getElementById('lora-input').value,
        ad_checkpoint: document.getElementById('model-input').value,
        ad_sampler: document.getElementById('sampler-input').value,
        seed: document.getElementById('seed-input').value,
        ad_clip_skip: document.getElementById('clip-skip-input').value,
        width: document.getElementById('width-input').value,
        height: document.getElementById('height-input').value,
        ad_cfg_scale: document.getElementById('cfg-scale-input').value,
        ad_denoising_strength: document.getElementById('denoising-strength-input').value,
    });

    xhr.send(data);
});


document.querySelector('.load-images').addEventListener('click', function () {
    let currentIndex = 0;
    let images = [];
    let fileNames = [];

    function loadImages() {
        const outputDir = document.getElementById('output-directory').value;

        fetch(`/images/${outputDir}`)
            .then(response => response.json())
            .then(files => {
                images = files.map(file => `/image/${outputDir}/${file}`);
                fileNames = files;  // Store just the file names
                currentIndex = 0; // Reset index when new images are loaded
                if (images.length > 0) {
                    displayImage(currentIndex);
                } else {
                    document.getElementById('image-display').src = "";
                    document.getElementById('image-name').textContent = "No images found.";
                }
            })
            .catch(error => {
                console.error('Error loading images:', error);
                alert('Failed to load images.');
            });
    }

    function navigate(direction) {
        if (images.length > 0) {
            currentIndex += direction;
            // Wrap around the navigation
            if (currentIndex < 0) {
                currentIndex = images.length - 1;
            } else if (currentIndex >= images.length) {
                currentIndex = 0;
            }
            displayImage(currentIndex);
        }
    }

    function displayImage(index) {
        document.getElementById('image-display').src = images[index];
        document.getElementById('image-name').textContent = fileNames[index];  // Update the file name
    }

    // Attach event listeners to navigation buttons
    document.querySelector('.nav-left').addEventListener('click', function () {
        navigate(-1); // Navigate left
    });

    document.querySelector('.nav-right').addEventListener('click', function () {
        navigate(1); // Navigate right
    });

    loadImages(); // Initial load of images
});

