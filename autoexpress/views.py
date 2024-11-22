from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename

import os
import pathlib

from autoexpress.modules import (
    a1111_client,
    image_parser,
    expression_generator,
)

from loguru import logger as log
import requests
import re



autoexpress = Flask(__name__)
sd = a1111_client.A1111Client()

uploaded = False
filepath = None
is_realistic = False


# Assuming you want to save uploaded files in a folder called 'uploads'
UPLOAD_FOLDER = "uploads"
MAX_FILES = 10
autoexpress.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


# AutoExpress UI
@autoexpress.route("/", methods=["GET"])
def index():
    return render_template("index.html")


# Stable diffusion API Calls
@autoexpress.route("/interrupt", methods=["POST"])
def interrupt_generation():
    print("Interrupting generation...")
    global PAUSE_EXECUTION
    # Simulate fetching models from an API
    try:
        PAUSE_EXECUTION = not PAUSE_EXECUTION
        response = sd.interrupt()
    except requests.exceptions.ConnectionError:
        response = "Failed to Interrupt the SD Session."
    return jsonify(response)


@autoexpress.route("/get-models")
def get_models():
    # Simulate fetching models from an API
    try:
        models = sd.models
    except requests.exceptions.ConnectionError:
        models = []
    return jsonify(models)


@autoexpress.route("/get-samplers")
def get_samplers():
    # Simulate fetching models from an API
    try:
        samplers = sd.samplers
    except requests.exceptions.ConnectionError:
        samplers = []
    return jsonify(samplers)


@autoexpress.route("/get-schedulers")
def get_schedulers():
    # Simulate fetching models from an API
    try:
        schedulers = sd.schedulers
    except requests.exceptions.ConnectionError:
        schedulers = []
    return jsonify(schedulers)


@autoexpress.route("/get-loras")
def get_loras():
    # Simulate fetching models from an API
    try:
        loras = sd.loras
    except requests.exceptions.ConnectionError:
        loras = []
    return jsonify(loras)

# End of Stable diffusion API Calls

# Image uploaded
@autoexpress.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(autoexpress.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        full_image_data = {"cleaned_data": None, "uncleaned_data": None, "width": None, "height": None}
        full_image_data["cleaned_data"] = image_parser.generate_cleaned_parameters(filepath)
        full_image_data["uncleaned_data"] = image_parser.generate_uncleaned_params(filepath)
        full_image_data["width"], full_image_data["height"] = image_parser.get_size_from_image_metadata(filepath)

        return (
            jsonify(full_image_data),
            200,
        )


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {
        "png",
        "jpg",
        "jpeg",
        "gif",
    }

# Try connecting to SD
@autoexpress.route("/receive_data", methods=["POST"])
def receive_data():
    """Set the Stable Diffusion URL."""

    data = request.json
    url = data["text"]

    if not url:
        sd.setURL("http://127.0.0.1:7860")
        log.info("No url found, defaulting to http://127.0.0.1:7860")
    elif url.endswith("/"):
        sd.setURL(url[:-1])
    elif url.startswith("http"):
        sd.setURL(url)
    else:
        sd.setURL("http://" + url)

    log.info(f"SD URL set to: {sd.getURL()}")

    return jsonify({"status": "success"})

# Generate Images
@autoexpress.route("/generate", methods=["POST"])
def generate():
    data = request.json

    adetailer_exists = sd.is_extension()

    if not adetailer_exists:
        return jsonify({"status": "Failed", "message": "Could not find adetailer"})

    matches = get_lora_from_prompt(data.get("ad_prompt"))
    img_str = data.get("init_images")

    output_dir = data.get("output_dir").strip().rsplit(".", 1)[0] or "New_Character"
    lora_list = data.get("loras")
    
    for lora_item in lora_list:
        lora_name = lora_item.get("lora_name")
        lora_strength = lora_item.get("lora_strength")
        data["ad_prompt"] += f" <lora: {lora_name}: {lora_strength}>, "
    
    data.pop("output_dir")
    data.pop("loras")
    data.pop("init_images")

    log.info("Using the following generation parameters:\n" + str(data))

    try:
        expression_generator.generate_expressions(
            sd=sd,
            image_str=img_str,
            output_path=f"Output/{output_dir}",
            settings=data,
            is_realistic=is_realistic,
        )
    except KeyboardInterrupt:
        sd.interrupt()

    # Process data here, e.g., generate text based on the model and prompt
    return jsonify({"status": "success", "message": "Data processed successfully"})


def get_lora_from_prompt(text):
    if not text:
        return []
    # Regular expression pattern to find text and strength
    pattern = r"<lora:(.*?):(.*?)>"
    # Find all matches
    matches = re.findall(pattern, text)
    return matches


@autoexpress.route("/images/<path:subpath>")
def list_images(subpath):
    root = pathlib.Path(autoexpress.root_path).parent
    directory = os.path.join(root, "Output", subpath)
    log.info("Attempting to list images from:", directory)  # Debugging statement
    try:
        files = [
            f
            for f in os.listdir(directory)
            if os.path.isfile(os.path.join(directory, f))
        ]
        return jsonify(files)
    except FileNotFoundError:
        log.info("Directory not found:", directory)  # Debugging statement
        return jsonify({"error": "Directory not found"}), 404


@autoexpress.route("/image/<path:filename>")
def get_image(filename):
    """Endpoint to serve images from the entire 'Output' directory."""
    root_path = pathlib.Path(autoexpress.root_path).parent
    return send_from_directory(os.path.join(root_path, "Output"), filename)


@autoexpress.route("/toggle", methods=["POST"])
def handle_toggle():
    global is_realistic
    data = request.get_json()
    is_realistic = data.get("isRealistic")

    return jsonify({"message": f"Is realistic status set to {is_realistic}"})
