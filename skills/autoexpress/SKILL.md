---
name: autoexpress
description: Make a character's 28 expression sprites (and optional poses, animations, transparent backgrounds or a Live2D puppet) from one picture with AutoExpress. Use when someone wants expression sprites, SillyTavern character expressions, VN sprites, animated sprites or a Live2D model from a character image.
---

# Using AutoExpress

This guide teaches an AI assistant or agent to use AutoExpress for someone. It works with any assistant: use the
**MCP tools** when the AutoExpress MCP server is connected, or the **HTTP API** when you can run shell commands or make
web requests. Each step below gives both.

## What it does

From one picture of a character, AutoExpress makes 28 expression sprites, one per emotion SillyTavern's classifier
detects:

admiration, amusement, anger, annoyance, approval, caring, confusion, curiosity, desire, disappointment, disapproval,
disgust, embarrassment, excitement, fear, gratitude, grief, joy, love, nervousness, neutral, optimism, pride,
realization, relief, remorse, sadness, surprise.

Optional extras: a pose per expression, a looping animation of each, transparent backgrounds, and a Live2D model kit
with a ready-to-play puppet.

AutoExpress doesn't run a model itself. It drives a Stable Diffusion **WebUI** (ComfyUI, AUTOMATIC1111, Forge, reForge,
SD.Next, SwarmUI or InvokeAI) that can run anywhere: the same computer, the local network, or a rented GPU. **Never
assume the WebUI is local.**

## The pieces

```
your assistant ──MCP──▶ AutoExpress MCP server ──HTTP──▶ AutoExpress app ──HTTP──▶ WebUI (GPU)
your assistant ─────────────────HTTP───────────────────▶ AutoExpress app
```

1. **The AutoExpress app** (`python -m autoexpress`, `./run.sh`, a release zip or
   `docker run -p 5000:5000 ghcr.io/deepratna-awale/autoexpress`). Web UI and HTTP API, port 5000 by default. On macOS
   port 5000 belongs to AirPlay, so use another one: `AUTOEXPRESS_PORT=5055`.
