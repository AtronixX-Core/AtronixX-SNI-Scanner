"""
AX-Scanner :: stage1_filter.py

Stage 1 of the two-stage test engine. Runs from wherever the operator is
currently connected (i.e. through the real carrier's network path), so a
block/throttle by that carrier's DPI shows up right here.

For every candidate domain we do several independent TCP+TLS handshakes
to domain:443 and record: connect success, TLS version, ALPN, and latency.
Multiple passes exist purely for statistical stability, per spec.

When a probe client is connected (see probe_session.py) the whole
handshake series for a domain is executed ON THAT COMPUTER and only the
measured numbers come back, so latency is the real carrier-path latency
and a DPI block on your carrier shows up here. Without a probe client the
same code runs locally on this server (server-network results only).
"""

import concurrent.futures
import ssl
import time

from core import probe_session
from core.agent_client import AgentError
import socket
from core.config import (
    STAGE1_PASSES,
    STAGE1_MAX_CONCURRENCY,
    TCP_CONNECT_TIMEOUT,
    TLS_HANDSHAKE_TIMEOUT,
)


def _single_attempt(domain, port=443):
    t0 = time.perf_counter()
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_alpn_protocols(["h2", "http/1.1"])

        with socket.create_connection((domain, port), timeout=TCP_CONNECT_TIMEOUT) as sock:
            sock.settimeout(TLS_HANDSHAKE_TIMEOUT)
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                latency_ms = (time.perf_counter() - t0) * 1000
                return {
                    "ok": True,
                    "latency_ms": latency_ms,
                    "tls_version": ssock.version(),
                    "alpn": ssock.selected_alpn_protocol(),
                }
    except Exception as e:
        return {"ok": False, "error": type(e).__name__}


def _attempts_remote(domain, passes):
    budget = passes * (TCP_CONNECT_TIMEOUT + TLS_HANDSHAKE_TIMEOUT) + 10
    try:
        return probe_session.job("tls_probe", {
            "domain": domain, "port": 443, "passes": passes,
            "connect_timeout": TCP_CONNECT_TIMEOUT, "tls_timeout": TLS_HANDSHAKE_TIMEOUT,
        }, timeout=budget)["attempts"]
    except AgentError:
        return [{"ok": False, "error": "probe-unreachable"}] * passes


def test_domain(domain, passes=STAGE1_PASSES):
    if probe_session.active():
        attempts = _attempts_remote(domain, passes)
    else:
        attempts = [_single_attempt(domain) for _ in range(passes)]
    successes = [a for a in attempts if a["ok"]]
    success_rate = len(successes) / len(attempts) if attempts else 0.0

    avg_latency = (
        sum(a["latency_ms"] for a in successes) / len(successes)
        if successes else None
    )
    tls13 = any(a.get("tls_version") == "TLSv1.3" for a in successes)
    h2 = any(a.get("alpn") == "h2" for a in successes)

    return {
        "domain": domain,
        "connects": success_rate > 0,
        "success_rate": success_rate,
        "avg_latency_ms": avg_latency,
        "tls13": tls13,
        "h2": h2,
    }


def run_stage1(domains, ui):
    results = []
    total = len(domains)
    done = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=STAGE1_MAX_CONCURRENCY) as pool:
        futures = {pool.submit(test_domain, d): d for d in domains}
        for future in concurrent.futures.as_completed(futures):
            try:
                results.append(future.result())
            except Exception:
                results.append({"domain": futures[future], "connects": False,
                                 "success_rate": 0.0, "avg_latency_ms": None,
                                 "tls13": False, "h2": False})
            done += 1
            ui.progress_bar(done, total)

    # Rank: connects first, then success_rate, then latency (lower is better)
    def sort_key(r):
        latency = r["avg_latency_ms"] if r["avg_latency_ms"] is not None else float("inf")
        return (not r["connects"], -r["success_rate"], latency)

    results.sort(key=sort_key)
    return results
