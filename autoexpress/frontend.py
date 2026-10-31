"""Serves the Next.js frontend (frontend/out), the default web interface.

The release zips and the Docker image ship it built. A source checkout builds it
with ./install.sh when Node.js is there; otherwise the app downloads the build
that was published with the release (autoexpress-frontend.zip) on first start,
see ensure_built. Only when neither worked does "/" fall back to the classic
HTML/JS interface, which also stays reachable at "/classic" (views.py).
"""

import io
import os
import pathlib
import shutil
import tempfile
import zipfile

from flask import Blueprint, abort, send_from_directory
from werkzeug.security import safe_join

FRONTEND_DIR = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "out"

frontend = Blueprint("frontend", __name__)

RELEASES = "https://github.com/deepratna-awale/AutoExpress/releases"
ASSET = "autoexpress-frontend.zip"
# Written next to a downloaded build, so a later version downloads its own. A local build has none and is kept.
VERSION_FILE = ".autoexpress-version"
MAX_DOWNLOAD = 50 * 1024 * 1024


def is_built() -> bool:
    return (FRONTEND_DIR / "index.html").is_file()


def download_urls(version: str) -> list[str]:
    """This version's build first, then the latest release's."""
    return [f"{RELEASES}/download/v{version}/{ASSET}", f"{RELEASES}/latest/download/{ASSET}"]


def _extract(blob: bytes, target: pathlib.Path) -> None:
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        root = target.resolve()
        for member in archive.infolist():
            path = (target / member.filename).resolve()
            if path != root and root not in path.parents:
                raise ValueError(f"Unsafe path in {ASSET}: {member.filename}")
        archive.extractall(target)
    if not (target / "index.html").is_file():
        raise ValueError(f"{ASSET} has no index.html")


def ensure_built(version: str, fetch=None, log=None) -> bool:
    """
    Make sure the web interface is there, downloading the released build when it isn't.

    A build made here (./install.sh, pnpm build) is always kept. A downloaded one is
    replaced when AutoExpress is updated to another version. Set
    AUTOEXPRESS_DOWNLOAD_FRONTEND=false to never download.

    Returns:
        bool: True when the web interface can be served.
    """
    marker = FRONTEND_DIR / VERSION_FILE
    downloaded = marker.is_file()
    if is_built() and (not downloaded or marker.read_text(encoding="utf-8").strip() == version):
        return True
    if os.environ.get("AUTOEXPRESS_DOWNLOAD_FRONTEND", "true").strip().lower() in ("0", "false", "no", "off"):
        return is_built()
    if fetch is None:
        import requests

        def fetch(url):
            response = requests.get(url, timeout=(10, 60), stream=True)
            response.raise_for_status()
            blob = response.raw.read(MAX_DOWNLOAD + 1, decode_content=True)
            if len(blob) > MAX_DOWNLOAD:
                raise ValueError(f"{ASSET} is larger than {MAX_DOWNLOAD} bytes")
            return blob

    say = log or (lambda message: None)
    for url in download_urls(version):
        try:
            blob = fetch(url)
            FRONTEND_DIR.parent.mkdir(parents=True, exist_ok=True)
            staging = pathlib.Path(tempfile.mkdtemp(prefix=".out-", dir=FRONTEND_DIR.parent))
            try:
                _extract(blob, staging)
                (staging / VERSION_FILE).write_text(version, encoding="utf-8")
                shutil.rmtree(FRONTEND_DIR, ignore_errors=True)
                staging.rename(FRONTEND_DIR)
            finally:
                shutil.rmtree(staging, ignore_errors=True)
        except Exception as e:  # offline, no such release yet, a bad archive: try the next, then keep what's there
            say(f"Could not get the web interface from {url}: {e}")
            continue
        say(f"Downloaded the web interface from {url}")
        return True
    return is_built()


def index():
    return send_from_directory(FRONTEND_DIR, "index.html")


@frontend.route("/_next/<path:filename>", methods=["GET"])
def next_assets(filename):
    if not is_built():
        abort(404)
    return send_from_directory(FRONTEND_DIR / "_next", filename, max_age=31536000)


@frontend.route("/<path:filename>", methods=["GET"])
def public_files(filename):
    # Files from frontend/public (icons etc.). Every API route is more specific and wins.
    path = safe_join(str(FRONTEND_DIR), filename)
    if not is_built() or path is None or not pathlib.Path(path).is_file():
        abort(404)
    return send_from_directory(FRONTEND_DIR, filename)
