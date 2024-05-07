from flask import Flask, request, jsonify, render_template, send_from_directory
from werkzeug.utils import secure_filename
import os
import pathlib
from modules import image_parser
from modules import a1111_api as sd
from modules import logger 
import requests
import re
import json
from termcolor import colored

# Setup logging as per logger.py configuration
log = logger.setup_logging()

app = Flask(__name__)


uploaded = False
filepath = None

# Assuming you want to save uploaded files in a folder called 'uploads'
UPLOAD_FOLDER = "uploads"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/get-models")
def get_models():
    # Simulate fetching models from an API
    try:
        log.info(sd.url)
        models = sd.get_models()
    except requests.exceptions.ConnectionError:
        models = []
    return jsonify(models)


@app.route("/get-samplers")
def get_samplers():
    # Simulate fetching models from an API
    try:
        samplers = sd.get_samplers()
    except requests.exceptions.ConnectionError:
        samplers = []
    return jsonify(samplers)


@app.route("/get-loras")
def get_loras():
    # Simulate fetching models from an API
    try:
        loras = sd.get_loras()
    except requests.exceptions.ConnectionError:
        loras = []
    return jsonify(loras)


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        params = generate_parameters(filepath)
        log.info(params)

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
    pattern = r'<lora:(.*?):(.*?)>'

    # Find all matches
    matches = re.findall(pattern, text)

    return matches

def generate_parameters(image_path):
    parser_manager = image_parser.ParserManager()
    parsed_data = parser_manager.parse(image_path)
    
    lora = get_lora_from_prompt(image_parser.get_prompt(parsed_data))[0]
    
    if not parsed_data:
        return None

    meta_data = get_image_parameters(image_path)
    params = {
        "prompt": image_parser.get_prompt(parsed_data),
        "negative_prompt": image_parser.get_negative_prompt(parsed_data),
        "model": image_parser.get_model(meta_data),
        "sampler": image_parser.get_sampler(meta_data),
        "lora": image_parser.get_lora(meta_data)
        or lora[0],
        "clip_skip": "2",
        "seed": image_parser.get_seed(meta_data),
        "width": image_parser.get_width(meta_data),
        "height": image_parser.get_height(meta_data),
        "cfg_scale": image_parser.get_cfg_scale(meta_data),
        "denoising_strength": "0.5",
    }
    return params


def get_image_parameters(filepath):

    parser_manager = image_parser.ParserManager()
    parsed_data = parser_manager.parse(filepath)
    meta_data = image_parser.get_metadata(parsed_data)

    return meta_data


@app.route("/receive_data", methods=['POST'])
def receive_data():
    data = request.json
    url = data["text"]
    
    if url not in [''] and url[-1] not in ["/"]:
        url += "/"

    if url in ['']:
        sd.url = "http://127.0.0.1:7860/"
    elif 'http' in url:
        sd.url = url
    else:
        sd.url = "http://" + url + "/"

    log.info("SD URL set to: " + sd.url)  # Print or process the data as needed
    
    return jsonify({"status": "success"})


@app.route("/generate", methods = ["POST"])
def generate():
    data = request.json

    matches = get_lora_from_prompt(data["prompt"])
    
    if not matches:
        data["prompt"] += f" <lora: {data['lora']}: 0.8>"
    
    img_str = data["init_images"]
    
    data.pop("lora")
    data.pop("init_images")
    
    log.info(colored("Using the following generation parameters:\n", "cyan") + colored(str(data), "green"))
    sd.generate_expressions(
        image_str=img_str, 
        output_path="Output/Hina", 
        settings=data
    )
    # Process data here, e.g., generate text based on the model and prompt
    return jsonify({"status": "success", "message": "Data processed successfully"})


def get_lora_from_prompt(text):

    # Regular expression pattern to find text and strength
    pattern = r"<lora:(.*?):(.*?)>"

    # Find all matches
    matches = re.findall(pattern, text)

    return matches


@app.route("/images/<path:subpath>")
def list_images(subpath):
    root = pathlib.Path(app.root_path).parent
    directory = os.path.join(root, "Output", subpath)
    print("Attempting to list images from:", directory)  # Debugging statement
    try:
        files = [
            f
            for f in os.listdir(directory)
            if os.path.isfile(os.path.join(directory, f))
        ]
        return jsonify(files)
    except FileNotFoundError:
        print("Directory not found:", directory)  # Debugging statement
        return jsonify({"error": "Directory not found"}), 404


@app.route("/image/<path:filename>")
def get_image(filename):
    """Endpoint to serve images from the entire 'Output' directory."""
    root_path = pathlib.Path(app.root_path).parent
    return send_from_directory(os.path.join(root_path, "Output"), filename)


if __name__ == "__main__":
    app.run(debug=True)
