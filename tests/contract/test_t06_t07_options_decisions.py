"""T06: варианты и возражения. T07: решения, обязательства, обзор."""
from tests.conftest import state


def _options(cli):
    cli("claim", "add", "--type", "hypothesis", "--text", "H1")
    for title, kind in [("Оставить как есть", "status_quo"), ("Закрыть направление", "close"), ("Изменить онбординг", "change")]:
        assert cli("option", "add", "--title", title, "--kind", kind, "--summary", title, "--based-on", "C-001")[0] == 0


def test_options_objections(cli, project, root):
    _options(cli)
    assert cli("objection", "add", "--option", "O-001", "--text", "Отток продолжится", "--strength", "strong",
               "--by", "red_team")[0] == 0
    assert cli("objection", "respond", "X-001", "--response", "Принимаем риск на квартал")[0] == 0
    rows = {o["id"]: o for o in cli("option", "list")[1]["data"]}
    assert rows["O-001"]["objections_count"] == 1 and rows["O-001"]["strong_objections_count"] == 1
    assert len(cli("objection", "list", "--option", "O-001")[1]["data"]) == 1


def test_single_chosen(cli, project, root):
    _options(cli)
    cli("option", "set", "O-001", "--status", "chosen", "--reason", "a")
    cli("option", "set", "O-003", "--status", "chosen", "--reason", "b")
    st = {o["id"]: o["status"] for o in state(root, project, "options")}
    assert st == {"O-001": "active", "O-002": "active", "O-003": "chosen"}


def test_option_based_on_retracted_rejected(cli, project):
    cli("claim", "add", "--type", "hypothesis", "--text", "H1")
    cli("claim", "retract", "C-001", "--reason", "x")
    assert cli("option", "add", "--title", "A", "--kind", "new", "--summary", "A", "--based-on", "C-001")[0] == 1


def test_decision_and_review(cli, project, root):
    _options(cli)
    code, r = cli("decision", "add", "--option", "O-003", "--rationale", "Лучшее соотношение", "--owner", "РП",
                  "--by", "РП", "--based-on", "C-001", "--metric", "удержание M1|0.70|0.75|2026-12-31",
                  "--trigger", "date:2026-11-20", "--trigger", "claim:C-001", "--trigger", "metric:удержание < 0.65")
    assert code == 0 and r["data"]["id"] == "D-001"
    assert {o["id"]: o["status"] for o in state(root, project, "options")}["O-003"] == "chosen"
    cli("commitment", "add", "--decision", "D-001", "--what", "Новый онбординг", "--owner", "дизайнер", "--due", "2026-11-15")
    cli("commitment", "add", "--decision", "D-001", "--what", "Письмо до списания", "--owner", "CRM", "--due", "2026-11-27")
    cli("claim", "retract", "C-001", "--reason", "опровергнута")
    d = cli("review", "--today", "2026-11-22")[1]["data"]
    assert [k["id"] for k in d["overdue"]] == ["K-001"]
    assert [k["id"] for k in d["due_7d"]] == ["K-002"]
    kinds = sorted(t["kind"] for t in d["triggered"])
    assert kinds == ["claim", "date", "metric"]
    assert any(x["urgency"] == "high" for x in d["decide_now"])
    assert cli("commitment", "done", "K-001")[0] == 0
    assert cli("review", "--today", "2026-11-22")[1]["data"]["overdue"] == []


def test_decision_requires_metric(cli, project):
    _options(cli)
    assert cli("decision", "add", "--option", "O-001", "--rationale", "r", "--owner", "o", "--by", "b",
               "--trigger", "date:2026-12-01")[0] == 2
