"""Единый формат ответа CLI. Реализовано в фазе 0 (Claude). НЕ МЕНЯТЬ.

Успех (--json):        {"ok": true,  "data": ..., "warnings": [...]}
Нарушения (код 1):     {"ok": false, "data": ..., "warnings": [...], "error": {"code": "VALIDATION_FAILED", ...}}
Ошибка (CliError):     {"ok": false, "error": {"code": ..., "message": ..., "details": {...}}}
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any

EXIT_CODES: dict[str, int] = {
    "VALIDATION_FAILED": 1,
    "RULE_VIOLATION": 1,
    "BAD_ARGS": 2,
    "NO_PROJECT": 2,
    "DUPLICATE_SLUG": 2,
    "NOT_FOUND": 3,
    "FETCH_FAILED": 4,
    "CONVERT_FAILED": 4,
    "IO_ERROR": 4,
    "POLICY_BLOCKED": 5,
    "NOT_IMPLEMENTED": 9,
}


class CliError(Exception):
    """Ошибка команды. Код выхода берётся из EXIT_CODES, если не задан явно."""

    def __init__(self, code: str, message: str, details: dict | None = None, exit_code: int | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.exit_code = exit_code if exit_code is not None else EXIT_CODES.get(code, 1)


@dataclass
class Result:
    """Результат обработчика команды.

    exit_code=1 используют проверки (validate, verify, guard): данные отдаются полностью,
    но ok=false и error.code=error_code (по умолчанию VALIDATION_FAILED).
    """

    data: Any = None
    warnings: list[str] = field(default_factory=list)
    exit_code: int = 0
    error_code: str | None = None
    message: str | None = None
    human: str | None = None


def not_implemented(what: str) -> CliError:
    return CliError("NOT_IMPLEMENTED", f"Не реализовано: {what}")


def _dump(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def emit(result: Result, as_json: bool) -> None:
    if as_json:
        obj: dict[str, Any] = {"ok": result.exit_code == 0, "data": result.data, "warnings": result.warnings}
        if result.exit_code != 0:
            obj["error"] = {
                "code": result.error_code or "VALIDATION_FAILED",
                "message": result.message or "Проверка нашла нарушения",
                "details": {},
            }
        print(_dump(obj))
        return
    text = result.human if result.human is not None else render_human(result.data)
    if text:
        print(text)
    if result.exit_code != 0 and result.message:
        print(f"Ошибка: {result.message}", file=sys.stderr)
    for w in result.warnings:
        print(f"Внимание: {w}", file=sys.stderr)


def emit_error(err: CliError, as_json: bool) -> None:
    if as_json:
        print(_dump({"ok": False, "error": {"code": err.code, "message": err.message, "details": err.details}}))
    else:
        print(f"Ошибка [{err.code}]: {err.message}", file=sys.stderr)


def _scalar(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "да" if v else "нет"
    if isinstance(v, (list, tuple)) and all(not isinstance(x, (dict, list)) for x in v):
        return ", ".join(_scalar(x) for x in v) if v else "—"
    return str(v)


def _is_flat(d: dict) -> bool:
    return all(not isinstance(v, dict) and not (isinstance(v, list) and any(isinstance(x, (dict, list)) for x in v))
               for v in d.values())


def render_human(data: Any, indent: int = 0) -> str:
    """Человекочитаемый вид: dict → «ключ: значение», список одинаковых плоских dict → markdown-таблица."""
    pad = "  " * indent
    if data is None:
        return ""
    if isinstance(data, dict):
        lines = []
        for k, v in data.items():
            scalar_list = isinstance(v, list) and all(not isinstance(x, (dict, list)) for x in v)
            if isinstance(v, (dict, list)) and v and not scalar_list:
                lines.append(f"{pad}{k}:")
                lines.append(render_human(v, indent + 1))
            else:
                lines.append(f"{pad}{k}: {_scalar(v)}")
        return "\n".join(lines)
    if isinstance(data, list):
        if not data:
            return f"{pad}—"
        if all(isinstance(x, dict) for x in data) and all(_is_flat(x) for x in data):
            keys: list[str] = []
            for x in data:
                keys += [k for k in x if k not in keys]
            head = f"{pad}| " + " | ".join(keys) + " |"
            sep = f"{pad}|" + "---|" * len(keys)
            rows = [f"{pad}| " + " | ".join(_scalar(x.get(k)).replace("|", "\\|") for k in keys) + " |" for x in data]
            return "\n".join([head, sep, *rows])
        return "\n".join(
            f"{pad}- " + (render_human(x, indent + 1).lstrip() if isinstance(x, (dict, list)) else _scalar(x)) for x in data
        )
    return f"{pad}{_scalar(data)}"
