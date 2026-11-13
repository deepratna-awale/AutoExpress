# AutoExpress guide for AI agents

This file is for AI coding agents and assistants (and the people driving them) that set up, run,
extend or automate AutoExpress. It says what the project does, what each feature needs, which tools
make deployment easy, and the rules to keep. People new to the project should start with the
[README](README.md) and the [docs](docs/README.md); this guide links to them instead of repeating them.

## What AutoExpress is

AutoExpress makes a character's 28 expression sprites (the emotions SillyTavern's classifier
detects: admiration, amusement, anger ... surprise) from one image. It doesn't run a model itself: it
drives a Stable Diffusion WebUI over its API (or from inside it), repainting only the face with face
inpainting or editing the whole picture with Qwen-Image-Edit. On top of that it can animate the
sprites, change the pose with each expression, remove backgrounds, and turn a character picture into
a Live2D-style puppet.

| Feature | What comes out | Needs | Docs |
| --- | --- | --- | --- |
| Expressions (face inpainting) | 28 PNGs in `Output/<character>/` | Any supported WebUI (below) with a face detector | [standalone.md](docs/standalone.md) |
| Expressions (instruction edit) | Same, edited by Qwen-Image-Edit 2511 | ComfyUI with the Qwen models (31 GB, 24 GB+ VRAM) | [comfyui.md](docs/comfyui.md) |
| Poses | A gesture per expression, same outfit | Qwen-Image-Edit on ComfyUI | [comfyui.md](docs/comfyui.md) |
| Remove background | Transparent sprites | Nothing on the WebUI (rembg runs in AutoExpress) | [standalone.md](docs/standalone.md) |
| Expression LoRAs | Stronger, cleaner expressions | A Civitai key for downloads | [expression-loras.md](docs/expression-loras.md) |
| Animated sprites | Looping WebP/APNG/GIF per expression, a persona idle | Wan 2.2 I2V 14B on ComfyUI (38 GB, 48 GB+ VRAM is comfortable) | [animated-sprites.md](docs/animated-sprites.md) |
| Live2D model kits and puppets | A ready-to-play puppet for the SillyTavern Live2D extension, a Cubism-ready PSD, 28 expressions and motions | ComfyUI with the See-through nodes (10 GB of models, 20-24 GB VRAM at the default 2048 px); Qwen-Image-Edit for blink/mouth art and swappable clothing | [live2d.md](docs/live2d.md) |
| SillyTavern extension | Sprites straight into a character's expressions folder; puppets in the Live2D extension | The standalone app running and reachable from SillyTavern | [sillytavern.md](docs/sillytavern.md) |

## Ways to run it

Pick by where the WebUI is and what the user wants:

| Where | How | When |
| --- | --- | --- |
| Inside A1111 / Forge / reForge / SD.Next | Install the repo URL as an extension: an **AutoExpress** tab that uses ADetailer in-process | The user already lives in that WebUI |
| Inside ComfyUI | The custom nodes (`AutoExpress Expression Prompts`, `Edit Instructions`, `Save Expressions`, `Sprite Sheet` ...) and the workflows in `example_workflows/` | Node graphs; also published to the Comfy Registry |
| Inside InvokeAI | The Expression Prompts node in `invokeai_nodes/` | InvokeAI users |
| Standalone app | `python -m autoexpress` (or a release zip, or Docker), web UI and HTTP API on port 5000, drives any supported WebUI anywhere | Automation, remote GPUs, SillyTavern, every newer feature (animation, Live2D) |

For automation, use the standalone app and its HTTP API, or the [MCP server](docs/mcp.md)
(`python -m autoexpress_mcp`) on top of it. To use AutoExpress for someone rather than change its code, follow
[skills/autoexpress/SKILL.md](skills/autoexpress/SKILL.md).

### Standalone app

```bash
git clone https://github.com/deepratna-awale/AutoExpress.git && cd AutoExpress
./install.sh && ./run.sh                     # Windows: install.bat, run.bat
# or, for development
uv sync --extra standalone && uv run python -m autoexpress
# or
docker run -p 5000:5000 ghcr.io/deepratna-awale/autoexpress
```

