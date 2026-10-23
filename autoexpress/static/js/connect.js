
var multiSelectElement = null;
let image_data = null;

// Show the selected WebUI's usual address as the URL placeholder. The WebUI can be anywhere:
// this machine, the LAN, or a hosted proxy URL with https and a sub-path.
var anyUrlPlaceholder = document.querySelector('#ip-input').placeholder;
function updateUrlPlaceholder() {
    var backendSelect = document.querySelector('#backend-input');
    var option = backendSelect.options[backendSelect.selectedIndex];
    var defaultUrl = option && option.dataset.defaultUrl;
    document.querySelector('#ip-input').placeholder = defaultUrl
        ? defaultUrl.replace(/127\.0\.0\.1/, 'host') + ' or an https proxy URL'
        : anyUrlPlaceholder;
}

document.querySelector('#backend-input').addEventListener('change', function () {
    updateUrlPlaceholder();
    document.querySelector('.sd-connect').style.backgroundColor = '';
});
updateUrlPlaceholder();

document.querySelector('.sd-connect').addEventListener('click', function () {
    var inputText = document.querySelector('#ip-input').value;  // Get the input value
    var backend = document.querySelector('#backend-input').value;
    var button = this;

    // Create an XMLHttpRequest to send data
    var xhr = new XMLHttpRequest();
    xhr.open("POST", "/receive_data", true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.onreadystatechange = function () {
        if (xhr.readyState === 4) {
            var result = {};
            try {
                result = JSON.parse(xhr.responseText || '{}');
            } catch (e) {
                result = {};
            }
            if (xhr.status === 200) {
                console.log('Connected to ' + (result.name || 'the WebUI'));
                button.style.backgroundColor = 'grey';  // Set button background to grey
                loadListings();
                loadEditMethods();
                checkCapabilities(result.detected ? result.name : null);
            } else {
                console.log('Failed to connect', result);
                button.style.backgroundColor = 'red';  // Set button background to red
                showConnectionError(result);
            }
        }
    };

    var data = JSON.stringify({ text: inputText, backend: backend });
    xhr.send(data);

    // Function to handle empty dropdown data and clear previous options
    function handleEmptyData(models, dropdownId, required = true) {
        const dropdown = document.getElementById(dropdownId);
        // Clear existing options first
        while (dropdown.firstChild) {
            dropdown.removeChild(dropdown.firstChild);
        }
        // Set the button to red if no models are fetched
        if (models.length === 0 && required) {
            button.style.backgroundColor = 'red';  // Set button background to red
        }

        // Create 1 blank option
        const option = document.createElement('option');
        option.value = "";
        option.textContent = "";
        dropdown.appendChild(option);

        // Populate dropdown with new data
        models.forEach(model => {
            const option = document.createElement('option');
            option.value = model;
            option.textContent = model;
            dropdown.appendChild(option);
        });
    }

    // Fill the dropdowns once the server has switched to the selected WebUI.
    function loadListings() {
        // Fetch models and populate dropdown
        fetch('/get-models')
            .then(response => response.json())
            .then(models => {
                handleEmptyData(models, 'model-input');
                button.style.backgroundColor = 'green';
                if (image_data != null) {
                    document.getElementById('model-input').value = image_data.ad_checkpoint;
                }
            })
            .catch(error => {
                console.error('Error loading models:', error);
                button.style.backgroundColor = 'red';  // Set button background to red
            });


        // Fetch schedulers and populate dropdown
        fetch('/get-samplers')
            .then(response => response.json())
            .then(models => {
                handleEmptyData(models, 'sampler-input');
                button.style.backgroundColor = 'green';
                if (image_data != null) {
                    document.getElementById('sampler-input').value = image_data.ad_sampler;
                }
            })
            .catch(error => {
                console.error('Error loading models:', error);
                button.style.backgroundColor = 'red';  // Set button background to red
            });

        // Fetch schedulers and populate dropdown
        fetch('/get-schedulers')
            .then(response => response.json())
            .then(models => {
                handleEmptyData(models, 'scheduler-input', false);
                button.style.backgroundColor = 'green';
                if (image_data != null) {
                    document.getElementById('scheduler-input').value = image_data.ad_scheduler;
                }
            })
            .catch(error => {
                console.error('Error loading models:', error);
                button.style.backgroundColor = 'red';  // Set button background to red
            });

        // Fetch LORAs and populate dropdown
        fetch('/get-loras')
            .then(response => response.json())
            .then(models => {
                const multiSelectData = models.map(model => ({
                    value: model,
                    text: model
                }));

                multiSelectElement = new MultiSelect('#lora-input', {
                    data: multiSelectData, // Array of model names
                    placeholder: 'Select Lora(s)',
                    selectAll: false,
                    search: true,
                    listAll: false,
                });


            })
            .catch(error => {
                console.error('Error loading models:', error);
                button.style.backgroundColor = 'red';  // Set button background to red
            });

    }

    setTimeout(() => {
        if (globalThis.image_data != null) {
            console.log('Found Image Data');
            updateUI(globalThis.image_data);
        }
    }, 2000);
});