"""T09: база знаний. T10: граф влияния."""
from tests.conftest import QUOTE, state


def test_search_finds_claim_and_source(cli, sample_source):
    cli("claim", "add", "--type", "fact", "--text", "Треть подписчиков уходит после пробного периода",
        "--source", sample_source, "--quote", QUOTE)
    code, r = cli("kb", "search", "подписчики уходят после пробного", "--scope", "claims")
    assert code == 0 and r["data"][0]["ref"] == "C-001"
    hits = cli("kb", "search", "онбординг", "--scope", "sources")[1]["data"]
    assert hits and hits[0]["ref"].startswith(f"{sample_source}#")
    assert all(len(h["snippet"]) <= 240 for h in hits)


def test_search_excludes_retracted_and_marks_agent_output(cli, project, root):
    cli("claim", "add", "--type", "hypothesis", "--text", "Отток вызван сезонностью")
    cli("claim", "retract", "C-001", "--reason", "опровергнута")
    assert cli("kb", "search", "сезонностью", "--scope", "claims")[1]["data"] == []
    assert cli("kb", "search", "сезонностью", "--scope", "claims", "--include-retracted")[1]["data"]
    (root / "projects" / project / "docs" / "situation.md").write_text("## Что известно\nСезонность оттока не подтвердилась.\n",
                                                                         encoding="utf-8")
    assert cli("kb", "search", "сезонность", "--scope", "claims")[1]["data"] == []
    docs = cli("kb", "search", "сезонность", "--scope", "docs")[1]["data"]
    assert docs and all(h["agent_output"] is True for h in docs)


def test_search_across_projects(cli, project):
    cli("claim", "add", "--type", "hypothesis", "--text", "Семейный тариф интересен родителям")
    cli("project", "new", "other", "--title", "Другой")
    assert cli("kb", "search", "семейный тариф", "--scope", "claims")[1]["data"] == []
    hits = cli("kb", "search", "семейный тариф", "--scope", "claims", "--project", "all")[1]["data"]
    assert hits and hits[0]["ref"] == "C-001"


def _chain(cli, root, project, sid):
    cli("claim", "add", "--type", "fact", "--text", "30%", "--source", sid, "--quote", QUOTE)
    cli("claim", "add", "--type", "hypothesis", "--text", "Причина — списание", "--depends", "C-001")
    cli("claim", "add", "--type", "hypothesis", "--text", "Независимая")
    cli("option", "add", "--title", "Напоминание", "--kind", "change", "--summary", "s", "--based-on", "C-002")
    cli("decision", "add", "--option", "O-001", "--rationale", "r", "--owner", "РП", "--by", "РП",
        "--metric", "m|1|2|2026-12-31", "--trigger", "date:2026-12-31")
    (root / "projects" / project / "docs" / "options.md").write_text(
        "## Варианты\nНапоминание до списания [C-002].\n\n## Рекомендация\nНезависимо [C-003].\n", encoding="utf-8")


def test_links(cli, sample_source, root, project):
    _chain(cli, root, project, sample_source)
    d = cli("kb", "links", "C-002")[1]["data"]
    assert d["depends_on"] == ["C-001"] and d["options"] == ["O-001"]
    assert d["cited_in"][0]["file"].endswith("options.md")


def test_impact_finds_delivered_memo_intro_and_section(cli, sample_source, root, project):
    _chain(cli, root, project, sample_source)
    path = root / "projects" / project / "out" / "strategy.md"
    path.write_text("Предложение [C-002].\n\n## План\nПроверить [C-001].\n", encoding="utf-8")
    result = cli("impact", "--changed", sample_source)[1]["data"]
    headings = {s["heading"] for s in result["doc_sections"] if s["file"] == "out/strategy.md"}
    assert headings == {"", "План"}
    links = cli("kb", "links", "C-002")[1]["data"]["cited_in"]
    assert {"file": "out/strategy.md", "line": 1} in links


def test_impact_chain_and_apply(cli, sample_source, root, project):
    _chain(cli, root, project, sample_source)
    code, r = cli("impact", "--changed", sample_source)
    affected = {a["id"] for a in r["data"]["affected"]}
    assert code == 0 and {"C-001", "C-002", "O-001", "D-001"} <= affected and "C-003" not in affected
    assert {"file": "options.md", "heading": "Варианты"} in r["data"]["doc_sections"]
    assert state(root, project, "claims")[0]["status"] == "active"  # без --apply ничего не меняется
    assert cli("impact", "--changed", sample_source, "--apply", "--reason", "источник обновлён")[0] == 0
    claims = {c["id"]: c["status"] for c in state(root, project, "claims")}
    assert claims == {"C-001": "needs_review", "C-002": "needs_review", "C-003": "active"}
    assert state(root, project, "decisions")[0]["review_flag"] is True
    n = len(state(root, project, "journal"))
    cli("impact", "--changed", sample_source, "--apply", "--reason", "источник обновлён")
    assert len(state(root, project, "journal")) <= n + 1
