"""T08: проверка цитат и валидатор V01–V14."""
import json

from tests.conftest import QUOTE, advance


def _checks(r, level="error"):
    return {c["check"] for c in r["data"]["checks"] if c["level"] == level}


def _docs(root, slug):
    return root / "projects" / slug / "docs"


def test_fresh_project_valid(cli, project):
    code, r = cli("validate")
    assert code == 0 and r["data"]["errors"] == 0


def test_verify_quotes_detects_broken_snapshot(cli, sample_source, root, project):
    cli("claim", "add", "--type", "fact", "--text", "30%", "--source", sample_source, "--quote", QUOTE)
    assert cli("verify", "quotes")[0] == 0
    snap = root / "projects" / project / "materials" / "snapshots" / f"{sample_source}.md"
    snap.write_text(snap.read_text(encoding="utf-8").replace("около 30%", "примерно десятая часть"), encoding="utf-8")
    code, r = cli("verify", "quotes")
    assert code == 1 and r["data"]["failed"][0]["id"] == "C-001"


def test_v03_unverified_fact(cli, sample_source):
    cli("claim", "add", "--type", "fact", "--text", "x", "--source", sample_source,
        "--quote", "этого текста в источнике совсем нет и не было")
    advance(cli, "S2")
    code, r = cli("validate", "--stage", "S1")
    assert code == 1 and "V03" in _checks(r)


def test_v04_retracted_source(cli, sample_source):
    cli("claim", "add", "--type", "fact", "--text", "30%", "--source", sample_source, "--quote", QUOTE)
    cli("source", "retract", sample_source, "--reason", "устарел")
    advance(cli, "S1")
    assert "V04" in _checks(cli("validate")[1])


def test_v06_options_rules(cli, project):
    cli("claim", "add", "--type", "hypothesis", "--text", "H")
    cli("option", "add", "--title", "Оставить", "--kind", "status_quo", "--summary", "s")
    cli("option", "add", "--title", "Изменить", "--kind", "change", "--summary", "s")
    advance(cli, "S3")
    code, r = cli("validate", "--stage", "S2")
    assert code == 1 and "V06" in _checks(r)
    msgs = " ".join(c["message"] for c in r["data"]["checks"] if c["check"] == "V06")
    assert "close" in msgs or "закрыть" in msgs.lower()


def test_v07_missing_sections(cli, project, root):
    advance(cli, "S1")
    (_docs(root, project) / "brief.md").write_text("# Бриф\n\n## Вопрос\nПочему падает удержание?\n", encoding="utf-8")
    code, r = cli("validate")
    assert code == 1 and "V07" in _checks(r)


def test_v08_and_v10_doc_refs(cli, project, root):
    cli("claim", "add", "--type", "hypothesis", "--text", "H")
    f = root / "syn.md"
    f.write_text("Модельный респондент говорит, что его раздражают списания.", encoding="utf-8")
    sid = cli("source", "add", "--file", f, "--kind", "synthetic")[1]["data"]["id"]
    cli("claim", "add", "--type", "synthetic", "--text", "Раздражают списания", "--source", sid)
    advance(cli, "S1")
    (_docs(root, project) / "situation.md").write_text(
        "## Что известно\nСм. [C-001] и [C-077].\nРеспондентов раздражают списания [C-002].\n", encoding="utf-8")
    r = cli("validate")[1]
    assert {"V08", "V10"} <= _checks(r)


def test_v09_promises_table(cli, sample_source, project, root):
    cli("claim", "add", "--type", "fact", "--text", "30%", "--source", sample_source, "--quote", QUOTE)
    cli("claim", "add", "--type", "hypothesis", "--text", "H")
    advance(cli, "S4")
    (_docs(root, project) / "strategy_comms.md").write_text(
        "## Обещания и подтверждения\n\n| Обещание | Свойство продукта | Подтверждение |\n|---|---|---|\n"
        "| Без внезапных списаний | Напоминание за 3 дня | [C-001] |\n| Лучший сервис | | [C-002] |\n", encoding="utf-8")
    code, r = cli("validate", "--stage", "S3")
    assert code == 1 and "V09" in _checks(r)


def test_v11_stage_beyond_gate(cli, project, root):
    p = root / "projects" / project / "project.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["stage"] = "S2"
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert "V11" in _checks(cli("validate")[1])


def test_v13_warns_without_unknowns(cli, project):
    advance(cli, "S2")
    assert "V13" in _checks(cli("validate", "--stage", "S1")[1], level="warn")


def test_v06_rejected_options_still_count(cli, project):
    cli("claim", "add", "--type", "hypothesis", "--text", "H")
    for t, k in (("Оставить", "status_quo"), ("Закрыть", "close"), ("Изменить", "change")):
        cli("option", "add", "--title", t, "--kind", k, "--summary", "s")
    cli("option", "set", "O-001", "--status", "rejected", "--reason", "РП: потери копятся")
    cli("option", "set", "O-002", "--status", "rejected", "--reason", "РП: не закрываем")
    cli("option", "set", "O-003", "--status", "chosen", "--reason", "РП")
    msgs = [c["message"] for c in cli("validate", "--stage", "S2")[1]["data"]["checks"] if c["check"] == "V06"]
    assert not any("вариантов" in m or "оставить как есть" in m or "закрыть" in m for m in msgs)
