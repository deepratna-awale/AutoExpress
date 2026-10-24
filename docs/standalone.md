# AutoExpress standalone app

The standalone app is a small web server that talks to a WebUI over its API, locally or on a remote GPU (RunPod, a home server, and so on). Use it when you'd rather keep AutoExpress out of your WebUI, or when the WebUI runs somewhere else.

<p align="center">
  <img src="../.github/readme/nextjs_ui.jpg" alt="The AutoExpress web interface with the WebUI selector, prompt style, the dropped image and the generated expressions" width="100%">
</p>

It gives matching results whichever WebUI does the work:

<p align="center">
  <img src="../.github/readme/standalone_backends.jpg" alt="Joy, anger and surprise generated through the A1111, Forge and ComfyUI APIs" width="60%">
</p>

## Pre-built releases (recommended)

Download the latest release for your platform from the [Releases page](https://github.com/deepratna-awale/AutoExpress/releases), extract it and run `run.bat` (Windows) or `./run.sh` (Linux). Then open [http://127.0.0.1:5000](http://127.0.0.1:5000). Releases include all dependencies and the web interface.

## Hugging Face Space

Try it without installing anything at [huggingface.co/spaces/damientheodore/AutoExpress](https://huggingface.co/spaces/damientheodore/AutoExpress), then paste the address of your WebUI (it has to be reachable from the internet, such as a RunPod proxy URL). The Space is one shared instance: the connected WebUI, a Civitai key and the generated images are shared with everyone using it. For your own private copy, use **⋮ → Duplicate this Space** and make it private. Generated images last until the Space restarts.

The Space is built from the [Dockerfile](../Dockerfile) and updated from `main` by the [Hugging Face Space workflow](../.github/workflows/huggingface-space.yml). Its page and settings come from [space/README.md](../space/README.md). The workflow needs an `HF_TOKEN` repository secret with write access; set the `HF_SPACE` repository variable to publish somewhere else.

## Docker

```bash
docker pull deepratna/autoexpress
docker run -p 5000:5000 deepratna/autoexpress
```

The container runs as an unprivileged user with uid 1000. If you mount a folder for the results, make it writable by that user (`-v "$PWD/Output:/AutoExpress/Output"` after `chown 1000 Output`). Build with `--build-arg PRELOAD_REMBG_MODELS="isnet-anime u2net_human_seg"` to include the background removal models in the image instead of downloading them on first use.

## From source

Needs [Python](https://www.python.org/downloads/) 3.10+ (on Debian/Ubuntu also `python3-venv`) and, for the web interface, [Node.js](https://nodejs.org/) 20.9+ (26 recommended) with [pnpm](https://pnpm.io/) or corepack.

```bash
git clone https://github.com/deepratna-awale/AutoExpress.git
cd AutoExpress
./install.sh            # Windows: install.bat
./run.sh                # Windows: run.bat
```

`install` creates `.venv`, installs the Python requirements and builds the web interface into `frontend/out`. Run it again after pulling updates. It reuses `.venv`; `--clean` starts over and `--skip-frontend` installs only the Python side. Without Node.js it skips the build and the original interface is served. `run` starts the production server; set `AUTOEXPRESS_PORT`, `AUTOEXPRESS_BACKEND_URL` and the other [settings](../autoexpress/config.py) as environment variables. `run_debug` starts Flask's debug server on 127.0.0.1 for development.

Or by hand:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m autoexpress              # production server on 0.0.0.0:5000
```

The web interface is built with Next.js. Release zips and the Docker image already include it, and `install` builds it from source. To build it by hand:

```bash
cd frontend
pnpm install
pnpm build
```

Flask then serves it at [http://127.0.0.1:5000](http://127.0.0.1:5000). Without a build, the original interface is served instead, and it's always available at [/classic](http://127.0.0.1:5000/classic). See [frontend/README.md](../frontend/README.md) for development.

## Using it

1. Paste your WebUI's address and press connect. AutoExpress detects which WebUI it is, checks that everything it needs is installed, and reads the model, sampler, scheduler and LoRA lists from it.
2. Drop, paste or browse for a character image. Every parameter is filled in from its metadata. If the image's checkpoint, sampler or scheduler isn't on the connected WebUI, the closest installed one from the same model family is used, with a note under the field.
3. Choose a prompt style, enter a character name (the output folder) and press **Generate**. A progress bar shows the current expression, results appear in the gallery as they finish, and **Interrupt** cancels the job.

Results are saved to `Output/<character name>/`.

Tick **Remove background** to save every expression with a transparent background, so only the character is left (for SillyTavern sprites, VN engines and overlays). It runs [rembg](https://github.com/danielgatis/rembg) on the AutoExpress machine, not on the WebUI: `isnet-anime` for drawn characters and `u2net_human_seg` for photos (the **Photo** style or a realistic prompt style). Each model downloads once on first use (about 170 MB) and takes a few seconds per image on a CPU. Set `AUTOEXPRESS_BACKGROUND_MODEL` to use another rembg model, such as `birefnet-portrait` on a machine with a GPU.

With a ComfyUI backend, the **Method** dropdown switches between **Face inpainting** (FaceDetailer) and **Instruction edit** ([Qwen-Image-Edit](comfyui.md#instruction-edit-mode-qwen-image-edit), which needs its models on the ComfyUI side).

## Supported WebUIs

Paste the WebUI's address and press connect. The WebUI can run anywhere: on this machine, elsewhere on your network, or on a hosted GPU such as RunPod (`https://<pod-id>-7860.proxy.runpod.net`), behind https, a reverse-proxy sub-path or a login. With **Detect automatically** (the default) AutoExpress asks the address which WebUI it is. Pick one in the **WebUI** dropdown to skip detection.

After connecting, AutoExpress checks over the WebUI's API that everything it needs is there, such as ADetailer and its face model, ComfyUI's Impact Pack, checkpoints and samplers. Each missing piece is listed with steps for that WebUI, commands to copy and download links. Fix them, then press **Re-check**. The same report is at `GET /backend/capabilities`.

| WebUI | Usual address | What it needs | How the face is repainted |
| ----- | --------------- | ------------- | ------------------------- |
| [AUTOMATIC1111](https://github.com/AUTOMATIC1111/stable-diffusion-webui) | `127.0.0.1:7860` | Started with `--api`, [ADetailer](https://github.com/Bing-su/adetailer) installed | ADetailer |
| [Forge](https://github.com/lllyasviel/stable-diffusion-webui-forge) / [reForge](https://github.com/Panchovix/stable-diffusion-webui-reForge) | `127.0.0.1:7860` | Started with `--api`, ADetailer installed | ADetailer |
| [SD.Next](https://github.com/vladmandic/sdnext) | `127.0.0.1:7860` | ADetailer installed | ADetailer |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | `127.0.0.1:8188` | [Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) + [Impact Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack), a face model such as `face_yolov8m.pt` in `models/ultralytics/bbox` | FaceDetailer |
| [SwarmUI](https://github.com/mcmonkeyprojects/SwarmUI) | `127.0.0.1:7801` | Nothing extra. A YOLO face model in `Models/yolov8` is used when present, otherwise CLIPSeg | `<segment:face>` refining |
| [InvokeAI](https://github.com/invoke-ai/InvokeAI) 5+ | `127.0.0.1:9090` | An SD 1.x, SD 2.x or SDXL model | Face mask + inpainting graph |

- The A1111 family only receives the built-in scripts that WebUI actually has, so the same request works on A1111, Forge, reForge and SD.Next.
- ComfyUI, SwarmUI and InvokeAI have no "use same checkpoint", so pick a model. If none is picked the first one is used and a warning is logged.
- A1111 sampler and scheduler names read from image metadata (e.g. `DPM++ 2M` + `Karras`) are translated to the selected WebUI's names.
- `<lora:name:weight>` tags in the prompt are turned into that WebUI's LoRA loaders.
- Expression LoRAs are downloaded into the WebUI's LoRA folder only when that folder is on this machine. Otherwise InvokeAI is asked to install them through its Model Manager. For the other WebUIs, each missing LoRA is listed after the run with its download link and the folder it belongs in.

### Protected or remote WebUIs

- **Username and password**: put them in the URL (`https://user:pass@host:7860`) or set `AUTOEXPRESS_BACKEND_USERNAME` / `AUTOEXPRESS_BACKEND_PASSWORD`. A1111/Forge started with `--api-auth` get them as basic auth, SwarmUI logs in with them, and InvokeAI (multi-user mode) trades its email and password for a token and renews it when it expires.
- **Token**: `AUTOEXPRESS_BACKEND_TOKEN` is sent as `Authorization: Bearer ...` (for proxies such as RunPod or a reverse proxy), or as SwarmUI's `swarm_token` cookie.

## Configuration

Every setting is an environment variable, listed with defaults in [autoexpress/config.py](../autoexpress/config.py). The most useful ones:

| Variable | Default | |
| --- | --- | --- |
| `AUTOEXPRESS_BACKEND` / `AUTOEXPRESS_BACKEND_URL` | `auto` / none | WebUI to connect to at startup (`auto` detects it from the URL) |
| `AUTOEXPRESS_REQUEST_TIMEOUT` / `AUTOEXPRESS_JOB_TIMEOUT` | `30` / `1800` s | Quick calls / one expression |
| `AUTOEXPRESS_RETRIES` | `2` | Retries with backoff on connection errors and 502/503/504 |
| `AUTOEXPRESS_OUTPUT_DIR` | `./Output` | Where expressions are saved |
| `AUTOEXPRESS_LORA_DIR` | unset | The WebUI's LoRA folder, for expression LoRA downloads |
| `AUTOEXPRESS_MAX_UPLOAD_MB` | `32` | Request size limit |
| `AUTOEXPRESS_LOG_JSON` / `AUTOEXPRESS_LOG_FILE` | off | JSON log lines, rotated log file |
| `AUTOEXPRESS_BACKGROUND_MODEL` | `isnet-anime` / `u2net_human_seg` | rembg model for **Remove background** (drawn / photo) |
| `AUTOEXPRESS_HOST` / `AUTOEXPRESS_PORT` | `0.0.0.0` / `5000` | Listen address |

Generation runs as a queued job on one worker thread, so several clicks or clients never send overlapping requests to the WebUI. Each job keeps its own connection, so switching WebUI doesn't disturb a running job. Every response carries an `X-Request-ID`, which also appears in the log lines.

## HTTP API

| Route | |
| --- | --- |
| `GET /health` | AutoExpress is up (does not call the WebUI) |
| `GET /backend/status` | Selected WebUI: `ready`, `message`, `error`, `latency_ms`, `info` (version etc.) |
| `GET /backend/capabilities` | What the selected WebUI has for AutoExpress: `ready`, `missing`, and `items` of `{key, label, ok, detail, required, fix: {steps, commands, links}}` |
| `GET /backends` | WebUIs you can pick (`auto` first), the selected one and its URL |
| `POST /receive_data` | `{"text": url, "backend": "auto" or an id, "username", "password", "token"}` (all optional). Returns the WebUI it connected to |
| `GET /get-models`, `/get-samplers`, `/get-schedulers`, `/get-loras` | Lists from the selected WebUI (`[]` when unreachable) |
| `GET /expression-families`, `POST /expression-family` | Prompt styles and the selected one |
| `GET /expression-loras`, `POST /expression-loras` | Expression LoRA settings and status, including which source the Civitai key came from |
| `GET /edit-methods` | Expression methods the selected WebUI supports (`inpaint`, and `instruct` on ComfyUI) |
| `POST /generate` | Settings from the UI. `"method": "instruct"` uses instruction edit instead of face inpainting. Waits for the result unless `"wait": false`, which returns `202 {"job_id"}`. Optional `"expressions": [...]` picks a subset |
| `GET /jobs`, `GET /jobs/<id>` | Status (`queued`, `running`, `completed`, `failed`, `cancelled`), `progress` (`done`, `total`, `fraction`, `current`, and `step` with the sampler's `fraction`, `step`, `steps` and `eta` where the WebUI reports them), `images`, `error`, `notes` (e.g. expression LoRAs to install by hand, with links) |
| `POST /jobs/<id>/cancel`, `POST /interrupt` | Cancel one job / every queued and running job |
| `GET /images/<folder>`, `GET /image/<folder>/<file>` | Saved results |

Invalid input gets HTTP 400 with `{"status": "Failed", "message", "error": {"code": "invalid_request", "fields": {...}}}`.

`/generate` checks the WebUI before queueing, so an unreachable or unready WebUI fails at once instead of after the jobs ahead of it. WebUI failures answer with the same body and an HTTP status that matches `error.code`:

| `error.code` | HTTP |
| --- | --- |
| `backend_unavailable` | 503 |
| `backend_timeout` | 504 |
| `backend_auth` | 401 |
| `backend_not_ready` | 409 |
| `backend_rejected`, `backend_error` | 502 |

[← Back to the README](../README.md)
