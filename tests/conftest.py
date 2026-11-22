"""Общие фикстуры. Фаза 0 (Claude). НЕ МЕНЯТЬ."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from strateg.cli import main

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def root(tmp_path, monkeypatch):
    """Чистый корень данных: STRATEG_ROOT=tmp, projects/ пустая."""
    monkeypatch.setenv("STRATEG_ROOT", str(tmp_path))
    monkeypatch.delenv("STRATEG_PROJECT", raising=False)
    monkeypatch.delenv("STRATEG_DEV", raising=False)
    (tmp_path / "projects").mkdir()
    return tmp_path


@pytest.fixture
def cli(root, capsys):
    """cli("claim", "add", ...) → (exit_code, json-ответ или None). --json добавляется сам."""

    def run(*argv):
        code = main([str(a) for a in argv] + ["--json"])
        text = capsys.readouterr().out.strip()
        return code, (json.loads(text) if text else None)

    return run


@pytest.fixture
def project(cli):
    code, r = cli("project", "new", "t-proj", "--title", "Тестовый проект")
    assert code == 0, r
    return "t-proj"


@pytest.fixture
def sample_source(cli, project, root):
    """Источник S-001 из tests/fixtures/snapshots/sample.html."""
    src = root / "sample.html"
    shutil.copy(FIX / "snapshots" / "sample.html", src)
    code, r = cli("source", "add", "--file", src, "--title", "Обзор удержания")
    assert code == 0, r
    return r["data"]["id"]


QUOTE = "около 30% пользователей отменяют подписку в первый месяц"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def state(root: Path, slug: str, name: str) -> list[dict]:
    return read_jsonl(root / "projects" / slug / "state" / f"{name}.jsonl")


def advance(cli, to_stage: str) -> None:
    """Пройти ворота и этапы до to_stage включительно (без проверки документов)."""
    order = ["S0", "S1", "S2", "S3", "S4", "S5"]
    gates = {"S0": "G1", "S1": "G2", "S2": "G3", "S3": "G4"}
    for cur, nxt in zip(order, order[1:], strict=False):
        if order.index(cur) >= order.index(to_stage):
            break
        if cur in gates:
            assert cli("project", "gate", gates[cur], "--status", "approved", "--note", "ok")[0] == 0
        code, r = cli("project", "stage", nxt)
        assert code == 0, r
