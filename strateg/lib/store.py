"""Хранилище JSON/JSONL: атомарная запись, блокировки, история. T01."""
from __future__ import annotations

import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from strateg.lib import clock
from strateg.lib.out import CliError

LOCK_WAIT_S = 5.0
LOCK_STALE_S = 30.0


def _dumps(obj: Any, indent: int | None = None) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=indent, default=str)


@contextmanager
def lock(path: Path) -> Iterator[None]:
    """Блокировка через файл <path>.lock (O_CREAT|O_EXCL). Ждать до 5 с; старше 30 с — брошена."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lp = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + LOCK_WAIT_S
    while True:
        try:
            fd = os.open(lp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lp.stat().st_mtime > LOCK_STALE_S:
                    lp.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() > deadline:
                raise CliError("IO_ERROR", f"Файл занят другим процессом: {path.name}") from None
            time.sleep(0.01)
    try:
        yield
    finally:
        lp.unlink(missing_ok=True)


def read_jsonl(path: Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    recs = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            recs.append(json.loads(line))
        except json.JSONDecodeError:
            raise CliError("IO_ERROR", f"Повреждена строка {n} в {path.name}", {"line": n, "file": str(path)}) from None
    return recs


def append_jsonl(path: Path, rec: dict) -> None:
    path = Path(path)
    with lock(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(_dumps(rec) + "\n")
            f.flush()
            os.fsync(f.fileno())


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def rewrite_jsonl(path: Path, recs: list[dict]) -> None:
    path = Path(path)
    with lock(path):
        _atomic_write(path, "".join(_dumps(r) + "\n" for r in recs))


def read_json(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        raise CliError("NOT_FOUND", f"Файл не найден: {path.name}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        raise CliError("IO_ERROR", f"Повреждён JSON: {path.name}") from None


def write_json(path: Path, obj: dict) -> None:
    path = Path(path)
    with lock(path):
        _atomic_write(path, _dumps(obj, indent=2) + "\n")


def apply_patch(rec: dict, patch: dict, reason: str, actor: str) -> list[str]:
    """Применить patch к записи в памяти, дописать history. Возвращает изменённые поля."""
    changed = []
    at = clock.now()
    for field, new in patch.items():
        old = rec.get(field)
        if old == new and field in rec:
            continue
        rec[field] = new
        rec.setdefault("history", []).append(
            {"at": at, "field": field, "old": old, "new": new, "reason": reason, "actor": actor})
        changed.append(field)
    if changed and "updated_at" in rec:
        rec["updated_at"] = at
    return changed


def update_record(path: Path, rec_id: str, patch: dict, reason: str, actor: str) -> dict:
    path = Path(path)
    with lock(path):
        recs = read_jsonl(path)
        for rec in recs:
            if rec.get("id") == rec_id:
                apply_patch(rec, patch, reason, actor)
                _atomic_write(path, "".join(_dumps(r) + "\n" for r in recs))
                return rec
    raise CliError("NOT_FOUND", f"{rec_id} не найден")
