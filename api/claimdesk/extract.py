"""Field extraction with any OpenAI-compatible model, plus field-level scoring against ground truth.

The champion (a frontier API model) gets the full JSON schema in its prompt. The challenger (the fine-tuned open-weight
model) learned the format in training, so it gets a one-line instruction: far fewer input tokens per document.
"""

import json
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from pydantic import ValidationError

from claimdesk.config import Endpoint, settings
from claimdesk.schemas import SCHEMAS

# USD per 1M tokens (input, cached input, output). Self-hosted models are costed from GPU time instead (see evals).
PRICES = {"deepseek-chat": (0.27, 0.07, 1.10), "gpt-4.1-mini": (0.40, 0.10, 1.60), "claude-haiku-4-5": (1.00, 0.10, 5.00),
          "claude-sonnet-4-5": (3.00, 0.30, 15.00)}

RULES = """You extract data from Hungarian motor-insurance claim documents for Kékhíd Biztosító. The text comes from a PDF
text layer or from OCR of a scan, so expect lost accents, broken lines and misread characters.
Rules: copy names, addresses and descriptions exactly as written, restoring Hungarian accents only where the word is
unambiguous; dates as YYYY-MM-DD (and YYYY-MM-DDTHH:MM for date-times); amounts as integers in HUF without spaces;
IBAN without spaces; registration numbers in upper case with a hyphen. Accident statements only: list just the ticked
boxes (marked X), each exactly as printed and prefixed with "A: " or "B: "; no other field gets a prefix.
Never invent a value: if a field is unreadable, return your best reading of the text."""


def system_prompt(doc_type: str, *, short: bool) -> str:
    if short:
        return f"Extract the {doc_type} fields as JSON."
    return f"{RULES}\n\nDocument type: {doc_type}. Respond with JSON only, matching this schema:\n{json.dumps(SCHEMAS[doc_type].model_json_schema())}"


@dataclass
class Result:
    model: str
    fields: dict | None
    error: str | None
    tokens_in: int
    tokens_out: int
    latency_ms: int
    cost_usd: float


_clients: dict[str, Any] = {}


def _bedrock(model: str, system: str, text: str) -> tuple[str, int, int]:
    """Amazon Bedrock Converse API (IAM auth, no API key). Use an EU inference profile (eu.anthropic...) for EU residency."""
    import boto3
    from botocore.config import Config

    # New accounts start with low Bedrock quotas: back off and retry instead of failing the document.
    client = _clients.setdefault("bedrock", boto3.client("bedrock-runtime", config=Config(retries={"mode": "adaptive", "max_attempts": 10})))
    r = client.converse(modelId=model, system=[{"text": system}], messages=[{"role": "user", "content": [{"text": text}]}],
                        inferenceConfig={"maxTokens": 1200, "temperature": 0})
    raw = r["output"]["message"]["content"][0]["text"].strip().removeprefix("```json").removesuffix("```")
    return raw, r["usage"]["inputTokens"], r["usage"]["outputTokens"]


def extract(ep: Endpoint, doc_type: str, text: str) -> Result:
    short = ep.model.startswith("claimdesk-")  # fine-tuned adapters learned the output format
    system = system_prompt(doc_type, short=short)
    t0 = time.perf_counter()
    if ep.base_url == "bedrock":
        raw, tin, tout = _bedrock(ep.model, system, text)
    else:
        # Self-hosted: fail fast (a cold GPU takes minutes) so the caller can fall back to the frontier API.
        timeout, retries = (25, 0) if short else (120, 2)
        client = _clients.setdefault(ep.name + ep.base_url, OpenAI(base_url=ep.base_url, api_key=ep.api_key, timeout=timeout, max_retries=retries))
        resp = client.chat.completions.create(
            model=ep.model, temperature=0, response_format={"type": "json_object"}, max_tokens=1200,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": text}])
        u = resp.usage
        tin, tout = (u.prompt_tokens, u.completion_tokens) if u else (0, 0)
        raw = resp.choices[0].message.content or ""
    ms = int((time.perf_counter() - t0) * 1000)
    p_in, _, p_out = next((p for k, p in PRICES.items() if k in ep.model), (0.0, 0.0, 0.0))
    cost = (tin * p_in + tout * p_out) / 1_000_000 if not short else settings().challenger_usd_per_1k_docs / 1000
    try:
        fields = SCHEMAS[doc_type].model_validate_json(raw).model_dump()
        return Result(ep.model, fields, None, tin, tout, ms, cost)
    except ValidationError as e:
        return Result(ep.model, None, f"invalid output: {e.errors()[:2]}", tin, tout, ms, cost)


def endpoint(name: str) -> Endpoint:
    """"champion" or "challenger" from settings, or a fine-tuned version by name (claimdesk-v1 → the vLLM server)."""
    if name.startswith(("claimdesk-", "qwen3-")):  # served by our vLLM server: fine-tuned adapters or the untuned base
        return settings().endpoint("challenger").model_copy(update={"model": name})
    return settings().endpoint(name)


# ── scoring ────────────────────────────────────────────────────────────────────────────────────────────────────

def _norm(v: Any) -> Any:
    if isinstance(v, str):
        return " ".join(v.split()).casefold()
    return v


def _flat(d: Any, prefix: str = "") -> dict[str, Any]:
    if isinstance(d, dict):
        out: dict[str, Any] = {}
        for k, v in d.items():
            out |= _flat(v, f"{prefix}{k}.")
        return out
    if isinstance(d, list) and d and isinstance(d[0], dict):
        out = {f"{prefix}count": len(d)}
        for i, v in enumerate(d):
            out |= _flat(v, f"{prefix}{i}.")
        return out
    if isinstance(d, list):
        return {prefix[:-1]: sorted(_norm(x) for x in d)}
    return {prefix[:-1]: _norm(d)}


def strip_accents(v: Any) -> Any:
    return "".join(ch for ch in unicodedata.normalize("NFD", v) if unicodedata.category(ch) != "Mn") if isinstance(v, str) else v


def score(truth: dict, got: dict | None) -> dict[str, bool]:
    """Per-field exact match (case and whitespace normalised). Line items are compared position by position."""
    t = _flat(truth)
    g = _flat(got or {})
    return {k: g.get(k) == v for k, v in t.items()}
