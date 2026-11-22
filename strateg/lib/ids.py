"""Идентификаторы и ключи идемпотентности. T01."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from strateg.lib import store

_SKIP = {"json", "project", "op_id", "handler", "group", "command"}


def next_id(path: Path, prefix: str, width: int = 3) -> str:
    rx = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    nums = [int(m.group(1)) for r in store.read_jsonl(path) if (m := rx.match(str(r.get("id", ""))))]
    return f"{prefix}-{(max(nums) + 1 if nums else 1):0{width}d}"


def next_in(items: list[dict], prefix: str, width: int = 3) -> str:
    """То же, что next_id, но по списку в памяти."""
    rx = re.compile(rf"^{re.escape(prefix)}-(\d+)$")
    nums = [int(m.group(1)) for r in items if (m := rx.match(str(r.get("id", ""))))]
    return f"{prefix}-{(max(nums) + 1 if nums else 1):0{width}d}"


def op_id(command: str, args: dict) -> str:
    clean = {k: v for k, v in args.items() if k not in _SKIP and v is not None}
    raw = command + json.dumps(clean, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def find_by_op_id(path: Path, op: str) -> dict | None:
    return next((r for r in store.read_jsonl(path) if r.get("op_id") == op), None)
