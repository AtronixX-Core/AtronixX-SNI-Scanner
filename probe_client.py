#!/usr/bin/env python3
"""
AX-Scanner :: probe_client.py   (by @AtronixX_Core — support @AtronixX_Support)

Run this on YOUR OWN computer (Windows or Linux) — the one that is really
connected through the carrier you want to measure. It dials OUT to your
AX-Scanner server and stays connected. From then on, when you start a test
from the server's menu, every test is executed HERE, on your real network:

  * TLS handshakes to candidate SNI domains  (does your carrier block them?)
  * real VLESS+Reality (TCP/Vision) and VLESS+Reality (XHTTP) handshakes to
    your server, through a private local xray-core copy
  * the public IP / ISP lookup (so the carrier is verified for real)

You never type any tunnel/proxy commands. Only Python 3.8+ is required —
no pip packages, no admin/root rights.

    First run (values are printed by the server's menu, option 2):
        python probe_client.py --server SERVER_IP --port 41081 --token TOKEN
    Every later run:
        python probe_client.py
    Optional: start automatically when you log in:
        python probe_client.py --autostart on        (off = disable)
    Remove EVERYTHING this tool ever put on your computer:
        python probe_client.py --uninstall
"""

import argparse
import atexit
import concurrent.futures
import json
import os
import platform
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import zipfile

VERSION = 2
PROBE_URL_HOST, PROBE_URL_PATH = "cp.cloudflare.com", "/generate_204"
XRAY_RELEASES_API = "https://api.github.com/repos/XTLS/Xray-core/releases/latest"
XHTTP_PATH = "/ax"

IS_WIN = os.name == "nt"
HOME = os.path.expanduser("~")
if IS_WIN:
    APP_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.join(HOME, "AppData", "Local")),
                           "AX-Scanner-Probe")
else:
    APP_DIR = os.path.join(HOME, ".ax-scanner-probe")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
BIN_DIR = os.path.join(APP_DIR, "bin")
RUN_DIR = os.path.join(APP_DIR, "run")
PID_PATH = os.path.join(APP_DIR, "probe.pid")
LOG_PATH = os.path.join(APP_DIR, "probe.log")
XRAY_PATH = os.path.join(BIN_DIR, "xray.exe" if IS_WIN else "xray")

SYSTEMD_UNIT_PATH = os.path.join(HOME, ".config", "systemd", "user", "ax-scanner-probe.service")
WIN_STARTUP_VBS = os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                               "Start Menu", "Programs", "Startup", "AX-Scanner-Probe.vbs")

if IS_WIN:
    os.system("")  # enables ANSI colors in the Windows console
R, G, Y, C, B, X = "\033[38;5;196m", "\033[38;5;46m", "\033[38;5;220m", "\033[38;5;51m", "\033[1m", "\033[0m"


def say(msg=""):
    print(msg, flush=True)


def ok(msg):
    say(f" {G}✔{X} {msg}")


def info(msg):
    say(f" {C}ℹ{X}  {msg}")


def warn(msg):
    say(f" {Y}⚠{X}  {msg}")


def err(msg):
    say(f" {R}✖{X} {msg}")


def banner():
    say(f"""{R}{B}
  ╔═╗ ╔╗ ╔╦╗ ╔═╗ ╦ ╦ ╦ ═╗ ╦ ═╗ ╦
  ╠═╣  ║   ║  ╠╦╝ ║ ║ ║ ╔╩╦╝ ╔╩╦╝
  ╩ ╩  ╩   ╩  ╩╚═ ╚═╝ ╩ ╩ ╚═ ╩ ╚═   {X}{R}[ PROBE CLIENT ]{X}
  {R}CHANNEL : @AtronixX_Core   |   SUPPORT : @AtronixX_Support{X}
""")


# ---------------------------------------------------------------- config

def load_config():
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def save_config(cfg):
    os.makedirs(APP_DIR, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f)
    try:
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------- VPN check

VPN_WORDS = ("tun", "tap", "wg", "ppp", "wintun", "wireguard", "openvpn", "vpn", "nekoray",
             "v2ray", "xray", "sing", "warp", "nord", "proton", "utun")


