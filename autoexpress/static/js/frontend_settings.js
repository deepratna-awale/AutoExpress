
var gradientSelector = document.getElementById('gradient-animation-toggle');
const htmlElement = document.documentElement;
gradientSelector.addEventListener('change', () => {
    if (gradientSelector.checked) {
        htmlElement.style.animationPlayState = "running";
        console.log('Gradient animation on');
    } else {
        htmlElement.style.animationPlayState = "paused";
        console.log('Gradient animation off');
    }
});
