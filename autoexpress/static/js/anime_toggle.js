const toggleButton = document.getElementById('toggleButton');

// Event listener for button state change
toggleButton.addEventListener('change', () => {
    if (toggleButton.checked) {
        // Button is toggled ON (Realistic)
        sendDataToServer(true);
    } else {
        // Button is toggled OFF (Anime)
        sendDataToServer(false);
    }
});

// Function to send data to your Flask server
function sendDataToServer(isRealistic) {
    // Make an HTTP request (e.g., using fetch or XMLHttpRequest)
    // Replace the URL with your Flask server endpoint
    const url = '/toggle'; // Example endpoint

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ isRealistic }), // Send data to server
    })
        .then(response => {
            if (response.ok) {
                console.log('Data sent successfully!');
            } else {
                console.error('Error sending data to server.');
            }
        })
        .catch(error => {
            console.error('Network error:', error);
        });
}