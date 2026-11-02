"""Tiny blob store: S3 when STORE_BUCKET is set (AWS), a local folder otherwise. Claims, files, router state and reviewer
feedback are all small JSON or binary objects, so object storage is the whole database for this workload."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from claimdesk.config import DATA, settings

LOCAL = DATA / "store"


@lru_cache
def _s3():
    import boto3

    return boto3.client("s3")


def put(key: str, body: bytes | str, content_type: str = "application/json") -> None:
    data = body.encode() if isinstance(body, str) else body
    if b := settings().store_bucket:
        _s3().put_object(Bucket=b, Key=key, Body=data, ContentType=content_type)
    else:
        p = LOCAL / key
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def get(key: str) -> bytes | None:
    if b := settings().store_bucket:
        try:
            return _s3().get_object(Bucket=b, Key=key)["Body"].read()
        except _s3().exceptions.NoSuchKey:
            return None
    p = LOCAL / key
    return p.read_bytes() if p.exists() else None


def keys(prefix: str) -> list[str]:
    if b := settings().store_bucket:
        out, token = [], None
        while True:
            kw: dict[str, Any] = {"Bucket": b, "Prefix": prefix} | ({"ContinuationToken": token} if token else {})
            page = _s3().list_objects_v2(**kw)
            out += [o["Key"] for o in page.get("Contents", [])]
            if not page.get("IsTruncated"):
                return out
            token = page["NextContinuationToken"]
    base = LOCAL / prefix
    root = base if base.is_dir() else base.parent
    return sorted(p.relative_to(LOCAL).as_posix() for p in root.rglob("*") if p.is_file() and p.relative_to(LOCAL).as_posix().startswith(prefix))


def put_json(key: str, obj: Any) -> None:
    put(key, json.dumps(obj, ensure_ascii=False, default=str))


def get_json(key: str) -> Any:
    raw = get(key)
    return json.loads(raw) if raw is not None else None


def artifact(local: Path) -> Path:
    """A published model or report: the local file in development, `artifacts/<name>` from the store on AWS."""
    if local.exists() or not settings().store_bucket:
        return local
    return path_for(f"artifacts/{local.name}")


def path_for(key: str) -> Path:
    """Local path of an object (downloads from S3 to /tmp when needed): OCR and PDF parsing want a file."""
    if not settings().store_bucket:
        return LOCAL / key
    p = Path("/tmp") / key
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(get(key) or b"")
    return p
