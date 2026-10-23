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

// Face inpainting or instruction edit, limited to what the connected WebUI can do
const editMethodSelect = document.getElementById("edit-method-input");

function loadEditMethods() {
  fetch("/edit-methods")
    .then((response) => response.json())
    .then((data) => {
      const selected = editMethodSelect.value;
      editMethodSelect.innerHTML = "";
      data.methods.forEach((method) => {
        const option = document.createElement("option");
        option.value = method.id;
        option.textContent = method.available ? method.name : `${method.name} (ComfyUI only)`;
        option.title = method.description;
        option.disabled = !method.available;
        editMethodSelect.appendChild(option);
      });
      const still = data.methods.find((method) => method.id === selected && method.available);
      editMethodSelect.value = still ? selected : "inpaint";
      editMethodSelect.dispatchEvent(new Event("change"));
    })
    .catch((error) => {
      console.error("Could not load edit methods:", error);
    });
}

// Prompt style and expression LoRAs only apply to face inpainting
editMethodSelect.addEventListener("change", () => {
  const inpaint = editMethodSelect.value === "inpaint";
  expressionFamilySelect.disabled = !inpaint;
  const lorasToggle = document.getElementById("expression-loras-toggle");
  if (lorasToggle) lorasToggle.disabled = !inpaint;
});

loadEditMethods();

// Expression LoRA settings
const expressionLorasToggle = document.getElementById("expression-loras-toggle");
const loraDirInput = document.getElementById("lora-dir-input");
const civitaiKeyInput = document.getElementById("civitai-key-input");

function saveExpressionLoraSettings(settings) {
  fetch("/expression-loras", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(settings),
  })
    .then((response) => response.json())
    .then((data) => {
      civitaiKeyInput.value = "";
      civitaiKeyInput.placeholder = data.has_civitai_api_key
        ? "Key saved for this session"
        : "Needed to download LoRAs from Civitai";
    })
    .catch((error) => {
      console.error("Network error:", error);
    });
}

fetch("/expression-loras")
  .then((response) => response.json())
  .then((data) => {
    expressionLorasToggle.checked = data.enabled;
    loraDirInput.value = data.lora_dir;
    if (data.has_civitai_api_key) {
      civitaiKeyInput.placeholder = "Key saved for this session";
    }
  })
  .catch((error) => {
    console.error("Could not load expression LoRA settings:", error);
  });

expressionLorasToggle.addEventListener("change", () => {
  saveExpressionLoraSettings({ enabled: expressionLorasToggle.checked });
});

loraDirInput.addEventListener("change", () => {
  saveExpressionLoraSettings({ lora_dir: loraDirInput.value });
});

civitaiKeyInput.addEventListener("change", () => {
  if (civitaiKeyInput.value.trim()) {
    saveExpressionLoraSettings({ civitai_api_key: civitaiKeyInput.value });
  }
});
