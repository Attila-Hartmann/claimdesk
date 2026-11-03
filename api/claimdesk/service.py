"""Claim lifecycle: files in → per document: text, type, extraction (champion or canary challenger), rule checks →
claim-level checks and fraud score → human review → feedback that drives the canary decision."""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from claimdesk import router, store, validate

# OCR, the classifier, XGBoost and the model clients load on first use: listing claims should not pay for them on a cold start.


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def create_claim(files: list[tuple[str, bytes]], *, source: str = "upload", ref: str | None = None) -> str:
    cid = f"CL-{uuid.uuid4().hex[:8].upper()}"
    docs = []
    for i, (name, body) in enumerate(files, 1):
        key = f"files/{cid}/{i}{name[name.rfind('.'):].lower()}"
        store.put(key, body, "application/pdf" if name.lower().endswith(".pdf") else "image/png")
        docs.append({"doc_id": f"{cid}-{i}", "file": key, "name": name})
    store.put_json(f"claims/{cid}.json", {"id": cid, "ref": ref, "source": source, "received_at": _now(), "status": "new", "documents": docs})
    return cid


def _process_doc(d: dict, model: str | None) -> None:
    from claimdesk import classify, extract, ocr

    t0 = time.perf_counter()
    d["text"], d["text_method"] = ocr.text_of(store.path_for(d["file"]))
    d["ocr_ms"] = int((time.perf_counter() - t0) * 1000)
    d["type"], d["type_confidence"] = classify.predict(d["text"])
    d["model"] = model or router.pick()
    try:
        r = extract.extract(extract.endpoint(d["model"]), d["type"], d["text"])
    except Exception as e:  # self-hosted model cold or down: the frontier API keeps the queue moving
        if d["model"] == "champion":
            raise
        d["fallback_from"], d["fallback_reason"], d["model"] = d["model"], str(e)[:200], "champion"
        r = extract.extract(extract.endpoint("champion"), d["type"], d["text"])
    d |= {"fields": r.fields, "error": r.error, "latency_ms": r.latency_ms, "cost_usd": r.cost_usd, "tokens_in": r.tokens_in,
          "tokens_out": r.tokens_out, "served_by": r.model}
    d["issues"] = validate.check_document(d["type"], r.fields or {})


def process(cid: str, model: str | None = None) -> dict:
    c = store.get_json(f"claims/{cid}.json")
    with ThreadPoolExecutor(4) as ex:  # documents are independent: OCR and model calls overlap
        list(ex.map(lambda d: _process_doc(d, model), c["documents"]))
    from claimdesk import fraud

    by_type = {d["type"]: d["fields"] for d in c["documents"] if d.get("fields")}
    c["claim_issues"] = validate.check_claim(by_type)
    c["fraud"] = fraud.score_claim(by_type, c["claim_issues"] + [i for d in c["documents"] for i in d["issues"]])
    c["status"] = "review"
    c["processed_at"] = _now()
    store.put_json(f"claims/{cid}.json", c)
    return c


def review(cid: str, doc_id: str, fields: dict, reviewer: str, *, simulated: bool = False) -> dict:
    """Store the reviewer's final fields; every field the model got right counts as accepted for that model."""
    c = store.get_json(f"claims/{cid}.json")
    d = next(x for x in c["documents"] if x["doc_id"] == doc_id)
    from claimdesk import extract

    checks = extract.score(fields, d.get("fields"))
    d["review"] = {"fields": fields, "reviewer": reviewer, "at": _now(), "accepted": sum(checks.values()), "total": len(checks),
                   "corrected": [k for k, ok in checks.items() if not ok], "simulated": simulated}
    if all("review" in x for x in c["documents"]):
        c["status"] = "approved"
    store.put_json(f"claims/{cid}.json", c)
    store.put_json(f"feedback/{doc_id}.json", {"model": d["model"], "fields": len(checks), "accepted": sum(checks.values()),
                                               "cost_usd": d.get("cost_usd", 0.0), "latency_ms": d.get("latency_ms", 0), "type": d["type"],
                                               "simulated": simulated})
    return {"review": d["review"], "router": router.decide()}


def uploads_today() -> int:
    today = datetime.now(UTC).date().isoformat()
    return sum(1 for c in store.get_json_many("claims/") if c["source"] == "upload" and c["received_at"].startswith(today))


def list_claims() -> list[dict]:
    out = []
    for c in store.get_json_many("claims/"):
        out.append({k: c.get(k) for k in ("id", "ref", "status", "received_at", "processed_at")}
                   | {"docs": len(c["documents"]), "fraud": (c.get("fraud") or {}).get("score"),
                      "issues": len(c.get("claim_issues") or []) + sum(len(d.get("issues") or []) for d in c["documents"]),
                      "models": sorted({d.get("model") for d in c["documents"] if d.get("model")})})
    return sorted(out, key=lambda x: x["received_at"], reverse=True)
