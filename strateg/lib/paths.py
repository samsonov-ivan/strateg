"""Пути. Реализовано в фазе 0 (Claude). НЕ МЕНЯТЬ.

code_dir() — корень репозитория с кодом, config/, schemas/, knowledge/.
root()     — корень данных (projects/). По умолчанию совпадает с code_dir(); в тестах — STRATEG_ROOT.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from strateg.lib.out import CliError


def code_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def root() -> Path:
    env = os.environ.get("STRATEG_ROOT")
    return Path(env).resolve() if env else code_dir()


def projects_dir() -> Path:
    return root() / "projects"


def project_dir(slug: str) -> Path:
    return projects_dir() / slug


def state_path(slug: str, name: str) -> Path:
    """Путь к реестру: state_path(slug, "claims") → projects/<slug>/state/claims.jsonl."""
    return project_dir(slug) / "state" / f"{name}.jsonl"


def config_path(name: str) -> Path:
    return code_dir() / "config" / name


def load_config(name: str) -> dict:
    """load_config("stages") читает config/stages.json."""
    name = name if name.endswith(".json") else f"{name}.json"
    return json.loads(config_path(name).read_text(encoding="utf-8"))


def schema_path(name: str) -> Path:
    return code_dir() / "schemas" / f"{name}.json"


def knowledge_dir() -> Path:
    return code_dir() / "knowledge"


def _current_file() -> Path:
    return projects_dir() / ".current"


def current_slug(arg: str | None = None, required: bool = True) -> str | None:
    """Аргумент → STRATEG_PROJECT → projects/.current. Нет проекта → NO_PROJECT; нет папки → NOT_FOUND."""
    slug = arg or os.environ.get("STRATEG_PROJECT")
    if not slug and _current_file().exists():
        slug = _current_file().read_text(encoding="utf-8").strip() or None
    if not slug:
        if required:
            raise CliError("NO_PROJECT", "Нет активного проекта: укажи --project или создай проект командой project new")
        return None
    if not project_dir(slug).exists():
        if required:
            raise CliError("NOT_FOUND", f"Проект {slug} не найден")
        return None
    return slug


def set_current(slug: str) -> None:
    projects_dir().mkdir(parents=True, exist_ok=True)
    _current_file().write_text(slug + "\n", encoding="utf-8")


def claude_transcripts_dir() -> Path | None:
    """~/.claude/projects/<root(), где каждый символ не [A-Za-z0-9] заменён на "-">, если папка есть."""
    enc = re.sub(r"[^A-Za-z0-9]", "-", str(root()))
    p = Path.home() / ".claude" / "projects" / enc
    return p if p.exists() else None
