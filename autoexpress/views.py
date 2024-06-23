from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename
# from autoexpress import app
import os
import pathlib
from autoexpress.modules import (
    image_parser,
)  # Adjust if specific functions/classes need to be imported
from autoexpress.modules import a1111_api as sd
from loguru import logger as log
from autoexpress.modules import generate as expression_generator
import requests
import re


autoexpress = Flask(__name__)

uploaded = False
filepath = None
is_realistic = False

# Assuming you want to save uploaded files in a folder called 'uploads'
UPLOAD_FOLDER = "uploads"
MAX_FILES = 10
autoexpress.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


@autoexpress.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@autoexpress.route("/get-models")
def get_models():
    # Simulate fetching models from an API
    try:
        models = sd.get_models()
    except requests.exceptions.ConnectionError:
        models = []
    return jsonify(models)


@autoexpress.route("/get-samplers")
def get_samplers():
    # Simulate fetching models from an API
    try:
        samplers = sd.get_samplers()
    except requests.exceptions.ConnectionError:
        samplers = []
    return jsonify(samplers)


@autoexpress.route("/get-loras")
def get_loras():
    # Simulate fetching models from an API
    try:
        loras = sd.get_loras()
    except requests.exceptions.ConnectionError:
        loras = []
    return jsonify(loras)


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

        params = generate_parameters(filepath)

        return (
            jsonify(params),
            200,
        )


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in {
        "png",
        "jpg",
        "jpeg",
        "gif",
    }


def get_lora_from_prompt(text):

    # Regular expression pattern to find text and strength
    pattern = r"<lora:(.*?):(.*?)>"

    # Find all matches
    matches = re.findall(pattern, text)

    return matches


def generate_parameters(image_path):
    parser_manager = image_parser.ParserManager()
    parsed_data = parser_manager.parse(image_path)
    prompt = image_parser.get_prompt(parsed_data)
    if prompt not in [""]:
        lora = get_lora_from_prompt(prompt)[0]

    if not parsed_data:
        return None

    meta_data = get_image_parameters(image_path)
    params = {
        "seed": image_parser.get_seed(meta_data),
        "lora": image_parser.get_lora(meta_data) or lora[0],
        "ad_prompt": image_parser.get_prompt(parsed_data),
        "ad_negative_prompt": image_parser.get_negative_prompt(parsed_data),
        "ad_checkpoint": image_parser.get_model(meta_data),
        "ad_sampler": image_parser.get_sampler(meta_data),
        "ad_clip_skip": "2",
        "ad_inpaint_width": image_parser.get_width(meta_data),
        "ad_inpaint_height": image_parser.get_height(meta_data),
        "ad_cfg_scale": image_parser.get_cfg_scale(meta_data),
        "ad_denoising_strength": "0.5",
    }
    return params


def get_image_parameters(filepath):

    parser_manager = image_parser.ParserManager()
    parsed_data = parser_manager.parse(filepath)
    meta_data = image_parser.get_metadata(parsed_data)

    return meta_data


@autoexpress.route("/receive_data", methods=["POST"])
def receive_data():
    data = request.json
    url = data["text"]

    if url not in [""] and url[-1] in ["/"]:
        url = url[:-1]

    if url in [""]:
        sd.url = "http://127.0.0.1:7860"

    elif "http" in url:
        sd.url = url

    else:
        sd.url = "http://" + url

    log.info("SD URL set to: " + sd.url)

    return jsonify({"status": "success"})


@autoexpress.route("/generate", methods=["POST"])
def generate():
    data = request.json

    adetailer_exists = sd.is_extension()

    if not adetailer_exists:
        return jsonify({"status": "Failed", "message": "Could not find adetailer"})

    matches = get_lora_from_prompt(data.get("ad_prompt"))
    img_str = data.get("init_images")

    output_dir = data.get("output_dir") or "New_Character"

    if not matches and data.get("lora") not in [""]:
        data["ad_prompt"] += f" <lora: {data.get('lora')}: 0.8>"

    data.pop("output_dir")
    data.pop("lora")
    data.pop("init_images")

    log.info(
        "Using the following generation parameters:\n" + str(data)
    )

    try:
        expression_generator.generate_expressions(
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
    data = request.get_json()
    is_realistic = data.get("isRealistic")
    
    # Process the data (e.g., save to a database, perform an action, etc.)
    # You can customize this part based on your requirements

    return jsonify({"message": "Data received successfully"})
