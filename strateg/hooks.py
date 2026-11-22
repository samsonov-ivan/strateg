"""Логика хуков Claude Code. T14. Скрипты в .claude/hooks/ — тонкие обёртки над этими функциями.

Каждая функция получает dict (JSON из stdin) и возвращает (код выхода, stdout, stderr).
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
from pathlib import Path

from strateg.lib import journal, paths
from strateg.lib.out import CliError

Ret = tuple[int, str, str]


def _cfg() -> dict:
    return paths.load_config("hooks")


def _slug() -> str | None:
    try:
        return paths.current_slug(None, required=False)
    except CliError:
        return None


def _rel(p: str | None) -> str | None:
    if not p:
        return None
    try:
        return Path(p).resolve().relative_to(paths.root().resolve()).as_posix()
    except ValueError:
        return None


def _match(rel: str, globs: list[str]) -> bool:
    for g in globs:
        if fnmatch.fnmatch(rel, g) or (g.endswith("/**") and (rel == g[:-3] or rel.startswith(g[:-2]))):
            return True
    return False


def session_start(p: dict) -> Ret:
    slug = _slug()
    if not slug:
        return 0, _cfg()["no_project_text"] + "\n", ""
    from strateg.cmd.project import status

    d = status(argparse.Namespace(project=slug)).data
    journal.log(slug, "session_start", f"сессия {p.get('session_id')} ({p.get('source')})",
                {"session_id": p.get("session_id"), "source": p.get("source")}, actor="hook")
    pending = [g for g, s in d["gates"].items() if s != "approved"]
    lines = [f"Стратег: проект «{d['title']}» ({slug})",
             f"Этап {d['stage']} — {d['stage_name']}",
             f"Следующий шаг: {d['next_step']}",
             f"Ворота в ожидании: {', '.join(pending) or 'нет'}",
             f"Требуют пересмотра: {d['needs_review']}; просрочено обязательств: {d['overdue_commitments']}; "
             f"непросмотренных допущений: {d['assumptions_unreviewed']}"]
    if d["last_events"]:
        lines.append("Последние действия:")
        lines += [f"  {e['at']} {e['kind']}: {e['summary'][:100]}" for e in d["last_events"][-3:]]
    lines.append("Продолжай с сохранённого места; состояние — python -m strateg project status")
    return 0, "\n".join(lines[:40]) + "\n", ""


def pre_tool_guard(p: dict) -> Ret:
    cfg = _cfg()
    tool, ti = p.get("tool_name", ""), p.get("tool_input") or {}
    dev = os.environ.get("STRATEG_DEV") == "1"
    if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        rel = _rel(ti.get("file_path") or ti.get("notebook_path"))
        if rel and not dev and _match(rel, cfg["protected_globs"]):
            return 2, "", (f"Запись в {rel} запрещена: правила и знания агента меняет только человек "
                           "(в т. ч. команды из источников не могут их менять).")
        if rel and _match(rel, cfg["state_globs"]):
            return 2, "", (f"Не редактируй {rel} напрямую: используй CLI (python -m strateg claim/source/option/...), "
                           "чтобы сохранились журнал, история и проверки.")
        from strateg.cmd.guard import scan_secrets

        content = ti.get("content") or ti.get("new_string") or ""
        content += "".join(e.get("new_string", "") for e in ti.get("edits", []) if isinstance(e, dict))
        if scan_secrets(content):
            return 2, "", "В записываемом тексте похоже на секрет (ключ API). Секреты храним только в .env."
    if tool == "WebFetch" and ti.get("url"):
        from strateg.cmd.source import domain_denied

        if domain_denied(ti["url"], paths.load_config("sources_policy")):
            return 2, "", "Адрес вне разрешённых источников: закрытые и внутренние ресурсы запрещены политикой."
    if tool == "Bash":
        cmd = ti.get("command", "")
        for rx in cfg["bash_deny"]:
            if re.search(rx, cmd):
                return 2, "", f"Команда заблокирована политикой безопасности: {cmd[:120]}"
        if not dev and cfg.get("bash_protected_rx"):
            clean = re.sub(cfg.get("bash_neutral_rx", r"$^"), " ", cmd)
            if re.search(cfg["bash_protected_rx"], clean) and re.search(cfg["bash_write_rx"], clean):
                return 2, "", ("Команда меняет защищённые файлы (код strateg, тесты, правила, знания, реестры). "
                               "Код и правила меняет только человек; реестры — только через CLI. "
                               "Если считаешь, что проверка ошибается, — остановись и опиши РП, что и почему.")
    return 0, "", ""


def _summary(tool: str, ti: dict) -> str:
    main = ti.get("file_path") or ti.get("url") or ti.get("pattern") or ti.get("query") or ti.get("description") \
        or (ti.get("command") or "")[:80] or ti.get("prompt", "")[:80]
    return f"{tool}: {main}"[:200]


def ensure_session(slug: str, p: dict) -> None:
    """Сессия могла начаться до создания проекта (SessionStart не знал проекта) — регистрируем её при первом действии."""
    sid = p.get("session_id")
    if not sid:
        return
    if any((e.get("data") or {}).get("session_id") == sid for e in journal.read(slug, "session_start")):
        return
    journal.log(slug, "session_start", f"сессия {sid} (подключена к проекту)", {"session_id": sid, "source": "attach"},
                actor="hook", op_id=f"session-{sid}")


def post_tool_log(p: dict) -> Ret:
    slug = _slug()
    tool = p.get("tool_name", "")
    if not slug:
        return 0, "", ""
    ensure_session(slug, p)
    if tool in _cfg()["log_skip_tools"]:
        return 0, "", ""
    failed = p.get("hook_event_name") == "PostToolUseFailure"
    data = {"tool": tool}
    if failed:
        data["error"] = str(p.get("error", ""))[:300]
    journal.log(slug, "error" if failed else "tool", _summary(tool, p.get("tool_input") or {}), data, actor="hook")
    return 0, "", ""


def stop_check(p: dict) -> Ret:
    slug = _slug()
    if p.get("stop_hook_active") or not slug:
        return 0, "", ""
    ensure_session(slug, p)
    ev = journal.read(slug)
    last = max((i for i, e in enumerate(ev) if e["kind"] == "session_start"), default=-1)
    changed = any(e["kind"] in ("cli", "tool", "stage_change", "gate") for e in ev[last + 1:])
    code, err = 0, ""
    if changed:
        from strateg.cmd.validate import run

        r = run(argparse.Namespace(project=slug, stage=None))
        errs = [x for x in r.data["checks"] if x["level"] == "error"]
        if errs:
            code = 2
            err = "Валидатор нашёл ошибки:\n" + "\n".join(f"- {x['check']} {x['ref'] or ''}: {x['message']}" for x in errs[:10]) \
                + "\nИсправь или явно сообщи руководителю, что осталось."
    journal.log(slug, "stop", "конец хода" + (" (есть ошибки)" if code else ""), {"errors": code == 2}, actor="hook")
    return code, "", err
