"""
Backend for an InvokeAI server (5.x and later), driven through its session queue API.

InvokeAI has no ADetailer, so each expression is an inpainting graph built from
core nodes: face_mask_detection (mediapipe) makes the face mask, and
denoise_latents repaints only the masked face with the expression prompt.
SD 1.x, SD 2.x and SDXL main models are supported.

Multi-user InvokeAI servers take a bearer token, or an email and password
that are exchanged for one through /api/v1/auth/login (and again when the
token expires).
"""

import random
import time

import sdmux
from PIL import Image
from sdmux.backends import invokeai as sdmux_invokeai
from sdmux.backends.invokeai import QUEUE, SCHEDULERS, SUPPORTED_BASES, identifier  # noqa: F401

from ..images import b64_to_pil
from ..log import log
from .base import (
    BackendError,
    BackendNotReady,
    BackendRejected,
    BackendTimeout,
    Capability,
    FaceEditRequest,
    Fix,
    RemoteBackend,
    listed,
    match_choice,
    sdmux_errors,
)



def scheduler_name(sampler: str | None, scheduler: str | None) -> str:
    """Map an A1111 sampler + scheduler pair (or an InvokeAI name) to an InvokeAI scheduler; euler when there is none."""
    try:
        return sdmux_invokeai.scheduler_name(sampler, scheduler)
    except sdmux.Rejected:
        return "euler"


