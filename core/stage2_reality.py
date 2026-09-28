"""
AX-Scanner :: stage2_reality.py

Deep, real-protocol test, run on only the top ~50 domains that survived
stage 1 (config.STAGE2_CANDIDATE_COUNT) so the target server's IP isn't
hammered with hundreds of Reality handshakes.

Per candidate domain, for EACH transport (VLESS+Reality over TCP/Vision,
and VLESS+Reality over XHTTP):
  1. the Agent (on the server) spawns a temporary Reality server that
     uses this domain as its SNI/dest
  2. the probe client on YOUR computer starts an isolated xray client,
     connects to that server through your real carrier path, and fetches
     a tiny URL through it — proving the actual protocol works there
     (not just a bare TLS connect) and measuring real latency
  3. the temporary server is destroyed, success or failure

Nothing here runs on the server's own network: that would say nothing
about your carrier.
"""

from core import probe_session
from core.agent_client import AgentError
from core.config import REALITY_TEST_TIMEOUT

TRANSPORTS = ("tcp", "xhttp")


def _test_transport(domain, transport):
    agent = probe_session.agent()
    instance_id = None
    try:
        spawned = agent.spawn(domain, transport=transport)
        instance_id = spawned["instance_id"]
        data = probe_session.job("reality_probe", {
            "transport": transport,
            "sni": domain,
            "server_port": spawned["port"],
            "public_key": spawned["public_key"],
            "short_id": spawned["short_id"],
            "timeout": REALITY_TEST_TIMEOUT,
        }, timeout=REALITY_TEST_TIMEOUT * 3 + 20)
        return {"ok": bool(data.get("ok")), "latency_ms": data.get("latency_ms"),
                "error": data.get("error")}
    except AgentError as e:
        return {"ok": False, "latency_ms": None, "error": str(e)}
    finally:
        if instance_id:
            try:
                agent.destroy(instance_id)
            except AgentError:
                pass  # best effort; the Agent also cleans up orphans


def test_one(domain):
    tcp = _test_transport(domain, "tcp")
    xh = _test_transport(domain, "xhttp")
    return {
        "domain": domain,
        "reality_ok": tcp["ok"], "reality_latency_ms": tcp["latency_ms"],
        "xhttp_ok": xh["ok"], "xhttp_latency_ms": xh["latency_ms"],
        "error": tcp["error"] or xh["error"],
    }


def run_stage2(candidates, ui):
    if not probe_session.active():
        ui.warn("Deep Reality/XHTTP tests need a connected probe client (they only mean "
                "something from your own carrier). Skipped — showing stage-1 results only.")
        return []

    ui.info(f"Running deep Reality + XHTTP tests on the top {len(candidates)} candidates "
            "from your carrier (kept small on purpose to protect this server's IP)...")
    results = []
    for i, c in enumerate(candidates, 1):
        results.append(test_one(c["domain"]))
        ui.progress_bar(i, len(candidates))
    return results
