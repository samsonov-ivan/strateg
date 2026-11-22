"""Фаза 2: HTML-отчёт."""
from tests.conftest import QUOTE


def test_report_builds_with_refs(cli, sample_source, root, project):
    cli("claim", "add", "--type", "fact", "--text", "30% уходят", "--source", sample_source, "--quote", QUOTE)
    cli("claim", "add", "--type", "unknown", "--text", "Доля отказов на оплате", "--why", "нет данных")
    for t, k in [("Оставить", "status_quo"), ("Закрыть", "close"), ("Напоминание <до> списания", "change")]:
        cli("option", "add", "--title", t, "--kind", k, "--summary", t, "--based-on", "C-001")
    cli("objection", "add", "--option", "O-003", "--text", "Напоминание ускорит отмены", "--strength", "strong", "--by", "red_team")
    (root / "projects" / project / "docs" / "onepager.md").write_text(
        "## Что решаем\nПочему уходят **после** пробного [C-001].\n\n| A | B |\n|---|---|\n| 1 | [C-002] |\n", encoding="utf-8")
    code, r = cli("report")
    assert code == 0
    html = (root / "projects" / project / "out" / "report.html").read_text(encoding="utf-8")
    assert "<details id='C-001'>" in html and 'href="#C-001"' in html and "цитата найдена в источнике" in html
    assert "Напоминание &lt;до&gt; списания" in html and "<b>после</b>" in html and "<table>" in html
