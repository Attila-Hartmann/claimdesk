"""`python -m claimdesk.cli <command>`

corpus                 generate, render and OCR the synthetic corpus (data/corpus)
classifier | fraud     train and log the document classifier / fraud model to MLflow
seed [n]               load n held-out claims into the store and process them with the champion (showcase)
simulate [n]           replay n more held-out claims through the router; a simulated reviewer answers with ground truth
export [dir]           static snapshot of the API for the read-only demo
publish                upload model artifacts and eval summaries to the store (S3 on AWS)
"""

import json
import shutil
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from claimdesk import dataset, router, service, store
from claimdesk.config import ROOT


def _test_claims() -> dict[str, list[dict]]:
    by_claim: dict[str, list[dict]] = defaultdict(list)
    for r in dataset.load("test"):
        by_claim[r["claim_id"]].append(r)
    return dict(sorted(by_claim.items()))


def _load(ref: str, docs: list[dict]) -> str:
    files = [(d["file"], (dataset.CORPUS / "files" / d["file"]).read_bytes()) for d in sorted(docs, key=lambda d: d["doc_id"])]
    return service.create_claim(files, source="corpus", ref=ref)


def _used_refs() -> set[str]:
    return {(store.get_json(k) or {}).get("ref") for k in store.keys("claims/")}


def seed(n: int) -> None:
    claims = list(_test_claims().items())[:n]
    with ThreadPoolExecutor(6) as ex:
        list(ex.map(lambda kv: service.process(_load(*kv), model="champion"), claims))
    print(f"seeded {len(claims)} claims")


def simulate(n: int) -> None:
    used = _used_refs()
    todo = [(ref, docs) for ref, docs in _test_claims().items() if ref not in used][:n]

    def one(kv):
        ref, docs = kv
        cid = _load(ref, docs)
        c = service.process(cid)
        truth = sorted(docs, key=lambda d: d["doc_id"])
        for d, t in zip(c["documents"], truth, strict=True):
            service.review(cid, d["doc_id"], t["fields"], "simulated-reviewer", simulated=True)
        return [d["model"] for d in c["documents"]]

    with ThreadPoolExecutor(6) as ex:
        models = [m for ms in ex.map(one, todo) for m in ms]
    print(f"simulated {len(todo)} claims, {len(models)} documents:", {m: models.count(m) for m in set(models)})
    print(json.dumps(router.decide(), indent=1))


def export(out: Path) -> None:
    from claimdesk import main as api

    out.mkdir(parents=True, exist_ok=True)
    files = {"claims": api.claims(), "rollout": api.rollout(), "evals": api.evals()}
    for row in files["claims"]:
        c = api.claim(row["id"])
        files[f"claims-{row['id']}"] = c
        for d in c["documents"]:
            dst = out / d["file"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(store.path_for(d["file"]), dst)
    for name, data in files.items():
        (out / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"exported {len(files)} JSON files to {out}")


def main() -> None:
    cmd, *args = sys.argv[1:] or ["help"]
    if cmd == "corpus":
        dataset.build()
    elif cmd == "classifier":
        from claimdesk import classify

        print(classify.train())
    elif cmd == "fraud":
        from claimdesk import fraud

        print(fraud.train())
    elif cmd == "seed":
        seed(int(args[0]) if args else 24)
    elif cmd == "simulate":
        simulate(int(args[0]) if args else 60)
    elif cmd == "publish":
        from claimdesk import classify, fraud
        from claimdesk import main as api

        for p in (classify.MODEL, fraud.BUNDLE):
            store.put(f"artifacts/{p.name}", p.read_bytes(), "application/octet-stream")
        store.put_json("artifacts/evals.json", api.evals())
        print("published artifacts")
    elif cmd == "export":
        export(Path(args[0]) if args else ROOT / "web" / "public" / "demo")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()

