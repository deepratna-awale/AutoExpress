"""
Run the standalone app: python -m emotica

Serves with waitress (a production WSGI server) when it is installed, and with
Flask's threaded development server otherwise. EMOTICA_HOST and
EMOTICA_PORT pick the address (default 0.0.0.0:5000).
"""

import os

from emotica import emotica, frontend


def main() -> None:
    from loguru import logger

    from emotica_core import __version__

    if not frontend.ensure_built(__version__, log=logger.info):
        logger.warning(
            "The web interface isn't built and couldn't be downloaded, so the classic interface is served. "
            "Install Node.js and run the install script, or check the internet connection and restart."
        )
    host = os.environ.get("EMOTICA_HOST", "0.0.0.0")
    port = int(os.environ.get("EMOTICA_PORT", "5000"))
    try:
        from waitress import serve
    except ImportError:
        emotica.run(host=host, port=port, threaded=True)
        return
    # Generation runs on the job worker, so request threads only wait on I/O.
    serve(emotica, host=host, port=port, threads=int(os.environ.get("EMOTICA_THREADS", "8")))


if __name__ == "__main__":
    main()
