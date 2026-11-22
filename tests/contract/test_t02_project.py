"""T02: проект, этапы, ворота."""
import json

from strateg.cli import main


def test_new_creates_tree_and_current(cli, project, root):
    d = root / "projects" / project
    for sub in ["project.json", "brief.md", "materials/inbox", "materials/snapshots", "state", "docs", "out"]:
        assert (d / sub).exists(), sub
    assert (root / "projects" / ".current").read_text().strip() == project
    p = json.loads((d / "project.json").read_text())
    assert p["stage"] == "S0" and all(p["gates"][g]["status"] == "pending" for g in ["G1", "G2", "G3", "G4"])


def test_new_rejects_duplicate_and_bad_slug(cli, project):
    assert cli("project", "new", project, "--title", "x")[1]["error"]["code"] == "DUPLICATE_SLUG"
    code, r = cli("project", "new", "Bad Slug", "--title", "x")
    assert code == 2 and r["error"]["code"] == "BAD_ARGS"


def test_no_project(cli):
    code, r = cli("project", "status")
    assert code == 2 and r["error"]["code"] == "NO_PROJECT"


def test_stage_rules(cli, project):
    code, r = cli("project", "stage", "S1")
    assert code == 1 and r["error"]["code"] == "RULE_VIOLATION"  # G1 не пройдены
    assert cli("project", "gate", "G1", "--status", "approved", "--note", "ок")[0] == 0
    assert cli("project", "stage", "S1")[0] == 0
    assert cli("project", "stage", "S3")[0] == 1  # прыжок через этап
    code, r = cli("project", "stage", "S0")
    assert code == 2 and r["error"]["code"] == "BAD_ARGS"  # назад без --note
    assert cli("project", "stage", "S0", "--note", "переформулировали вопрос")[0] == 0


def test_status_shape(cli, project):
    code, r = cli("project", "status")
    assert code == 0
    d = r["data"]
    for k in ["slug", "title", "stage", "stage_name", "next_step", "gates", "counts", "needs_review",
              "overdue_commitments", "assumptions_unreviewed", "last_events", "cost_usd"]:
        assert k in d, k
    assert d["stage_name"] == "Постановка задачи"


def test_set_and_assume(cli, project):
    assert cli("project", "set", "--goal", "Снизить отток", "--constraint", "только открытые данные")[0] == 0
    code, r = cli("project", "assume", "Аудитория — B2C")
    assert code == 0 and r["data"]["id"] == "A-001"
    assert cli("project", "status")[1]["data"]["assumptions_unreviewed"] == 1
    assert cli("project", "assume", "--review")[1]["data"]["reviewed"] == 1


def test_gate_and_stage_are_journaled(cli, project, root):
    cli("project", "gate", "G1", "--status", "approved", "--note", "ок")
    cli("project", "stage", "S1")
    ev = [json.loads(x) for x in (root / "projects" / project / "state" / "journal.jsonl").read_text().splitlines()]
    kinds = [e["kind"] for e in ev]
    assert "gate" in kinds and "stage_change" in kinds
    sc = [e for e in ev if e["kind"] == "stage_change"][-1]
    assert sc["stage"] == "S1" and sc["data"] == {"from": "S0", "to": "S1"}
    assert [e for e in ev if e["kind"] == "gate"][-1]["actor"] == "human"


def test_human_output_is_russian_text(root, capsys):
    assert main(["project", "new", "h-proj", "--title", "Тест"]) == 0
    capsys.readouterr()
    assert main(["project", "status"]) == 0
    assert "Постановка задачи" in capsys.readouterr().out
