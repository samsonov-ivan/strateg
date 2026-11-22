"""Стоимость и время по транскриптам Claude Code. T11."""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from strateg.cmd import _common as c
from strateg.lib import journal, paths, store
from strateg.lib.out import Result

FIELDS = ["input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"]


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _price(model: str, prices: dict) -> dict | None:
    best = max((k for k in prices if model.startswith(k)), key=len, default=None)
    return prices[best] if best else None


def _usage_lines(files: list[Path]) -> dict[str, dict]:
    msgs: dict[str, dict] = {}
    for f in files:
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            m = r.get("message") or {}
            if r.get("type") != "assistant" or not m.get("usage"):
                continue
            key = m.get("id") or f"{f.name}:{r.get('timestamp')}"
            msgs[key] = {"model": m.get("model", "unknown"), "usage": m["usage"], "at": r.get("timestamp")}
    return msgs


def _transcript_span_min(files: list[Path], sessions: list[str], tdir: Path | None) -> float | None:
    """Сумма по сессиям: от первого до последнего сообщения (основной транскрипт + субагенты)."""
    if not files or not tdir:
        return None
    total = 0.0
    for sid in sessions:
        stamps = []
        for f in files:
            if f.name == f"{sid}.jsonl" or sid in f.parts:
                for line in f.read_text(encoding="utf-8").splitlines():
                    try:
                        t = json.loads(line).get("timestamp")
                    except json.JSONDecodeError:
                        continue
                    if t:
                        stamps.append(_ts(t))
        if stamps:
            total += (max(stamps) - min(stamps)).total_seconds() / 60
    return total


def _is_human(e: dict) -> bool:
    """Реплика человека (а не результат инструмента): до неё агент ждал — это не его рабочее время."""
    if e.get("type") != "user" or e.get("isMeta"):
        return False
    c = (e.get("message") or {}).get("content")
    if isinstance(c, str):
        return True
    return isinstance(c, list) and not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c)


def _active_min(files: list[Path], sessions: list[str]) -> float | None:
    """Активное время агента: сумма интервалов основного транскрипта, кроме ожидания реплик человека."""
    total, seen = 0.0, False
    for sid in sessions:
        for f in files:
            if f.name != f"{sid}.jsonl":
                continue
            rows = []
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("timestamp") and e.get("type") in ("user", "assistant") and not e.get("isMeta"):  # без служебных записей
                    rows.append((_ts(e["timestamp"]), _is_human(e)))
            rows.sort(key=lambda r: r[0])
            seen = seen or bool(rows)
            for (t0, _), (t1, human) in zip(rows, rows[1:], strict=False):
                if not human:
                    total += (t1 - t0).total_seconds() / 60
    return total if seen else None


