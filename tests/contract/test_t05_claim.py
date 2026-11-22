"""T05: утверждения и проверка цитат."""
from strateg.cmd.verify import quote_match
from tests.conftest import QUOTE, state


def test_quote_match_normalizes():
    text = "Главная причина оттока — первое списание оплаты,\n к которому пользователи оказываются «не готовы»."
    assert quote_match("первое списание оплаты, к которому пользователи оказываются не готовы", text) == (True, 1.0)
    ok, score = quote_match("первое списание оплаты к которому пользователи оказались не готовы", text)
    assert ok and 0.9 <= score < 1.0
    assert quote_match("рост в 5 раз за год у всех операторов связи", text)[0] is False
    assert quote_match("причина", text) == (False, 0.0)  # слишком короткая цитата


def test_fact_with_verified_quote(cli, sample_source):
    code, r = cli("claim", "add", "--type", "fact", "--text", "30% отменяют подписку в первый месяц",
                  "--source", sample_source, "--quote", QUOTE)
    assert code == 0 and r["data"]["id"] == "C-001" and r["data"]["quote_verified"] is True


def test_fact_with_wrong_quote_warns(cli, sample_source):
    code, r = cli("claim", "add", "--type", "fact", "--text", "x", "--source", sample_source,
                  "--quote", "этого текста в источнике совсем нет и не было")
    assert code == 0 and r["data"]["quote_verified"] is False and r["warnings"]


def test_rule_fact_needs_source_and_quote(cli, sample_source):
    assert cli("claim", "add", "--type", "fact", "--text", "x")[1]["error"]["code"] == "RULE_VIOLATION"
    assert cli("claim", "add", "--type", "fact", "--text", "x", "--source", sample_source)[0] == 1


def test_rule_synthetic(cli, project, root):
    f = root / "synthetic.md"
    f.write_text("Модельный респондент: меня раздражает внезапное списание денег за подписку.", encoding="utf-8")
    code, r = cli("source", "add", "--file", f, "--kind", "synthetic", "--title", "Синтетическое интервью")
    sid = r["data"]["id"]
    assert cli("claim", "add", "--type", "fact", "--text", "x", "--source", sid,
               "--quote", "меня раздражает внезапное списание денег")[0] == 1
    assert cli("claim", "add", "--type", "synthetic", "--text", "Респондента раздражает списание", "--source", sid)[0] == 0


def test_rule_unknown_needs_why(cli, project):
    assert cli("claim", "add", "--type", "unknown", "--text", "Доля отказов на шаге оплаты")[0] == 1
    assert cli("claim", "add", "--type", "unknown", "--text", "Доля отказов на шаге оплаты",
               "--why", "Нет открытых данных о воронке")[0] == 0


def test_depends_and_cycle(cli, project):
    cli("claim", "add", "--type", "hypothesis", "--text", "H1")
    assert cli("claim", "add", "--type", "hypothesis", "--text", "H2", "--depends", "C-001")[0] == 0
    assert cli("claim", "add", "--type", "hypothesis", "--text", "H3", "--depends", "C-099")[0] in (1, 3)
    code, r = cli("claim", "update", "C-001", "--depends", "C-002", "--reason", "цикл")
    assert code == 1 and r["error"]["code"] == "RULE_VIOLATION"


def test_update_marks_dependents(cli, project, root):
    cli("claim", "add", "--type", "hypothesis", "--text", "H1")
    cli("claim", "add", "--type", "hypothesis", "--text", "H2", "--depends", "C-001")
    code, r = cli("claim", "update", "C-001", "--text", "H1 уточнённая", "--reason", "новые данные", "--by", "human")
    assert code == 0 and r["data"]["marked_needs_review"] == ["C-002"]
    claims = {c["id"]: c for c in state(root, project, "claims")}
    assert claims["C-002"]["status"] == "needs_review"
    assert claims["C-001"]["history"][-1]["actor"] == "human"


def test_reviewed_clears_needs_review(cli, project, root):
    cli("claim", "add", "--type", "hypothesis", "--text", "H1")
    cli("claim", "add", "--type", "hypothesis", "--text", "H2", "--depends", "C-001")
    cli("claim", "add", "--type", "hypothesis", "--text", "H3", "--depends", "C-001")
    cli("claim", "update", "C-001", "--text", "H1 уточнённая", "--reason", "новые данные")
    code, _ = cli("claim", "update", "C-002", "--reviewed", "--reason", "вывод не меняется")
    assert code == 0
    code, _ = cli("claim", "update", "C-003", "--text", "H3 уточнённая", "--reason", "уточнили вслед за C-001")
    assert code == 0
    claims = {c["id"]: c for c in state(root, project, "claims")}
    assert claims["C-002"]["status"] == "active" and claims["C-002"]["text"] == "H2"
    assert claims["C-003"]["status"] == "active"
    code, _ = cli("claim", "update", "C-001", "--reviewed", "--reason", "нечего снимать")
    assert code != 0


def test_retracted_is_frozen_and_idempotent_add(cli, project, root):
    a = cli("claim", "add", "--type", "hypothesis", "--text", "H1")[1]
    b = cli("claim", "add", "--type", "hypothesis", "--text", "H1")[1]
    assert b["data"]["existing"] is True and a["data"]["id"] == b["data"]["id"]
    assert cli("claim", "retract", "C-001", "--reason", "опровергнута")[0] == 0
    assert cli("claim", "update", "C-001", "--text", "x", "--reason", "y")[0] == 1
    assert len(state(root, project, "claims")) == 1


def test_list_and_show(cli, sample_source):
    cli("claim", "add", "--type", "fact", "--text", "30%", "--source", sample_source, "--quote", QUOTE)
    cli("claim", "add", "--type", "hypothesis", "--text", "H", "--depends", "C-001")
    assert len(cli("claim", "list", "--type", "fact")[1]["data"]) == 1
    d = cli("claim", "show", "C-001")[1]["data"]
    assert d["dependents"] == ["C-002"] and d["sources"][0]["id"] == sample_source
