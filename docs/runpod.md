# Running the ComfyUI workflows on RunPod

AutoExpress talks to ComfyUI over its API, so ComfyUI can run on a rented GPU while AutoExpress runs on your own machine. This is the setup used to develop and test the expression, pose and animated sprite workflows.

## Pod

| | |
|---|---|
| Container image | `runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04` (RunPod's official PyTorch image, available on every RunPod GPU) |
| GPU | RTX PRO 6000 (96 GB) is what the animated sprites were tested on. Any 48 GB+ card works well (RTX 6000 Ada, L40S, A40, A100, H100); 24 GB cards work with ComfyUI's model offloading, more slowly. Blackwell cards need the CUDA 12.8 image above. |
| Container disk | 200 GB (the models below take about 80 GB) |
| Volume | none, or 100 GB+ if you want the models to survive stopping the pod (then run the setup script with `COMFYUI_DIR=/workspace/ComfyUI`). RunPod's default 20 GB volume is too small. |
| HTTP ports | 8888 (Jupyter), 8188 (ComfyUI) |
| Environment | `JUPYTER_PASSWORD` set to a password of your own |

Create it in the RunPod console (Pods > Deploy, pick the GPU, "Edit template" to set the image, disk, ports and password), or with the API:

```bash
pip install requests
RUNPOD_API_KEY=... python scripts/runpod/create_pod.py
```

`create_pod.py` tries the GPUs above in order and prints the Jupyter and ComfyUI addresses. Jupyter's password is `JUPYTER_PASSWORD` if you set it, else a new one saved to `runpod_jupyter_password.txt`.

## ComfyUI and the models

Open the pod's Jupyter (`https://<pod id>-8888.proxy.runpod.net`), start a terminal and run:

```bash
curl -fsSL https://raw.githubusercontent.com/deepratna-awale/AutoExpress/main/scripts/runpod/setup_comfyui.sh | bash
```

[`setup_comfyui.sh`](../scripts/runpod/setup_comfyui.sh) installs ComfyUI with the Impact Pack and Subpack, downloads the models and starts ComfyUI on port 8188. It installs into `~/ComfyUI` on the container disk (set `COMFYUI_DIR` to use a volume), and skips anything already there, so it's safe to run again. Set `SKIP_WAN=1` or `SKIP_QWEN=1` to leave out a model, and `CHECKPOINT_URL` to also download a checkpoint for face inpainting.

| Model | Used for | Files (ComfyUI `models/`) | Size |
|---|---|---|---|
| Face detector | face inpainting (FaceDetailer) | `ultralytics/bbox/face_yolov8m.pt` | 50 MB |
| Qwen-Image-Edit 2511 | instruction edit expressions, poses | `diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors`, `text_encoders/qwen_2.5_vl_7b_fp8_scaled.safetensors`, `vae/qwen_image_vae.safetensors`, `loras/Qwen-Image-Edit-2509-Lightning-8steps-V1.0-bf16.safetensors` | 31 GB |
| Wan 2.2 image to video 14B | animated sprites | `diffusion_models/wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors`, `diffusion_models/wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors`, `text_encoders/umt5_xxl_fp8_e4m3fn_scaled.safetensors`, `vae/wan_2.1_vae.safetensors`, `loras/wan2.2_i2v_lightx2v_4steps_lora_v1_{high,low}_noise.safetensors` | 38 GB |
| Any SDXL / SD 1.5 checkpoint | face inpainting | `checkpoints/` (Animagine XL 4.0 for anime, RealVisXL for photos were used in testing) | 7 GB |

The same files can be fetched on any ComfyUI install with `python -m autoexpress_core.instruction_edit download <ComfyUI folder>` and `python -m autoexpress_core.animation download <ComfyUI folder>`.

### NSFW characters

Every model AutoExpress downloads is open weights and runs locally on the pod, with no content filter: Qwen-Image-Edit 2511 and Wan 2.2 image to video edit and animate adult characters as they are, and AutoExpress's poses never add or remove clothing. Nothing is sent to an online service.

For face inpainting, the checkpoint decides what the model can draw. These uncensored checkpoints work with AutoExpress's prompt styles (picked automatically from the file name):

| Checkpoint | Style | Prompt style |
|---|---|---|
| [Pony Diffusion V6 XL](https://civitai.com/models/257749) | anime, cartoon | `pony` |
| [NoobAI-XL](https://civitai.com/models/833294) / [WAI-Illustrious](https://civitai.com/models/827184) | anime (Danbooru tags) | `illustrious` |
| [Animagine XL 4.0](https://civitai.com/models/1188071) | anime (Danbooru tags) | `danbooru` |
| [Lustify SDXL](https://civitai.com/models/573152) | realistic photos | `sdxl_base` |

Civitai downloads need your API key: `wget -O models/checkpoints/<name>.safetensors "https://civitai.com/api/download/models/<version id>?token=$CIVITAI_API_KEY"`, or pass that URL as `CHECKPOINT_URL` to the setup script.

### Anime

No separate anime model is needed. The expressions and poses are edits of your own image, so its art style carries over, and Wan 2.2 keeps a drawn style through the animation. The anime checkpoints above only matter for face inpainting.

## Connecting AutoExpress

In AutoExpress pick ComfyUI (or Auto) and enter `https://<pod id>-8188.proxy.runpod.net`. The setup checklist then shows which features the pod is ready for.

On RTX PRO 6000 a Qwen-Image-Edit expression with a pose takes about 15 seconds and a 3 second Wan 2.2 clip (49 frames, 480p, 4 steps) about 15 seconds, so all 28 animated expressions take around 15 to 30 minutes including background removal.

Stop the pod in the RunPod console when you're done; it bills by the hour while running.