def detect_vpn_warnings():
    names = []
    try:
        if IS_WIN:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-NetAdapter | Where-Object Status -eq 'Up' | "
                 "ForEach-Object { $_.Name + ' | ' + $_.InterfaceDescription }"],
                capture_output=True, text=True, timeout=10,
                creationflags=0x08000000).stdout
            names = [l.strip() for l in out.splitlines() if l.strip()]
        elif os.path.isfile("/proc/net/dev"):
            with open("/proc/net/dev") as f:
                names = [l.split(":")[0].strip() for l in f.readlines()[2:]]
        else:
            out = subprocess.run(["ifconfig", "-l"], capture_output=True, text=True, timeout=5).stdout
            names = out.split()
    except Exception:
        return []
    hits = [n for n in names if any(w in n.lower() for w in VPN_WORDS)
            and not n.lower().startswith(("lo", "docker", "br-", "veth"))]
    if not hits:
        return []
    return [f"A VPN/TUN-like network adapter looks active on this computer: {', '.join(hits[:3])}. "
            "If it carries your traffic, the results describe THAT VPN, not your carrier. "
            "Disconnect it (and any 'TUN mode' in v2ray/Nekoray/Hiddify) before testing."]


# ---------------------------------------------------------------- xray-core

def _asset_name():
    m = platform.machine().lower()
    arm = m in ("aarch64", "arm64")
    if IS_WIN:
        return "Xray-windows-arm64-v8a.zip" if arm else "Xray-windows-64.zip"
    if sys.platform == "darwin":
        return "Xray-macos-arm64-v8a.zip" if arm else "Xray-macos-64.zip"
    return "Xray-linux-arm64-v8a.zip" if arm else "Xray-linux-64.zip"


def ensure_xray():
    """Downloads a private xray-core into our own folder (once). Returns path or None."""
    if os.path.isfile(XRAY_PATH):
        return XRAY_PATH
    try:
        os.makedirs(BIN_DIR, exist_ok=True)
        info("Downloading a private xray-core copy (first time only)...")
        with urllib.request.urlopen(XRAY_RELEASES_API, timeout=20) as r:
            rel = json.loads(r.read().decode())
        name = _asset_name()
        asset = next(a for a in rel["assets"] if a["name"] == name)
        zpath = os.path.join(BIN_DIR, "dl.zip")
        urllib.request.urlretrieve(asset["browser_download_url"], zpath)
        with zipfile.ZipFile(zpath) as z:
            member = "xray.exe" if IS_WIN else "xray"
            z.extract(member, BIN_DIR)
        os.remove(zpath)
        if not IS_WIN:
            os.chmod(XRAY_PATH, 0o755)
        ok("xray-core ready.")
        return XRAY_PATH
    except Exception as e:
        warn(f"Could not get xray-core ({e}). Reality/XHTTP tests will be unavailable. "
             f"You can place an xray binary manually at: {XRAY_PATH}")
        return None


_procs = []


def _cleanup_procs():
    for p in _procs:
        try:
            p.kill()
        except Exception:
            pass


atexit.register(_cleanup_procs)


# ---------------------------------------------------------------- jobs

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def op_env(_p):
    return {"os": f"{platform.system()} {platform.release()}", "python": platform.python_version(),
            "xray": os.path.isfile(XRAY_PATH), "warnings": detect_vpn_warnings()}


def op_http_get_json(p):
    with urllib.request.urlopen(p["url"], timeout=p.get("timeout", 5)) as r:
        return {"json": json.loads(r.read().decode())}


def op_tls_probe(p):
    domain, port = p["domain"], p.get("port", 443)
    attempts = []
    for _ in range(int(p.get("passes", 3))):
        t0 = time.perf_counter()
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            ctx.set_alpn_protocols(["h2", "http/1.1"])
            with socket.create_connection((domain, port), timeout=p.get("connect_timeout", 4)) as s:
                s.settimeout(p.get("tls_timeout", 5))
                with ctx.wrap_socket(s, server_hostname=domain) as ss:
                    attempts.append({"ok": True, "latency_ms": (time.perf_counter() - t0) * 1000,
                                     "tls_version": ss.version(),
                                     "alpn": ss.selected_alpn_protocol()})
        except Exception as e:
            attempts.append({"ok": False, "error": type(e).__name__})
    return {"attempts": attempts}


