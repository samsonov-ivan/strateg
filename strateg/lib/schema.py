"""Проверка записей по schemas/*.json. T01."""
from __future__ import annotations

import json
from functools import cache

from jsonschema import Draft202012Validator

from strateg.lib import paths


@cache
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(json.loads(paths.schema_path(name).read_text(encoding="utf-8")))


def validate(record: dict, name: str) -> list[str]:
    errs = sorted(_validator(name).iter_errors(record), key=lambda e: list(e.absolute_path))
    return [f"{'.'.join(str(p) for p in e.absolute_path) or '<запись>'}: {e.message}" for e in errs]