class InvokeAIClient(RemoteBackend):

    kind = "invokeai"
    label = "InvokeAI"
    default_url = "http://127.0.0.1:9090"

    def __init__(self, url: str | None = None, timeout: float | None = None, poll_interval: float = 0.5, **options) -> None:
        super().__init__(url, timeout, poll_interval=poll_interval, **options)

    # The email/password login (traded for a JWT through /api/v1/auth/login, and again when it
    # expires) is done by the sdmux client's transport.

    # Listings -------------------------------------------------------------
    def _models(self, model_type: str) -> list[dict]:
        with sdmux_errors():
            return self.client._raw_models(model_type)

    def main_models(self) -> list[dict]:
        return [m for m in self._models("main") if m.get("base") in SUPPORTED_BASES]

    @property
    def models(self) -> list[str]:
        return self._safe_list("models", lambda: (m["name"] for m in self.main_models()))

    @property
    def loras(self) -> list[str]:
        return self._safe_list("loras", lambda: (m["name"] for m in self._models("lora")))

    def lora_identities(self) -> dict[str, set[str]]:
        """InvokeAI's own hash of each LoRA file (sha256 when InvokeAI is set to hash with it)."""
        try:
            loras = self._models("lora")
        except BackendError:
            return {}
        return {m["name"]: {m["hash"].split(":", 1)[-1].lower()} for m in loras if m.get("name") and m.get("hash")}

    @property
    def samplers(self) -> list[str]:
        return list(SCHEDULERS)

    def ensure_ready(self) -> None:
        if not self.main_models():
            raise BackendNotReady("InvokeAI has no SD 1.x, SD 2.x or SDXL main models installed.")

    def capabilities(self) -> list[Capability]:
        version = self._get_json("/api/v1/app/version", timeout=10).get("version") or ""
        major = int(version.split(".")[0]) if version.split(".")[0].isdigit() else 0
        items = [
            Capability(
                "api",
                "InvokeAI 5 or newer",
                major >= 5,
                f"Version {version or 'unknown'}",
                fix=Fix(["Update InvokeAI to version 5 or newer with its launcher, then re-check."]),
            )
        ]
        items.append(
            listed(
                "Models",
                [m["name"] for m in self.main_models()],
                Fix(
                    [
                        "Install an SD 1.5 or SDXL main model: open the Model Manager, choose Add Models,",
                        "paste a model URL or Hugging Face repo, or pick one from Starter Models, then re-check.",
                    ]
                ),
            )
        )
        items.append(listed("LoRAs", self.loras, required=False))
        items.append(
            Capability(
                "lora_folder",
                "Automatic expression LoRA downloads",
                True,
                "InvokeAI installs missing expression LoRAs itself through its Model Manager API",
                required=False,
            )
        )
        return items

    def can_install_models(self) -> bool:
        return True

    def install_lora(self, url: str, name: str, access_token: str | None = None, timeout: float = 1800) -> bool:
        """Have InvokeAI download a LoRA from url through its Model Manager. access_token is sent as a bearer token."""
        params = {"source": url, "inplace": "false"}
        if access_token:
            params["access_token"] = access_token
        job = self._post_json("/api/v2/models/install", {"name": name}, params=params, timeout=60)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = (job.get("status") or "").lower()
            if status == "completed":
                return True
            if status in ("error", "cancelled"):
                raise BackendRejected(f"InvokeAI could not install {name}: {job.get('error') or status}")
            time.sleep(self.poll_interval)
            job = self._get_json(f"/api/v2/models/install/{job['id']}", timeout=30)
        raise BackendTimeout(f"InvokeAI did not finish installing {name} within {timeout:.0f}s.")

    def server_info(self) -> dict:
        return {"version": self._get_json("/api/v1/app/version", timeout=10).get("version")}

    def refresh_loras(self) -> bool:
        return True  # model lists are read fresh on every call

    # Graph ----------------------------------------------------------------
    def pick_model(self, wanted: str | None, models: list[dict], what: str) -> dict | None:
        names = [m["name"] for m in models]
        match = match_choice(wanted, names)
        return models[names.index(match)] if match else None

    def build_graph(self, request: FaceEditRequest, image_name: str, width: int, height: int) -> dict:
        models = self.main_models()
        model = self.pick_model(request.checkpoint, models, "model")
        if model is None:
            if not models:
                raise BackendNotReady("InvokeAI has no SD 1.x, SD 2.x or SDXL models.")
            model = models[0]
            log.warning(
                f"Checkpoint '{request.checkpoint or 'not set'}' not found in InvokeAI, using {model['name']}. "
                "Pick a model to choose another one."
            )
        sdxl = model["base"] == "sdxl"

        nodes: dict[str, dict] = {}
        edges: list[dict] = []

        def node(node_id: str, node_type: str, **fields) -> str:
            nodes[node_id] = {"id": node_id, "type": node_type, "is_intermediate": True, "use_cache": False, **fields}
            return node_id

        def edge(source: str, source_field: str, destination: str, destination_field: str) -> None:
            edges.append(
                {
                    "source": {"node_id": source, "field": source_field},
                    "destination": {"node_id": destination, "field": destination_field},
                }
            )

        loader = node("model_loader", "sdxl_model_loader" if sdxl else "main_model_loader", model=identifier(model))
        unet_source, clip_source = loader, loader
        if not sdxl and request.clip_skip > 1:
            clip_source = node("clip_skip", "clip_skip", skipped_layers=request.clip_skip - 1)
            edge(loader, "clip", clip_source, "clip")

        lora_models = self._models("lora") if request.loras else []
        selected = []
        for name, weight in request.loras:
            lora = self.pick_model(name, lora_models, "lora")
            if lora is None or lora.get("base") != model["base"]:
                log.warning(f"Lora '{name}' not found for {model['base']} in InvokeAI, skipping it.")
                continue
            selected.append(node(f"lora_{len(selected)}", "lora_selector", lora=identifier(lora), weight=weight))
        if selected:
            collect = node("lora_collect", "collect")
            for lora in selected:
                edge(lora, "lora", collect, "item")
            lora_loader = node("lora_loader", "sdxl_lora_collection_loader" if sdxl else "lora_collection_loader")
            edge(collect, "collection", lora_loader, "loras")
            edge(unet_source, "unet", lora_loader, "unet")
            edge(clip_source, "clip", lora_loader, "clip")
            if sdxl:
                edge(loader, "clip2", lora_loader, "clip2")
            unet_source, clip_source = lora_loader, lora_loader

        for prompt_id, text in (("positive", request.prompt), ("negative", request.negative_prompt)):
            if sdxl:
                node(
                    prompt_id, "sdxl_compel_prompt", prompt=text, style=text,
                    original_width=width, original_height=height, crop_top=0, crop_left=0,
                    target_width=width, target_height=height,
                )
                edge(clip_source, "clip", prompt_id, "clip")
                edge(clip_source if selected else loader, "clip2", prompt_id, "clip2")
            else:
                node(prompt_id, "compel", prompt=text)
                edge(clip_source, "clip", prompt_id, "clip")

        image = {"image_name": image_name}
        face_mask = node("face_mask", "face_mask_detection", image=image, minimum_confidence=request.confidence)
        i2l = node("i2l", "i2l", image=image)
        edge(loader, "vae", i2l, "vae")
        mask = node(
            "gradient_mask", "create_gradient_mask", image=image,
            edge_radius=max(request.mask_blur, 0) * 4, coherence_mode="Gaussian Blur", minimum_denoise=0.0,
        )
        edge(face_mask, "mask", mask, "mask")
        edge(loader, "vae", mask, "vae")
        edge(unet_source, "unet", mask, "unet")

        seed = request.seed if request.seed >= 0 else random.randint(0, 2**31 - 1)
        noise = node("noise", "noise", seed=seed, width=width, height=height, use_cpu=True)
        denoise = node(
            "denoise", "denoise_latents",
            steps=request.steps, cfg_scale=request.cfg_scale,
            scheduler=scheduler_name(request.sampler, request.scheduler),
            denoising_start=round(1 - min(max(request.denoise, 0.0), 1.0), 4), denoising_end=1.0,
        )
        edge(unet_source, "unet", denoise, "unet")
        edge("positive", "conditioning", denoise, "positive_conditioning")
        edge("negative", "conditioning", denoise, "negative_conditioning")
        edge(noise, "noise", denoise, "noise")
        edge(i2l, "latents", denoise, "latents")
        edge(mask, "denoise_mask", denoise, "denoise_mask")

        l2i = node("output", "l2i")
        edge(denoise, "latents", l2i, "latents")
        edge(loader, "vae", l2i, "vae")

        return {"id": "autoexpress", "nodes": nodes, "edges": edges}

    # Running --------------------------------------------------------------
    def upload_image(self, image: Image.Image) -> str:
        with sdmux_errors():
            return self.client.upload(image)

    def enqueue(self, graph: dict) -> int:
        with sdmux_errors():
            return self.client.enqueue_graph(graph)

    def wait_for(self, item_id: int) -> dict:
        with sdmux_errors():
            return self.client.wait(item_id)

    def fetch_image(self, item: dict) -> Image.Image:
        with sdmux_errors():
            return self.client.fetch(item)

    def img2img(self, payload: dict) -> Image.Image | None:
        self.last_error = None
        try:
            request = FaceEditRequest.from_payload(payload)
            source = b64_to_pil(request.image).convert("RGB")
            # Latents are 1/8 of the image size, so work on a multiple of 8 and scale back afterwards.
            width, height = max(64, source.width // 8 * 8), max(64, source.height // 8 * 8)
            work = source if (width, height) == source.size else source.resize((width, height), Image.LANCZOS)

            graph = self.build_graph(request, self.upload_image(work), width, height)
            result = self.fetch_image(self._run(graph))
            if result.size != source.size:
                result = result.resize(source.size, Image.LANCZOS)
            return result
        except BackendError as e:
            return self._fail(e)
        except (KeyError, ValueError, TypeError) as e:
            return self._fail(BackendRejected(f"Unexpected response from InvokeAI: {e}"))

    def _run(self, graph: dict) -> dict:
        """Enqueue a graph and return its queue item once finished; interrupt() cancels just this item."""
        client = self.client
        with sdmux_errors(), client._job():
            client._item_id = client.enqueue_graph(graph)
            try:
                if client._cancel.is_set():
                    client.http.request("PUT", f"{QUEUE}/i/{client._item_id}/cancel", timeout=10)
                return client.wait(client._item_id)
            finally:
                client._item_id = None

    def interrupt(self) -> None:
        try:
            with sdmux_errors():
                self.client.interrupt()
        except BackendError as e:
            log.error(f"Interrupt failed: {e}")
