"""Receive the agency sign-in's redirect on this machine, so nothing has to be copied out of a browser.

WHY THIS EXISTS. Google redirects the browser to GOOGLE_REDIRECT_URI, and for the agency sign-in that is `http://localhost:3000/api/v1/google/callback` (one of the three registered URIs).
On a machine where FlowQR's own local stack is running, that address is FlowQR's CUSTOMER callback, which (correctly) rejects the agency state, never uses the code, and sends the browser on to
`/gbp/locations`, which sends a signed-out visitor to `/login`. The code and state then exist only inside one browser request that has already been redirected away: the app's access log
redacts them, and they cannot be recovered. Copying them out by hand is fragile, and it failed in practice.

WHAT IT DOES. `google-agency-register --listen` opens ONE listener on the redirect's port BEFORE the sign-in address is shown (so a busy port fails at once, not after you have signed in), waits
for exactly the callback it expects, and hands the code to the registration in the same process. It is deliberately small and strict:
  * it serves only GET on the exact callback path; anything else is a 404 or 405 and is ignored;
  * it accepts a request only if the `state` equals the one this process issued (constant-time compare); a request with any other state is refused with a 400 and the wait continues;
  * the state is still the signed, random, single-use one, and the registration still consumes it and still checks Google's own answer for the e-mail before anything is stored;
  * it writes no log line (the default handler would print the request line, code included), shows the browser only a plain page that contains neither value, and closes after one valid callback;
  * it gives up after a timeout, and refuses a redirect that is not localhost (use the manual flow for those).
It makes no Google call and stores nothing: the registration does that.
"""
from __future__ import annotations

import hmac
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlsplit


class ListenError(Exception):
    pass


def parse_redirect(uri: str) -> tuple[str, int, str]:
    """(host, port, path) of a localhost redirect URI. Anything that is not http on localhost is refused: only a local listener can receive it, and only localhost is safe to open."""
    p = urlsplit(uri or "")
    if p.scheme != "http" or p.hostname not in ("localhost", "127.0.0.1") or not p.path.startswith("/"):
        raise ListenError("--listen needs GOOGLE_REDIRECT_URI to be an http://localhost address (for example http://localhost:3000/api/v1/google/callback). For any other address use --code and --state.")
    return p.hostname, p.port or 80, p.path


class _Box:
    code: str | None = None
    error: str | None = None
    done = False


def _handler(path: str, expected_state: str, box: _Box):
    page = lambda text: ("<!doctype html><meta charset=utf-8><title>FlowQR agency sign-in</title><body style=\"font-family:sans-serif;max-width:32rem;margin:4rem auto\"><p>" + text + "</p>").encode()  # noqa: E731

    class H(BaseHTTPRequestHandler):
        server_version = "FlowQRAgencyListener"

        def log_message(self, *args, **kwargs):  # the default would write the request line, and the code with it
            pass

        def _send(self, status: int, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlsplit(self.path)
            if u.path != path:
                return self._send(404, page("Not found."))
            q = parse_qs(u.query)
            got = (q.get("state") or [""])[0]
            if not hmac.compare_digest(got.encode(), expected_state.encode()):
                return self._send(400, page("This is not the sign-in this command is waiting for. Nothing was done."))
            if q.get("error"):
                box.error, box.done = (q["error"][0] or "error")[:40], True
                return self._send(200, page("Google did not complete the sign-in. You can close this tab; the command will say what happened."))
            code = (q.get("code") or [""])[0]
            if not code:
                return self._send(400, page("The sign-in carried no code. Nothing was done."))
            box.code, box.done = code, True
            self._send(200, page("Received. You can close this tab: the registration continues in the terminal."))

        def _no(self):
            self._send(405, page("Not allowed."))

        do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _no

    return H


def open_listener(bind_host: str, port: int) -> HTTPServer:
    """Bind the port. Called BEFORE the sign-in address is shown so a busy port is found at once."""
    try:
        server = HTTPServer((bind_host, port), BaseHTTPRequestHandler)
    except OSError as exc:
        raise ListenError(f"Port {port} is not free ({exc.strerror or 'in use'}). Something else is listening there: most likely FlowQR's own local frontend. "
                          "Stop it first (docker stop flowqr-frontend-1), then run this command again.")
    return server


def wait_for_callback(server: HTTPServer, *, path: str, expected_state: str, timeout: float = 600.0) -> tuple[str | None, str | None]:
    """Serve until ONE valid callback arrives (or the timeout), then close. Returns (code, error): exactly one of them is set. The listener is always closed."""
    box = _Box()
    server.RequestHandlerClass = _handler(path, expected_state, box)
    server.timeout = 0.5
    deadline = time.monotonic() + timeout
    try:
        while not box.done and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not box.done:
        raise ListenError("No sign-in arrived before the time limit. Nothing was done. Run the command again.")
    return box.code, box.error
