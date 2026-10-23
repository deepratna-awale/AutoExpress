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
from .base import BackendError, BackendNotReady, BackendRejected, RemoteBackend

ADETAILER = "adetailer"


def _image_size(b64_image) -> tuple[int, int] | None:
    """Width and height of a base64 image, reading only its header."""
    if not isinstance(b64_image, str) or not b64_image:
        return None
    try:
        with b64_to_pil(b64_image) as image:
            return image.size
    except (ValueError, OSError):
        return None


class A1111Client(RemoteBackend):

    kind = "a1111"
    label = "AUTOMATIC1111"
    default_url = "http://127.0.0.1:7860"

    def __init__(self, host: str = "127.0.0.1", port: str = "7860", use_https: bool = False, url: str | None = None, **options) -> None:
        """
        Initialize the A1111Client object.

        Args:
            host (str, optional): The host of the sd server. Defaults to "127.0.0.1".
            port (str, optional): The port of the sd server. Defaults to "7860".
            use_https (bool, optional): Whether to use https for the connection. Defaults to False.
            url (str, optional): Full base URL, takes precedence over host/port.
            **options: ConnectionOptions fields (username, password, token, timeout, retries, ...).
        """
        protocol = "https" if use_https else "http"
        self._alwayson_scripts: set[str] | None = None
        super().__init__(url or f"{protocol}://{host}:{port}", **options)
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
            "progress": "/sdapi/v1/progress",
        }

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
        except (BackendError, requests.RequestException, ValueError, KeyError, TypeError) as e:
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
        except BackendError as e:
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
        except (BackendError, requests.RequestException, ValueError, AttributeError):
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
        except BackendError:
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
            except (BackendError, requests.RequestException, ValueError, KeyError, TypeError) as e:
                log.debug(f"Could not read script info: {e}")
                return None
        return self._alwayson_scripts

    def prepare_payload(self, payload: dict) -> dict:
        """
        Fit the request body to this server and image.

        - width/height follow the input image (as in the in-process backend). The
          template's 512x512 would make ADetailer inpaint SDXL faces at 512 and
          garble them.
        - Always-on scripts this server does not have are dropped; unknown script
          names make it reject the request.
        """
        payload = copy.copy(payload)
        size = _image_size((payload.get("init_images") or [None])[0])
        if size:
            payload["width"], payload["height"] = size

        available = self.alwayson_scripts()
        scripts = payload.get("alwayson_scripts")
        if not available or not scripts:
            return payload

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
            requests.Response | bool: The response from the server, or False if the request failed
            (the reason is kept in last_error).
        """
        try:
            return self._img2img_response(json_payload)
        except BackendError as e:
            self._fail(e, "img2img")
            return False

    def _img2img_response(self, json_payload: str | dict) -> requests.Response:
        if isinstance(json_payload, str):
            json_payload = json.loads(json_payload)
        json_payload = self.prepare_payload(json_payload)

        response = self._request("POST", self._endpoints["img2img"], json=json_payload, timeout=self.connection.job_timeout)
        if response.status_code == 200:
            return response
        if response.status_code == 422:
            raise BackendRejected(f"{self.label} rejected the request: {response.text[:1000]}")
        raise BackendRejected(f"{self.label} img2img failed ({response.status_code}): {response.text[:1000]}")

    def img2img(self, payload: dict) -> Image.Image | None:
        """
        Backend entry point used by ExpressionGenerator.

        Args:
            payload (dict): The img2img request body.

        Returns:
            Image.Image | None: The first generated image, or None if the request failed.
        """
        self.last_error = None
        try:
            r = self._json(self._img2img_response(payload))
            images = r.get("images") or []
            if not images:
                raise BackendRejected(f"{self.label} returned no image.")
            image = b64_to_pil(images[0])
        except BackendError as e:
            return self._fail(e)
        except (ValueError, KeyError, TypeError) as e:
            return self._fail(BackendRejected(f"Unexpected img2img response from {self.label}: {e}"))

        try:
            infotexts = json.loads(r.get("info") or "{}").get("infotexts") or []
        except (TypeError, ValueError, AttributeError):
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
        except BackendError as e:
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
            response = self._request("POST", self._endpoints["interrupt"], timeout=10)
        except BackendError as e:
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

    def ensure_ready(self) -> None:
        try:
            self._get_json(self._endpoints["samplers"], timeout=10)
        except BackendRejected as e:
            raise BackendNotReady(
                f"{self.label} at {self._base_url} does not serve the API. Start it with --api. ({e})"
            ) from e
        if not self.is_extension(ADETAILER):
            raise BackendNotReady(f"ADetailer is not installed or not enabled in {self.label}.")
        if not self.models:
            raise BackendNotReady(f"{self.label} has no checkpoints.")

    def server_info(self) -> dict:
        info = {"alwayson_scripts": sorted(self.alwayson_scripts() or [])}
        try:
            flags = self._get_json(self._endpoints["cmd_flags"], timeout=10)
            info["api_auth"] = bool(flags.get("api_auth"))
        except (BackendError, AttributeError):
            pass
        return info

    def progress(self) -> dict | None:
        try:
            r = self._get_json(self._endpoints["progress"], params={"skip_current_image": "true"}, timeout=10)
        except BackendError as e:
            log.debug(f"{self.label} progress unavailable: {e}")
            return None
        state = r.get("state") or {}
        step, steps = state.get("sampling_step") or 0, state.get("sampling_steps") or 0
        fraction = float(r.get("progress") or 0.0)
        if not fraction and steps:
            # ADetailer's inpaint pass runs outside the job count A1111 bases "progress" on.
            fraction = min(step / steps, 1.0)
        return {"fraction": fraction, "eta": r.get("eta_relative") or None, "step": step, "steps": steps}


class ForgeClient(A1111Client):
    """Stable Diffusion WebUI Forge and reForge. Same API, different built-in scripts."""

    kind = "forge"
    label = "Forge / reForge"


class SDNextClient(A1111Client):
    """SD.Next. Same /sdapi/v1 routes; schedulers are part of the sampler list there."""

    kind = "sdnext"
    label = "SD.Next"
