"""
Backend for an InvokeAI server (5.x and later), driven through its session queue API.

InvokeAI has no ADetailer, so each expression is an inpainting graph built from
core nodes: face_mask_detection (mediapipe) makes the face mask, and
denoise_latents repaints only the masked face with the expression prompt.
SD 1.x, SD 2.x and SDXL main models are supported.
"""

import io
import random
import time

import requests
from PIL import Image

from ..images import b64_to_pil
from ..log import log
from .base import BackendError, FaceEditRequest, RemoteBackend, match_choice

QUEUE = "/api/v1/queue/default"
SUPPORTED_BASES = ("sd-1", "sd-2", "sdxl")

# InvokeAI folds the scheduler into the sampler name; "_k" variants use Karras sigmas.
SCHEDULERS = [
    "euler", "euler_k", "euler_a", "dpmpp_2m", "dpmpp_2m_k", "dpmpp_2m_sde", "dpmpp_2m_sde_k",
    "dpmpp_sde", "dpmpp_sde_k", "dpmpp_2s", "dpmpp_2s_k", "dpmpp_3m", "dpmpp_3m_k", "heun", "heun_k",
    "lms", "lms_k", "kdpm_2", "kdpm_2_k", "kdpm_2_a", "kdpm_2_a_k", "deis", "deis_k", "unipc", "unipc_k",
    "ddim", "ddpm", "pndm", "lcm", "tcd",
]
A1111_SAMPLERS = {
    "euler": "euler",
    "euler a": "euler_a",
    "heun": "heun",
    "lms": "lms",
    "dpm2": "kdpm_2",
    "dpm2 a": "kdpm_2_a",
    "dpm++ 2s a": "dpmpp_2s",
    "dpm++ sde": "dpmpp_sde",
    "dpm++ 2m": "dpmpp_2m",
    "dpm++ 2m sde": "dpmpp_2m_sde",
    "dpm++ 3m sde": "dpmpp_3m",
    "ddim": "ddim",
    "unipc": "unipc",
    "lcm": "lcm",
}


def scheduler_name(sampler: str | None, scheduler: str | None) -> str:
    """Map an A1111 sampler + scheduler pair (or an InvokeAI name) to an InvokeAI scheduler."""
    if sampler in SCHEDULERS:
        return sampler
    name = A1111_SAMPLERS.get((sampler or "").strip().lower(), "euler")
    if (scheduler or "").strip().lower() == "karras" and f"{name}_k" in SCHEDULERS:
        name = f"{name}_k"
    return name


def identifier(model: dict) -> dict:
    return {key: model[key] for key in ("key", "hash", "name", "base", "type")}


class InvokeAIClient(RemoteBackend):

    kind = "invokeai"
    label = "InvokeAI"
    default_url = "http://127.0.0.1:9090"

    def __init__(self, url: str | None = None, timeout: float = 30, job_timeout: float = 1800, poll_interval: float = 0.5) -> None:
        super().__init__(url, timeout)
        self.job_timeout = job_timeout
        self.poll_interval = poll_interval
        self._item_id: int | None = None
        self._interrupted = False

    # Listings -------------------------------------------------------------
    def _models(self, model_type: str) -> list[dict]:
        return self._get_json("/api/v2/models/", params={"model_type": model_type}).get("models", [])

    def main_models(self) -> list[dict]:
        return [m for m in self._models("main") if m.get("base") in SUPPORTED_BASES]

    @property
    def models(self) -> list[str]:
        return self._safe_list("models", lambda: (m["name"] for m in self.main_models()))

    @property
    def loras(self) -> list[str]:
        return self._safe_list("loras", lambda: (m["name"] for m in self._models("lora")))

    @property
    def samplers(self) -> list[str]:
        return list(SCHEDULERS)

    def check_ready(self) -> tuple[bool, str]:
        try:
            models = self.main_models()
        except (requests.RequestException, ValueError) as e:
            return False, f"Could not reach InvokeAI at {self._base_url}. ({e})"
        if not models:
            return False, "InvokeAI has no SD 1.x, SD 2.x or SDXL main models installed."
        return True, "ok"

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
                raise BackendError("InvokeAI has no SD 1.x, SD 2.x or SDXL models.")
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
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        response = self._request(
            "POST",
            "/api/v1/images/upload",
            params={"image_category": "user", "is_intermediate": "true"},
            files={"file": ("autoexpress.png", buffer.getvalue(), "image/png")},
        )
        response.raise_for_status()
        return response.json()["image_name"]

    def enqueue(self, graph: dict) -> int:
        response = self._request("POST", f"{QUEUE}/enqueue_batch", json={"batch": {"graph": graph, "runs": 1}, "prepend": False})
        if response.status_code not in (200, 201):
            raise BackendError(f"InvokeAI rejected the graph: {response.text[:2000]}")
        item_ids = response.json().get("item_ids")
        if not item_ids:
            raise BackendError("InvokeAI did not return a queue item. InvokeAI 5 or later is required.")
        return item_ids[0]

    def wait_for(self, item_id: int) -> dict | None:
        deadline = time.monotonic() + self.job_timeout
        while time.monotonic() < deadline:
            item = self._get_json(f"{QUEUE}/i/{item_id}")
            status = item.get("status")
            if status == "completed":
                return item
            if status in ("failed", "canceled"):
                log.error(f"InvokeAI job {item_id} {status}: {item.get('error_message') or item.get('error') or ''}")
                return None
            if self._interrupted:
                return None
            time.sleep(self.poll_interval)
        log.error(f"InvokeAI job {item_id} did not finish within {self.job_timeout}s.")
        return None

    def fetch_image(self, item: dict) -> Image.Image | None:
        session = item.get("session") or {}
        prepared = (session.get("source_prepared_mapping") or {}).get("output") or []
        results = session.get("results") or {}
        output = next((results[p] for p in prepared if p in results), None)
        if not output or "image" not in output:
            log.error("InvokeAI finished without an output image.")
            return None
        response = self._request("GET", f"/api/v1/images/i/{output['image']['image_name']}/full")
        response.raise_for_status()
        result = Image.open(io.BytesIO(response.content))
        result.load()
        return result

    def img2img(self, payload: dict) -> Image.Image | None:
        self._interrupted = False
        try:
            request = FaceEditRequest.from_payload(payload)
            source = b64_to_pil(request.image).convert("RGB")
            # Latents are 1/8 of the image size, so work on a multiple of 8 and scale back afterwards.
            width, height = max(64, source.width // 8 * 8), max(64, source.height // 8 * 8)
            work = source if (width, height) == source.size else source.resize((width, height), Image.LANCZOS)

            graph = self.build_graph(request, self.upload_image(work), width, height)
            self._item_id = self.enqueue(graph)
            item = self.wait_for(self._item_id)
            result = self.fetch_image(item) if item else None
            if result is not None and result.size != source.size:
                result = result.resize(source.size, Image.LANCZOS)
            return result
        except (BackendError, requests.RequestException, KeyError, ValueError) as e:
            log.error(f"InvokeAI generation failed: {e}")
            return None
        finally:
            self._item_id = None

    def interrupt(self) -> None:
        self._interrupted = True
        if self._item_id is None:
            return
        try:
            self._request("PUT", f"{QUEUE}/i/{self._item_id}/cancel")
        except requests.RequestException as e:
            log.error(f"Interrupt failed: {e}")
