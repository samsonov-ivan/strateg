"""T11: стоимость. T12: анализ данных."""
import json
import shutil

import pytest

from strateg.lib import clock, journal
from tests.conftest import FIX


@pytest.fixture
def costed(cli, project, monkeypatch):
    times = iter(["2026-11-10T09:00:00Z", "2026-11-10T10:20:00Z", "2026-11-10T10:30:00Z", "2026-11-10T11:45:00Z"])
    monkeypatch.setattr(clock, "now", lambda: next(times))
    journal.log(project, "session_start", "старт", {"session_id": "sess-1", "source": "startup"}, actor="hook")
    journal.log(project, "gate", "G1 approved", {"gate": "G1", "status": "approved"}, actor="human")
    journal.log(project, "stage_change", "S0 → S1", {"from": "S0", "to": "S1"}, stage="S1")
    journal.log(project, "stop", "стоп", {}, actor="hook")
    return project


def test_cost_by_stage_and_dedupe(cli, costed, root):
    code, r = cli("cost", "--transcripts", FIX / "transcripts", "--prices", FIX / "prices_test.json")
    assert code == 0
    d = r["data"]
    assert d["total_usd"] == pytest.approx(3.0)
    assert d["by_stage"]["S0"]["usd"] == pytest.approx(1.0) and d["by_stage"]["S1"]["usd"] == pytest.approx(2.0)
    assert d["by_stage"]["S0"]["input_tokens"] == 1_000_000  # дубль msg_a посчитан один раз, последняя версия
    assert any("mystery-model" in w for w in d["warnings"])
    assert d["sessions"] == ["sess-1"]
    assert d["human_gate_min"] == pytest.approx(80.0)
    assert d["wall_time_min"] == pytest.approx(120.0)  # по транскриптам: 09:30 → 11:30 (с субагентом)
    assert d["agent_min"] == pytest.approx(100.0)  # основной транскрипт 09:30 → 11:10, реплик человека нет
    out = root / "projects" / costed / "out"
    assert json.loads((out / "cost.json").read_text())["total_usd"] == pytest.approx(3.0)
    assert "|" in (out / "cost.md").read_text(encoding="utf-8")


def test_cost_without_transcripts(cli, project, root):
    code, r = cli("cost", "--transcripts", root / "nope", "--prices", FIX / "prices_test.json")
    assert code == 0 and r["data"]["total_usd"] == 0 and r["data"]["warnings"]


def test_cost_keeps_saved_snapshot_without_transcripts(cli, costed, root):
    """Свежий клон / другая машина: транскриптов нет — прежний расчёт не затирается нулём."""
    cli("cost", "--transcripts", FIX / "transcripts", "--prices", FIX / "prices_test.json")
    out = root / "projects" / costed / "out"
    before = (out / "cost.json").read_text(encoding="utf-8")
    code, r = cli("cost", "--transcripts", root / "nope", "--prices", FIX / "prices_test.json")
    assert code == 0
    assert r["data"]["total_usd"] == pytest.approx(3.0) and r["data"]["source"] == "snapshot"
    assert any("сохранённый расчёт" in w for w in r["data"]["warnings"])
    assert (out / "cost.json").read_text(encoding="utf-8") == before


def test_profile_issues(cli, project, root):
    f = root / "profile.csv"
    shutil.copy(FIX / "data" / "profile.csv", f)
    code, r = cli("data", "profile", f)
    assert code == 0 and r["data"]["rows"] == 6
    kinds = {(i["column"], i["kind"]) for i in r["data"]["issues"]}
    for exp in [("segment", "missing_high"), ("active_users", "negative_count"), ("conversion_pct", "mixed_percent_scale"),
                ("month", "period_gap")]:
        assert exp in kinds, exp
    assert any(k == "duplicate_rows" for _, k in kinds)
    assert (root / "projects" / project / "out" / "profile_profile.md").exists()


def test_cohort_matrix(cli, project, root):
    f = root / "cohort.csv"
    shutil.copy(FIX / "data" / "cohort.csv", f)
    code, r = cli("data", "cohort", f, "--user", "user_id", "--start", "start_date", "--event", "event_date")
    assert code == 0 and r["data"]["cohorts"] == 2
    m = (root / "projects" / project / r["data"]["matrix_path"]).read_text(encoding="utf-8").splitlines()
    assert m[0].startswith("cohort")
    jan = [x for x in m if x.startswith("2026-01")][0].split(",")
    assert float(jan[2]) == pytest.approx(1.0) and float(jan[3]) == pytest.approx(2 / 3, abs=0.01)
    assert any("data cohort" in json.dumps(e, ensure_ascii=False)
               for e in map(json.loads, (root / "projects" / project / "state" / "journal.jsonl").read_text().splitlines()))


def test_agent_time_excludes_waiting_for_human(tmp_path):
    from strateg.cmd.cost import _active_min
    rows = [("user", "2026-11-10T09:00:00Z", "вопрос"), ("assistant", "2026-11-10T09:10:00Z", None),
            ("user", "2026-11-10T09:12:00Z", [{"type": "tool_result", "content": "ok"}]),
            ("assistant", "2026-11-10T09:20:00Z", None),
            ("user", "2026-11-10T21:00:00Z", "да"), ("assistant", "2026-11-10T21:05:00Z", None)]
    f = tmp_path / "s.jsonl"
    f.write_text("\n".join(json.dumps({"type": t, "timestamp": ts, "message": {"content": c}}) for t, ts, c in rows))
    assert _active_min([f], ["s"]) == pytest.approx(25.0)
