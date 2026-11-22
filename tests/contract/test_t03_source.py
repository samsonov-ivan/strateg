"""T03: источники и снимки."""
import shutil

import httpx

from strateg.cmd import source
from tests.conftest import FIX, state

HTML = (FIX / "snapshots" / "sample.html").read_bytes()


def _mock(monkeypatch, handler):
    monkeypatch.setattr(source, "make_client", lambda policy: httpx.Client(transport=httpx.MockTransport(handler)))


def test_add_file_creates_snapshot_and_is_idempotent(cli, project, root):
    f = root / "a.html"
    shutil.copy(FIX / "snapshots" / "sample.html", f)
    code, r = cli("source", "add", "--file", f, "--title", "Обзор")
    assert code == 0 and r["data"]["id"] == "S-001" and r["data"]["existing"] is False
    assert r["data"]["snapshot"] == "materials/snapshots/S-001.md"  # путь от папки проекта
    text = (root / "projects" / project / r["data"]["snapshot"]).read_text(encoding="utf-8")
    assert "около 30% пользователей" in text and len(r["data"]["sha256"]) == 64
    code, r2 = cli("source", "add", "--file", f, "--title", "Обзор")
    assert code == 0 and r2["data"]["existing"] is True and r2["data"]["id"] == "S-001"
    assert len(state(root, project, "sources")) == 1
    assert (root / "projects" / project / "materials" / "inbox" / "a.html").exists()


def test_add_url_and_dedupe_utm(cli, project, root, monkeypatch):
    _mock(monkeypatch, lambda req: httpx.Response(200, content=HTML, headers={"content-type": "text/html; charset=utf-8"}))
    code, r = cli("source", "add", "--url", "https://example.org/retention/", "--title", "Обзор")
    assert code == 0 and r["data"]["id"] == "S-001"
    code, r = cli("source", "add", "--url", "https://example.org/retention?utm_source=tg#top")
    assert code == 0 and r["data"]["existing"] is True


def test_fetch_failure_creates_nothing(cli, project, root, monkeypatch):
    _mock(monkeypatch, lambda req: httpx.Response(404))
    code, r = cli("source", "add", "--url", "https://example.org/missing")
    assert code == 4 and r["error"]["code"] == "FETCH_FAILED"
    assert state(root, project, "sources") == []


def test_denied_domain_blocked(cli, project, root):
    code, r = cli("source", "add", "--url", "http://wiki.corp/secret-plan")
    assert code == 5 and r["error"]["code"] == "POLICY_BLOCKED"
    assert any(e["kind"] == "error" for e in state(root, project, "journal"))


def test_poisoned_page_flagged_not_blocked(cli, project, root):
    f = root / "p.html"
    shutil.copy(FIX / "poisoned" / "page.html", f)
    code, r = cli("source", "add", "--file", f)
    assert code == 0 and len(r["data"]["injection_flags"]) >= 2 and r["warnings"]


def test_image_source(cli, project, root):
    f = root / "screen.png"
    shutil.copy(FIX / "snapshots" / "screen.png", f)
    code, r = cli("source", "add", "--file", f, "--title", "Экран подписки")
    assert code == 0
    assert state(root, project, "sources")[0]["kind"] == "image"


def test_pdf_source_preserves_row_and_column_positions(cli, project, root):
    code, result = cli("source", "add", "--file", FIX / "snapshots" / "capacity_grid.pdf")
    assert code == 0, result
    snapshot = root / "projects" / project / result["data"]["snapshot"]
    original, grid = snapshot.read_text().split("## Таблицы с сохранением расположения ячеек")
    assert "Workshop shifts" in original
    assert "Страница 2, таблица 1" in grid
    rows = [line.split() for line in grid.splitlines() if line.lstrip().startswith(("Shift", "Morning", "Evening"))]
    assert rows == [["Shift", "Expected", "Actual"], ["Morning", "92", "67"], ["Evening", "40", "0"]]


def test_rate_show_retract(cli, project, sample_source, root):
    assert cli("source", "rate", sample_source, "--reliability", "B", "--by", "human")[0] == 0
    code, r = cli("source", "show", sample_source, "--lines", "1-200")
    assert code == 0 and "около 30%" in r["data"]["text"]
    code, r = cli("source", "retract", sample_source, "--reason", "устарел")
    assert code == 0 and state(root, project, "sources")[0]["status"] == "retracted"
    assert cli("source", "show", "S-099")[0] == 3
