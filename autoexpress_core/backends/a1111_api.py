import json
import pathlib

import requests
from PIL import Image

from ..images import b64_to_pil
from ..log import log


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
            "schedulers": "/sdapi/v1/schedulers",
            "refresh_loras": "/sdapi/v1/refresh-loras",
            "cmd_flags": "/sdapi/v1/cmd-flags",
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


    @property
    def lora_dir(self) -> str | None:
        """
        The server's LoRA folder, if this machine can see it (i.e. the WebUI runs locally).

        Returns:
            str | None: The LoRA folder path, or None if it isn't reachable from here.
        """
        try:
            response = requests.get(url=f"{self._base_url}{self._endpoints['cmd_flags']}")
        except requests.exceptions.RequestException:
            return None

        if response.status_code != 200:
            return None

        lora_dir = response.json().get("lora_dir")
        if lora_dir and pathlib.Path(lora_dir).is_dir():
            return lora_dir
        return None

    def refresh_loras(self) -> bool:
        """
        Asks the server to rescan its LoRA folder.

        Returns:
            bool: True if successful, otherwise False.
        """
        response = requests.post(url=f"{self._base_url}{self._endpoints['refresh_loras']}")
        return response.status_code == 200

    def img2img_api(self, json_payload: str | dict) -> requests.Response | bool:
        """
        Performs an img2img request to the A1111 server.

        Args:
            json_payload (str | dict): The request payload, as a JSON string or a dict.

        Returns:
            requests.Response | bool: The response from the server, or False if the request failed.
        """
        if isinstance(json_payload, dict):
            json_payload = json.dumps(json_payload)

        response = requests.post(
            url=f"{self._base_url}{self._endpoints['img2img']}",
            data=json_payload,
            headers={"Content-Type": "application/json"},
        )

        if response.status_code == 200:
            return response

        log.error(f"Request failed with code: {response.status_code} {response.json()}")
        return False


    def img2img(self, payload: dict) -> Image.Image | None:
        """
        Backend entry point used by ExpressionGenerator.

        Args:
            payload (dict): The img2img request body.

        Returns:
            Image.Image | None: The first generated image, or None if the request failed.
        """
        response = self.img2img_api(payload)
        if not response:
            return None
        return b64_to_pil(response.json()["images"][0])

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

    def interrupt(self) -> bool:  # also satisfies the Backend protocol
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
