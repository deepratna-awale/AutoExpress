"""The SillyTavern extension: its manifest, and the CORS headers that let it call the standalone app."""

import json
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_manifest_points_at_the_extension_files():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["display_name"] == "AutoExpress"
    assert (ROOT / manifest["js"]).is_file()
    assert (ROOT / manifest["css"]).is_file()


def test_manifest_version_matches_the_package():
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    version = re.search(r'^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    assert manifest["version"] == version


def test_extension_labels_match_the_expressions():
    from autoexpress_core import get_expressions

    script = (ROOT / "sillytavern" / "index.js").read_text(encoding="utf-8")
    block = re.search(r"const EXPRESSIONS = \[(.*?)\];", script, re.S).group(1)
    labels = re.findall(r"'([a-z]+)'", block)
    assert labels == list(get_expressions("danbooru", None))


pytest.importorskip("flask")
pytest.importorskip("sd_parsers")

from autoexpress import views  # noqa: E402

ST = "http://localhost:8000"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(views.settings, "cors_origins", ("http://localhost:8000", "http://127.0.0.1:8000"))
    return views.autoexpress.test_client()


def test_allowed_origin_gets_cors_headers(client):
    response = client.get("/health", headers={"Origin": ST})
    assert response.headers["Access-Control-Allow-Origin"] == ST
    assert "Origin" in response.headers.get("Vary", "")


def test_preflight_allows_json_posts(client):
    response = client.options(
        "/generate",
        headers={"Origin": ST, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"},
    )
    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == ST
    assert "POST" in response.headers["Access-Control-Allow-Methods"]
    assert "Content-Type" in response.headers["Access-Control-Allow-Headers"]


def test_private_network_preflight(client):
    response = client.options(
        "/health",
        headers={"Origin": ST, "Access-Control-Request-Method": "GET", "Access-Control-Request-Private-Network": "true"},
    )
    assert response.headers["Access-Control-Allow-Private-Network"] == "true"


def test_other_origins_get_no_cors_headers(client):
    response = client.get("/health", headers={"Origin": "https://example.com"})
    assert "Access-Control-Allow-Origin" not in response.headers


def test_errors_carry_cors_headers_too(client):
    response = client.get("/jobs/nope", headers={"Origin": ST})
    assert response.status_code == 404
    assert response.headers["Access-Control-Allow-Origin"] == ST


def test_wildcard_allows_any_page(client, monkeypatch):
    monkeypatch.setattr(views.settings, "cors_origins", ("*",))
    response = client.get("/health", headers={"Origin": "https://example.com"})
    assert response.headers["Access-Control-Allow-Origin"] == "*"


def test_origins_from_environment(monkeypatch):
    from autoexpress.config import DEFAULT_CORS_ORIGINS, Settings

    monkeypatch.delenv("AUTOEXPRESS_CORS_ORIGINS", raising=False)
    assert Settings.from_env().cors_origins == DEFAULT_CORS_ORIGINS
    monkeypatch.setenv("AUTOEXPRESS_CORS_ORIGINS", "http://a:8000/, http://b:9000")
    assert Settings.from_env().cors_origins == ("http://a:8000", "http://b:9000")
    monkeypatch.setenv("AUTOEXPRESS_CORS_ORIGINS", "")
    assert Settings.from_env().cors_origins == ()
