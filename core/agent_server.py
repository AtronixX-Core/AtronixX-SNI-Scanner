"""
AX-Scanner :: agent_server.py

The persistent piece that runs on the target/"Germany" server. It does
exactly two things over a tiny JSON/HTTP API:

  POST /spawn   {sni: "example.com"}       -> creates one ephemeral Reality
                                              inbound with that SNI, returns
                                              connection details
  POST /destroy {instance_id: "..."}       -> kills that one instance
  GET  /health                             -> liveness probe
  GET  /probe/clients                      -> probe clients currently connected
  POST /probe/job {op,payload,timeout}     -> run one test on the connected
                                              probe client (your own computer)
                                              and return its answer

It holds no state beyond "which ephemeral xray processes are currently
running", all under core.xray_manager's isolation guarantees. It is not,
and must never become, anything close to the panel's own xray-core.

Auth: a shared secret token (generated at install time, stored in
BASE_DIR/agent.token) must be sent as `X-Auth-Token`. This is a testing
tool for the operator's own use, not a public-facing service.
"""

import json
import os
import secrets
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from core.config import BASE_DIR, AGENT_DEFAULT_PORT, BROKER_DEFAULT_PORT
from core import xray_manager, probe_broker

TOKEN_PATH = os.path.join(BASE_DIR, "agent.token")

_instances = {}  # instance_id -> {"process": XrayProcess, "port": int, "public_key": str, "short_id": str}
_lock = threading.Lock()


def get_or_create_token():
    os.makedirs(BASE_DIR, exist_ok=True)
    if os.path.isfile(TOKEN_PATH):
        return open(TOKEN_PATH).read().strip()
    token = secrets.token_hex(24)
    with open(TOKEN_PATH, "w") as f:
        f.write(token)
    os.chmod(TOKEN_PATH, 0o600)
    return token


class Handler(BaseHTTPRequestHandler):
    server_version = "AXScannerAgent/1.0"

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self):
        expected = get_or_create_token()
        got = self.headers.get("X-Auth-Token", "")
        return secrets.compare_digest(got, expected)

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "active_instances": len(_instances)})
            return
        if self.path == "/probe/clients":
            if not self._check_auth():
                self._send_json(401, {"error": "unauthorized"})
                return
            self._send_json(200, {"clients": probe_broker.clients()})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if not self._check_auth():
            self._send_json(401, {"error": "unauthorized"})
            return

        length = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self._send_json(400, {"error": "invalid json"})
            return

        if self.path == "/spawn":
            self._handle_spawn(body)
        elif self.path == "/destroy":
            self._handle_destroy(body)
        elif self.path == "/probe/job":
            self._handle_probe_job(body)
        else:
            self._send_json(404, {"error": "not found"})

    def _handle_spawn(self, body):
        sni = body.get("sni")
        if not sni:
            self._send_json(400, {"error": "missing 'sni'"})
            return
        try:
            private_key, public_key = xray_manager.generate_keypair()
            short_id = secrets.token_hex(4)
            transport = body.get("transport", "tcp")
            if transport not in ("tcp", "xhttp"):
                self._send_json(400, {"error": "transport must be 'tcp' or 'xhttp'"})
                return
            config, port = xray_manager.build_reality_server_config(
                sni, private_key, short_id, transport=transport)
            proc = xray_manager.XrayProcess(config, tag=f"srv-{uuid.uuid4().hex[:8]}")
            proc.start()

            if not proc.is_alive():
                proc.stop()
                self._send_json(500, {"error": "xray failed to start (port busy or bad config)"})
                return

            instance_id = uuid.uuid4().hex
            with _lock:
                _instances[instance_id] = {"process": proc, "port": port}

            self._send_json(200, {
                "instance_id": instance_id,
                "port": port,
                "public_key": public_key,
                "short_id": short_id,
                "sni": sni,
                "transport": transport,
            })
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def _handle_probe_job(self, body):
        try:
            data = probe_broker.dispatch(
                body["op"], body.get("payload", {}),
                timeout=float(body.get("timeout", 15)),
                client_id=body.get("client_id"),
            )
            self._send_json(200, {"ok": True, "data": data})
        except probe_broker.ProbeUnavailable as e:
            self._send_json(200, {"ok": False, "error": str(e), "kind": "unavailable"})
        except probe_broker.ProbeTimeout as e:
            self._send_json(200, {"ok": False, "error": str(e), "kind": "timeout"})
        except Exception as e:
            self._send_json(200, {"ok": False, "error": str(e), "kind": "failed"})

    def _handle_destroy(self, body):
        instance_id = body.get("instance_id")
        with _lock:
            inst = _instances.pop(instance_id, None)
        if not inst:
            self._send_json(404, {"error": "unknown instance_id"})
            return
        inst["process"].stop()
        self._send_json(200, {"status": "destroyed"})

    def log_message(self, format, *args):
        pass  # keep stdout clean; systemd journal captures this if needed


def destroy_all():
    with _lock:
        for inst in _instances.values():
            inst["process"].stop()
        _instances.clear()


def run(port=AGENT_DEFAULT_PORT, broker_port=None):
    token = get_or_create_token()
    broker_port = broker_port or (port + 1)
    probe_broker.start(broker_port, get_or_create_token)
    print(f"[AX-Scanner Agent] probe broker listening on 0.0.0.0:{broker_port}")
    print(f"[AX-Scanner Agent] listening on 0.0.0.0:{port}")
    print(f"[AX-Scanner Agent] auth token stored at {TOKEN_PATH} (chmod 600)")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        destroy_all()
        server.server_close()


if __name__ == "__main__":
    run()
