"""The MCP server, driving the real Flask app (with a fake WebUI) through its HTTP API."""

import asyncio
import base64
import io
import json
import urllib.parse

import pytest
from PIL import Image

pytest.importorskip("mcp")
pytest.importorskip("flask")
pytest.importorskip("sd_parsers")

from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from test_app import FakeWebUI, client  # noqa: E402,F401

from autoexpress_mcp.__main__ import bearer_guard, parse_args  # noqa: E402
from autoexpress_mcp.client import AppError, AutoExpressClient, describe_error  # noqa: E402
from autoexpress_mcp.server import GUIDE_PATH, Settings, build_server  # noqa: E402

APP = "http://autoexpress.test"


class FlaskResponse:
    def __init__(self, response):
        self.status_code = response.status_code
        self.headers = response.headers
        self.content = response.get_data()
        self.text = self.content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)

    def iter_content(self, size):
        for start in range(0, len(self.content), size):
            yield self.content[start : start + size]


class FlaskSession:
    """A requests.Session stand-in that sends requests to the Flask test client."""

    def __init__(self, flask_client):
        self.client = flask_client
        self.calls = []

    def request(self, method, url, json=None, params=None, timeout=None, stream=False):
        parsed = urllib.parse.urlsplit(url)
        path = urllib.parse.unquote(parsed.path) + (f"?{urllib.parse.urlencode(params)}" if params else "")
        self.calls.append((method, path, json))
        return FlaskResponse(self.client.open(path, method=method, json=json))

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)


def png_b64(color=(200, 150, 120), size=(64, 96)):
    out = io.BytesIO()
    Image.new("RGB", size, color).save(out, "PNG")
    return base64.b64encode(out.getvalue()).decode()


@pytest.fixture
def mcp(client, tmp_path):  # noqa: F811
    session = FlaskSession(client)
    app = AutoExpressClient(APP, session=session)
    server = build_server(Settings(app_url=APP, results_dir=str(tmp_path / "results")), client=app)
    server.session = session
    return server


def call(server, name, arguments=None):
    result = asyncio.run(server.call_tool(name, arguments or {}))
    if result.structured_content is not None and "result" in result.structured_content and len(result.structured_content) == 1:
        return result.structured_content["result"]
    if result.structured_content is not None:
        return result.structured_content
    if len(result.content) == 1 and result.content[0].type == "text":
        try:
            return json.loads(result.content[0].text)
        except ValueError:
            pass
    return result.content


def test_lists_every_tool_with_a_description(mcp):
    tools = asyncio.run(mcp.list_tools())
    names = {tool.name for tool in tools}
    assert {"autoexpress_status", "connect_webui", "check_capabilities", "generate_expressions", "retry_expression", "wait_for_job", "get_result_image", "save_results", "build_live2d_kit"} <= names
    assert all(tool.description for tool in tools)


def test_status_reports_app_and_webui(mcp):
    status = call(mcp, "autoexpress_status")
    assert status["app"]["status"] == "ok"
    assert status["webui"]["selected"] == "fake"
    assert "comfyui" in status["webui_choices"]


def test_generate_wait_and_fetch_results(mcp, tmp_path):
    job = call(mcp, "generate_expressions", {"image": png_b64(), "character": "Mira", "expressions": ["joy", "anger"], "checkpoint": "model-a"})
    assert job["status"] == "queued"
    finished = call(mcp, "wait_for_job", {"job_id": job["job_id"], "timeout_seconds": 30})
    assert finished["status"] == "completed"
    assert {image["expression"] for image in finished["images"]} == {"joy", "anger"}

    files = call(mcp, "list_results", {"character": "Mira"})["files"]
    assert {f["name"] for f in files} >= {"joy.png", "anger.png"}

    picture = call(mcp, "get_result_image", {"character": "Mira", "file": "joy.png", "max_size": 64})
    assert picture[0].type == "image" and picture[0].mime_type == "image/png"

    saved = call(mcp, "save_results", {"character": "Mira"})
    assert (tmp_path / "results" / "Mira" / "joy.png").is_file()
    assert len(saved["saved"]) == len(files)


def test_generate_reads_a_local_image_path(mcp, tmp_path):
    picture = tmp_path / "mira.png"
    Image.new("RGB", (64, 96), (10, 20, 30)).save(picture)
    job = call(mcp, "generate_expressions", {"image": str(picture), "character": "Mira", "expressions": ["joy"], "settings": {"ad_steps": 12}})
    method, path, body = mcp.session.calls[-1]
    assert (method, path) == ("POST", "/generate")
    assert body["init_images"][0].startswith("data:image/png;base64,")
    assert body["ad_steps"] == 12 and body["wait"] is False
    call(mcp, "wait_for_job", {"job_id": job["job_id"], "timeout_seconds": 30})


