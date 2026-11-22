"""Переменные окружения с подхватом .env из корня репозитория (без перезаписи уже заданных)."""
from __future__ import annotations

import os

from strateg.lib import paths


def get(name: str) -> str | None:
    if os.environ.get(name):
        return os.environ[name]
    f = paths.code_dir() / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == name and v.strip() and not k.lstrip().startswith("#"):
                return v.strip().strip('"').strip("'")
    return None