Open `http://127.0.0.1:5000`. Configuration is environment variables (all in
[autoexpress/config.py](autoexpress/config.py)); the ones an agent usually sets:

| Variable | Use |
| --- | --- |
| `AUTOEXPRESS_BACKEND_URL` (+ `AUTOEXPRESS_BACKEND`, default `auto`) | Connect to a WebUI at startup |
| `AUTOEXPRESS_BACKEND_USERNAME` / `_PASSWORD` / `_TOKEN` | WebUIs behind a login or a proxy |
| `AUTOEXPRESS_PORT`, `AUTOEXPRESS_HOST` | Listen address (on macOS port 5000 is taken by AirPlay: use another, such as 5055) |
| `AUTOEXPRESS_OUTPUT_DIR` | Where results go (default `./Output`) |
| `AUTOEXPRESS_CORS_ORIGINS` | Pages allowed to call the API from a browser (SillyTavern's address is in by default) |
| `CIVITAI_API_KEY` | Expression LoRA and character LoRA downloads (also found in WebUI Civitai extensions) |
| `AUTOEXPRESS_LLM_URL`, `_MODEL`, `_API_KEY` | An OpenAI compatible LLM that writes idle animations from a character's persona |

## The backend it needs

AutoExpress needs a WebUI to do the image work. It can run anywhere: the same machine, the LAN, or a
rented GPU. Never assume it is local: AutoExpress detects the WebUI from its API, checks over the API
that everything is installed, and only uses the filesystem as a shortcut when the WebUI happens to be
on the same machine.

| WebUI | Address | Required for expressions |
| --- | --- | --- |
| AUTOMATIC1111, Forge, reForge | `:7860` | Started with `--api`, ADetailer |
| SD.Next | `:7860` | ADetailer |
| ComfyUI | `:8188` | Impact Pack + Subpack, `face_yolov8m.pt` in `models/ultralytics/bbox` |
| SwarmUI | `:7801` | Nothing extra |
| InvokeAI 5+ | `:9090` | An SD 1.x / 2.x / SDXL model |

ComfyUI is the only backend for instruction edit, poses, animation and Live2D kits. After
connecting, `GET /backend/capabilities` lists every missing piece with `fix.steps`, `fix.commands`
and `fix.links`: read it and do what it says rather than guessing. `GET /animation` and
`GET /live2d` do the same for those features.

Model downloads onto a ComfyUI install:

```bash
python -m autoexpress_core.instruction_edit check|download <ComfyUI folder>   # Qwen-Image-Edit
python -m autoexpress_core.animation check|download <ComfyUI folder>          # Wan 2.2
# See-through (Live2D): git clone https://github.com/jtydhr88/ComfyUI-See-through into custom_nodes/,
# pip install its requirements, restart ComfyUI; its models download on first use.
```

## Deploying a GPU backend (RunPod)

The heavy models want a big GPU. Don't run them on a laptop or a shared desktop: rent one. Everything
for RunPod is in [docs/runpod.md](docs/runpod.md) and `scripts/runpod/`:

1. **Create a pod**: `RUNPOD_API_KEY=... python scripts/runpod/create_pod.py` picks a 48 GB+ GPU,
   the right image (`runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04`), a 200 GB disk
   and ports 8888 (Jupyter) and 8188 (ComfyUI), and prints the addresses.
2. **Install ComfyUI and every model**: in the pod (Jupyter terminal, SSH or the Jupyter API), run
   `scripts/runpod/setup_comfyui.sh`. It installs the Impact Pack, See-through, Qwen-Image-Edit and
   Wan 2.2 and starts ComfyUI on 8188. `SKIP_QWEN=1`, `SKIP_WAN=1`, `SKIP_SEETHROUGH=1` leave parts
   out; `CHECKPOINT_URL` adds a checkpoint; `COMFYUI_DIR=/workspace/ComfyUI` puts it on a volume.
3. **Connect**: point AutoExpress at `https://<pod id>-8188.proxy.runpod.net`.
4. **Stop the pod when done.** It bills by the hour: `POST https://rest.runpod.io/v1/pods/<id>/stop`
   with `Authorization: Bearer $RUNPOD_API_KEY`, or the console.

Tools that make this easier when you have them:

- **runpodctl** (RunPod's CLI): create, start, stop and remove pods, send and receive files, SSH.
- **The RunPod MCP server**: structured pod, template and volume tools for MCP-capable agents.
- **The RunPod REST API** (`https://rest.runpod.io/v1`): what `create_pod.py` uses; `GET /pods/<id>`
  shows the status and the env (including `JUPYTER_PASSWORD`).
- **Jupyter on the pod** (port 8888): run shell commands and copy files through its REST and kernel
  websocket API when SSH isn't available. `*.proxy.runpod.net` is reachable from most sandboxes.
- **Hugging Face and Civitai** downloads happen on the pod, so sandboxes that block those hosts can
  still set up a pod.

Other hosting works the same way: anything that exposes ComfyUI (or another WebUI) over HTTP(S).

## Driving it over HTTP

The full API is in [docs/standalone.md](docs/standalone.md#http-api). A typical session:

```bash
API=http://127.0.0.1:5000
curl -s -X POST $API/receive_data -H 'Content-Type: application/json' \
     -d '{"text": "https://<pod id>-8188.proxy.runpod.net", "backend": "auto"}'
curl -s $API/backend/capabilities                  # ready? what's missing, with fixes
curl -s $API/get-models                            # checkpoints on the WebUI
# Start a job (base64 image or data URI). "wait": false returns 202 {"job_id"}.
curl -s -X POST $API/generate -H 'Content-Type: application/json' -d @- <<EOF
{"init_images": ["$(base64 -w0 character.png)"], "output_dir": "Mira", "wait": false,
 "method": "instruct", "remove_background": true, "pose": false,
 "expressions": ["joy", "anger", "surprise"]}
EOF
curl -s $API/jobs/<job_id>                         # status, progress, images, notes, error
curl -s -o joy.png $API/image/Mira/joy.png         # results
```

- Jobs run one at a time on a queue; poll `GET /jobs/<id>` (a few seconds apart) rather than holding
  a request open for long runs. `POST /jobs/<id>/cancel` stops one.
- `"animate": true` with an `"animation"` object animates as it goes; `POST /animate` animates stills
  already saved. `POST /character-card` reads a SillyTavern card (name, persona, idle motion).
- Live2D: `POST /live2d/check` scores pictures, `POST /live2d/character-lora` finds a character LoRA,
  `POST /live2d` builds a kit (a job; `job.live2d` has the links, including `puppet_zip`).
- Errors come back as `{"status": "Failed", "message", "error": {"code", ...}}` with an HTTP status
  that matches the code (`backend_unavailable` 503, `backend_not_ready` 409, `invalid_request` 400 ...).

Command line equivalents for the Live2D tools:

```bash
python -m autoexpress_core.live2d check picture.png                     # picture advice
python -m autoexpress_core.live2d kit --url <ComfyUI URL> --name mira picture.png
python -m autoexpress_core.live2d kit --url <ComfyUI URL> --name mira --outfits --adult picture.png   # swappable clothing (drawn adults only)
python -m autoexpress_core.live2d kit --url <ComfyUI URL> --name mira --undress --adult picture.png   # undress chain, picture's pose (fixed-pose puppet)
python -m autoexpress_core.live2d puppet path/to/kit_folder              # puppet from a kit
python -m autoexpress_core.live2d attach path/to/cubism_model_folder     # 28 emotions on a rigged model
python -m autoexpress_core.live2d lora "Character Name" --arch illustrious
```

## SillyTavern

Install `https://github.com/deepratna-awale/AutoExpress` from SillyTavern's **Extensions > Install
extension**. It needs the standalone app running and reachable (`AUTOEXPRESS_CORS_ORIGINS` must allow
SillyTavern's address; the default covers `http://localhost:8000` and `http://127.0.0.1:8000`). It
also lets the [Live2D extension](https://github.com/SillyTavern/Extension-Live2d) play AutoExpress
puppets: put a puppet folder in `data/<user>/assets/live2d` and pick its `.puppet.model.json`.

## Working on the code

| Path | What it is |
| --- | --- |
| `autoexpress_core/` | Shared core: prompt sets (`resources/expressions/*.json`), payloads, the generation loop, WebUI backends (`backends/`), instruction edit, animation, background removal, Live2D (`live2d/`) |
| `autoexpress/` | The standalone Flask app: `views.py` (HTTP API), `jobs.py` (queue), `validation.py`, `config.py` |
| `frontend/` | The Next.js interface (static export served by Flask) |
| `scripts/autoexpress_tab.py` | The A1111-family extension tab |
| `autoexpress_comfy/`, `__init__.py` | ComfyUI nodes |
| `invokeai_nodes/` | InvokeAI node |
| `sillytavern/` | The SillyTavern extension (`manifest.json` at the repo root points to it) |
| `scripts/runpod/` | Pod creation and ComfyUI setup |
| `autoexpress_mcp/` | The MCP server, a client of the standalone app's HTTP API (a new route usually wants a tool) |
| `skills/autoexpress/` | The assistant skill (keep it in step with the tools and routes) |
| `tests/` | pytest, with mocked WebUI APIs (no GPU needed); `tests/live/` needs a real ComfyUI |

Checks before a change is done:

```bash
uv run pytest                                  # the whole suite, about a minute
cd frontend && pnpm build                      # for interface changes (and npx tsc --noEmit)
```

Conventions:

- Keep the 28 expression keys identical across prompt sets. A new WebUI is a backend in
  `autoexpress_core/backends/` registered in `registry.py`, with tests in `tests/test_remote_backends.py`.
  The HTTP side (detection, transport, logins, each WebUI's request steps) belongs in
  [sdmux](https://github.com/deepratna-awale/sdmux); a backend drives an sdmux client (`self.client`).
- A missing dependency on the WebUI is reported as a capability with step-by-step fixes, not as a
  crash or a silent fallback.
- Update the docs and add a line to `CHANGELOG.md` (under Unreleased) when users will notice a change.
- Dependencies live in `pyproject.toml` (`dependencies` for the WebUI extension and nodes, the
  `standalone` extra for the app); run `uv lock` after changing them (CI checks `uv lock --check`).
- Releases: bump the version in `pyproject.toml`, `autoexpress_core/__init__.py`,
  `frontend/package.json` and the root `manifest.json` (a test checks they match), turn the
  Unreleased changelog section into `## X.Y.Z (date)` (it becomes the release notes), merge, then push
  a `vX.Y.Z` tag. The tag builds the platform zips and the web interface zip, publishes the Docker
  image to GHCR, and a version bump on `main` publishes the ComfyUI nodes to the Comfy Registry.
- Characters react to the chat and don't talk: expressions and animations keep the mouth closed or
  only change its shape (smile, frown), and motions stay small and calm.
- Images in the repository, issues and pull requests must be safe for work.
- Branch from `main` with a descriptive name, one focused change per pull request, and fill in the
  pull request template. Commit as the human you are working for; don't add AI attribution lines,
  co-author trailers or "generated with" footers to commits, pull requests or code.

## Safety and cost

- GPU pods bill until stopped: stop them as soon as a test is done, and say so.
- API keys (RunPod, Civitai, Hugging Face, LLM) come from the environment; never commit or log them.
- The standalone app is meant to run on the user's machine or a private network. Don't publish it as a
  public online service.
- Swappable clothing in Live2D kits draws nudity, so it only runs for drawn adult characters with an
  explicit adult confirmation (`outfit_layers` or `undress_chain`, + `adult_confirmed`); photos and child-coded names or
  descriptions are refused in `autoexpress_core/live2d/outfits.py`. Keep those checks, and use SFW
  characters for tests and public examples. Images that show inner wear or less are named
  `INTERNAL_` and never go in previews or contact sheets.
