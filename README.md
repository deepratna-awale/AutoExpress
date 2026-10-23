<h1> <img src="autoexpress\static\ico\favicon-rounded.png" alt="Favicon" width="25px"> AutoExpress</h1>

# Introduction
Automatically creates 28 different expressions from a given image using [Automatic1111 Stable Diffusion WebUI API](https://github.com/AUTOMATIC1111/stable-diffusion-webui). The application uses Inpainting with [After Detailer Extension](https://github.com/Bing-su/adetailer) to inpaint the following expressions on the face:

### For the latest changes, goto: [Change Log](Changelog.md)

<p align="center">

| Emotion       | Emotion        | Emotion     | Emotion     |
| ------------- | -------------- | ----------- | ----------- |
| Admiration    | Amusement      | Anger       | Annoyance   |
| Approval      | Caring         | Confusion   | Curiosity   |
| Desire        | Disappointment | Disapproval | Disgust     |
| Embarrassment | Excitement     | Fear        | Gratitude   |
| Grief         | Joy            | Love        | Nervousness |
| Neutral       | Optimism       | Pride       | Realization |
| Relief        | Remorse        | Sadness     | Surprise    |

</p>

## Prompt Styles

Different checkpoints understand prompts differently, so the expression prompts come in one set per model family. Pick one from the **Prompt Style** dropdown, or leave it on **Auto** to choose from the checkpoint name.

| Prompt Style | Use for | Quality tags added |
| --- | --- | --- |
| Danbooru tags | SD1.5 anime models, Animagine, Anything, Counterfeit | `masterpiece, best quality` |
| e621 tags | Furry/anthro models (FluffyRock, Fluffusion, YiffyMix) | `best quality, detailed` |
| Pony Diffusion | Pony V6 XL and merges | `score_9, score_8_up, score_7_up` |
| Illustrious / NoobAI | Illustrious-XL, NoobAI-XL, WAI | `masterpiece, best quality, amazing quality` |
| SDXL / SD1.5 (CLIP) | General and realistic SDXL/SD1.5 models | none |
| Natural language | Flux, SD3/3.5, HiDream, Chroma, Qwen-Image, Lumina (for face detailing on Flux, use dev rather than schnell) | none |

Quality and negative tags are only added when your prompt doesn't already contain them. The sets live in `autoexpress_core/resources/expressions/`, one JSON file per family, so adding a new family is just adding a file.

### Expression LoRAs

AutoExpress also adds a LoRA that helps faces show emotion, matched to the checkpoint's architecture:

| Architecture | LoRA |
| --- | --- |
| Pony | [Facial Expressions (Pony v1.0)](https://civitai.com/models/541620?modelVersionId=1815859) |
| Illustrious / NoobAI | [Facial Expressions (Illu v1.0)](https://civitai.com/models/541620?modelVersionId=1815930) + [Face Enhancer Illustrious](https://civitai.com/models/1625070) |
| SDXL | [Facial Expressions (XL v3)](https://civitai.com/models/541620?modelVersionId=761462) |
| SD1.5 | [Facial Expressions (SD1.5)](https://civitai.com/models/541620?modelVersionId=715217) |
| Flux | [Expression Helper 2.0](https://civitai.com/models/914282) |

If the WebUI runs on the same machine (or you set **WebUI LoRA folder** in settings, or `AUTOEXPRESS_LORA_DIR`), missing LoRAs are downloaded there automatically and checked against their SHA-256. Civitai requires an API key for downloads: enter it in settings or set `CIVITAI_API_KEY`. If the folder isn't reachable, AutoExpress uses the LoRAs only when they're already installed on the server. Turn them off with the **Expression LoRAs** switch. The list lives in `autoexpress_core/resources/expression_loras.json`. Inside a WebUI or ComfyUI the LoRA folder is always known, so missing LoRAs are always fetched there (see below).


# Examples

### Anime

<div style="text-align:center">
    <figure>
        <img src ="autoexpress/resources/images/anime_grid.png" alt="Anime Image Grid" width="100%">
        <figcaption>Anime Image Emotion Grid</figcaption>
    </figure>
</div>


The above is an example anime expressions on the following image without cherry picking results.

<div style="text-align:center">
    <figure>
        <img src="autoexpress\resources\images\anime_input.png" alt="Realistic Input Image" width="100%">
        <figcaption>Anime input image</figcaption>
    </figure>
</div>


### Realistic

<div style="text-align:center">
    <figure>
        <img src ="autoexpress/resources/images/realistic_grid.png" alt="Realistic Image Grid" width="100%">
        <figcaption>Realistic Image Emotion Grid</figcaption>
    </figure>
</div>

The above is an example realistic expressions on the following image without cherry picking results.

<div style="text-align:center">
    <figure>
        <img src="autoexpress\resources\images\realistic_input.png" alt="Realistic Input Image" width="100%">
        <figcaption>Realistic input image</figcaption>
    </figure>
</div>

---

# Use AutoExpress inside your WebUI

AutoExpress can run inside the WebUI you already use. Inside a WebUI it runs in-process like any other extension, so the `--api` flag is not needed. All integrations share the same expression prompts and generation logic (`autoexpress_core`).

| WebUI | How it shows up | Face inpainting done by |
| ----- | --------------- | ----------------------- |
| AUTOMATIC1111, Forge, reForge, SD.Next | **AutoExpress** tab | [ADetailer](https://github.com/Bing-su/adetailer) |
| ComfyUI (and SwarmUI, which runs ComfyUI) | **AutoExpress** nodes | [Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) FaceDetailer |
| InvokeAI | **AutoExpress Expression Prompts** node | InvokeAI's own inpainting nodes |
| Standalone (this repo's Flask app) | Web app on port 5000 | Any of the WebUIs above over their HTTP API, see [Supported WebUIs](#supported-webuis) |

Fooocus has no extension system, so it is not supported.

## AUTOMATIC1111 / Forge / reForge / SD.Next

1. Install [ADetailer](https://github.com/Bing-su/adetailer) if you have not already.
2. Go to **Extensions → Install from URL**, paste `https://github.com/deepratna-awale/AutoExpress` and press **Install**. You can also clone the repository into `extensions/`.
3. Restart the WebUI and open the **AutoExpress** tab.
4. Drop in a character image. The prompt, sampler, steps, CFG and seed are filled in from the image's metadata when it has any.
5. Pick a [prompt style](#prompt-styles) (**auto** picks it from the checkpoint) and the expressions you want, then press **Generate**.

Images are saved to `outputs/autoexpress/<character name>/`. You can change that folder under **Settings → AutoExpress**. A labelled sprite sheet is saved next to them when that option is ticked.

With **Expression LoRAs** ticked, the matching [expression LoRA](#expression-loras) is downloaded into the WebUI's LoRA folder (`--lora-dir`, or `models/Lora`) the first time, then added to the prompt. Civitai needs an API key for downloads. AutoExpress reuses one you already have: it checks the key typed into the tab, then **Settings → AutoExpress**, then the key saved by [Civitai Browser+](https://github.com/BlafKing/sd-civitai-browser-plus) or [Civitai Helper](https://github.com/zixaphir/Stable-Diffusion-Webui-Civitai-Helper), then `CIVITAI_API_KEY` / `CIVITAI_API_TOKEN`.

## ComfyUI

1. Install [ComfyUI Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) and [Impact Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack), which provides the face detector.
2. Clone this repository into `ComfyUI/custom_nodes/` (or install it from ComfyUI Manager), then restart ComfyUI.
3. Build the graph:

```
Load Checkpoint ─ model / clip ─► AutoExpress Expression LoRAs ─ model / clip ──────────────┐
                └ vae ──────────────────────────────────────────────────────────────────────┤
                                  AutoExpress Expression LoRAs ─ lora_trigger ─┐            │
Load Image ────────────────────────────────────────────────────────────────────┼────────────┤
UltralyticsDetectorProvider (bbox/face) ───────────────────────────────────────┼────────────┤
CLIP Text Encode (positive: your character prompt) ────────────────────────────┼────────────┤
                                                                               ▼            ▼
AutoExpress Expression Prompts ─ negative ─► CLIP Text Encode ─────────────────────► FaceDetailer
                               ─ prompts ──────────────────────────────────────────► (wildcard input)
                               ─ names ─┐                                                   │ image
                                        ├─► AutoExpress Save Expressions ◄──────────────────┤
                                        └─► AutoExpress Sprite Sheet ◄──────────────────────┘ ─► Preview Image
```

`prompts` is a list, so ComfyUI runs FaceDetailer once per expression on its own. Connect `names` to the save and sprite sheet nodes so every file is named after its expression. Set the same checkpoint in the `ckpt_name` input of the AutoExpress nodes so **auto** can pick the prompt style and LoRAs. The LoRA node is optional.

| Node | What it does |
| ---- | ------------ |
| AutoExpress Expression Prompts | Every expression (or a comma separated subset) as a prompt list in the right [prompt style](#prompt-styles), plus the matching negative prompt |
| AutoExpress Expression Prompt | One expression prompt |
| AutoExpress Expression LoRAs | Applies the matching [expression LoRAs](#expression-loras), downloading them into `models/loras` when missing, and outputs their trigger words. Leave its key empty to reuse the one from [ComfyUI LoRA Manager](https://github.com/willmiao/ComfyUI-Lora-Manager) or `CIVITAI_API_KEY` / `CIVITAI_API_TOKEN` |
| AutoExpress Save Expressions | Saves to `output/autoexpress/<character>/<expression>.png` |
| AutoExpress Sprite Sheet | Tiles the results into one labelled image |

## InvokeAI

Symlink (or copy) `invokeai_nodes/autoexpress` into `<INVOKEAI_ROOT>/nodes/` and restart InvokeAI. If you copied the folder, also run `pip install git+https://github.com/deepratna-awale/AutoExpress` inside InvokeAI's environment. The **AutoExpress Expression Prompts** node outputs one prompt per expression in the chosen prompt style, plus the matching negative prompt, ready to iterate over in a face inpainting graph.

---

# Standalone App

## Requirements
- [Python3](https://www.python.org/downloads/) Prefer version 10
- One of the [supported WebUIs](#supported-webuis), running locally or online, with its API reachable.
    - I'm currently working on integrating my [CivitAI-Model-Downloader](https://github.com/deepratna-awale/CivitAI-Model-Downloader) to automatically download LORAs.

## Supported WebUIs

Pick the WebUI in the **WebUI** dropdown at the top of the sidebar, enter its address (or leave it empty for the default shown) and press connect. The model, sampler, scheduler and lora lists are then read from that WebUI.

| WebUI | Default address | What it needs | How the face is repainted |
| ----- | --------------- | ------------- | ------------------------- |
| [AUTOMATIC1111](https://github.com/AUTOMATIC1111/stable-diffusion-webui) | `127.0.0.1:7860` | Started with `--api`, [ADetailer](https://github.com/Bing-su/adetailer) installed | ADetailer |
| [Forge](https://github.com/lllyasviel/stable-diffusion-webui-forge) / [reForge](https://github.com/Panchovix/stable-diffusion-webui-reForge) | `127.0.0.1:7860` | Started with `--api`, ADetailer installed | ADetailer |
| [SD.Next](https://github.com/vladmandic/sdnext) | `127.0.0.1:7860` | ADetailer installed | ADetailer |
| [ComfyUI](https://github.com/comfyanonymous/ComfyUI) | `127.0.0.1:8188` | [Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) + [Impact Subpack](https://github.com/ltdrdata/ComfyUI-Impact-Subpack), a face model such as `face_yolov8m.pt` in `models/ultralytics/bbox` | FaceDetailer |
| [SwarmUI](https://github.com/mcmonkeyprojects/SwarmUI) | `127.0.0.1:7801` | Nothing extra. A YOLO face model in `Models/yolov8` is used when present, otherwise CLIPSeg | `<segment:face>` refining |
| [InvokeAI](https://github.com/invoke-ai/InvokeAI) 5+ | `127.0.0.1:9090` | An SD 1.x, SD 2.x or SDXL model | Face mask + inpainting graph |

Notes:
- The A1111 family only receives the built-in scripts that WebUI actually has, so the same request works on A1111, Forge, reForge and SD.Next.
- ComfyUI, SwarmUI and InvokeAI have no "use same checkpoint", so pick a model. If none is picked the first one is used and a warning is logged.
- A1111 sampler and scheduler names read from image metadata (e.g. `DPM++ 2M` + `Karras`) are translated to the selected WebUI's names.
- `<lora:name:weight>` tags in the prompt are turned into that WebUI's lora loaders.

### Protected or remote WebUIs

- **Username and password**: put them in the URL (`https://user:pass@host:7860`) or set `AUTOEXPRESS_BACKEND_USERNAME` / `AUTOEXPRESS_BACKEND_PASSWORD`. A1111/Forge started with `--api-auth` get them as basic auth, SwarmUI logs in with them, and InvokeAI (multi-user mode) trades its email and password for a token and renews it when it expires.
- **Token**: `AUTOEXPRESS_BACKEND_TOKEN` is sent as `Authorization: Bearer ...` (for proxies such as RunPod or a reverse proxy), or as SwarmUI's `swarm_token` cookie.
- Connection problems come back as one of these error codes, shown in the UI and returned by the API: `backend_unavailable`, `backend_timeout`, `backend_auth`, `backend_not_ready`, `backend_rejected`, `cancelled`, `invalid_request`.

## Running in production

```bash
pip install -r requirements.txt
python -m autoexpress            # waitress on 0.0.0.0:5000
```

Every setting is an environment variable, listed with defaults in [autoexpress/config.py](autoexpress/config.py). The most useful ones:

| Variable | Default | |
| --- | --- | --- |
| `AUTOEXPRESS_BACKEND` / `AUTOEXPRESS_BACKEND_URL` | `a1111` / its default | WebUI to connect to at startup |
| `AUTOEXPRESS_REQUEST_TIMEOUT` / `AUTOEXPRESS_JOB_TIMEOUT` | `30` / `1800` s | Quick calls / one expression |
| `AUTOEXPRESS_RETRIES` | `2` | Retries with backoff on connection errors and 502/503/504 |
| `AUTOEXPRESS_OUTPUT_DIR` | `./Output` | Where expressions are saved |
| `AUTOEXPRESS_MAX_UPLOAD_MB` | `32` | Request size limit |
| `AUTOEXPRESS_LOG_JSON` / `AUTOEXPRESS_LOG_FILE` | off | JSON log lines, rotated log file |
| `AUTOEXPRESS_HOST` / `AUTOEXPRESS_PORT` | `0.0.0.0` / `5000` | Listen address |

Generation runs as a queued job on one worker thread, so several clicks or clients never send overlapping requests to the WebUI. Each job keeps its own connection, so switching WebUI in the sidebar doesn't disturb a running job. Every response carries an `X-Request-ID`, which also appears in the log lines.

### HTTP API

| Route | |
| --- | --- |
| `GET /health` | AutoExpress is up (does not call the WebUI) |
| `GET /backend/status` | Selected WebUI: `ready`, `message`, `error`, `latency_ms`, `info` (version etc.) |
| `GET /backends` | WebUIs you can pick, the selected one and its URL |
| `POST /receive_data` | `{"text": url, "backend": id, "username", "password", "token"}` (all optional) |
| `GET /get-models`, `/get-samplers`, `/get-schedulers`, `/get-loras` | Lists from the selected WebUI (`[]` when unreachable) |
| `POST /generate` | Settings from the UI. Waits for the result unless `"wait": false`, which returns `202 {"job_id"}`. Optional `"expressions": [...]` picks a subset |
| `GET /jobs`, `GET /jobs/<id>` | Status (`queued`, `running`, `completed`, `failed`, `cancelled`), `progress` (`done`, `total`, `fraction`, `current`, `step`), `images`, `error` |
| `POST /jobs/<id>/cancel`, `POST /interrupt` | Cancel one job / every queued and running job |
| `GET /images/<folder>`, `GET /image/<folder>/<file>` | Saved results |

Invalid input gets HTTP 400 with `{"status": "Failed", "message", "error": {"code": "invalid_request", "fields": {...}}}`.

- ## Additional packages for Linux
- python3-pip
- python3-venv


## Run With Docker (Requires [Docker](https://www.docker.com/))

> Now AutoExpress is also available as a [Docker Image](https://hub.docker.com/r/deepratna/autoexpress)

Pull image from DockerHub
```bash
docker pull deepratna/autoexpress
```
Run
```bash
docker run -p 5000:5000 deepratna/autoexpress
```

## Quick Start with Pre-built Releases (Recommended)

Download the latest pre-built release for your platform from the [Releases page](https://github.com/deepratna-awale/AutoExpress/releases):

### Windows
1. Download `autoexpress-v*.*.* -Windows_Release.zip`
2. Extract the zip file
3. Double-click `run.bat` to start AutoExpress
4. Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser

### Linux
1. Download `autoexpress-v*.*.* -Linux_Release.zip`
2. Extract the zip file
3. Run `./run.sh` to start AutoExpress
4. Open [http://127.0.0.1:5000](http://127.0.0.1:5000) in your browser

**Note**: Pre-built releases include all dependencies pre-installed in a virtual environment. No additional setup required!

## Alternative Installation Methods

### Using Installer
- Clone repository
```bash
git clone https://github.com/deepratnaawale/AutoExpress.git
cd AutoExpress
```
- Run installer
  - Linux
  ```bash
  chmod +x install.sh
  ./install.sh
  ```
  - Windows (Simply execute the [install.bat](install.bat) file)

### Manual Installation
```bash
git clone https://github.com/deepratnaawale/AutoExpress.git
cd AutoExpress
```

- Create and activate virtual enviorenment
```bash
python3 -m venv .venv
```
- WINDOWS
```bash
.venv\Scripts\activate
```
- LINUX
```bash
source .venv/bin/activate
```

- Install Requirements
```bash
pip install -r requirements.txt
```
---

## Launch App
- Linux
```bash
chmod +x ./run.sh
./run.sh
```
- Windows (Simply execute the [run.bat](run.bat) file)

> Connect to the AutoExpress UI at
[http://127.0.0.1:5000](http:127.0.0.1:5000)


---

## Launch Your WebUI's API (A1111 / Forge example)
> You can check if the api is active by accessing the docs (if running locally)
[http://127.0.0.1:7860/docs#/default/](http://127.0.0.1:7860/docs#/default/)


# Usage
![UI Description](autoexpress/resources/images/UI.png)

It's pretty Straight forward. Keep an eye on the logs in the console. Dropping an image will auto populate all attributes in the UI if the image has Stable Diffusion info text. The Generate button shows how many expressions are done while a job runs.

PS: This is a very handy tool to use with [Silly Tavern](https://github.com/SillyTavern/SillyTavern) to **generate character expressions sprites** for any bot.

# Latest UI
![LatestUI](autoexpress/resources/images/AutoExpressUI_2024_11_13.png)

# Future Work
- Change pose along with expression keeping consistent clothes and background. (Probably via Controlnets and ADetailer)
- Better Expressions for Realistic Images.
- Tests to check each module.

# Special Thanks
[SD Parsers by d3x-at](https://github.com/d3x-at/sd-parsers)

[SD API Examples](https://github.com/AUTOMATIC1111/stable-diffusion-webui/discussions/3734)

[Avery Velfaire](https://github.com/AveryVeilfaire) for bug fixes, UI design, and prompt engineering.
