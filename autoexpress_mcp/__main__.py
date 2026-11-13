"""python -m autoexpress_mcp: run the AutoExpress MCP server over stdio (default) or streamable HTTP."""

import argparse
import hmac
import os
import sys

from .server import Settings, build_server


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="python -m autoexpress_mcp", description="MCP server for the AutoExpress standalone app.")
    parser.add_argument("--transport", choices=["stdio", "http"], default=os.environ.get("AUTOEXPRESS_MCP_TRANSPORT", "stdio"))
    parser.add_argument("--app-url", help="The AutoExpress app (default $AUTOEXPRESS_URL or http://127.0.0.1:5000)")
    parser.add_argument("--host", default=os.environ.get("AUTOEXPRESS_MCP_HOST", "127.0.0.1"), help="HTTP: listen address")
    parser.add_argument("--port", type=int, default=int(os.environ.get("AUTOEXPRESS_MCP_PORT", "5056")), help="HTTP: port")
    parser.add_argument("--path", default="/mcp", help="HTTP: endpoint path")
    parser.add_argument("--token", default=os.environ.get("AUTOEXPRESS_MCP_TOKEN"), help="HTTP: require 'Authorization: Bearer <token>'")
    parser.add_argument("--allowed-host", action="append", default=[], help="HTTP: extra Host header values to accept (e.g. a LAN name:port)")
    parser.add_argument("--results-dir", help="Where save_results puts files (default ./autoexpress-results)")
    files = parser.add_mutually_exclusive_group()
    files.add_argument("--allow-local-files", dest="local_files", action="store_true", default=None, help="Read image paths and save results on this machine (default for stdio)")
    files.add_argument("--no-local-files", dest="local_files", action="store_false", help="Images only as URLs/base64; results only as pictures (default for HTTP)")
    return parser.parse_args(argv)


def bearer_guard(app, token: str):
    expected = f"Bearer {token}".encode()

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            supplied = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(supplied, expected):
                await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain"), (b"www-authenticate", b"Bearer")]})
                await send({"type": "http.response.body", "body": b"Missing or wrong bearer token."})
                return
        await app(scope, receive, send)

    return guarded


def main(argv=None):
    args = parse_args(argv)
    local_files = args.local_files
    if local_files is None:
        local_files = os.environ.get("AUTOEXPRESS_MCP_LOCAL_FILES", "1" if args.transport == "stdio" else "0").lower() in ("1", "true", "yes", "on")
    server = build_server(Settings(app_url=args.app_url, allow_local_files=local_files, results_dir=args.results_dir))

    if args.transport == "stdio":
        server.run("stdio")
        return

    import uvicorn
    from mcp.server.transport_security import TransportSecuritySettings

    loopback = args.host in ("127.0.0.1", "localhost", "::1")
    if not loopback and not args.token:
        print("Refusing to listen on a non-loopback address without --token (or AUTOEXPRESS_MCP_TOKEN).", file=sys.stderr)
        sys.exit(2)
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", *args.allowed_host]
    if not loopback and args.host not in ("0.0.0.0", "::"):
        hosts.append(f"{args.host}:*")
    security = TransportSecuritySettings(enable_dns_rebinding_protection=loopback or bool(args.allowed_host), allowed_hosts=hosts, allowed_origins=[f"http://{h}" for h in hosts])
    app = server.streamable_http_app(streamable_http_path=args.path, transport_security=security, host=args.host)
    if args.token:
        app = bearer_guard(app, args.token)
    print(f"AutoExpress MCP server on http://{args.host}:{args.port}{args.path}", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
