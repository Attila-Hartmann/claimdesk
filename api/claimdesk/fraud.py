"""Claim fraud score: gradient-boosted trees on features from the extracted documents, the policy system and claim
history, with per-claim SHAP contributions (XGBoost's built-in TreeSHAP) so a handler sees *why* a claim is flagged.

The score only prioritises human investigation; it never rejects a claim (see docs: EU AI Act, human oversight).
"""

import json
from datetime import date, datetime

import joblib
import numpy as np

from claimdesk import store, synth, validate
from claimdesk.config import DATA, settings

BUNDLE = DATA / "models" / "fraud.joblib"
FEATURES = ["days_since_policy_start", "night_time", "repairer_risk", "invoice_vs_estimate", "claim_vs_vehicle_value", "prior_claims",
            "invalid_tax_number", "iban_other_claimants", "rule_issues"]
LABELS = {"days_since_policy_start": "Days between policy start and loss", "night_time": "Loss reported between 22:00 and 05:00",
          "repairer_risk": "Repairer's historical fraud rate", "invoice_vs_estimate": "Invoice ÷ claimant's own estimate",
          "claim_vs_vehicle_value": "Invoice ÷ vehicle value", "prior_claims": "Prior claims on the policy",
          "invalid_tax_number": "Invoice tax number fails its check digit", "iban_other_claimants": "Other claimants paid to the same IBAN",
          "rule_issues": "Other rule violations"}


def _features(docs: dict[str, dict], issues: list[dict], h: dict) -> list[float]:
    form, inv = docs.get("claim_form") or {}, docs.get("repair_invoice") or {}
    pol = h["policies"].get(form.get("policy_number", ""), {})
    try:
        loss = datetime.fromisoformat(form.get("loss_datetime", ""))
    except ValueError:
        loss = None
    start = date.fromisoformat(pol["start"]) if pol else None
    gross, est, value = inv.get("gross_total_huf") or 0, form.get("estimated_amount_huf") or 0, pol.get("vehicle_value_huf") or 0
    codes = [i["code"] for i in issues]
    return [
        (loss.date() - start).days if loss and start else 365.0,
        float(bool(loss) and (loss.hour >= 22 or loss.hour < 5)),
        h["shop_rate"].get(inv.get("seller_name", ""), h["base_rate"]),
        gross / est if est else 1.0,
        gross / value if value else 0.0,
        float(pol.get("prior_claims", 0)),
        float("tax_number_invalid" in codes),
        float(max(0, len(h["iban_claimants"].get(form.get("payout_iban", ""), [])) - 1)),
        float(sum(c not in ("tax_number_invalid",) for c in codes)),
    ]


def train() -> dict:
    import mlflow
    from sklearn.metrics import average_precision_score, roc_auc_score
    from xgboost import XGBClassifier

    claims = synth.generate(600)  # same seed as the corpus: the "historical book" of verified claims
    rows = [json.loads(line) for line in (DATA / "corpus" / "claims.jsonl").read_text(encoding="utf-8").splitlines()]
    split = {r["claim_id"]: r["split"] for r in rows}
    train_ids = {c.id for c in claims if split[c.id] != "test"}
    hist_train = [c for c in claims if c.id in train_ids]
    base = sum(c.fraud for c in hist_train) / len(hist_train)
    shops: dict[str, list[bool]] = {}
    for c in hist_train:
        shops.setdefault(c.shop, []).append(c.fraud)
    iban_claimants: dict[str, set[str]] = {}
    for c in claims:  # bank-account reuse is visible across the whole book, including today's claims
        iban_claimants.setdefault(c.payout_iban, set()).add(c.claimant)
    h = {"base_rate": base,
         "shop_rate": {s: (sum(v) + 5 * base) / (len(v) + 5) for s, v in shops.items()},  # smoothed target encoding
         "policies": {c.policy_number: {"start": c.policy_start.isoformat(), "vehicle_value_huf": c.vehicle_value_huf,
                                        "prior_claims": c.prior_claims} for c in claims},
         "iban_claimants": {k: sorted(v) for k, v in iban_claimants.items()}}

    def xy(cs):
        X, y = [], []
        for c in cs:
            docs = {d["type"]: d["fields"] for d in c.documents}
            issues = [i for t, f in docs.items() for i in validate.check_document(t, f)] + validate.check_claim(docs)
            X.append(_features(docs, issues, h))
            y.append(int(c.fraud))
        return np.array(X), np.array(y)

    Xtr, ytr = xy(hist_train)
    Xte, yte = xy([c for c in claims if c.id not in train_ids])
    params = {"n_estimators": 300, "max_depth": 3, "learning_rate": 0.05, "subsample": 0.9, "colsample_bytree": 0.9,
              "scale_pos_weight": float((ytr == 0).sum() / max(1, ytr.sum()))}
    model = XGBClassifier(**params, eval_metric="aucpr")
    model.fit(Xtr, ytr)
    p = model.predict_proba(Xte)[:, 1]
    top = np.argsort(-p)[: max(1, len(p) // 10)]
    metrics = {"roc_auc": roc_auc_score(yte, p), "pr_auc": average_precision_score(yte, p), "base_rate_test": float(yte.mean()),
               "precision_top10pct": float(yte[top].mean()), "recall_top10pct": float(yte[top].sum() / max(1, yte.sum())),
               "n_train": len(ytr), "n_test": len(yte)}
    BUNDLE.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"model": model, "history": h}, BUNDLE)
    mlflow.set_tracking_uri(settings().mlflow_tracking_uri)
    mlflow.set_experiment("fraud")
    with mlflow.start_run(run_name="xgboost"):
        mlflow.log_params(params)
        mlflow.log_metrics(metrics)
        mlflow.log_artifact(str(BUNDLE))
    return metrics


_cache: dict = {}


def score_claim(docs: dict[str, dict], issues: list[dict]) -> dict:
    """Probability-like score plus the top contributions (SHAP values in log-odds) behind it."""
    if "b" not in _cache:
        path = store.artifact(BUNDLE)
        if not path.exists() or not path.stat().st_size:
            return {"score": None, "reasons": []}
        _cache["b"] = joblib.load(path)
    model, h = _cache["b"]["model"], _cache["b"]["history"]
    x = np.array([_features(docs, issues, h)])
    from xgboost import DMatrix

    contrib = model.get_booster().predict(DMatrix(x, feature_names=FEATURES), pred_contribs=True)[0][:-1]
    order = np.argsort(-np.abs(contrib))[:4]
    return {"score": round(float(model.predict_proba(x)[0, 1]), 3),
            "reasons": [{"feature": FEATURES[i], "label": LABELS[FEATURES[i]], "value": round(float(x[0, i]), 3),
                         "impact": round(float(contrib[i]), 3)} for i in order if abs(contrib[i]) > 0.05]}
