"""Score an extraction model on the held-out test documents and log the run to MLflow.

`python -m claimdesk.evaluate champion|challenger [--limit N]` → evals/reports/<name>.json (per-document results +
summary). The same summary drives the promotion decision for a fine-tuned model.
"""

import argparse
import json
import statistics
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import mlflow

from claimdesk import dataset, extract
from claimdesk.config import ROOT, settings

REPORTS = ROOT / "evals" / "reports"


def run_one(ep, r: dict) -> dict:
    try:
        res = extract.extract(ep, r["type"], r["text"])
    except Exception as e:  # network or server failure counts as a miss, not a crash
        return {"doc_id": r["doc_id"], "type": r["type"], "text_method": r["text_method"], "error": str(e)[:200], "checks": {},
                "latency_ms": 0, "cost_usd": 0.0, "tokens_in": 0, "tokens_out": 0}
    checks = extract.score(r["fields"], res.fields)
    return {"doc_id": r["doc_id"], "type": r["type"], "text_method": r["text_method"], "error": res.error, "checks": checks,
            "got": res.fields, "latency_ms": res.latency_ms, "cost_usd": res.cost_usd, "tokens_in": res.tokens_in, "tokens_out": res.tokens_out}


def summarise(results: list[dict]) -> dict:
    def field_acc(rows: list[dict]) -> float:
        checks = [v for r in rows for v in r["checks"].values()]
        return sum(checks) / len(checks) if checks else 0.0

    groups: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        groups[r["type"]].append(r)
        groups[r["text_method"]].append(r)
    lat = sorted(r["latency_ms"] for r in results if r["latency_ms"])
    return {
        "docs": len(results),
        "field_accuracy": field_acc(results),
        "doc_exact": sum(bool(r["checks"]) and all(r["checks"].values()) for r in results) / len(results),
        "valid_json": sum(r["error"] is None for r in results) / len(results),
        "by_group": {k: round(field_acc(v), 4) for k, v in sorted(groups.items())},
        "tokens_in_avg": statistics.mean(r["tokens_in"] for r in results),
        "tokens_out_avg": statistics.mean(r["tokens_out"] for r in results),
        "cost_per_1k_docs_usd": 1000 * statistics.mean(r["cost_usd"] for r in results),
        "p50_ms": lat[len(lat) // 2] if lat else None,
        "p95_ms": lat[int(len(lat) * 0.95)] if lat else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("endpoint", help="champion | challenger | claimdesk-<version>")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    ep = extract.endpoint(a.endpoint)
    docs = dataset.load("test")[: a.limit]
    with ThreadPoolExecutor(a.workers) as ex:
        results = list(ex.map(lambda r: run_one(ep, r), docs))
    summary = {"endpoint": a.endpoint, "model": ep.model, "at": datetime.now(UTC).isoformat(timespec="seconds")} | summarise(results)
    REPORTS.mkdir(parents=True, exist_ok=True)
    name = ep.model if a.endpoint.startswith("claimdesk-") else a.endpoint
    (REPORTS / f"{name}.json").write_text(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1), encoding="utf-8")
    mlflow.set_tracking_uri(settings().mlflow_tracking_uri)
    mlflow.set_experiment("extraction")
    with mlflow.start_run(run_name=f"{a.endpoint}:{ep.model}"):
        mlflow.log_params({"endpoint": a.endpoint, "model": ep.model, "docs": len(docs)})
        mlflow.log_metrics({k: v for k, v in summary.items() if isinstance(v, int | float) and v is not None}
                           | {f"acc_{k}": v for k, v in summary["by_group"].items()})
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
