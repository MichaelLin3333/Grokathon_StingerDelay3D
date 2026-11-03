"""Same-origin web + JSON API server. Run: python3 -m server.main."""
from __future__ import annotations

import argparse
import json
import logging
import mimetypes
import os
import sys
import threading
import time
import ast
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import planner

try:
    from server import integrations
except ImportError:
    integrations = None
try:
    from server import upstream
except ImportError:
    upstream = None

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
MAX_BODY = 1024 * 512
LOG = logging.getLogger("buzzroute")


class Handler(SimpleHTTPRequestHandler):
    server_version = "StingerD-GPT/0.1"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_request(self, code="-", size="-"):
        # OAuth authorization codes must never appear in server access logs.
        self.log_message('"%s %s %s" %s %s', self.command,
                         urlsplit(self.path).path, self.request_version, str(code), str(size))

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Permissions-Policy", "microphone=(self), geolocation=(self)")
        self.send_header("Cache-Control", "no-store" if self.path.startswith(("/api/", "/trips/", "/grok/", "/auth/", "/calendar/")) else "no-cache")
        super().end_headers()

    def respond(self, status, payload, headers=None):
        data = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, str(value))
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _route(self, method, body=None):
        parts = urlsplit(self.path)
        path = parts.path.removeprefix("/api") if parts.path.startswith("/api/") else parts.path
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        if path == "/auth/google/callback":
            cookies = SimpleCookie()
            try:
                cookies.load(self.headers.get("Cookie", ""))
                cookie = cookies.get("buzz_oauth_state")
                query["_oauth_cookie"] = cookie.value if cookie else ""
            except Exception:
                query["_oauth_cookie"] = ""
        if method == "GET":
            if path == "/health":
                return 200, {"ok": True, "mode": "replay", "integrations": integrations.integration_status() if integrations else {}, "upstream": upstream.status() if upstream else {"status": "unavailable"}}, {}
            if path == "/places":
                return 200, {"places": planner.places()}, {}
            if path == "/routes":
                return 200, {"routes": planner.routes()}, {}
            if path == "/upstream":
                return 200, upstream.status() if upstream else {"status": "unavailable", "interval_seconds": 300}, {}
            if path in ["/openapi.json", "/contracts/trip-trace.json"]:
                file = ROOT / "docs" / ("openapi.json" if path == "/openapi.json" else "trip-trace.schema.json")
                if file.exists():
                    return 200, json.loads(file.read_text()), {}
                return 200, {"version": "v0", "documentation": "/docs", "message": "See docs/INTERFACE.md in source."}, {}
        if method == "POST" and path == "/trips/plan":
            if 'constraints' in body:
                from server.compat import shared_plan
                return 200, shared_plan(body, planner), {}
            return 200, planner.plan_trip(body), {}
        if method == "POST" and path == "/trips/verify":
            return 200, {"verified": planner.verify_trace(body)}, {}
        if integrations:
            result = integrations.dispatch(method, path, body or {}, query, planner)
            if result is not None:
                return result
        if path.startswith(("/schedule/", "/day/", "/routes/", "/places/", "/trips/", "/calendar/", "/grok/", "/signals/", "/integrations/", "/auth/", "/upstream")) or parts.path.startswith("/api/"):
            return 404, {"error": "Unknown API endpoint", "path": path}, {}
        return None

    def do_GET(self):
        try:
            result = self._route("GET")
            if result is not None:
                self.respond(*result)
            else:
                # Browser routes share the same client; never serve outside web/.
                if urlsplit(self.path).path in ["/plan", "/schedule", "/saved", "/settings"]:
                    self.path = "/index.html"
                super().do_GET()
        except ValueError as exc:
            self.respond(422, {"error": str(exc)})
        except Exception:
            LOG.exception("Request failed")
            self.respond(500, {"error": "The request could not be completed"})

    def do_POST(self):
        # Reject cross-origin browser writes. Local native clients can omit Origin.
        origin = self.headers.get("Origin")
        host = self.headers.get("Host", "")
        if origin and origin not in [f"http://{host}", f"https://{host}"]:
            self.respond(403, {"error": "Cross-origin requests are not permitted"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                self.respond(413 if length > MAX_BODY else 400, {"error": "JSON body required; maximum size is 512 KB"})
                return
            if self.headers.get("Transfer-Encoding"):
                self.respond(400, {"error": "Chunked request bodies are not supported"})
                return
            raw = self.rfile.read(length)
            body = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON values are not allowed")))
            if not isinstance(body, dict):
                raise ValueError("JSON body must be an object")
            result = self._route("POST", body)
            self.respond(*(result or (404, {"error": "Unknown API endpoint"}, {})))
        except (ValueError, UnicodeDecodeError) as exc:
            self.respond(422, {"error": str(exc)})
        except Exception:
            LOG.exception("Request failed")
            self.respond(500, {"error": "The request could not be completed"})

    def do_OPTIONS(self):
        self.respond(405, {"error": "Use this API from the same origin; CORS is disabled"})


def main():
    parser = argparse.ArgumentParser(description="Buzz Route local web app")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-watch", action="store_true")
    parser.add_argument("--reload", action="store_true", help="Reload this development process when Python or base data changes")
    args = parser.parse_args()
    os.environ["STINGER_APP_ORIGIN"] = f"http://127.0.0.1:{args.port}"
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    mimetypes.add_type("text/javascript", ".js")
    if upstream and not args.no_watch:
        upstream.start()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"Buzz Route ready: http://{args.host}:{args.port}", flush=True)
    print("Historical replay + demo uncertainty. Ctrl-C to stop.", flush=True)
    if args.reload:
        def versions():
            files = list((ROOT / 'server').glob('*.py')) + list((ROOT / 'data').glob('*.json'))
            return {str(p): p.stat().st_mtime_ns for p in files}
        def reload_loop():
            baseline = versions()
            while True:
                time.sleep(1)
                current = versions()
                if current == baseline:
                    continue
                time.sleep(.75)
                try:
                    for file in (ROOT / 'server').glob('*.py'):
                        ast.parse(file.read_text())
                except (SyntaxError, OSError):
                    continue
                print('Reloading changed development code…', flush=True)
                os.execv(sys.executable, [sys.executable, '-m', 'server.main', *sys.argv[1:]])
        threading.Thread(target=reload_loop, daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if upstream:
            upstream.stop()


if __name__ == "__main__":
    main()
