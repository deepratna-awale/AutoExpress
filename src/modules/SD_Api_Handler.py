import json
import requests
import io
import base64
from PIL import Image

url = "http://127.0.0.1:7860/"
img2img_api = "sdapi/v1/img2img"



def generate_expression(input_image: str, prompt: str, negative_prompt: str, payload: dict):
    
    # Convert the input image to base64 format (SDapi accepts base64)
    with Image.open(input_image) as image:
        with io.BytesIO() as img_buffer:
            # Save the image to a bytes buffer
            image.save(img_buffer, format=input_image.suffix)

            # Encode the image to base64 and decode to a string in one step
            input_img_base64_str = base64.b64encode(img_buffer.getvalue()).decode(
                "utf-8"
            )

    payload["prompt"] = prompt
    payload["negative_prompt"] = negative_prompt
    payload["init_images"][0] = input_img_base64_str

    json_payload = json.dumps(payload, indent=4)

    response = requests.post(
        url=f"{url}{img2img_api}",
        data=json_payload,
        headers={"Content-Type": "application/json"},
    )

    if response.status_code == 200:
        r = response.json()
        image = Image.open(io.BytesIO(base64.b64decode(r["images"][0])))
        image.save("output.png")

    else:
        print("Error Code: ", response.status_code)
        print(response.json())


if __name__ == "__main__":
    with open(r"src\modules\payload.json", "r") as payload_file:
        payload = json.load(payload_file)

    with open(r"src\modules\expressions.json", "r") as exp_file:
        expressions = json.load(exp_file)

    generate_expression(r"src\modules\Himawari Uzumaki.png", expressions, payload)
