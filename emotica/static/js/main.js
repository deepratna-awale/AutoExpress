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


