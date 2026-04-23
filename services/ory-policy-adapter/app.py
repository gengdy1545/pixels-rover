from __future__ import annotations

import http.client
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from urllib.parse import urlsplit


HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
AUTH_HEADERS = {
    "x-auth-user-id",
    "x-auth-user-email",
    "x-auth-session-id",
}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _cookies(header_value: str | None) -> SimpleCookie:
    jar = SimpleCookie()
    if header_value:
        jar.load(header_value)
    return jar


def _json_error(code: int, message: str) -> bytes:
    return json.dumps(
        {
            "code": code,
            "message": message,
            "details": {
                "errorCode": "GATEWAY_CSRF_INVALID",
                "category": "AUTH",
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")


class PolicyAdapterHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def do_OPTIONS(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_PATCH(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def log_message(self, fmt: str, *args: object) -> None:
        print("%s - - %s" % (self.address_string(), fmt % args), flush=True)

    def _handle(self) -> None:
        if self.path == "/health":
            self._send_json(200, b'{"status":"UP","service":"ory-policy-adapter"}')
            return

        if not self._csrf_valid():
            self._send_json(403, _json_error(403, "CSRF token missing or invalid"))
            return

        self._proxy_to_oathkeeper()

    def _csrf_valid(self) -> bool:
        if self.command.upper() in SAFE_METHODS:
            return True

        cookie_token = _cookies(self.headers.get("Cookie")).get("XSRF-TOKEN")
        header_token = self.headers.get("X-XSRF-TOKEN")
        if not cookie_token or not header_token:
            return False
        return cookie_token.value == header_token

    def _proxy_to_oathkeeper(self) -> None:
        host = os.environ.get("OATHKEEPER_PROXY_HOST", "oathkeeper")
        port = int(os.environ.get("OATHKEEPER_PROXY_PORT", "4455"))
        parsed = urlsplit(self.path)
        path = parsed.path + (("?" + parsed.query) if parsed.query else "")

        headers: dict[str, str] = {}
        for key, value in self.headers.items():
            lowered = key.lower()
            if lowered in HOP_BY_HOP_HEADERS or lowered in AUTH_HEADERS:
                continue
            headers[key] = value
        headers["Host"] = f"{host}:{port}"

        body = None
        content_length = self.headers.get("Content-Length")
        if content_length:
            body = self.rfile.read(int(content_length))

        conn = http.client.HTTPConnection(host, port, timeout=900)
        try:
            conn.request(self.command, path, body=body, headers=headers)
            response = conn.getresponse()
            self.send_response(response.status, response.reason)
            self.send_header("Connection", "close")
            self.close_connection = True
            for key, value in response.getheaders():
                lowered = key.lower()
                if lowered in HOP_BY_HOP_HEADERS:
                    continue
                self.send_header(key, value)
            self.end_headers()

            if self.command.upper() == "HEAD":
                return

            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()
        finally:
            conn.close()

    def _send_json(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command.upper() != "HEAD":
            self.wfile.write(body)


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), PolicyAdapterHandler)
    print(f"ory-policy-adapter listening on :{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
