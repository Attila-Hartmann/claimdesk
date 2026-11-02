"""Document-type classifier: TF-IDF character n-grams + logistic regression, tracked in MLflow.

Routing a page to the right extractor does not need an LLM. A linear model trained in seconds is cheaper, faster, and
easy to explain. Character n-grams survive OCR noise (lost accents, split words) better than word features.
"""

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.pipeline import Pipeline

from claimdesk import store
from claimdesk.config import DATA, settings

MODEL = DATA / "models" / "doc_classifier.joblib"


def train() -> dict:
    import mlflow

    from claimdesk import dataset  # training-only imports: the Lambda image ships without them

    tr, te = dataset.load("train"), dataset.load("test")
    params = {"analyzer": "char_wb", "ngram_range": (2, 4), "min_df": 2, "C": 4.0}
    pipe = Pipeline([("tfidf", TfidfVectorizer(analyzer=params["analyzer"], ngram_range=params["ngram_range"], min_df=params["min_df"],
                                               sublinear_tf=True)),
                     ("lr", LogisticRegression(C=params["C"], max_iter=2000))])
    pipe.fit([r["text"] for r in tr], [r["type"] for r in tr])
    pred = pipe.predict([r["text"] for r in te])
    truth = [r["type"] for r in te]
    scanned = [i for i, r in enumerate(te) if r["text_method"] == "ocr"]
    metrics = {"accuracy": accuracy_score(truth, pred), "macro_f1": f1_score(truth, pred, average="macro"),
               "accuracy_scans": accuracy_score([truth[i] for i in scanned], [pred[i] for i in scanned]),
               "n_train": len(tr), "n_test": len(te)}
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, MODEL)
    mlflow.set_tracking_uri(settings().mlflow_tracking_uri)
    mlflow.set_experiment("doc-classifier")
    with mlflow.start_run(run_name="tfidf-char-lr"):
        mlflow.log_params({k: str(v) for k, v in params.items()})
        mlflow.log_metrics(metrics)
        mlflow.log_text(str(classification_report(truth, pred, digits=3)), "classification_report.txt")
        mlflow.log_artifact(str(MODEL))
    return metrics


def predict(text: str) -> tuple[str, float]:
    pipe = _model()
    proba = pipe.predict_proba([text])[0]
    i = int(proba.argmax())
    return str(pipe.classes_[i]), float(proba[i])


_cache: dict[str, Pipeline] = {}


def _model() -> Pipeline:
    if "m" not in _cache:
        _cache["m"] = joblib.load(store.artifact(MODEL))
    return _cache["m"]
