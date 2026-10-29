# Contributing to AutoExpress

Thanks for your interest in improving AutoExpress. Bug reports, new prompt styles, WebUI support and documentation fixes are all welcome.

## Before you start

- Search the [existing issues](https://github.com/deepratna-awale/AutoExpress/issues) first. For larger changes, open an issue to discuss the idea before you write the code.
- Read the [Code of Conduct](CODE_OF_CONDUCT.md).
- Don't report security problems in public issues. See [SECURITY.md](SECURITY.md) instead.

## Project layout

| Path | What it is |
| --- | --- |
| `autoexpress_core/` | Shared core: expression prompt sets, expression LoRAs, intensity, payloads, the generation loop and the WebUI backends |
| `scripts/autoexpress_tab.py` | The AUTOMATIC1111 / Forge / reForge / SD.Next extension tab |
| `autoexpress_comfy/`, `__init__.py` | The ComfyUI nodes |
| `invokeai_nodes/` | The InvokeAI node |
| `autoexpress/` | The standalone Flask app and its HTTP API |
| `frontend/` | The Next.js interface for the standalone app |
| `example_workflows/` | Ready-made ComfyUI workflows |
| `docs/` | User documentation |
| `tests/` | The pytest suite |

## Development setup

You need Python 3.11 or newer. For the web interface you also need Node.js 20.9 or newer and pnpm.

```bash
git clone https://github.com/deepratna-awale/AutoExpress.git
cd AutoExpress
uv sync --extra standalone         # .venv with the app's dependencies and the dev tools (pytest)
```

Dependencies live in `pyproject.toml`: `dependencies` for the WebUI extension and nodes, the `standalone` extra for the app, and the `dev` group for tests. After changing them, run `uv lock` and commit `uv.lock`; the release zips, the Docker image and `install` use the versions pinned there. Without uv:

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[standalone]" pytest
```

Run the standalone app with `python -m autoexpress`, then open http://127.0.0.1:5000. To work on the interface, see [frontend/README.md](frontend/README.md).

## Tests

```bash
uv run pytest                      # or python -m pytest in an activated .venv
```

The suite doesn't need a GPU or a running WebUI, because the backends are tested against mocked APIs. `tests/live/` holds optional smoke tests that need a real ComfyUI. For frontend changes, also run `pnpm lint` and `pnpm build` in `frontend/`.

## Common changes

- **Adding a prompt style:** add a JSON file to `autoexpress_core/resources/expressions/`. Copy an existing one and keep the same 28 expression keys.
- **Adding an expression LoRA:** add an entry to `autoexpress_core/resources/expression_loras.json` with its Civitai version id and SHA-256.
- **Supporting a new WebUI:** add a backend in `autoexpress_core/backends/` and register it in `registry.py`. Add tests to `tests/test_remote_backends.py`.

## Pull requests

1. Fork the repository, then create a branch from `main` with a descriptive name, such as `fix-comfyui-seed`.
2. Keep each pull request focused on one change. Add or update tests for behaviour changes.
3. Update the docs and add a line to [CHANGELOG.md](CHANGELOG.md) when users will notice the change.
4. Make sure `python -m pytest` passes, then open the pull request and fill in the template.

Images in issues, pull requests and docs must be safe for work.

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