2. **A WebUI** with what AutoExpress needs (the app checks it and tells you exactly what's missing).
3. **Optionally the MCP server** (`python -m autoexpress_mcp`), which turns the app's API into tools. Setup for each
   client is in [docs/mcp.md](../../docs/mcp.md).

Before anything else, find out from the person where the app runs and where their WebUI runs. If the app isn't
running, help them start it; don't start GPU work on a laptop that isn't meant for it.

## Workflow

| Step | MCP tool | HTTP |
| --- | --- | --- |
| 1. Is the app up, which WebUI is connected | `autoexpress_status` | `GET /health`, `GET /backends`, `GET /backend/status` |
| 2. Connect the WebUI (if needed) | `connect_webui(url)` | `POST /receive_data {"text": url, "backend": "auto"}` |
| 3. Check what's missing | `check_capabilities` | `GET /backend/capabilities` (+ `/animation`, `/live2d`) |
| 4. Pick a checkpoint and prompt style | `list_webui_options`, `list_prompt_styles` | `GET /get-models`, `GET /expression-families` |
| 5. Start the job | `generate_expressions(image, character)` | `POST /generate` with `"wait": false` |
| 6. Follow it | `wait_for_job(job_id)` | `GET /jobs/<id>` every few seconds |
| 7. Look at the results | `list_results`, `get_result_image` | `GET /images/<character>`, `GET /image/<character>/<file>` |
| 8. Redo bad ones | `retry_expression` | `POST /generate` with `"expressions": [name], "seed": -1` |
| 9. Hand them over | `save_results` | download the files |

Step 3 matters most. Every missing item comes with `fix.steps`, `fix.commands` and `fix.links`. Follow them, or
walk the person through them, instead of guessing. Don't start a job until `ready` is true for the feature.

### HTTP example

```bash
API=http://127.0.0.1:5000
curl -s -X POST $API/receive_data -H 'Content-Type: application/json' -d '{"text": "http://127.0.0.1:8188"}'
curl -s $API/backend/capabilities
curl -s -X POST $API/generate -H 'Content-Type: application/json' -d @- <<EOF
{"init_images": ["$(base64 -w0 character.png)"], "output_dir": "Mira", "wait": false}
EOF
curl -s $API/jobs/<job_id>
curl -s -o joy.png $API/image/Mira/joy.png
```

Errors come back as `{"status": "Failed", "message", "error": {"code", "fields", ...}}` with a matching HTTP status
(`invalid_request` 400, `backend_auth` 401, `backend_not_ready` 409, `backend_unavailable` 503, `backend_timeout` 504,
`backend_rejected` / `backend_error` 502). The MCP tools turn these into one readable message with the fix steps.

## Choosing settings

- **Method.** `inpaint` repaints only the face with face inpainting and works on every WebUI. `instruct` edits the
  whole picture with Qwen-Image-Edit, which needs ComfyUI with the Qwen models (about 31 GB, 24 GB+ VRAM). Leave it
  unset and AutoExpress picks the prompt style's default (photos and realistic renders get `instruct` where available).
- **Checkpoint.** For face inpainting, use a checkpoint that matches the art style of the picture (anime, Pony,
  Illustrious, realistic). `list_webui_options("models")` lists them; `set_prompt_style("auto")` picks the prompt
  wording from the checkpoint's name.
- **Intensity** (0 to 1) makes expressions stronger or subtler.
- **`remove_background`** gives transparent sprites. It runs inside the app (rembg), not on the WebUI.
- **`pose`** adds a small gesture per expression with the outfit kept. ComfyUI with Qwen-Image-Edit only.
- **`animate`** makes looping WebP/APNG/GIF clips per expression with Wan 2.2 on ComfyUI (about 38 GB of models,
  48 GB+ VRAM is comfortable). Or animate stills already made with `animate_expressions` / `POST /animate`.
- **A subset.** `expressions: ["joy", "anger"]` makes only those: good for a quick test before a full set.

A full set takes from a few minutes to much longer depending on the GPU, the method and the extras. Start with two or
three expressions to check the look, then run the rest.

## Fixing single expressions

Look at the results (with `get_result_image`, or by opening the files) before handing them over. If one is off:

- Retry it with a new seed: `retry_expression(image, character, "joy")`.
- Give it its own wording: `get_expression_prompts(["joy"])` shows the default text; pass a changed `prompt`.
- Give it its own settings, e.g. `{"ad_denoising_strength": 0.5}` when the face changed too much, higher when it
  barely changed.
- `remember=True` (HTTP: `"save_overrides": true`) keeps the prompt and settings for that character's later runs.
  `get_expression_overrides` / `set_expression_overrides` read and replace them.

## Live2D

1. `live2d_check_pictures` scores pictures and says which works best. The best picture is one character facing the
   viewer, waist up or full body, at least 1280 px, plain background, nothing overlapping, mouth closed.
2. `check_capabilities("live2d")` needs ComfyUI with the See-through nodes (about 10 GB of models, 20-24 GB VRAM at
   2048 px).
3. `live2d_find_character_lora(name)` finds the character's LoRA on Civitai for cleaner art (optional).
4. `build_live2d_kit(images, name)` returns a job. When it completes, `job.live2d` lists the puppet zip, a Cubism-ready
   PSD and previews. `save_results("live2d/<name>")` downloads them. The puppet plays in SillyTavern's Live2D
   extension.

## Getting a GPU

The heavy features want a big GPU. If the person has none, they can rent one; the repository has a RunPod guide
([docs/runpod.md](../../docs/runpod.md)) with a script that creates a pod and one that installs ComfyUI with every
model. GPU pods bill by the hour: **remind the person to stop the pod when they're done**, and stop it yourself if you
started it.

## Delivering to SillyTavern

The sprites are named after the 28 emotions, which is what SillyTavern's Character Expressions extension expects. The
person can upload the folder there, or install the AutoExpress SillyTavern extension (from the repository URL in
**Extensions > Install extension**), which sends sprites straight to a character. See
[docs/sillytavern.md](../../docs/sillytavern.md).

## Rules

- Ask the person for the picture and the character's name; use the name as the output folder.
- Characters react to the chat; they don't talk. Keep mouths closed or only change their shape (smile, frown), and keep
  motions small and calm. Don't add "speaking" or "talking" to prompts.
- Use safe-for-work characters in examples, tests and anything public.
- API keys (Civitai, LLM, WebUI logins) come from the person. Never print, log or commit them; the app never echoes
  them back.
- The app is meant for the person's own computer or private network. Don't expose it, or the MCP server's HTTP mode,
  to the internet without a token.
- Don't change the app's code to get around a capability check. A missing piece is fixed on the WebUI.

## More

- [docs/standalone.md](../../docs/standalone.md): the app, its settings and every HTTP route
- [docs/mcp.md](../../docs/mcp.md): the MCP server and client setup
- [docs/comfyui.md](../../docs/comfyui.md), [docs/animated-sprites.md](../../docs/animated-sprites.md),
  [docs/live2d.md](../../docs/live2d.md)
- [AGENTS.md](../../AGENTS.md): for agents changing the AutoExpress code itself
