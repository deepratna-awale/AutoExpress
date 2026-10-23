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
- Model, sampler and scheduler pickers with search. Values read from an image stay selectable and are outlined red when the connected WebUI doesn't have them.
- LoRA picker with a strength for each LoRA. LoRAs already written in the prompt get the strength from the list instead of being added twice.
- Prompt Style dropdown for model-family expression prompts when the backend offers `GET /expression-families`; the Anime/Realistic switch otherwise.
- Drop an image to fill in every parameter from its generation metadata; the info button shows the raw metadata.
- Generate and Interrupt, with the gallery filling in while expressions are generated. Arrow keys move between expressions.
- Light/dark mode and a theme editor with presets, saved in the browser.

## Backend routes used

| Route | Purpose |
| --- | --- |
| `GET /backends` | Optional. `{selected, url, backends: [{id, name, default_url}]}` |
| `POST /receive_data` | `{text: url, backend?: id}` sets the WebUI |
| `GET /get-models`, `/get-samplers`, `/get-schedulers`, `/get-loras` | String lists |
| `POST /upload` | Image file; returns parsed parameters and raw metadata |
| `POST /generate` | Generates the expression set into `Output/<output_dir>` |
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
