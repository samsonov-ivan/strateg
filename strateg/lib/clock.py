"""Время. Реализовано в фазе 0 (Claude). НЕ МЕНЯТЬ.

Всегда вызывать через модуль (`from strateg.lib import clock; clock.now()`), чтобы тесты могли подменить время.
"""
from __future__ import annotations

from datetime import UTC, datetime


def now() -> str:
    """UTC в ISO 8601 с точностью до секунды: 2026-11-10T09:00:00Z."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today() -> str:
    """Дата YYYY-MM-DD (UTC), согласованная с now()."""
    return now()[:10]
