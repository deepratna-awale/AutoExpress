import requests
import io
import base64
from PIL import Image, PngImagePlugin
from loguru import logger as log
import pathlib


class A1111Client:

    def __init__(self, host: str = "127.0.0.1", port: str = "7860", use_https: bool = False) -> None:
        """
        Initialize the A1111Client object.

        Args:
            host (str, optional): The host of the sd server. Defaults to "127.0.0.1".
            port (str, optional): The port of the sd server. Defaults to "7860".
            use_https (bool, optional): Whether to use https for the connection. Defaults to False.
        """
        protocol = "https" if use_https else "http"
        self._base_url = f"{protocol}://{host}:{port}"
        self._endpoints = {
            "img2img": "/sdapi/v1/img2img",
            "samplers": "/sdapi/v1/samplers",
            "models": "/sdapi/v1/sd-models",
            "loras": "/sdapi/v1/loras",
            "extensions": "/sdapi/v1/extensions",
            "interrupt": "/sdapi/v1/interrupt",
            "image_info": "/sdapi/v1/png-info",
            "schedulers": "/sdapi/v1/schedulers"
        }


    @property
    def extensions(self) -> dict[str, bool]:
        """
        Get a dictionary of extension names mapped to their enabled status.

        Returns:
            dict[str, bool]: A dictionary of extension names mapped to their enabled status.
        """
        response = requests.get(
            url=f"{self._base_url}{self._endpoints['extensions']}",
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            r = response.json()
            extensions = {extension["name"]: extension["enabled"] for extension in r}
            return extensions
        else:
            log.error(
                f"Request failed with code: {response.status_code} {response.json()}"
            )
            return {}

    @property
    def loras(self) -> list[str] | None:
        """
        Fetches the list of Lora names from the server.

        Returns:
            list[str] | None: A list of Lora names if successful, otherwise None.
        """
        response = requests.get(
            url=f"{self._base_url}{self._endpoints['loras']}",
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            r = response.json()
            loras = [lora["name"] for lora in r]
            return loras
        else:
            log.error(
                f"Request failed with code: {response.status_code} {response.json()}"
            )
            return None

    @property
    def samplers(self) -> list[str] | None:
        """
        Fetches the list of sampler names from the server.

        Returns:
            list[str] | None: A list of sampler names if successful, otherwise None.
        """
        response = requests.get(
            url=f"{self._base_url}{self._endpoints['samplers']}",
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            r = response.json()
            samplers = [sampler["name"] for sampler in r]
            return samplers
        else:
            log.error(
                f"Request failed with code: {response.status_code} {response.json()}"
            )
            return None

    @property
    def schedulers(self) -> list[str] | None:
        """
        Fetches the list of scheduler names from the server.

        Returns:
            list[str] | None: A list of scheduler names if successful, otherwise None.
        """
        response = requests.get(
            url=f"{self._base_url}{self._endpoints['schedulers']}",
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            r = response.json()
            schedulers = [scheduler["name"] for scheduler in r]
            return schedulers
        else:
            log.error(
                f"Request failed with code: {response.status_code} {response.json()}"
            )
            return None

    @property
    def models(self) -> list[str] | None:
        """
        Fetches the list of model names from the server.

        Returns:
            list[str] | None: A list of model names if successful, otherwise None.
        """
        response = requests.get(
            url=f"{self._base_url}{self._endpoints['models']}",
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            r: list[dict[str, str]] = response.json()
            models = [model["model_name"] for model in r]
            return models
        else:
            log.error(
                f"Request failed with code: {response.status_code} {response.json()}"
            )
            return None


    def img2img_api(self, json_payload: str) -> requests.Response | bool:
        """
        Performs an img2img request to the A1111 server.

        Args:
            json_payload (str): A JSON string containing the request payload.

        Returns:
            requests.Response | bool: The response from the server, or False if the request failed.
        """
        response = requests.post(
            url=f"{self._base_url}{self._endpoints['img2img']}",
            data=json_payload,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            return response

        log.error(f"Request failed with code: {response.status_code} {response.json()}")
        return False


    def get_image_info(self, b64_image: str) -> requests.Response | bool:
        """
        Retrieves image information from the server.

        Args:
            b64_image (str): Base64 encoded image string.

        Returns:
            requests.Response | bool: The server response if successful, otherwise False.
        """
        png_payload = "data:image/png;base64," + b64_image

        response = requests.post(
            url=f"{self._base_url}{self._endpoints['image_info']}",
            json=png_payload,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            return response

        log.error(f"Request failed with code: {response.status_code} {response.json()}")
        return False

    def interrupt(self) -> bool:
        """
        Interrupts the current generation.

        Returns:
            bool: True if successful, otherwise False.
        """
        response = requests.post(
            url=f"{self._base_url}{self._endpoints['interrupt']}",
            headers={"Content-Type": "application/json"},
        )

        if response.status_code != 200:
            log.error(
                f"Request failed with code: {response.status_code} {response.json()}"
            )
            return False

        r = response.json()
        log.error(f"Interrupted by user. {r.get('text', '')}")
        return True

    def is_extension(self, ext: str = "adetailer") -> bool:
        """
        Checks if the given extension is present and enabled on the A1111 server.

        Args:
            ext (str, optional): The name of the extension to check. Defaults to "adetailer".

        Returns:
            bool: True if the extension is found and enabled, False otherwise.
        """
        extensions = self.extensions
        log.debug(f"Found following extensions: {extensions}")

        if ext in extensions:
            log.info(f"Found {ext} extension.")

            if extensions[ext]:
                log.info(f"{ext} extension is enabled.")
                return True
            else:
                log.warning(f"Please enable the {ext} extension if you want to use it.")
                return False

        log.error(f"Could not find {ext} extension")
        return False

    def setURL(self, url: str):
        """
        Sets the URL of the A1111 server.

        Args:
            url (str): The URL of the A1111 server.
        """
        self._base_url = url

    def getURL(self):
        """
        Retrieves the current URL of the A1111 server.

        Returns:
            str: The URL of the A1111 server.
        """
        return self._base_url


def main():
    import utils
    file_path = r"D:\Workspace\AI\stable-diffusion-webui\outputs\txt2img-images\2024-04-15\00018-4139222450.png"
    file_path = pathlib.Path(file_path)
    image_str = utils.raw_b64_img(file_path)

    json_body = {
        "prompt": "",
        "negative_prompt": "",
        "styles": [""],
        "seed": -1,
        "subseed": -1,
        "subseed_strength": 0,
        "seed_resize_from_h": -1,
        "seed_resize_from_w": -1,
        "sampler_name": "Euler",
        "scheduler": "Automatic",
        "batch_size": 1,
        "n_iter": 1,
        "steps": 50,
        "cfg_scale": 7,
        "width": 512,
        "height": 768,
        "restore_faces": False,
        "tiling": True,
        "do_not_save_samples": False,
        "do_not_save_grid": False,
        "eta": 0,
        "denoising_strength": 0.75,
        "s_min_uncond": 0,
        "s_churn": 0,
        "s_tmax": 0,
        "s_tmin": 0,
        "s_noise": 0,
        "override_settings": {},
        "override_settings_restore_afterwards": True,
        "refiner_checkpoint": "",
        "refiner_switch_at": 0,
        "disable_extra_networks": False,
        "firstpass_image": "",
        "comments": {},
        "init_images": [""],
        "resize_mode": 0,
        "image_cfg_scale": 7,
        "mask": "string",
        "mask_blur_x": 4,
        "mask_blur_y": 4,
        "mask_blur": 0,
        "mask_round": True,
        "inpainting_fill": 0,
        "inpaint_full_res": True,
        "inpaint_full_res_padding": 0,
        "inpainting_mask_invert": 0,
        "initial_noise_multiplier": 0,
        "latent_mask": "string",
        "force_task_id": "string",
        "sampler_index": "Euler",
        "include_init_images": False,
        "script_name": "",
        "script_args": [],
        "send_images": True,
        "save_images": False,
        "alwayson_scripts": {},
        "infotext": "string",
    }

    png_payload = "data:image/png;base64," + image_str
    json_body["init_images"][0] = png_payload

    sd = A1111Client()
    response = sd.img2img_api(json_body)

    if response == 200:
        r = response.json()
        for i in r['images']:
            image = Image.open(io.BytesIO(base64.b64decode(i.split(",",1)[0])))

            info_response  = sd.get_image_info(i)
    
            pnginfo = PngImagePlugin.PngInfo()
            pnginfo.add_text("parameters", info_response.json().get("info"))
    
            image.save(f"Output/{file_path.stem}.png", pnginfo=pnginfo)
    else:
        print(response.json())


if __name__ == "__main__":
    main()
