"""
AX-Scanner :: probe_broker.py

Runs inside the Agent service on the target server. Your own computer
(Windows/Linux, on the carrier you want to measure) runs probe_client.py,
which dials OUT to this broker and stays connected. Every carrier-path
test (TLS probes, Reality/XHTTP handshakes, ISP lookup) is then executed
ON THAT COMPUTER with its own network stack — the server only sends
"do this test" jobs and collects the answers. Test traffic itself never
travels through this connection, so DPI on your carrier sees exactly what
a real user's connection would look like.

Wire format: TLS (self-signed, generated on first start) carrying one
JSON object per line. Auth: the Agent token, sent in the first message.

  client -> {"type":"hello","token":...,"client_id":...,"name":...,"os":...,"version":...}
  server -> {"type":"hello_ack","ok":true}
  server -> {"type":"job","id":...,"op":...,"payload":{...}}
  client -> {"type":"result","id":...,"ok":true,"data":{...}}
  either -> {"type":"ping"} / {"type":"pong"}
"""

import json
import os
import secrets
import socket
import ssl
import subprocess
import threading
import time
import uuid

from core.config import TLS_CERT_PATH, TLS_KEY_PATH, BASE_DIR

IDLE_TIMEOUT = 60  # seconds without any message before a client is dropped


class ProbeUnavailable(Exception):
    pass


class ProbeTimeout(Exception):
    pass


def ensure_cert():
    if os.path.isfile(TLS_CERT_PATH) and os.path.isfile(TLS_KEY_PATH):
        return
    os.makedirs(BASE_DIR, exist_ok=True)
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
         "-nodes", "-keyout", TLS_KEY_PATH, "-out", TLS_CERT_PATH,
         "-days", "3650", "-subj", "/CN=localhost"],
        check=True, capture_output=True,
    )
    os.chmod(TLS_KEY_PATH, 0o600)


class _Conn:
    def __init__(self, sock, addr, meta):
        self.sock = sock
        self.addr = addr
        self.meta = meta                     # client_id, name, os, version
        self.wlock = threading.Lock()
        self.pending = {}                    # job id -> [Event, result]
        self.connected_at = time.time()
        self.last_seen = time.time()
        self.alive = True

    def send(self, obj):
        data = (json.dumps(obj) + "\n").encode()
        with self.wlock:
            self.sock.sendall(data)

    def close(self):
        self.alive = False
        try:
            self.sock.close()
        except OSError:
            pass
        for ev, _ in list(self.pending.values()):
            ev.set()


_clients = {}            # client_id -> _Conn
_lock = threading.Lock()


def _reader(conn, token_check):
    f = conn.sock.makefile("rb")
    while conn.alive:
        line = f.readline()
        if not line:
            break
        conn.last_seen = time.time()
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        t = msg.get("type")
        if t == "ping":
            conn.send({"type": "pong"})
        elif t == "result":
            slot = conn.pending.get(msg.get("id"))
            if slot:
                slot[1] = msg
                slot[0].set()


def _watchdog(conn):
    while conn.alive:
        time.sleep(5)
        if time.time() - conn.last_seen > IDLE_TIMEOUT:
            conn.close()
            return


def _handle(raw, addr, ctx, token_provider):
    conn = None
    try:
        raw.settimeout(10)
        tls = ctx.wrap_socket(raw, server_side=True)
        f = tls.makefile("rb")
        line = f.readline(65536)
        hello = json.loads(line)
        if hello.get("type") != "hello" or not secrets.compare_digest(
                str(hello.get("token", "")), token_provider()):
            tls.sendall(b'{"type":"hello_ack","ok":false}\n')
            tls.close()
            return
        tls.settimeout(None)
        meta = {k: hello.get(k) for k in ("client_id", "name", "os", "version")}
        meta["client_id"] = meta["client_id"] or uuid.uuid4().hex
        conn = _Conn(tls, addr, meta)
        with _lock:
            old = _clients.pop(meta["client_id"], None)
            _clients[meta["client_id"]] = conn
        if old:
            old.close()
        conn.send({"type": "hello_ack", "ok": True})
        threading.Thread(target=_watchdog, args=(conn,), daemon=True).start()
        _reader(conn, token_provider)
    except Exception:
        pass
    finally:
        if conn:
            conn.close()
            with _lock:
                if _clients.get(conn.meta["client_id"]) is conn:
                    _clients.pop(conn.meta["client_id"], None)
        else:
            try:
                raw.close()
            except OSError:
                pass


def start(port, token_provider):
    ensure_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(TLS_CERT_PATH, TLS_KEY_PATH)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", port))
    srv.listen(32)

    def loop():
        while True:
            try:
                raw, addr = srv.accept()
            except OSError:
                return
            threading.Thread(target=_handle, args=(raw, addr, ctx, token_provider),
                             daemon=True).start()

    threading.Thread(target=loop, daemon=True).start()
    return srv


def clients():
    with _lock:
        return [{
            "client_id": c.meta["client_id"], "name": c.meta.get("name"),
            "os": c.meta.get("os"), "version": c.meta.get("version"),
            "remote_ip": c.addr[0], "connected_for_s": int(time.time() - c.connected_at),
        } for c in _clients.values() if c.alive]


def dispatch(op, payload, timeout=15, client_id=None):
    """Runs one job on a connected probe client and returns its data dict."""
    with _lock:
        if client_id:
            conn = _clients.get(client_id)
        else:
            conn = next((c for c in _clients.values() if c.alive), None)
    if not conn or not conn.alive:
        raise ProbeUnavailable("no probe client is connected")

    job_id = uuid.uuid4().hex
    slot = [threading.Event(), None]
    conn.pending[job_id] = slot
    try:
        conn.send({"type": "job", "id": job_id, "op": op, "payload": payload})
        if not slot[0].wait(timeout):
            raise ProbeTimeout(f"probe client did not answer '{op}' in {timeout}s")
        res = slot[1]
        if res is None:
            raise ProbeUnavailable("probe client disconnected mid-job")
        if not res.get("ok"):
            raise RuntimeError(res.get("error", "probe job failed"))
        return res.get("data", {})
    finally:
        conn.pending.pop(job_id, None)