def _socks5_connect(port, host, dest_port, timeout):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.settimeout(timeout)
    s.sendall(b"\x05\x01\x00")
    if s.recv(2) != b"\x05\x00":
        raise RuntimeError("socks handshake failed")
    h = host.encode()
    s.sendall(b"\x05\x01\x00\x03" + bytes([len(h)]) + h + dest_port.to_bytes(2, "big"))
    head = b""
    while len(head) < 4:
        chunk = s.recv(4 - len(head))
        if not chunk:
            raise RuntimeError("socks closed")
        head += chunk
    if head[1] != 0:
        raise RuntimeError(f"socks error {head[1]}")
    need = {1: 6, 4: 18}.get(head[3])
    if need is None:
        need = s.recv(1)[0] + 2
    got = 0
    while got < need:
        got += len(s.recv(need - got))
    return s


def _client_config(p, server_host, local_port):
    user = {"id": "00000000-0000-0000-0000-000000000000", "encryption": "none"}
    ss = {"network": "tcp", "security": "reality",
          "realitySettings": {"serverName": p["sni"], "publicKey": p["public_key"],
                              "shortId": p["short_id"], "fingerprint": "chrome"}}
    if p["transport"] == "tcp":
        user["flow"] = "xtls-rprx-vision"
    else:
        ss["network"] = "xhttp"
        ss["xhttpSettings"] = {"path": XHTTP_PATH, "mode": "auto"}
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{"listen": "127.0.0.1", "port": local_port, "protocol": "socks",
                      "settings": {"udp": False}}],
        "outbounds": [{"protocol": "vless",
                       "settings": {"vnext": [{"address": server_host, "port": p["server_port"],
                                               "users": [user]}]},
                       "streamSettings": ss}],
    }


def op_reality_probe(p, server_host):
    xray = ensure_xray()
    if not xray:
        return {"ok": False, "error": "xray-core not available on the probe client"}
    timeout = p.get("timeout", 8)
    port = _free_port()
    os.makedirs(RUN_DIR, exist_ok=True)
    cfg_path = os.path.join(RUN_DIR, f"c-{uuid.uuid4().hex[:8]}.json")
    with open(cfg_path, "w") as f:
        json.dump(_client_config(p, server_host, port), f)
    kw = {"creationflags": 0x08000000} if IS_WIN else {}
    proc = subprocess.Popen([xray, "run", "-c", cfg_path], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, **kw)
    _procs.append(proc)
    try:
        deadline = time.time() + 5
        while time.time() < deadline:
            if proc.poll() is not None:
                return {"ok": False, "error": "local xray exited early"}
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.3).close()
                break
            except OSError:
                time.sleep(0.15)
        else:
            return {"ok": False, "error": "local xray did not start"}

        lats, last_err = [], None
        for _ in range(2):
            t0 = time.perf_counter()
            try:
                raw = _socks5_connect(port, PROBE_URL_HOST, 443, timeout)
                ctx = ssl.create_default_context()
                with ctx.wrap_socket(raw, server_hostname=PROBE_URL_HOST) as s:
                    s.sendall((f"GET {PROBE_URL_PATH} HTTP/1.1\r\nHost: {PROBE_URL_HOST}\r\n"
                               "Connection: close\r\n\r\n").encode())
                    status = s.recv(64).split(b"\r\n")[0]
                if b" 204" in status or b" 200" in status:
                    lats.append((time.perf_counter() - t0) * 1000)
                else:
                    last_err = "bad response"
            except Exception as e:
                last_err = type(e).__name__
        if lats:
            return {"ok": True, "latency_ms": sum(lats) / len(lats)}
        return {"ok": False, "error": last_err or "no response"}
    finally:
        try:
            proc.kill()
            proc.wait(timeout=3)
        except Exception:
            pass
        if proc in _procs:
            _procs.remove(proc)
        try:
            os.remove(cfg_path)
        except OSError:
            pass


