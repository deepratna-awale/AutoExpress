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

document.querySelector('.load-images').addEventListener('click', function () {
    loadImages(); // Initial load of images
});

document.querySelector('#output-directory').addEventListener('change', function(){
    loadImages();
});

document.addEventListener('keydown', function (event) {
    if (event.key === 'ArrowLeft') {
        navigate(-1);
        // Add your custom logic here
    }else if (event.key === 'ArrowRight') {
        navigate(1);
        // Add your custom logic here
    }
});