document.querySelector('.interrupt-button').addEventListener('click', function () {
    const button = this; // Ensure button is properly scoped
    fetch('/interrupt', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json', // Set appropriate headers if needed
        },
    })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('Stopping generation after this image!', data);
            button.style.color = 'white';
        })
        .catch(error => {
            console.error('Error interrupting:', error);
            button.style.backgroundColor = 'red'; // Set button background to red
        });
});
