const expressionFamilySelect = document.getElementById("expression-family-input");

// Fill the prompt style dropdown with the families the server knows about
function loadExpressionFamilies() {
  fetch("/expression-families")
    .then((response) => response.json())
    .then((data) => {
      data.families.forEach((family) => {
        const option = document.createElement("option");
        option.value = family.id;
        option.textContent = family.name;
        option.title = `${family.description}\ne.g. ${family.models.join(", ")}`;
        expressionFamilySelect.appendChild(option);
      });
      expressionFamilySelect.value = data.selected;
    })
    .catch((error) => {
      console.error("Could not load expression families:", error);
    });
}

expressionFamilySelect.addEventListener("change", () => {
  fetch("/expression-family", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ family: expressionFamilySelect.value }),
  })
    .then((response) => {
      if (!response.ok) {
        console.error("Error setting expression family.");
      }
    })
    .catch((error) => {
      console.error("Network error:", error);
    });
});

loadExpressionFamilies();
