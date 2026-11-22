"""Диагностика окружения. T15."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import sys
import tempfile

from strateg.lib import paths
from strateg.lib.out import Result

PKGS = {"markitdown": "markitdown", "httpx": "httpx", "jsonschema": "jsonschema", "pandas": "pandas", "pytest": "pytest"}


def _env() -> dict:
    env = dict(os.environ)
    f = paths.code_dir() / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() and not k.startswith("#") and v.strip():
                env.setdefault(k.strip(), v.strip())
    return env


def run(args: argparse.Namespace) -> Result:
    checks = []

    def add(check: str, ok: bool, msg: str, fix: str, level: str = "fail") -> None:
        checks.append({"check": check, "status": "ok" if ok else level, "message": msg, "fix": "" if ok else fix})

    v = sys.version_info
    add("Python ≥3.11", v >= (3, 11), f"{v.major}.{v.minor}.{v.micro}", "Установите Python 3.11+ и создайте .venv")
    missing = []
    for mod in PKGS.values():
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    add("Зависимости", not missing, "все установлены" if not missing else f"нет: {', '.join(missing)}",
        "pip install -r requirements.txt")
    try:
        from markitdown import MarkItDown

        txt = MarkItDown().convert(str(paths.code_dir() / "tests" / "fixtures" / "snapshots" / "sample.html")).text_content
        add("Конвертация документов (markitdown)", "30%" in txt, "работает", "pip install 'markitdown[pdf,docx,pptx,xlsx]'")
    except Exception as e:
        add("Конвертация документов (markitdown)", False, str(e)[:120], "pip install 'markitdown[pdf,docx,pptx,xlsx]'")
    add("git", bool(shutil.which("git")), "найден" if shutil.which("git") else "не найден", "Установите git", "warn")
    add("Claude Code", bool(shutil.which("claude")), "найден" if shutil.which("claude") else "не найден в PATH",
        "Установите Claude Code или откройте папку в Cursor/opencode", "warn")
    env = _env()
    add(".env", (paths.code_dir() / ".env").exists(), "есть" if (paths.code_dir() / ".env").exists() else "нет",
        "cp .env.example .env", "warn")
    jev = bool(env.get("TYPESAFE_API_KEY"))
    add("Ключ Jev", jev, "есть" if jev else "нет: для резервного пути нужен доступ к Claude",
        "Добавьте TYPESAFE_API_KEY в .env (console.typesafe.ai/keys)", "warn")
    checks.append({"check": "ANTHROPIC_API_KEY", "status": "ok",
                   "message": "задан" if env.get("ANTHROPIC_API_KEY") else "не задан — не нужен при подписке Claude", "fix": ""})
    bad = []
    for d in ("schemas", "config"):
        for f in (paths.code_dir() / d).glob("*.json"):
            try:
                json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                bad.append(f.name)
    add("Схемы и конфиги", not bad, "читаются" if not bad else f"битые: {', '.join(bad)}", "Восстановите файлы из git")
    try:
        paths.projects_dir().mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=paths.projects_dir()):
            pass
        add("Папка projects/ доступна на запись", True, "да", "")
    except OSError as e:
        add("Папка projects/ доступна на запись", False, str(e)[:120], "Проверьте права на папку projects/")
    try:
        from strateg.cmd.guard import cli_secrets

        r = cli_secrets(argparse.Namespace(paths=[], staged=False, history=False))
        scope = "распакованная папка" if r.data["scope"] == "archive" else "файлы под контролем Git"
        count = r.data["files_scanned"]
        msg = (f"{scope}, проверено текстовых файлов: {count}, пропущено двоичных: {r.data['binary_skipped']}, "
               f"совпадений с шаблонами: {len(r.data['findings'])}")
        add("Проверка секретов", r.exit_code == 0 and count > 0, msg, "Проверьте состав поставки: python -m strateg guard secrets")
    except Exception as e:
        add("Проверка секретов", False, f"не проверено: {str(e)[:100]}", "Проверьте доступ к файлам и повторите doctor")
    fails = sum(c["status"] == "fail" for c in checks)
    human = "\n".join(f"[{c['status']:>4}] {c['check']}: {c['message']}" + (f"  → {c['fix']}" if c["fix"] else "")
                      for c in checks)
    if fails:
        return Result({"checks": checks}, exit_code=1, message=f"Проблем: {fails}", human=human)
    return Result({"checks": checks}, human=human)
