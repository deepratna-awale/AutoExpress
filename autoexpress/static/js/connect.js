let image_data = null;

document.querySelector('.sd-connect').addEventListener('click', function () {
    ;
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
            if (image_data != null) {
                document.getElementById('lora-input').value = image_data.lora;
                document.getElementById('model-input').value = image_data.ad_checkpoint;
                document.getElementById('sampler-input').value = image_data.ad_sampler;
            }
        })
        .catch(error => {
            console.error('Error loading models:', error);
            button.style.backgroundColor = 'red';  // Set button background to red
        });

});