def run_job(msg, server_host):
    op, p = msg["op"], msg.get("payload", {})
    try:
        if op == "env":
            data = op_env(p)
        elif op == "http_get_json":
            data = op_http_get_json(p)
        elif op == "tls_probe":
            data = op_tls_probe(p)
        elif op == "reality_probe":
            data = op_reality_probe(p, server_host)
        else:
            return {"type": "result", "id": msg["id"], "ok": False, "error": f"unknown op {op}"}
        return {"type": "result", "id": msg["id"], "ok": True, "data": data}
    except Exception as e:
        return {"type": "result", "id": msg["id"], "ok": False, "error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- connection

class Link:
    def __init__(self, cfg):
        self.cfg = cfg
        self.jobs_done = 0

    def session(self):
        raw = socket.create_connection((self.cfg["host"], self.cfg["port"]), timeout=10)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        tls = ctx.wrap_socket(raw)  # deliberately no SNI; auth is the token below
        wlock = threading.Lock()

        def send(obj):
            with wlock:
                tls.sendall((json.dumps(obj) + "\n").encode())

        send({"type": "hello", "token": self.cfg["token"], "client_id": self.cfg["client_id"],
              "name": self.cfg.get("name"), "os": f"{platform.system()} {platform.release()}",
              "version": VERSION})
        f = tls.makefile("rb")
        ack = json.loads(f.readline() or b"{}")
        if not ack.get("ok"):
            raise PermissionError("server rejected the token")
        tls.settimeout(50)
        ok(f"Connected to {self.cfg['host']}:{self.cfg['port']} — waiting for tests. "
           "Keep this window open.")

        stop = threading.Event()

        def heartbeat():
            while not stop.wait(15):
                try:
                    send({"type": "ping"})
                except OSError:
                    return

        threading.Thread(target=heartbeat, daemon=True).start()
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=48)

        def handle(msg):
            res = run_job(msg, self.cfg["host"])
            self.jobs_done += 1
            try:
                send(res)
            except OSError:
                pass
            print(f"\r {C}ℹ{X}  tests served: {self.jobs_done}   ", end="", flush=True)

        try:
            while True:
                line = f.readline()
                if not line:
                    raise ConnectionError("server closed the connection")
                msg = json.loads(line)
                if msg.get("type") == "job":
                    pool.submit(handle, msg)
        finally:
            stop.set()
            pool.shutdown(wait=False, cancel_futures=True)
            try:
                tls.close()
            except OSError:
                pass


def run(cfg):
    os.makedirs(RUN_DIR, exist_ok=True)
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))
    atexit.register(lambda: os.path.exists(PID_PATH) and os.remove(PID_PATH))

    for w in detect_vpn_warnings():
        warn(w)
    ensure_xray()

    link, backoff = Link(cfg), 2
    while True:
        try:
            link.session()
        except PermissionError as e:
            err(f"{e}. Check the token printed by the server (menu option 2).")
            return
        except KeyboardInterrupt:
            raise
        except Exception as e:
            say()
            warn(f"Disconnected ({type(e).__name__}: {e}). Reconnecting in {backoff}s...")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
            continue
        backoff = 2


# ---------------------------------------------------------------- autostart / uninstall

def set_autostart(enable):
    script = os.path.abspath(__file__)
    if IS_WIN:
        if enable:
            pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            pyw = pyw if os.path.isfile(pyw) else sys.executable
            os.makedirs(os.path.dirname(WIN_STARTUP_VBS), exist_ok=True)
            with open(WIN_STARTUP_VBS, "w") as f:
                f.write(f'CreateObject("WScript.Shell").Run """{pyw}"" ""{script}""", 0, False\n')
            ok("Will start automatically when you log in to Windows.")
        elif os.path.isfile(WIN_STARTUP_VBS):
            os.remove(WIN_STARTUP_VBS)
            ok("Autostart removed.")
        return
    if enable:
        os.makedirs(os.path.dirname(SYSTEMD_UNIT_PATH), exist_ok=True)
        with open(SYSTEMD_UNIT_PATH, "w") as f:
            f.write(f"[Unit]\nDescription=AX-Scanner probe client\nAfter=network-online.target\n\n"
                    f"[Service]\nExecStart={sys.executable} {script}\nRestart=always\nRestartSec=5\n\n"
                    "[Install]\nWantedBy=default.target\n")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "--user", "enable", "--now", "ax-scanner-probe.service"], check=False)
        ok("Will start automatically at login (systemd user service).")
    else:
        subprocess.run(["systemctl", "--user", "disable", "--now", "ax-scanner-probe.service"],
                       check=False, capture_output=True)
        if os.path.isfile(SYSTEMD_UNIT_PATH):
            os.remove(SYSTEMD_UNIT_PATH)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False, capture_output=True)
        ok("Autostart removed.")


