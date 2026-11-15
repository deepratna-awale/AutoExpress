# MCP server

Emotica ships a [Model Context Protocol](https://modelcontextprotocol.io) server, so any MCP-capable assistant or
agent can make expression sprites for you: desktop chat apps, coding assistants, agent frameworks and local LLM front
ends. It wraps the [standalone app's HTTP API](standalone.md#http-api), so the app and the WebUI behind it can run
anywhere.

```
assistant ──MCP (stdio or HTTP)──▶ python -m emotica_mcp ──HTTP──▶ Emotica app ──▶ WebUI
```

For assistants without MCP, the same workflow is written up as a plain guide in
[skills/emotica/SKILL.md](../skills/emotica/SKILL.md). Many assistants load it as a skill; any of them can read
it as instructions.

## Setup

1. Start the [standalone app](standalone.md) (`./run.sh`, `python -m emotica` or Docker) and connect it to your
   WebUI.
2. Install the server's dependencies (Python 3.10+). From the Emotica folder:

   ```bash
   uv sync --extra mcp          # or: pip install -e ".[mcp]"
   ```

3. Add it to your client (below). The server finds the app at `http://127.0.0.1:5000` unless you set
   `EMOTICA_URL`.

Check it with the MCP Inspector: `npx @modelcontextprotocol/inspector uv run --directory /path/to/Emotica python -m emotica_mcp`.

## Clients

Replace `/path/to/Emotica` with your clone, and the app URL if it isn't the default. Every client that starts
local servers takes the same command:

```
uv run --directory /path/to/Emotica --extra mcp python -m emotica_mcp
```

<details>
<summary>The common <code>mcpServers</code> JSON (Claude Desktop, Cursor, Windsurf, Cline, LM Studio, Gemini CLI and others)</summary>

In the client's MCP config file (`~/.cursor/mcp.json`, `~/.gemini/settings.json`, LM Studio's `mcp.json`, Claude
Desktop's `claude_desktop_config.json` ...):

```json
{
  "mcpServers": {
    "emotica": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/Emotica", "--extra", "mcp", "python", "-m", "emotica_mcp"],
      "env": { "EMOTICA_URL": "http://127.0.0.1:5000" }
    }
  }
}
```

</details>

<details>
<summary>VS Code (<code>.vscode/mcp.json</code>)</summary>

```json
{
  "servers": {
    "emotica": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/Emotica", "--extra", "mcp", "python", "-m", "emotica_mcp"],
      "env": { "EMOTICA_URL": "http://127.0.0.1:5000" }
    }
  }
}
```

</details>

<details>
<summary>Codex CLI (<code>~/.codex/config.toml</code>)</summary>

```toml
[mcp_servers.emotica]
command = "uv"
args = ["run", "--directory", "/path/to/Emotica", "--extra", "mcp", "python", "-m", "emotica_mcp"]
env = { EMOTICA_URL = "http://127.0.0.1:5000" }
```

</details>

<details>
<summary>Command line clients that add servers with a command (Claude Code, Gemini CLI, Codex)</summary>

```bash
claude mcp add emotica -- uv run --directory /path/to/Emotica --extra mcp python -m emotica_mcp
gemini mcp add emotica uv run --directory /path/to/Emotica --extra mcp python -m emotica_mcp
codex mcp add emotica -- uv run --directory /path/to/Emotica --extra mcp python -m emotica_mcp
```

</details>

<details>
<summary>Agent frameworks (OpenAI Agents SDK, LangChain, others) and remote clients: streamable HTTP</summary>

Run the server over HTTP:

```bash
uv run --extra mcp python -m emotica_mcp --transport http --port 5056
# endpoint: http://127.0.0.1:5056/mcp
```

Then point the framework's streamable HTTP MCP client at the endpoint. With the OpenAI Agents SDK:

```python
from agents import Agent, Runner
from agents.mcp import MCPServerStreamableHttp

async with MCPServerStreamableHttp(params={"url": "http://127.0.0.1:5056/mcp"}) as emotica:
    agent = Agent(name="Sprites", instructions="Make expression sprites with Emotica.", mcp_servers=[emotica])
    print((await Runner.run(agent, "Make Mira's sprites from /pictures/mira.png")).final_output)
```

To reach it from another machine, listen on the network with a token, and send `Authorization: Bearer <token>`:

```bash
EMOTICA_MCP_TOKEN=$(openssl rand -hex 24) uv run --extra mcp python -m emotica_mcp --transport http --host 0.0.0.0
```

Hosted assistants that only connect to public HTTPS servers need a tunnel or reverse proxy with TLS in front of it.
Keep the token on: the server can start GPU jobs.

</details>

## Tools

| Tool | What it does |
| --- | --- |
| `emotica_status` | The app, the selected WebUI and whether it's ready. Call it first |
| `connect_webui` | Point the app at a WebUI (`auto` detects which), with an optional login or token |
| `check_capabilities` | What the WebUI is missing for expressions, animation or Live2D, with fix steps, commands and links |
| `list_webui_options` | Checkpoints, samplers, schedulers, LoRAs |
| `list_prompt_styles`, `set_prompt_style` | Expression prompt styles (model families) |
| `get_expression_prompts` | The 28 expression names and the default wording of each |
| `generate_expressions` | Start a set (all 28 or a subset), with method, checkpoint, intensity, background removal, poses, animation, per-expression overrides |
| `retry_expression` | Redo one expression with a new seed and optionally its own prompt and settings |
| `get_expression_overrides`, `set_expression_overrides` | A character's saved per-expression prompts and settings |
| `get_job`, `wait_for_job`, `list_jobs`, `cancel_job` | Follow jobs (`wait_for_job` reports progress) or cancel them |
| `list_results`, `get_result_image`, `save_results` | See the files, look at a picture, download everything |
| `animate_expressions`, `read_character_card` | Animate saved stills; read a character card and its idle motion |
| `live2d_check_pictures`, `live2d_find_character_lora`, `build_live2d_kit` | Live2D model kits and puppets |
| `configure_options` | Expression LoRAs, the Civitai key, the idle-motion LLM, realistic mode |

The server also has a resource, `emotica://guide` (the [skill guide](../skills/emotica/SKILL.md)), and a
prompt, `make_expression_sprites`.

**Images** go in as a file path on the server's machine, an http(s) URL, a data URI or base64. **Results** come back as
pictures (`get_result_image`, downscaled for the model to look at) or as files (`save_results`, full size).

## Settings

| Variable / flag | Default | |
| --- | --- | --- |
| `EMOTICA_URL`, `--app-url` | `http://127.0.0.1:5000` | The Emotica app |
| `--transport` (`EMOTICA_MCP_TRANSPORT`) | `stdio` | `stdio` or `http` (streamable HTTP) |
| `--host`, `--port`, `--path` | `127.0.0.1`, `5056`, `/mcp` | HTTP listen address |
| `EMOTICA_MCP_TOKEN`, `--token` | none | HTTP: require `Authorization: Bearer <token>`; needed for a non-loopback `--host` |
| `--allowed-host` | loopback names | HTTP: extra `Host` headers to accept (DNS rebinding protection) |
| `EMOTICA_MCP_LOCAL_FILES`, `--allow-local-files` / `--no-local-files` | on for stdio, off for HTTP | Read image paths and save results on the server's machine |
| `EMOTICA_MCP_RESULTS_DIR`, `--results-dir` | `./emotica-results` | Where `save_results` puts files |
| `EMOTICA_MCP_TIMEOUT` | `60` | Seconds to wait for the app on each call |

Over HTTP, local file access is off by default so a remote client can't read or write files on the server's machine.

[← Back to the docs](README.md)
