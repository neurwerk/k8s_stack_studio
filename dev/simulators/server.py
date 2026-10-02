"""Three isolated dev-only HTTP integrations; one process per Compose service."""

from __future__ import annotations

import base64
import hmac
import json
import os
import ssl
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fixtures import langfuse_observations, policy_actions, policy_result, search_logs, usage_summary

mode = sys.argv[1]
ports = {"pii": 8443, "usage": 15000, "logs": 9200, "langfuse": 3000}
if mode not in ports:
    raise SystemExit("Expected pii, usage, logs or langfuse")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format_string: str, *args: object) -> None:
        # Langfuse filters travel in the URL and can contain search terms.
        if mode == "langfuse":
            sys.stderr.write("simulator: Langfuse request handled\n")
            return
        sys.stderr.write("simulator: " + format_string % args + "\n")

    def respond(self, status: int, body: object) -> None:
        content = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def handle_request(self) -> None:
        if mode == "pii":
            certificate = self.connection.getpeercert()
            names = [
                value
                for part in certificate.get("subject", ())
                for key, value in part
                if key == "commonName"
            ]
            if names != ["frontend-studio-api"]:
                self.respond(403, {"detail": "workload certificate required"})
                return
        if mode == "logs":
            expected = (
                "Basic "
                + base64.b64encode(
                    ("studio-logs-read:" + os.environ["STUDIO_LOGS_PASSWORD"]).encode()
                ).decode()
            )
            if self.headers.get("Authorization") != expected:
                self.respond(401, {"detail": "invalid log reader"})
                return
        if mode == "langfuse":
            expected = "Basic " + base64.b64encode(b"pk-lf-studio-dev:sk-lf-studio-dev").decode()
            if not hmac.compare_digest(self.headers.get("Authorization", ""), expected):
                self.respond(401, {"detail": "invalid sample project key"})
                return
            if self.command == "GET" and urlsplit(self.path).path == "/api/public/v2/observations":
                try:
                    self.respond(200, langfuse_observations(parse_qs(urlsplit(self.path).query)))
                except (ValueError, TypeError, KeyError, IndexError, StopIteration):
                    self.respond(400, {"detail": "invalid sample query"})
                return
            self.respond(404, {"detail": "unknown simulation route"})
            return
        if self.command == "GET" and mode == "pii":
            if self.path == "/v1/actions":
                self.respond(200, policy_actions())
            elif self.path == "/v1/policy":
                self.respond(
                    200,
                    {
                        "api_version": "v1",
                        "version": "synthetic-dev",
                        "default_action": "mask",
                        "entities": ["EMAIL_ADDRESS"],
                        "safety_rules": [],
                    },
                )
            else:
                self.respond(404, {"detail": "unknown simulation route"})
            return
        if self.command != "POST":
            self.respond(404, {"detail": "unknown simulation route"})
            return
        if not 0 < int(self.headers.get("Content-Length", "0")) <= 5_242_880:
            self.respond(413, {"detail": "request too large"})
            return
        try:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if not isinstance(payload, dict):
                raise ValueError("expected object")
            if mode == "pii" and self.path in (
                "/v1/studio/analyze-request",
                "/v1/studio/evaluate-policy",
            ):
                result = policy_result(
                    payload, evaluate=self.path.endswith("evaluate-policy")
                )
            elif mode == "usage" and self.path == "/api/logs/analytics/summary":
                result = usage_summary(payload)
            elif (
                mode == "logs"
                and self.path.endswith("/_search")
                and self.path.startswith("/fluent-bit-")
            ):
                result = search_logs(payload)
            else:
                self.respond(404, {"detail": "unknown simulation route"})
                return
        except (ValueError, TypeError, KeyError, OverflowError):
            self.respond(400, {"detail": "invalid sample request"})
            return
        self.respond(200, result)

    do_GET = handle_request
    do_POST = handle_request


server = ThreadingHTTPServer(("0.0.0.0", ports[mode]), Handler)
if mode in ("pii", "logs"):
    tls = Path("/tls")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(tls / "server.crt"), str(tls / "server.key"))
    if mode == "pii":
        context.load_verify_locations(str(tls / "ca.crt"))
        context.verify_mode = ssl.CERT_REQUIRED
    server.socket = context.wrap_socket(server.socket, server_side=True)
print(f"Local {mode} simulator listening on {ports[mode]}", flush=True)
server.serve_forever()
