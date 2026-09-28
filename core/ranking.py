"""
AX-Scanner :: ranking.py

Combines stage-1 (fast filter, all candidates) and stage-2 (deep Reality
test, top ~50 only) into one final table.

Column meaning:
  Connect  -> stage-1 raw TCP+TLS reachability on this carrier
  Reality  -> only set for the subset that went through stage 2's real
              protocol test; blank ("-") for anything stage 2 didn't reach
  XHTTP    -> for the stage-2 subset: a REAL VLESS+Reality+XHTTP handshake
              from your carrier. For anything stage 2 didn't reach it is
              only a reachability estimate from stage 1 (TLS1.3 + h2),
              shown with a "~" prefix so it's never mistaken for a real
              protocol test.

Ranking priority (per spec): connects/not-blocked first, then stability
(success_rate), then latency.
"""

from core.config import FINAL_RESULT_COUNT


def _xhttp_verdict(stage1_row):
    if not stage1_row["connects"]:
        return "❌"
    if stage1_row["tls13"] and stage1_row["h2"] and stage1_row["success_rate"] >= 0.66:
        return "✅"
    return "⚠️"


def build_final_table(stage1_results, stage2_results):
    stage2_by_domain = {r["domain"]: r for r in stage2_results}

    rows = []
    for r in stage1_results:
        s2 = stage2_by_domain.get(r["domain"])
        if s2 is not None:
            reality_verdict = "✅" if s2.get("reality_ok") else "❌"
            reality_latency = s2.get("reality_latency_ms")
        else:
            reality_verdict = "-"
            reality_latency = None

        latency_display = (
            f"{r['avg_latency_ms']:.0f}ms" if r["avg_latency_ms"] is not None else "-"
        )
        reality_latency_display = (
            f"{reality_latency:.0f}ms" if reality_latency is not None else "-"
        )

        if s2 is not None and "xhttp_ok" in s2:
            xhttp_verdict = "✅" if s2["xhttp_ok"] else "❌"
        else:
            xhttp_verdict = "~" + _xhttp_verdict(r)

        rows.append({
            "domain": r["domain"],
            "connect": "✅" if r["connects"] else "❌",
            "reality": reality_verdict,
            "xhttp": xhttp_verdict,
            "latency": latency_display,
            "reality_latency": reality_latency_display,
            "_sort_connects": r["connects"],
            "_sort_success_rate": r["success_rate"],
            "_sort_latency": r["avg_latency_ms"] if r["avg_latency_ms"] is not None else float("inf"),
            "_sort_reality_ok": s2.get("reality_ok") if s2 else False,
            "_sort_xhttp_ok": s2.get("xhttp_ok") if s2 else False,
        })

    rows.sort(key=lambda r: (
        not r["_sort_connects"],
        not (r["_sort_reality_ok"] and r["_sort_xhttp_ok"]),
        not r["_sort_reality_ok"],
        not r["_sort_xhttp_ok"],
        -r["_sort_success_rate"],
        r["_sort_latency"],
    ))

    return rows[:FINAL_RESULT_COUNT]
