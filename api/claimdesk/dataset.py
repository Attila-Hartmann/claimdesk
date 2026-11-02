"""Build the corpus once: generate claims, render documents, OCR them, split by claim. Everything downstream reads
data/corpus/docs.jsonl (one line per document: ids, type, split, file, text, ground-truth fields)."""

import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from claimdesk import ocr, render, synth
from claimdesk.config import DATA

CORPUS = DATA / "corpus"
DOCS = CORPUS / "docs.jsonl"
CLAIMS = CORPUS / "claims.jsonl"


def build(n_claims: int = 600, seed: int = 7) -> None:
    claims = synth.generate(n_claims, seed)
    manifest = CORPUS / "files" / "manifest.jsonl"
    if not manifest.exists():  # rendering ~1,400 documents takes a while; OCR can be redone on its own
        manifest = render.render_all(claims, CORPUS / "files")
    rows = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines()]
    rng = random.Random(seed)
    split = {c.id: rng.choices(["train", "val", "test"], weights=[70, 10, 20])[0] for c in claims}

    def with_text(r: dict) -> dict:
        r["text"], r["text_method"] = ocr.text_of(CORPUS / "files" / r["file"])
        r["split"] = split[r["claim_id"]]
        return r

    with ThreadPoolExecutor(6) as ex:  # Tesseract is a separate process per call, so threads parallelise fine
        rows = list(ex.map(with_text, rows))
    DOCS.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    CLAIMS.write_text("".join(json.dumps({
        "claim_id": c.id, "split": split[c.id], "fraud": c.fraud, "signals": c.signals, "lang": c.lang,
        "policy_start": c.policy_start.isoformat(), "vehicle_value_huf": c.vehicle_value_huf, "shop": c.shop,
        "prior_claims": c.prior_claims, "loss_kind": c.loss_kind}, ensure_ascii=False) + "\n" for c in claims), encoding="utf-8")


def load(split: str | None = None, path: Path = DOCS) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    return [r for r in rows if split is None or r["split"] == split]
