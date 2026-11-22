"""Общие помощники обработчиков команд."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from strateg.lib import ids, journal, paths, schema, store
from strateg.lib.out import CliError

ORDER = ["S0", "S1", "S2", "S3", "S4", "S5"]
ARG_SKIP = {"json", "project", "op_id", "handler", "group", "command"}


def slug_of(args: argparse.Namespace) -> str:
    return paths.current_slug(getattr(args, "project", None))


def project_file(slug: str) -> Path:
    return paths.project_dir(slug) / "project.json"


def load_project(slug: str) -> dict:
    return store.read_json(project_file(slug))


def save_project(slug: str, proj: dict) -> None:
    store.write_json(project_file(slug), proj)


def reg(slug: str, name: str) -> Path:
    return paths.state_path(slug, name)


def records(slug: str, name: str) -> list[dict]:
    return store.read_jsonl(reg(slug, name))


def by_id(slug: str, name: str) -> dict[str, dict]:
    return {r["id"]: r for r in records(slug, name)}


def get(slug: str, name: str, rec_id: str) -> dict:
    rec = by_id(slug, name).get(rec_id)
    if rec is None:
        raise CliError("NOT_FOUND", f"{rec_id} не найден")
    return rec


def split_ids(value: str | None) -> list[str]:
    if not value:
        return []
    out: list[str] = []
    for x in value.replace(";", ",").split(","):
        x = x.strip()
        if x and x not in out:
            out.append(x)
    return out


def args_dict(args: argparse.Namespace) -> dict[str, Any]:
    return {k: v for k, v in vars(args).items() if k not in ARG_SKIP}


def op_for(args: argparse.Namespace, command: str) -> str:
    return getattr(args, "op_id", None) or ids.op_id(command, args_dict(args))


def stage_of(slug: str) -> str:
    return load_project(slug).get("stage", "S0")


def stage_index(stage: str | None) -> int:
    return ORDER.index(stage) if stage in ORDER else 0


def check_schema(rec: dict, name: str) -> None:
    errs = schema.validate(rec, name)
    if errs:
        raise CliError("RULE_VIOLATION", "Запись не проходит схему: " + "; ".join(errs[:5]), {"errors": errs})


def create(slug: str, name: str, prefix: str, rec: dict, schema_name: str, command: str) -> tuple[dict, bool]:
    """Создать запись с идемпотентностью по rec['op_id']. → (запись, existing)."""
    path = reg(slug, name)
    with store.lock(path):
        recs = store.read_jsonl(path)
        for r in recs:
            if r.get("op_id") == rec["op_id"]:
                return r, True
        rec = {"id": ids.next_in(recs, prefix), **rec}
        check_schema(rec, schema_name)
        recs.append(rec)
        store._atomic_write(path, "".join(store._dumps(r) + "\n" for r in recs))
    journal.log(slug, "cli", f"{command} {rec['id']}", {"command": command, "ids": [rec["id"]]})
    return rec, False


def update(slug: str, name: str, rec_id: str, patch: dict, reason: str, actor: str, command: str) -> dict:
    rec = store.update_record(reg(slug, name), rec_id, patch, reason, actor)
    journal.log(slug, "cli", f"{command} {rec_id}", {"command": command, "ids": [rec_id], "fields": list(patch)})
    return rec


def require_existing(slug: str, refs: list[str], name: str, allowed_status: set[str] | None = None) -> None:
    recs = by_id(slug, name)
    for r in refs:
        if r not in recs:
            raise CliError("RULE_VIOLATION", f"Ссылка на несуществующий объект {r}", {"id": r})
        if allowed_status is not None and recs[r].get("status") not in allowed_status:
            raise CliError("RULE_VIOLATION", f"{r} в статусе {recs[r].get('status')} — на него нельзя ссылаться", {"id": r})


REF_RX = __import__("re").compile(r"\[([SCOXDK]-\d{3,})\]")
COMMENT_RX = __import__("re").compile(r"<!--.*?-->", __import__("re").S)


def doc_files(slug: str) -> list[Path]:
    d = paths.project_dir(slug)
    files = [d / "brief.md", *sorted((d / "docs").glob("*.md")), d / "out" / "strategy.md"]
    return [file for file in files if file.is_file()]


def sections(text: str) -> list[tuple[str, int, list[str]]]:
    """Разделы уровня ##: [(заголовок, номер строки заголовка, строки тела)]. До первого ## — заголовок ''."""
    out: list[tuple[str, int, list[str]]] = [("", 0, [])]
    for n, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            out.append((line[3:].strip(), n, []))
        else:
            out[-1][2].append(line)
    return out


def body_empty(lines: list[str]) -> bool:
    text = COMMENT_RX.sub("", "\n".join(lines))
    return not any(x.strip() for x in text.splitlines())