def run(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    ev = journal.read(slug)
    warnings: list[str] = []
    sessions: list[str] = []
    for e in ev:
        sid = e["kind"] == "session_start" and (e.get("data") or {}).get("session_id")
        if sid and sid not in sessions:
            sessions.append(sid)
    tdir = Path(args.transcripts) if args.transcripts else paths.claude_transcripts_dir()
    pfile = Path(args.prices) if args.prices else paths.config_path("prices.json")
    prices = json.loads(pfile.read_text(encoding="utf-8")).get("models", {})
    files: list[Path] = []
    if not tdir or not tdir.exists():
        warnings.append("Транскрипты Claude Code не найдены: укажи --transcripts")
    else:
        for sid in sessions:
            if (tdir / f"{sid}.jsonl").exists():
                files.append(tdir / f"{sid}.jsonl")
            if (tdir / sid).is_dir():
                files += sorted((tdir / sid).rglob("*.jsonl"))
        if sessions and not files:
            warnings.append("Для сессий проекта нет файлов транскриптов")
    if not sessions:
        warnings.append("В журнале нет событий session_start: стоимость не к чему привязать")
    out = paths.project_dir(slug) / "out"
    saved = _saved_snapshot(out / "cost.json", sessions, files)
    if saved is not None:  # другая машина или свежий клон: не затираем прежний расчёт нулём
        saved["source"] = "snapshot"
        saved["warnings"] = [f"Транскрипты сессий проекта недоступны на этой машине: показан сохранённый расчёт"
                             f"{' от ' + saved['computed_at'] if saved.get('computed_at') else ''} (out/cost.json)"]
        return Result(saved, warnings=saved["warnings"], human=_md(saved))
    changes =[(_ts(e["at"]), e["data"]["to"]) for e in ev if e["kind"] == "stage_change" and e.get("data", {}).get("to")]
    by_stage: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    total = 0.0
    unknown = set()
    for m in _usage_lines(files).values():
        at = _ts(m["at"]) if m.get("at") else None
        stage = "S0"
        for t, s in changes:
            if at and t <= at:
                stage = s
        u = {k: int(m["usage"].get(k) or 0) for k in FIELDS}
        pr = _price(m["model"], prices)
        usd = None
        if pr:
            usd = (u["input_tokens"] * pr["input"] + u["output_tokens"] * pr["output"] +
                   u["cache_creation_input_tokens"] * pr.get("cache_write", 0) +
                   u["cache_read_input_tokens"] * pr.get("cache_read", 0)) / 1_000_000
            total += usd
        else:
            unknown.add(m["model"])
        for bucket, key in ((by_stage, stage), (by_model, m["model"])):
            b = bucket.setdefault(key, {"usd": 0.0, "input_tokens": 0, "output_tokens": 0, "cache_read": 0,
                                        "cache_write": 0, "calls": 0})
            b["usd"] = round(b["usd"] + (usd or 0), 6)
            b["input_tokens"] += u["input_tokens"]
            b["output_tokens"] += u["output_tokens"]
            b["cache_read"] += u["cache_read_input_tokens"]
            b["cache_write"] += u["cache_creation_input_tokens"]
            b["calls"] += 1
    for mdl in sorted(unknown):
        warnings.append(f"Нет цены для модели {mdl}: её стоимость не учтена (config/prices.json)")
    routing = sum(r.get("cost_usd", 0) for r in c.records(slug, "routing"))
    gate_min, prev = 0.0, None
    for e in ev:
        if e["kind"] == "gate" and prev is not None:
            gate_min += (_ts(e["at"]) - _ts(prev["at"])).total_seconds() / 60
        prev = e
    wall = _transcript_span_min(files, sessions, tdir)
    active = _active_min(files, sessions) if wall is not None else None
    if wall is None:  # нет транскриптов — по журналу
        first = next((e for e in ev if e["kind"] == "session_start"), None)
        wall = (_ts(ev[-1]["at"]) - _ts(first["at"])).total_seconds() / 60 if first else 0.0
    data = {"total_usd": round(total + routing, 6), "by_stage": by_stage, "by_model": by_model, "routing_usd": round(routing, 6),
            "wall_time_min": round(wall, 1), "human_gate_min": round(gate_min, 1),
            "agent_min": round(active if active is not None else max(0.0, wall - gate_min), 1), "sessions": sessions, "warnings": warnings,
            "source": "transcripts" if files else "journal", "computed_at": _now()}
    store.write_json(out / "cost.json", data)
    (out / "cost.md").write_text(_md(data), encoding="utf-8")
    return Result(data, warnings=warnings, human=_md(data))


def _now() -> str:
    """Время расчёта (не через clock.now: в тестах он подменён последовательностью событий журнала)."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _saved_snapshot(path: Path, sessions: list[str], files: list[Path]) -> dict | None:
    """Сохранённый расчёт, если транскриптов части сессий нет, а прежний расчёт их покрывал."""
    have = {f.stem for f in files} | {p for f in files for p in f.parts}
    missing = [s for s in sessions if s not in have]
    if not missing or not path.exists():
        return None
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if saved.get("total_usd", 0) > 0 and set(missing) <= set(saved.get("sessions") or []):
        return saved
    return None


def _md(d: dict) -> str:
    rows = ["# Стоимость и время", "", "| Этап | $ | Вход | Выход | Кэш чтение | Кэш запись | Вызовы |", "|---|---|---|---|---|---|---|"]
    for k in sorted(d["by_stage"]):
        v = d["by_stage"][k]
        rows.append(f"| {k} | {v['usd']:.4f} | {v['input_tokens']} | {v['output_tokens']} | {v['cache_read']} | "
                    f"{v['cache_write']} | {v['calls']} |")
    rows += ["", "| Модель | $ | Вызовы |", "|---|---|---|"]
    rows += [f"| {k} | {v['usd']:.4f} | {v['calls']} |" for k, v in sorted(d["by_model"].items())]
    rows += ["", f"**Итого:** ${d['total_usd']:.4f} (маршрутизация ${d['routing_usd']:.4f}); "
             f"работа агента {d['agent_min']} мин; всего {d['wall_time_min']} мин, ожидание решений человека {d['human_gate_min']} мин."]
    if d.get("source") == "snapshot":
        when = f" от {d['computed_at']}" if d.get("computed_at") else ""
        rows += ["", f"_Сохранённый расчёт{when}: транскриптов сессий проекта на этой машине нет._"]
    return "\n".join(rows) + "\n"