def _our_xray_pids():
    """PIDs of xray processes that run from OUR private folder only —
    never touches any other xray (v2rayN, Nekoray, ...) on this computer."""
    pids = []
    try:
        if IS_WIN:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Get-Process xray -ErrorAction SilentlyContinue | Where-Object "
                 f"{{ $_.Path -like '{BIN_DIR}*' }} | ForEach-Object {{ $_.Id }}"],
                capture_output=True, text=True, timeout=15, creationflags=0x08000000).stdout
            pids = [int(x) for x in out.split() if x.isdigit()]
        elif os.path.isdir("/proc"):
            for d in os.listdir("/proc"):
                if d.isdigit():
                    try:
                        if os.readlink(f"/proc/{d}/exe").startswith(BIN_DIR):
                            pids.append(int(d))
                    except OSError:
                        pass
    except Exception:
        pass
    return pids


def _kill(pid):
    try:
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                           creationflags=0x08000000)
        else:
            os.kill(pid, 15)
    except Exception:
        pass


def uninstall():
    say(f"{Y}This removes everything AX-Scanner's probe client created on this computer:{X}")
    say(f"   • {APP_DIR}  (settings, private xray-core, logs)")
    say("   • the autostart entry (if you enabled one)")
    if input(" Type 'yes' to continue: ").strip().lower() != "yes":
        info("Cancelled.")
        return

    try:  # stop a running instance
        pid = int(open(PID_PATH).read().strip())
        if pid != os.getpid():
            _kill(pid)
    except Exception:
        pass
    for pid in _our_xray_pids():
        _kill(pid)
    time.sleep(1)

    set_autostart(False)

    def _onerr(fn, path, _exc):
        try:
            os.chmod(path, 0o700)
            fn(path)
        except OSError:
            pass

    if os.path.isdir(APP_DIR):
        shutil.rmtree(APP_DIR, onerror=_onerr)

    say()
    say(" Verification:")
    checks = [
        ("settings + xray-core folder removed", not os.path.exists(APP_DIR)),
        ("no leftover xray process from this tool", not _our_xray_pids()),
        ("autostart entry removed", not os.path.exists(SYSTEMD_UNIT_PATH)
         and not os.path.exists(WIN_STARTUP_VBS)),
    ]
    for label, good in checks:
        (ok if good else err)(label)
    if all(g for _, g in checks):
        ok("Nothing of AX-Scanner is left except this script file itself:")
    say(f"   {os.path.abspath(__file__)}   ← you can delete it now.")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="AX-Scanner probe client")
    ap.add_argument("--server")
    ap.add_argument("--port", type=int)
    ap.add_argument("--token")
    ap.add_argument("--name")
    ap.add_argument("--autostart", choices=["on", "off"])
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()

    if sys.stdout is None or sys.stdout.name is None:  # pythonw / autostart: log to file
        os.makedirs(APP_DIR, exist_ok=True)
        sys.stdout = sys.stderr = open(LOG_PATH, "a", buffering=1)
    else:
        banner()

    if a.uninstall:
        uninstall()
        return
    if a.autostart:
        if not load_config():
            err("Run once normally first so the settings are saved.")
            return
        set_autostart(a.autostart == "on")
        return

    cfg = load_config() or {}
    if a.server:
        cfg["host"] = a.server
    if a.port:
        cfg["port"] = a.port
    if a.token:
        cfg["token"] = a.token
    if not cfg.get("host"):
        cfg["host"] = input(" Server IP or hostname: ").strip()
    if not cfg.get("port"):
        cfg["port"] = int(input(" Broker port [41081]: ").strip() or 41081)
    if not cfg.get("token"):
        cfg["token"] = input(" Token: ").strip()
    cfg.setdefault("client_id", uuid.uuid4().hex)
    cfg["name"] = a.name or cfg.get("name") or socket.gethostname()
    save_config(cfg)

    try:
        run(cfg)
    except KeyboardInterrupt:
        say()
        info("Stopped. (Run with --uninstall to remove everything.)")


if __name__ == "__main__":
    main()
