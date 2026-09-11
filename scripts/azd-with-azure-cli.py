"""Run azd using the current Azure CLI login through azd's external-auth protocol."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("Usage: azd-with-azure-cli.py <azd command and arguments>")

    shared_key = secrets.token_urlsafe(32)

    class TokenHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/token":
                self.send_error(404)
                return
            if self.headers.get("Authorization") != f"Bearer {shared_key}":
                self.send_error(401)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                request = json.loads(self.rfile.read(length))
                scopes = request.get("scopes") or []
                if not scopes:
                    raise ValueError("azd requested a token without scopes")
                scopes = [scope.replace("//.default", "/.default") for scope in scopes]
                az_command = shutil.which("az")
                if not az_command:
                    raise RuntimeError("Azure CLI is not available on PATH")
                command = [
                    az_command,
                    "account",
                    "get-access-token",
                    "--scope",
                    *scopes,
                    "-o",
                    "json",
                ]
                if request.get("tenantId"):
                    command.extend(["--tenant", request["tenantId"]])
                token = json.loads(
                    subprocess.check_output(
                        command,
                        text=True,
                        stderr=subprocess.PIPE,
                        shell=os.name == "nt",
                    )
                )
                expires = datetime.fromtimestamp(int(token["expires_on"]), UTC).isoformat()
                response = {
                    "status": "success",
                    "token": token["accessToken"],
                    "expiresOn": expires.replace("+00:00", "Z"),
                }
                status = 200
            except Exception as exc:
                response = {
                    "status": "error",
                    "code": "GetTokenError",
                    "message": str(exc),
                }
                status = 200
            body = json.dumps(response).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), TokenHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = {
            **os.environ,
            "AZD_AUTH_ENDPOINT": f"http://127.0.0.1:{server.server_port}",
            "AZD_AUTH_KEY": shared_key,
        }
        return subprocess.run(sys.argv[1:], env=env, check=False).returncode
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
