#!/usr/bin/env python3
"""
AX-Scanner — main entry point.

Everything is menu-driven on purpose: run this file, pick numbered
options, done. No flags to remember.

    python3 ax_scanner.py

The one exception is a hidden internal flag used only by the systemd unit
that runs the backend Agent in the background — that's plumbing, not
something you're expected to type yourself (see the "Setup Backend Agent"
menu option, which sets that up for you).
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core import ui, config, carriers, discovery, stage1_filter, stage2_reality
from core import ranking, xray_manager, probe_link, uninstall
from core import agent_server, probe_session
import json
import time
import urllib.request


def _internal_agent_daemon_entrypoint():
    # Invoked only by the systemd unit created in setup_agent(). Not a
    # user-facing command.
    port = int(sys.argv[2]) if len(sys.argv) > 2 else config.AGENT_DEFAULT_PORT
    broker_port = int(sys.argv[3]) if len(sys.argv) > 3 else port + 1
    agent_server.run(port, broker_port)


SYSTEMD_UNIT_TEMPLATE = """[Unit]
Description=AX-Scanner backend agent (isolated, unrelated to any panel)
After=network.target

[Service]
Type=simple
ExecStart={python_bin} {script_path} --agent-daemon {port} {broker_port}
Restart=on-failure
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
"""


def setup_agent():
    ui.info("This installs the backend Agent on THIS machine (run this on your "
            "target server, e.g. the Germany box the real configs live on).")
    config.ensure_dirs()

    if not xray_manager.is_installed():
        with ui.Spinner("Downloading isolated xray-core..."):
            try:
                xray_manager.install(ui)
            except Exception as e:
                ui.err(f"Failed to install xray-core: {e}")
                return
    else:
        ui.ok("Isolated xray-core already installed.")

    port_input = input(f" Agent port [{config.AGENT_DEFAULT_PORT}]: ").strip()
    port = int(port_input) if port_input else config.AGENT_DEFAULT_PORT
    bp_input = input(f" Probe-client port [{config.BROKER_DEFAULT_PORT}] "
                     "(443 is best if it's free): ").strip()
    broker_port = int(bp_input) if bp_input else config.BROKER_DEFAULT_PORT

    token = agent_server.get_or_create_token()
    with open(config.AGENT_INFO_PATH, "w") as f:
        json.dump({"port": port, "broker_port": broker_port}, f)

    script_path = os.path.abspath(__file__)
    unit_content = SYSTEMD_UNIT_TEMPLATE.format(
        python_bin=sys.executable, script_path=script_path, port=port, broker_port=broker_port
    )
    try:
        with open(config.SYSTEMD_UNIT_PATH, "w") as f:
            f.write(unit_content)
        os.system("systemctl daemon-reload")
        os.system(f"systemctl enable {config.SYSTEMD_UNIT_NAME}")
        os.system(f"systemctl restart {config.SYSTEMD_UNIT_NAME}")
        ui.ok("Agent installed and running as a background service.")
    except PermissionError:
        ui.err("Need root privileges to install the systemd service. Re-run with sudo.")
        return

    if os.system("command -v ufw >/dev/null 2>&1 && ufw status | grep -q 'Status: active'") == 0:
        ui.warn(f"ufw is active — allow the probe port:  ufw allow {broker_port}/tcp")
    print()
    show_probe_client_instructions()


def _server_ip():
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=5) as r:
            return r.read().decode().strip()
    except Exception:
        return "SERVER_IP"


def show_probe_client_instructions():
    """Menu option 2: everything needed to connect your own computer."""
    info = {"port": config.AGENT_DEFAULT_PORT, "broker_port": config.BROKER_DEFAULT_PORT}
    try:
        with open(config.AGENT_INFO_PATH) as f:
            info.update(json.load(f))
    except Exception:
        ui.err("The Agent isn't set up yet — run option 1 first.")
        return
    token = agent_server.get_or_create_token()
    ip = _server_ip()
    args = f"--server {ip} --port {info['broker_port']} --token {token}"

    ui.ok("Connect YOUR computer (the one on the carrier you want to measure).")
    print(f" Copy {ui.C.BOLD}probe_client.py{ui.C.RESET} from this project to that computer "
          "(it needs only Python 3.8+), then run ONCE:")
    print()
    print(f"   {ui.C.BOLD}Windows :{ui.C.RESET}  py probe_client.py {args}")
    print(f"   {ui.C.BOLD}Linux   :{ui.C.RESET}  python3 probe_client.py {args}")
    print()
    ui.info("Afterwards just run it without arguments. Keep it open while you test "
            "(or add:  --autostart on).")
    ui.info("Turn OFF any VPN / TUN-mode on that computer first — otherwise you'd "
            "be measuring the VPN, not your carrier.")
    print()
    try:
        clients = probe_session_clients()
    except Exception:
        clients = []
    if clients:
        for c in clients:
            ui.ok(f"Connected now: {c.get('name')} ({c.get('os')}) from {c['remote_ip']}")
    else:
        ui.info("No probe client connected yet.")


def probe_session_clients():
    from core.agent_client import AgentClient
    link = probe_session._local_link()
    if not link:
        return []
    return AgentClient(link["host"], link["port"], link["token"]).probe_clients()


def agent_status():
    os.system(f"systemctl status {config.SYSTEMD_UNIT_NAME} --no-pager")


def _run_pipeline(candidates, carrier, ui):
    where = "your computer" if probe_session.active() else "THIS SERVER (not your carrier!)"
    ui.info(f"Stage 1/2 — fast connectivity filter across {len(candidates)} candidates "
            f"on {carrier['label']}, executed from {where}...")
    stage1_results = stage1_filter.run_stage1(candidates, ui)

    connecting = [r for r in stage1_results if r["connects"]]
    ui.ok(f"{len(connecting)}/{len(candidates)} candidates connect on this network.")

    top_for_deep_test = connecting[: config.STAGE2_CANDIDATE_COUNT]
    stage2_results = (stage2_reality.run_stage2(top_for_deep_test, ui)
                      if top_for_deep_test else [])

    final_rows = ranking.build_final_table(stage1_results, stage2_results)

    columns = [
        ("domain", "Domain", 28),
        ("connect", "Connect", 7),
        ("reality", "Reality", 7),
        ("xhttp", "XHTTP", 5),
        ("latency", "Latency", 8),
        ("reality_latency", "R-Latency", 9),
    ]
    ui.print_results_table(
        f"🏆 Top {len(final_rows)} SNIs — {carrier['emoji']} {carrier['label']}",
        final_rows, columns,
    )
    _save_last_scan(carrier, final_rows, len(connecting), len(candidates))


LAST_SCAN_PATH = os.path.join(config.CACHE_DIR, "last_scan.json")


def _save_last_scan(carrier, rows, connecting, total):
    try:
        top = rows[0]["domain"] if rows else "-"
        with open(LAST_SCAN_PATH, "w") as f:
            json.dump({"carrier": carrier["label"], "when": time.strftime("%Y-%m-%d %H:%M"),
                       "pass": f"{connecting}/{total}", "top": top,
                       "from_probe": probe_session.active()}, f)
    except Exception:
        pass


def _collect_status():
    st = {"agent": "not installed", "agent_ok": False, "probe": "none", "probe_ok": False}
    if os.path.isfile(config.SYSTEMD_UNIT_PATH):
        active = os.popen(f"systemctl is-active {config.SYSTEMD_UNIT_NAME} 2>/dev/null").read().strip()
        st["agent"] = "running" if active == "active" else (active or "stopped")
        st["agent_ok"] = active == "active"
    try:
        cl = probe_session_clients()
        if cl:
            st["probe"] = ", ".join(f"{c.get('name')} ({c.get('os')})" for c in cl)
            st["probe_ok"] = True
    except Exception:
        pass
    try:
        with open(LAST_SCAN_PATH) as f:
            d = json.load(f)
        st["last_scan"] = f"{d['carrier']} · {d['when']} · {d['pass']} pass · top: {d['top']}"
    except Exception:
        pass
    return st


def _begin_test(carrier):
    if not probe_session.start(ui):
        return False
    return carriers.detect_and_confirm_carrier(carrier["key"], ui)


def run_auto_discover():
    carrier = carriers.choose_carrier(ui)
    if not _begin_test(carrier):
        ui.info("Aborted.")
        return
    candidates = discovery.discover_candidates(ui)
    _run_pipeline(candidates, carrier, ui)


def run_manual_input():
    carrier = carriers.choose_carrier(ui)
    if not _begin_test(carrier):
        ui.info("Aborted.")
        return

    print()
    print("   1) A single domain")
    print("   2) A comma-separated list")
    print("   3) A path to a .txt file (one domain per line)")
    choice = input(" > ").strip()

    candidates = []
    if choice == "1":
        candidates = [input(" Domain: ").strip()]
    elif choice == "2":
        raw = input(" Domains (comma-separated): ").strip()
        candidates = [d.strip() for d in raw.split(",") if d.strip()]
    elif choice == "3":
        path = input(" File path: ").strip()
        try:
            with open(path) as f:
                candidates = [line.strip() for line in f if line.strip()]
        except OSError as e:
            ui.err(f"Could not read file: {e}")
            return
    else:
        ui.err("Invalid choice.")
        return

    if not candidates:
        ui.err("No domains to test.")
        return

    ui.ok(f"Loaded {len(candidates)} domain(s) to test.")
    _run_pipeline(candidates, carrier, ui)


def main_menu():
    while True:
        print()
        print(f"   1) 🛠️   Setup / Manage Backend Agent  (run on your target server)")
        print(f"   2) 🔌  Connect my computer  (probe client — Windows / Linux)")
        print(f"   3) 🔎  Run Carrier SNI Test — Auto-discover")
        print(f"   4) 📋  Run Carrier SNI Test — Manual SNI input (single / list / .txt)")
        print(f"   5) 📈  Agent status")
        print(f"   6) 🗑️   Uninstall AX-Scanner completely")
        print(f"   7) 🚪  Exit")
        print()
        choice = input(" > ").strip()

        if choice == "1":
            setup_agent()
        elif choice == "2":
            show_probe_client_instructions()
        elif choice == "3":
            run_auto_discover()
        elif choice == "4":
            run_manual_input()
        elif choice == "5":
            agent_status()
        elif choice == "6":
            uninstall.run(ui)
            if not os.path.isdir(config.BASE_DIR):
                return
        elif choice == "7":
            print("Goodbye.")
            return
        else:
            ui.err("Invalid choice.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--agent-daemon":
        _internal_agent_daemon_entrypoint()
        return

    config.ensure_dirs()
    ui.print_banner(_collect_status())
    main_menu()


if __name__ == "__main__":
    main()
