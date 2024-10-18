function loadImagesInput(event) {
    if (event.key === 'Enter') {
        loadImages();
    }
}

function loadImages() {
    const outputDir = document.getElementById('output-directory').value;

    fetch(`/images/${outputDir}`)
        .then(response => response.json())
        .then(files => {
            // Filter files to only include those with the .png extension
            images = files.filter(file => file.endsWith('.png')).map(file => `/image/${outputDir}/${file}`);
            fileNames = files.filter(file => file.endsWith('.png')); // Filter file names as well
            currentIndex = 0; // Reset index when new images are loaded

            if (images.length > 0) {
                displayImage(currentIndex);
            } else {
                document.getElementsById('image-display').src = "";
                document.getElementById('expression-image-name').textContent = "No PNG images found.";
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
    //document.getElementById('image-name').textContent = "Expression: " + fileNames[index]);
    //document.getElementById('image-name').textContent = "Expression: " + fileNames[index].substring(0, fileNames[index].lastIndexOf('.'));
    document.getElementById('expression-image-name').textContent = fileNames[index].replace(/\.[^.]+$/, '').charAt(0).toUpperCase() + fileNames[index].replace(/\.[^.]+$/, '').slice(1).toLowerCase();
}



function calculateAspectRatio(image) {
    const naturalWidth = image.naturalWidth;
    const naturalHeight = image.naturalHeight;
    if (naturalWidth && naturalHeight) {
        return naturalWidth / naturalHeight;
    } else {
        console.error("Error: Image dimensions not available.");
        return 1; // Default to 1:1 aspect ratio in case of errors
    }
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

document.querySelector('#output-directory').addEventListener('change', function () {
    loadImages();
});

document.addEventListener('keydown', function (event) {
    if (event.key === 'ArrowLeft') {
        navigate(-1);
        // Add your custom logic here
    } else if (event.key === 'ArrowRight') {
        navigate(1);
        // Add your custom logic here
    }
});