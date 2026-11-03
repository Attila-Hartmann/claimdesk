"""Canary routing between the champion (frontier API) and a challenger (fine-tuned adapter), with online evaluation.

Every reviewed document is a labelled example: for each extracted field the reviewer either accepted it or corrected it.
The router compares field acceptance rates of the two models with a two-proportion z-test and recommends (or, with
auto mode on, applies) promote / rollback. Thresholds are deliberately conservative: a regression must be visible to
roll back, an improvement must be significant to promote.
"""

import math
import random
from datetime import UTC, datetime

from claimdesk import store

STATE = "router/state.json"
DEFAULT = {"champion": "champion", "challenger": None, "canary_pct": 0, "auto": True, "history": []}
MIN_FIELDS = 300  # per model before any decision


def state() -> dict:
    return store.get_json(STATE) or dict(DEFAULT)


def save(s: dict) -> None:
    store.put_json(STATE, s)


def pick(rng: random.Random | None = None) -> str:
    """Model for the next document: the challenger for canary_pct % of traffic, otherwise the champion."""
    s = state()
    if s["challenger"] and (rng or random).random() * 100 < s["canary_pct"]:
        return s["challenger"]
    return s["champion"]


def set_canary(challenger: str | None, pct: int, reason: str) -> dict:
    s = state()
    s |= {"challenger": challenger, "canary_pct": pct}
    s["history"].append({"at": datetime.now(UTC).isoformat(timespec="seconds"), "action": "canary", "challenger": challenger, "pct": pct,
                         "reason": reason})
    save(s)
    return s


def feedback_stats() -> dict[str, dict]:
    """Field acceptance per model from reviewer feedback objects."""
    out: dict[str, dict] = {}
    for fb in store.get_json_many("feedback/"):
        m = out.setdefault(fb["model"], {"docs": 0, "fields": 0, "accepted": 0, "cost_usd": 0.0, "latency_ms": 0})
        m["docs"] += 1
        m["fields"] += fb["fields"]
        m["accepted"] += fb["accepted"]
        m["cost_usd"] += fb.get("cost_usd", 0.0)
        m["latency_ms"] += fb.get("latency_ms", 0)
    for m in out.values():
        m["acceptance"] = m["accepted"] / m["fields"] if m["fields"] else None
        m["cost_per_1k_docs_usd"] = 1000 * m["cost_usd"] / m["docs"] if m["docs"] else None
        m["avg_latency_ms"] = m["latency_ms"] // m["docs"] if m["docs"] else None
    return out


def z_test(a_ok: int, a_n: int, b_ok: int, b_n: int) -> float:
    """z for (rate_b - rate_a); positive means b is better."""
    p = (a_ok + b_ok) / (a_n + b_n)
    se = math.sqrt(p * (1 - p) * (1 / a_n + 1 / b_n)) or 1e-9
    return (b_ok / b_n - a_ok / a_n) / se


def decide(apply: bool = True, stats: dict[str, dict] | None = None) -> dict:
    """Recommendation for the current canary; applied when `apply` and state.auto are both on."""
    s, stats = state(), stats or feedback_stats()
    ch = s["challenger"]
    if not ch:
        return {"action": "none", "reason": "no challenger in canary"}
    a, b = stats.get(s["champion"]), stats.get(ch)
    if not a or not b or min(a["fields"], b["fields"]) < MIN_FIELDS:
        return {"action": "wait", "reason": f"need {MIN_FIELDS} reviewed fields per model"}
    z = z_test(a["accepted"], a["fields"], b["accepted"], b["fields"])
    if z < -2.0:
        verdict = {"action": "rollback", "z": z, "reason": f"challenger acceptance {b['acceptance']:.1%} vs {a['acceptance']:.1%} (z={z:.1f})"}
    elif z > -0.5 and b["fields"] >= 3 * MIN_FIELDS:
        verdict = {"action": "promote", "z": z, "reason": f"challenger not worse: {b['acceptance']:.1%} vs {a['acceptance']:.1%} (z={z:.1f}), "
                                                          f"cost {b['cost_per_1k_docs_usd']:.2f} vs {a['cost_per_1k_docs_usd']:.2f} USD/1k docs"}
    else:
        verdict = {"action": "wait", "z": z, "reason": "difference not conclusive yet"}
    if apply and s["auto"] and verdict["action"] in ("rollback", "promote"):
        s["history"].append({"at": datetime.now(UTC).isoformat(timespec="seconds"), "action": verdict["action"], "challenger": ch,
                             "reason": verdict["reason"], "auto": True})
        if verdict["action"] == "promote":
            s["champion"] = ch
        s["challenger"], s["canary_pct"] = None, 0
        save(s)
    return verdict
