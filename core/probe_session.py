"""
AX-Scanner :: probe_session.py

Decides, once per test run, WHERE the carrier-path tests execute:

  * on the probe client running on your own computer (the accurate way —
    tests really leave through your carrier), or
  * on this server itself (only as an explicitly-confirmed fallback; the
    results then describe the SERVER's network, not your carrier).

Everything that needs the answer (stage 1, stage 2, ISP detection) asks
this module instead of opening sockets on its own.
"""

import json
import os

from core import probe_link
from core.agent_client import AgentClient, AgentError
from core.config import AGENT_INFO_PATH, AGENT_DEFAULT_PORT, BASE_DIR

_agent = None
_remote = False
_client_info = None


def agent():
    return _agent


def active():
    """True when tests run on the probe client (your own computer)."""
    return _remote


def client_info():
    return _client_info


def _local_link():
    token_path = os.path.join(BASE_DIR, "agent.token")
    if not os.path.isfile(token_path):
        return None
    port = AGENT_DEFAULT_PORT
    try:
        with open(AGENT_INFO_PATH) as f:
            port = json.load(f).get("port", port)
    except Exception:
        pass
    return {"host": "127.0.0.1", "port": port, "token": open(token_path).read().strip()}


def job(op, payload, timeout=15):
    return _agent.probe_job(op, payload, timeout=timeout)


def start(ui):
    """Connects to the Agent, looks for a probe client. Returns True to go on."""
    global _agent, _remote, _client_info
    _agent, _remote, _client_info = None, False, None

    link = _local_link() or probe_link.get_or_prompt(ui)
    agent = AgentClient(link["host"], link["port"], link["token"])
    try:
        agent.health()
    except AgentError as e:
        ui.err(f"Cannot reach the backend Agent at {link['host']}:{link['port']} ({e}). "
               "Set it up first (menu option 1).")
        return False
    _agent = agent

    try:
        clients = agent.probe_clients()
    except AgentError:
        clients = []

    if clients:
        c = clients[0]
        _remote, _client_info = True, c
        ui.ok(f"Probe client connected: {c.get('name') or c['client_id'][:8]} "
              f"({c.get('os')}) — tests will run from ITS network.")
        try:
            env = agent.probe_job("env", {}, timeout=15)
            for w in env.get("warnings", []):
                ui.warn(w)
        except AgentError:
            pass
        return True

    ui.warn("No probe client is connected. On your own computer (the one on the "
            "carrier you want to measure) start probe_client.py — see menu option 2.")
    ui.warn("If you continue now, tests run on THIS SERVER's network, so results "
            "say nothing about your carrier.")
    if input(" Continue anyway with basic server-side stage 1 only? [y/N]: ").strip().lower() != "y":
        return False
    return True