def test_retry_sends_one_expression_with_a_new_seed_and_its_override(mcp):
    job = call(mcp, "retry_expression", {"image": png_b64(), "character": "Mira", "expression": "Joy", "prompt": "big grin", "remember": True})
    _, _, body = mcp.session.calls[-1]
    assert body["expressions"] == ["joy"] and body["seed"] == -1
    assert body["overrides"] == {"joy": {"prompt": "big grin"}} and body["save_overrides"] is True
    call(mcp, "wait_for_job", {"job_id": job["job_id"], "timeout_seconds": 30})
    saved = call(mcp, "get_expression_overrides", {"character": "Mira"})
    assert saved["expressions"]["joy"]["prompt"] == "big grin"


def test_app_errors_become_readable_tool_errors(mcp):
    with pytest.raises(ToolError, match="seed"):
        call(mcp, "generate_expressions", {"image": png_b64(), "character": "Mira", "seed": -5})
    with pytest.raises(ToolError, match="No such image file"):
        call(mcp, "generate_expressions", {"image": "/nowhere/mira.png", "character": "Mira"})


def test_webui_not_ready_shows_the_message(mcp):
    FakeWebUI.ready = False
    with pytest.raises(ToolError, match="ADetailer"):
        call(mcp, "generate_expressions", {"image": png_b64(), "character": "Mira"})


def test_expression_prompts_list_all_28(mcp):
    prompts = call(mcp, "get_expression_prompts", {})
    assert len(prompts["prompts"]) == 28 and prompts["kind"] == "tags"


def test_local_files_can_be_turned_off(client, tmp_path):  # noqa: F811
    app = AutoExpressClient(APP, allow_local_files=False, session=FlaskSession(client))
    server = build_server(Settings(app_url=APP, allow_local_files=False), client=app)
    with pytest.raises(ToolError, match="doesn't read local files"):
        call(server, "generate_expressions", {"image": str(tmp_path / "x.png"), "character": "Mira"})
    with pytest.raises(ToolError, match="local file access"):
        call(server, "save_results", {"character": "Mira"})


def test_unreachable_app_says_how_to_start_it():
    app = AutoExpressClient("http://127.0.0.1:9", timeout=1)
    with pytest.raises(AppError, match="python -m autoexpress"):
        app.get("/health")


def test_describe_error_keeps_fix_steps():
    body = {"status": "Failed", "message": "ComfyUI is missing the Impact Pack.", "error": {"code": "backend_not_ready", "fix": {"steps": ["Install it"], "commands": ["git clone x"], "links": [{"label": "Pack", "url": "https://example.com"}]}}}
    text = describe_error(409, body, "")
    lines = text.splitlines()
    assert "backend_not_ready" in lines[0] and "- Install it" in lines and "  $ git clone x" in lines and "  https://example.com" in lines


def test_guide_resource_is_the_skill(mcp):
    contents = asyncio.run(mcp.read_resource("autoexpress://guide"))
    text = contents[0].content if hasattr(contents[0], "content") else contents[0].text
    assert text == GUIDE_PATH.read_text(encoding="utf-8")
    assert text.startswith("---\nname: autoexpress\n")


def test_skill_mentions_every_tool(mcp):
    guide = GUIDE_PATH.read_text(encoding="utf-8")
    docs = (GUIDE_PATH.parents[2] / "docs" / "mcp.md").read_text(encoding="utf-8")
    for tool in asyncio.run(mcp.list_tools()):
        assert f"`{tool.name}" in docs, tool.name
    for tool in ("autoexpress_status", "connect_webui", "check_capabilities", "generate_expressions", "wait_for_job", "retry_expression", "save_results"):
        assert tool in guide


def test_http_defaults_turn_local_files_off():
    assert parse_args([]).transport == "stdio"
    assert parse_args(["--transport", "http"]).local_files is None
    assert parse_args(["--no-local-files"]).local_files is False


def test_bearer_guard_rejects_a_wrong_token():
    seen = []

    async def inner(scope, receive, send):
        seen.append(scope["path"])

    async def run(headers):
        sent = []

        async def send(message):
            sent.append(message)

        await bearer_guard(inner, "s3cret")({"type": "http", "path": "/mcp", "headers": headers}, None, send)
        return sent

    rejected = asyncio.run(run([(b"authorization", b"Bearer nope")]))
    assert rejected[0]["status"] == 401 and not seen
    asyncio.run(run([(b"authorization", b"Bearer s3cret")]))
    assert seen == ["/mcp"]
