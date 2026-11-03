import json

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from claimdesk import router, service, store
from claimdesk.config import ROOT, settings

app = FastAPI(title="Claimdesk API", version="0.1.0")


@app.middleware("http")
async def only_via_cdn(request: Request, call_next):
    """On AWS the function URL is public; CloudFront adds a secret header, so direct calls are refused."""
    secret = settings().origin_secret
    if secret and request.headers.get("x-origin-verify") != secret:
        return Response(status_code=403)
    return await call_next(request)


def _reviews_allowed() -> None:
    if settings().reviews_readonly:
        raise HTTPException(403, "Reviews are switched off on the public demo so visitors cannot skew the rollout statistics.")


class Review(BaseModel):
    fields: dict
    reviewer: str = "demo-reviewer"


class Canary(BaseModel):
    challenger: str | None
    pct: int
    reason: str = "manual"


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "readonly": settings().reviews_readonly, "router": router.state()}


@app.get("/api/claims")
def claims() -> list[dict]:
    return service.list_claims()


@app.post("/api/claims", status_code=201)
async def upload(files: list[UploadFile]) -> dict:
    if not 1 <= len(files) <= 5:
        raise HTTPException(400, "send 1 to 5 files")
    blobs = [(f.filename or "doc.pdf", await f.read()) for f in files]
    if any(len(b) > 5_000_000 or not n.lower().endswith((".pdf", ".png", ".jpg", ".jpeg")) for n, b in blobs):
        raise HTTPException(400, "PDF or image files up to 5 MB")
    if service.uploads_today() >= settings().daily_upload_limit:
        raise HTTPException(429, "Daily demo limit reached. Explore the processed claims, or try again tomorrow.")
    cid = service.create_claim(blobs)
    if q := settings().queue_url:  # AWS: the worker Lambda processes it; the UI polls the claim
        import boto3

        boto3.client("sqs").send_message(QueueUrl=q, MessageBody=json.dumps({"claim_id": cid}))
        return store.get_json(f"claims/{cid}.json")
    return service.process(cid)


@app.get("/api/claims/{cid}")
def claim(cid: str) -> dict:
    c = store.get_json(f"claims/{cid}.json")
    if not c:
        raise HTTPException(404, "claim not found")
    return c


@app.get("/api/files/{cid}/{name}")
def file(cid: str, name: str) -> Response:
    body = store.get(f"files/{cid}/{name}")
    if body is None:
        raise HTTPException(404, "file not found")
    return Response(body, media_type="application/pdf" if name.endswith(".pdf") else "image/png")


@app.post("/api/claims/{cid}/documents/{doc_id}/review")
def review(cid: str, doc_id: str, r: Review) -> dict:
    _reviews_allowed()
    return service.review(cid, doc_id, r.fields, r.reviewer)


@app.get("/api/rollout")
def rollout() -> dict:
    stats = router.feedback_stats()
    return {"state": router.state(), "stats": stats, "decision": router.decide(apply=False, stats=stats)}


@app.post("/api/rollout")
def set_rollout(c: Canary) -> dict:
    _reviews_allowed()
    if not 0 <= c.pct <= 50:
        raise HTTPException(400, "canary share must be 0–50%")
    return router.set_canary(c.challenger, c.pct, c.reason)


@app.get("/api/evals")
def evals() -> dict:
    """Offline eval summaries: published to the store on AWS (artifacts/evals.json), read from evals/reports locally."""
    return store.get_json("artifacts/evals.json") or local_evals()


def local_evals() -> dict:
    reports = ROOT / "evals" / "reports"
    return {p.stem: json.loads(p.read_text(encoding="utf-8"))["summary"] for p in sorted(reports.glob("*.json"))}
