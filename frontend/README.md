# AutoExpress web interface

The AutoExpress interface, built with Next.js, TypeScript, Tailwind CSS and shadcn/ui. It talks to the AutoExpress Flask backend (`autoexpress/views.py`); all image generation still happens in Python.

## Build for use

```bash
cd frontend
pnpm install
pnpm build
```

`pnpm build` writes a static export to `frontend/out/`. Start AutoExpress as usual (`run.sh` / `run.bat`) and open http://127.0.0.1:5000. Flask serves the export when it exists and falls back to the original interface otherwise. The original interface is always at `/classic`.

## Develop

Run the Flask backend on port 5000, then:

```bash
cd frontend
pnpm dev
```

Open http://localhost:3000. The dev server proxies the backend routes to Flask; set `AUTOEXPRESS_BACKEND_URL` to point it somewhere else, e.g. `AUTOEXPRESS_BACKEND_URL=http://127.0.0.1:5001 pnpm dev`.

## Features

- WebUI connection with a backend selector (A1111, Forge, SD.Next, ComfyUI, SwarmUI, InvokeAI) when the backend offers `GET /backends`; plain A1111 URL otherwise.
- Model, sampler and scheduler pickers with search. When a value read from an image isn't on the connected WebUI, it is swapped for the closest installed checkpoint or the usual sampler/scheduler for that model family (SD 1.5, SDXL, Pony, Illustrious, Flux, SD 3), with a note under the field. "Use … defaults" applies the family's usual sampler, scheduler, steps, CFG and clip skip (`lib/model-defaults.ts`).
- LoRA picker with a strength for each LoRA. LoRAs already written in the prompt get the strength from the list instead of being added twice.
- Prompt Style dropdown for model-family expression prompts when the backend offers `GET /expression-families`; the Anime/Realistic switch otherwise.
- Image drop zone: drag and drop, click or keyboard to browse, or paste from the clipboard. PNG/JPG/GIF up to 25 MB, with inline errors, a preview with Replace and Remove, and the raw generation data a click away. Every parameter is filled from the image's metadata.
- Generate and Interrupt. With the job API (`POST /generate` with `wait: false`, `GET /jobs/<id>`), a progress bar shows the current expression, a reload picks the running job back up, and Interrupt cancels that job. Otherwise the gallery is refreshed while the blocking request runs. Arrow keys move between expressions.
- Light/dark mode and a theme editor with presets, saved in the browser.

## Backend routes used

| Route | Purpose |
| --- | --- |
| `GET /backends` | Optional. `{selected, url, backends: [{id, name, default_url}]}` |
| `POST /receive_data` | `{text: url, backend?: id}` sets the WebUI |
| `GET /get-models`, `/get-samplers`, `/get-schedulers`, `/get-loras` | String lists |
| `POST /upload` | Image file; returns parsed parameters and raw metadata |
| `POST /generate` | Generates the expression set into `Output/<output_dir>`; sent with `wait: false` |
| `GET /jobs`, `GET /jobs/<id>`, `POST /jobs/<id>/cancel` | Optional. Job progress and cancel |
| `POST /interrupt` | Stops after the current expression |
| `GET /images/<dir>`, `GET /image/<dir>/<file>` | Lists and serves generated images |
| `GET /expression-families`, `POST /expression-family` | Optional. Prompt Style |
| `POST /toggle` | Anime/Realistic switch when Prompt Style isn't available |

## Layout

- `app/` – the single page and global styles
- `components/` – panels (`parameters-panel`, `drop-zone-panel`, `drop-zone-inputs-panel`, `image-carousel`), sidebar and theme editor; `components/ui/` holds shadcn/ui primitives
- `lib/api.ts` – typed client for the Flask routes
- `lib/store.tsx` – app state and actions shared by the panels
- `lib/theme.tsx` – live theme presets and persistence
