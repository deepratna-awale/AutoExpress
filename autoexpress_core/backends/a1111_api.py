"""
Backends for WebUIs that serve the A1111 HTTP API (/sdapi/v1, started with --api).

AUTOMATIC1111, Forge, reForge and SD.Next all accept the same img2img body
with ADetailer in alwayson_scripts. They differ in which built-in scripts they
ship (Forge has no Hypertile, SD.Next has no Soft Inpainting, ...) and in a few
listing endpoints, so the client asks the server which scripts exist and drops
the rest from the body instead of hard coding one WebUI.
"""

import copy
import json
import pathlib

import requests
from PIL import Image

from ..images import b64_to_pil
from ..log import log
from .base import RemoteBackend

ADETAILER = "adetailer"


class A1111Client(RemoteBackend):

    kind = "a1111"
    label = "AUTOMATIC1111"
    default_url = "http://127.0.0.1:7860"

    def __init__(self, host: str = "127.0.0.1", port: str = "7860", use_https: bool = False, url: str | None = None) -> None:
        """
        Initialize the A1111Client object.

        Args:
            host (str, optional): The host of the sd server. Defaults to "127.0.0.1".
            port (str, optional): The port of the sd server. Defaults to "7860".
            use_https (bool, optional): Whether to use https for the connection. Defaults to False.
            url (str, optional): Full base URL, takes precedence over host/port.
        """
        protocol = "https" if use_https else "http"
        super().__init__(url or f"{protocol}://{host}:{port}")
        self._endpoints = {
            "img2img": "/sdapi/v1/img2img",
            "samplers": "/sdapi/v1/samplers",
            "models": "/sdapi/v1/sd-models",
            "loras": "/sdapi/v1/loras",
            "extensions": "/sdapi/v1/extensions",
            "interrupt": "/sdapi/v1/interrupt",
            "image_info": "/sdapi/v1/png-info",
            "schedulers": "/sdapi/v1/schedulers",
            "script_info": "/sdapi/v1/script-info",
            "refresh_loras": "/sdapi/v1/refresh-loras",
            "cmd_flags": "/sdapi/v1/cmd-flags",
        }
        self._alwayson_scripts: set[str] | None = None

    def on_url_changed(self) -> None:
        self._alwayson_scripts = None

    @property
    def extensions(self) -> dict[str, bool]:
        """
        Get a dictionary of extension names mapped to their enabled status.

        Returns:
            dict[str, bool]: A dictionary of extension names mapped to their enabled status.
        """
        try:
            r = self._get_json(self._endpoints["extensions"])
            return {extension["name"]: extension.get("enabled", True) for extension in r}
        except (requests.RequestException, ValueError, KeyError, TypeError) as e:
            log.error(f"Could not list extensions: {e}")
            return {}

    @property
    def loras(self) -> list[str]:
        return self._safe_list("loras", lambda: (lora["name"] for lora in self._get_json(self._endpoints["loras"])))

    @property
    def samplers(self) -> list[str]:
        return self._safe_list(
            "samplers", lambda: (sampler["name"] for sampler in self._get_json(self._endpoints["samplers"]))
        )

    @property
    def schedulers(self) -> list[str]:
        """Scheduler names. Older A1111 builds and SD.Next have no scheduler endpoint and return []."""
        response = None
        try:
            response = self._request("GET", self._endpoints["schedulers"])
        except requests.RequestException as e:
            log.warning(f"Could not fetch schedulers: {e}")
        if response is None or response.status_code == 404:
            return []
        return self._safe_list(
            "schedulers", lambda: (s.get("label") or s["name"] for s in response.json())
        )

    @property
    def models(self) -> list[str]:
        return self._safe_list(
            "models", lambda: (model["model_name"] for model in self._get_json(self._endpoints["models"]))
        )

    @property
    def lora_dir(self) -> str | None:
        """
        The server's LoRA folder, if this machine can see it (i.e. the WebUI runs locally).

        Returns:
            str | None: The LoRA folder path, or None if it isn't reachable from here.
        """
        try:
            lora_dir = self._get_json(self._endpoints["cmd_flags"]).get("lora_dir")
        except (requests.RequestException, ValueError, AttributeError):
            return None
        if lora_dir and pathlib.Path(lora_dir).is_dir():
            return lora_dir
        return None

    def refresh_loras(self) -> bool:
        """
        Asks the server to rescan its LoRA folder.

        Returns:
            bool: True if successful, otherwise False.
        """
        try:
            return self._request("POST", self._endpoints["refresh_loras"]).status_code == 200
        except requests.RequestException:
            return False

    def alwayson_scripts(self) -> set[str] | None:
        """
        Lower case names of the img2img always-on scripts the server has, or None if it cannot tell.
        """
        if self._alwayson_scripts is None:
            try:
                scripts = self._get_json(self._endpoints["script_info"])
                self._alwayson_scripts = {
                    script["name"].lower()
                    for script in scripts
                    if script.get("is_alwayson") and script.get("is_img2img", True)
                }
            except (requests.RequestException, ValueError, KeyError, TypeError) as e:
                log.debug(f"Could not read script info: {e}")
                return None
        return self._alwayson_scripts

    def prepare_payload(self, payload: dict) -> dict:
        """Drop always-on scripts this server does not have; unknown script names make it reject the request."""
        available = self.alwayson_scripts()
        scripts = payload.get("alwayson_scripts")
        if not available or not scripts:
            return payload

        payload = copy.copy(payload)
        kept = {name: args for name, args in scripts.items() if name.lower() in available}
        dropped = sorted(set(scripts) - set(kept))
        if dropped:
            log.debug(f"{self.label} does not have these scripts, leaving them out: {', '.join(dropped)}")
        payload["alwayson_scripts"] = kept
        return payload

    def img2img_api(self, json_payload: str | dict) -> requests.Response | bool:
        """
        Performs an img2img request to the server.

        Args:
            json_payload (str | dict): The request payload, as a JSON string or a dict.

        Returns:
            requests.Response | bool: The response from the server, or False if the request failed.
        """
        if isinstance(json_payload, str):
            json_payload = json.loads(json_payload)
        json_payload = self.prepare_payload(json_payload)

        try:
            response = self._request("POST", self._endpoints["img2img"], json=json_payload, timeout=None)
        except requests.RequestException as e:
            log.error(f"img2img request failed: {e}")
            return False

        if response.status_code == 200:
            return response

        log.error(f"Request failed with code: {response.status_code} {response.text[:1000]}")
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

        r = response.json()
        image = b64_to_pil(r["images"][0])
        try:
            infotexts = json.loads(r.get("info") or "{}").get("infotexts") or []
        except (TypeError, ValueError):
            infotexts = []
        if infotexts:
            image.info["parameters"] = infotexts[0]
        return image

    def get_image_info(self, b64_image: str) -> requests.Response | bool:
        """
        Retrieves image information from the server.

        Args:
            b64_image (str): Base64 encoded image string.

        Returns:
            requests.Response | bool: The server response if successful, otherwise False.
        """
        png_payload = "data:image/png;base64," + b64_image

        try:
            response = self._request("POST", self._endpoints["image_info"], json=png_payload)
        except requests.RequestException as e:
            log.error(f"png-info request failed: {e}")
            return False

        if response.status_code == 200:
            return response

        log.error(f"Request failed with code: {response.status_code} {response.text[:1000]}")
        return False

    def interrupt(self) -> bool:  # also satisfies the Backend protocol
        """
        Interrupts the current generation.

        Returns:
            bool: True if successful, otherwise False.
        """
        try:
            response = self._request("POST", self._endpoints["interrupt"])
        except requests.RequestException as e:
            log.error(f"Interrupt failed: {e}")
            return False

        if response.status_code != 200:
            log.error(f"Request failed with code: {response.status_code} {response.text[:1000]}")
            return False

        log.error("Interrupted by user.")
        return True

    def is_extension(self, ext: str = ADETAILER) -> bool:
        """
        Checks if the given extension is present and enabled on the server.

        The always-on script list is checked first since the extension's folder
        name differs between installs (adetailer, !adetailer, ADetailer, ...).

        Args:
            ext (str, optional): The name of the extension to check. Defaults to "adetailer".

        Returns:
            bool: True if the extension is found and enabled, False otherwise.
        """
        scripts = self.alwayson_scripts()
        if scripts is not None and ext.lower() in scripts:
            log.info(f"Found {ext} script.")
            return True

        extensions = self.extensions
        log.debug(f"Found following extensions: {extensions}")

        for name, enabled in extensions.items():
            if ext.lower() in name.lower():
                if enabled:
                    log.info(f"Found enabled {name} extension.")
                    return True
                log.warning(f"Please enable the {name} extension if you want to use it.")
                return False

        log.error(f"Could not find {ext} extension")
        return False

    def check_ready(self) -> tuple[bool, str]:
        try:
            self._get_json(self._endpoints["samplers"])
        except requests.RequestException as e:
            return False, f"Could not reach the {self.label} API at {self._base_url}. Start it with --api. ({e})"
        if not self.is_extension(ADETAILER):
            return False, f"ADetailer is not installed or not enabled in {self.label}."
        return True, "ok"


class ForgeClient(A1111Client):
    """Stable Diffusion WebUI Forge and reForge. Same API, different built-in scripts."""

    kind = "forge"
    label = "Forge / reForge"


class SDNextClient(A1111Client):
    """SD.Next. Same /sdapi/v1 routes; schedulers are part of the sampler list there."""

    kind = "sdnext"
    label = "SD.Next"
