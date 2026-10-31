"""The prebuilt web interface download for source installs without Node.js (autoexpress/frontend.py)."""

import io
import zipfile

import pytest

pytest.importorskip("flask")

from autoexpress import frontend  # noqa: E402


def zipped(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


@pytest.fixture
def out(tmp_path, monkeypatch):
    target = tmp_path / "frontend" / "out"
    monkeypatch.setattr(frontend, "FRONTEND_DIR", target)
    monkeypatch.delenv("AUTOEXPRESS_DOWNLOAD_FRONTEND", raising=False)
    return target


def test_downloads_this_versions_build(out):
    urls = []

    def fetch(url):
        urls.append(url)
        return zipped({"index.html": "<html>_next</html>", "_next/app.js": "x"})

    assert frontend.ensure_built("9.9.9", fetch=fetch)
    assert urls == [frontend.download_urls("9.9.9")[0]]
    assert (out / "index.html").read_text() == "<html>_next</html>"
    assert (out / frontend.VERSION_FILE).read_text() == "9.9.9"


def test_falls_back_to_the_latest_release(out):
    def fetch(url):
        if "/latest/" not in url:
            raise OSError("404")
        return zipped({"index.html": "latest"})

    assert frontend.ensure_built("9.9.9", fetch=fetch)
    assert (out / "index.html").read_text() == "latest"


def test_offline_keeps_the_classic_fallback(out):
    def fetch(url):
        raise OSError("offline")

    assert not frontend.ensure_built("9.9.9", fetch=fetch)
    assert not out.exists()


def test_a_local_build_is_never_replaced(out):
    out.mkdir(parents=True)
    (out / "index.html").write_text("local")

    def fetch(url):
        raise AssertionError("should not download")

    assert frontend.ensure_built("9.9.9", fetch=fetch)
    assert (out / "index.html").read_text() == "local"


def test_a_downloaded_build_is_updated_with_the_version(out):
    out.mkdir(parents=True)
    (out / "index.html").write_text("old")
    (out / frontend.VERSION_FILE).write_text("1.0.0")
    assert frontend.ensure_built("2.0.0", fetch=lambda url: zipped({"index.html": "new"}))
    assert (out / "index.html").read_text() == "new"


def test_rejects_paths_outside_the_folder(out):
    assert not frontend.ensure_built("9.9.9", fetch=lambda url: zipped({"index.html": "x", "../evil.txt": "x"}))
    assert not (out.parent / "evil.txt").exists()


def test_can_be_turned_off(out, monkeypatch):
    monkeypatch.setenv("AUTOEXPRESS_DOWNLOAD_FRONTEND", "false")
    assert not frontend.ensure_built("9.9.9", fetch=lambda url: pytest.fail("downloaded"))
