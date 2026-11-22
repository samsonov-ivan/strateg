"""Журнал действий projects/<slug>/state/journal.jsonl. T01."""
from __future__ import annotations

from strateg.lib import clock, ids, paths, store


def _stage(slug: str) -> str | None:
    p = paths.project_dir(slug) / "project.json"
    try:
        return store.read_json(p).get("stage") if p.exists() else None
    except Exception:
        return None


def log(slug: str, kind: str, summary: str, data: dict | None = None, actor: str = "cli",
        stage: str | None = None, op_id: str | None = None) -> dict:
    path = paths.state_path(slug, "journal")
    at = clock.now()
    data = data or {}
    op = op_id or ids.op_id(kind, {"summary": summary, "data": data, "at": at})
    with store.lock(path):
        recs = store.read_jsonl(path)
        for r in recs:
            if r.get("op_id") == op:
                return r
        ev = {"id": ids.next_in(recs, "E", 6), "at": at, "kind": kind, "stage": stage or _stage(slug),
              "actor": actor, "summary": summary, "data": data, "op_id": op}
        with open(path, "a", encoding="utf-8") as f:
            f.write(store._dumps(ev) + "\n")
    return ev


def read(slug: str, kind: str | None = None) -> list[dict]:
    recs = store.read_jsonl(paths.state_path(slug, "journal"))
    return [r for r in recs if kind is None or r.get("kind") == kind]
