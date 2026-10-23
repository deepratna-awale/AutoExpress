"""Serves the Next.js frontend (frontend/out) when it has been built.

Without a build, "/" keeps rendering the classic HTML/JS interface, which also
stays reachable at "/classic" (both routes live in views.py).
"""

import pathlib

from flask import Blueprint, abort, send_from_directory

FRONTEND_DIR = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "out"

frontend = Blueprint("frontend", __name__)


def is_built() -> bool:
    return (FRONTEND_DIR / "index.html").is_file()


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
    if not is_built() or not (FRONTEND_DIR / filename).is_file():
        abort(404)
    return send_from_directory(FRONTEND_DIR, filename)
