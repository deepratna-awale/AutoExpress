import json
import re


def convert_to_json(input_str):
    # Replace single quotes with double quotes, while handling nested quotes
    json_like_str = re.sub(r"(?<!\\)'", '"', input_str)

    # Escape any unescaped double quotes inside strings
    json_like_str = re.sub(r'(?<!\\)"', '\\"', json_like_str)

    # Replace newline escape with actual newline character
    json_like_str = json_like_str.replace("\\n", "\n")

    # Attempt to parse and pretty print as JSON
    try:
        parsed_json = json.loads(json_like_str)
        return json.dumps(parsed_json, indent=4)
    except json.JSONDecodeError as e:
        return f"Error converting to JSON: {e}"


# Input string
input_str = """{
    "parameters": "ultra detailed 8k cg, ultra realitsic, masterpiece, spotlight, cinematic lighting, cinematic bloom, professional photography, serious, formal, epic,  <lora:boruko-10:0.8>  boruko, (facial mark:1.2), long hair, blonde hair,\nNegative prompt: (worst quality, low quality:1.4), logo, watermark\nSteps: 20, Sampler: DPM++ 2M Karras, CFG scale: 7, Seed: 213228792, Size: 512x768, Model hash: ca5befc099, Model: perfectWorld_v6Baked, Denoising strength: 0.53, Clip skip: 2, ADetailer model: face_yolov8n.pt, ADetailer prompt: "<lora:boruko-10:0.8>  boruko, facial mark, long hair, blonde hair", ADetailer confidence: 0.3, ADetailer dilate erode: 4, ADetailer mask blur: 4, ADetailer denoising strength: 0.4, ADetailer inpaint only masked: True, ADetailer inpaint padding: 32, ADetailer ControlNet model: controlnet11Models_inpaint [be8bc0ed], ADetailer ControlNet module: inpaint_global_harmonious, ADetailer version: 23.11.1, Hires upscale: 2, Hires steps: 10, Hires upscaler: 4x-UltraSharp, Lora hashes: "boruko-10: eb3b1a905093", ControlNet 0: "Module: inpaint_global_harmonious, Model: controlnet11Models_inpaint [be8bc0ed], Weight: 1.0, Resize Mode: ResizeMode.INNER_FIT, Low Vram: False, Guidance Start: 0.0, Guidance End: 1.0, Pixel Perfect: True, Control Mode: ControlMode.BALANCED, Save Detected Map: True", Version: v1.6.1, Hashes: {"lora:boruko-10": "21895f3ba9", "model": "ca5befc099"}"
}"""

# Convert to JSON
converted_json = convert_to_json(input_str)
print(converted_json)
