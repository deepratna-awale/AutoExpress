"""
Run the standalone app: python -m autoexpress

Serves with waitress (a production WSGI server) when it is installed, and with
Flask's threaded development server otherwise. AUTOEXPRESS_HOST and
AUTOEXPRESS_PORT pick the address (default 0.0.0.0:5000).
"""

import os

from autoexpress import autoexpress


def main() -> None:
    host = os.environ.get("AUTOEXPRESS_HOST", "0.0.0.0")
    port = int(os.environ.get("AUTOEXPRESS_PORT", "5000"))
    try:
        from waitress import serve
    except ImportError:
        autoexpress.run(host=host, port=port, threaded=True)
        return
    # Generation runs on the job worker, so request threads only wait on I/O.
    serve(autoexpress, host=host, port=port, threads=int(os.environ.get("AUTOEXPRESS_THREADS", "8")))


if __name__ == "__main__":
    main()
