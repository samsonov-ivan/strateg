"""Проверки записки через публичную команду CLI."""
import json

import pytest

from tests.conftest import QUOTE, read_jsonl

MEMO = """# Как сократить очередь в мастерской
За последнюю неделю доступность окна изменилась [S-001].
**Альтернатива** — перенести час приёма в текущем расписании.
**Проверка** — случайно назначить дни, считать время до приёма за неделю.
**Условие пересмотра** — изменить график, если очередь не сократится.
"""


def write_memo(root, slug, appendix):
    (root / "projects" / slug / "out" / "strategy.md").write_text(MEMO + appendix, encoding="utf-8")


def test_checked_memo_preserves_stage_and_catches_changed_number(cli, root, project, sample_source):
    project_file = root / "projects" / project / "project.json"
    before = project_file.read_bytes()
    calc = "```calc\nЧасы приёма | 2 * (3.125 + 1) | 8.3 | ч\nДни | 1 / 3 | 0.33 | дня\n```"
    write_memo(root, project, calc)
    code, result = cli("strategy", "check", "--project", project)
    assert code == 0 and result["data"]["valid_equations"] == 2
    assert project_file.read_bytes() == before
    write_memo(root, project, calc.replace("| 8.3 |", "| 8.2 |"))
    code, result = cli("strategy", "check")
    assert code == 1 and "8.3" in result["data"]["errors"][0]


def test_qualitative_memo_tracks_actual_evidence(cli, root, project, sample_source):
    write_memo(root, project, "```no-calc\nЧисло свободных окон уточнит диспетчер по журналу записи.\n```")
    assert cli("strategy", "check")[0] == 0
    cli("source", "retract", sample_source, "--reason", "Обновили расписание")
    code, result = cli("strategy", "check")
    assert code == 1 and "S-001" in " ".join(result["data"]["errors"])


@pytest.mark.parametrize("expression", ["open('example')", "1 / 0", "2 ** 100000", "6 // 3", "[][0]", "8"])
def test_invalid_equations_report_line_error(expression, cli, root, project, sample_source):
    write_memo(root, project, f"```calc\nПереносы | {expression} | 8 | смен\n```")
    code, result = cli("strategy", "check")
    assert code == 1 and result["data"]["valid_equations"] == 0
    assert "Строка 7" in result["data"]["errors"][0]


def test_examples_or_comments_do_not_satisfy_checks(cli, root, project, sample_source):
    path = root / "projects" / project / "out" / "strategy.md"
    assert cli("strategy", "check")[0] == 3
    path.write_text("<!--\n" + MEMO + "-->\n~~~markdown\n```calc\nЧасы | 3 + 2 | 5 | ч\n```\n~~~\n")
    code, result = cli("strategy", "check")
    assert code == 1 and len(result["data"]["errors"]) == 5


def test_empty_decision_line_is_not_filled_by_next_paragraph(cli, root, project, sample_source):
    path = root / "projects" / project / "out" / "strategy.md"
    text = MEMO.replace("— перенести", "—\nМожно перенести") + "```calc\nДни | 1 + 1 | 2 | дня\n```"
    path.write_text(text, encoding="utf-8")
    code, result = cli("strategy", "check")
    assert code == 1 and "Альтернатива" in result["data"]["errors"][0]


def cite_claim(root, project, ref):
    text = MEMO.replace("[S-001]", f"[{ref}]") + "```no-calc\nДанные о свободных окнах запросим у диспетчера.\n```"
    (root / "projects" / project / "out" / "strategy.md").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("direct", [True, False])
def test_s0_full_chain_detects_retracted_source(cli, root, project, sample_source, direct):
    assert cli("claim", "add", "--type", "fact", "--text", "Доля отмен", "--source", sample_source, "--quote", QUOTE)[0] == 0
    assert cli("claim", "add", "--type", "forecast", "--text", "Прогноз спроса", "--depends", "C-001")[0] == 0
    assert cli("claim", "add", "--type", "hypothesis", "--text", "Стоит перенести смену", "--depends", "C-002")[0] == 0
    cite_claim(root, project, "C-001" if direct else "C-003")
    assert cli("strategy", "check")[0] == 0
    assert cli("source", "retract", sample_source, "--reason", "Ошибка исходных данных")[0] == 0
    code, result = cli("strategy", "check")
    chain = "C-001 → S-001" if direct else "C-003 → C-002 → C-001 → S-001"
    assert code == 1 and any(chain in error for error in result["data"]["errors"])


def test_fact_quote_checked_against_current_original(cli, root, project, sample_source):
    cli("claim", "add", "--type", "fact", "--text", "Доля отмен", "--source", sample_source, "--quote", QUOTE)
    cite_claim(root, project, "C-001")
    snapshot = root / "projects" / project / "materials" / "snapshots" / f"{sample_source}.md"
    snapshot.write_text("Произошла замена данных и вывод требует повторной сверки.", encoding="utf-8")
    code, result = cli("strategy", "check")
    assert code == 1 and "цитата" in " ".join(result["data"]["errors"])


def test_transitive_needs_review_without_fabricated_source(cli, root, project):
    cli("claim", "add", "--type", "unknown", "--text", "Сколько окон?", "--why", "График ещё не получен")
    cli("claim", "add", "--type", "hypothesis", "--text", "Окна можно перенести", "--depends", "C-001")
    cli("claim", "add", "--type", "forecast", "--text", "Доступность повысится", "--depends", "C-002")
    cite_claim(root, project, "C-003")
    assert cli("strategy", "check")[0] == 0
    cli("claim", "update", "C-001", "--text", "Неизвестно число доступных смен", "--reason", "Уточнён знаменатель")
    code, result = cli("strategy", "check")
    assert code == 1 and any("C-003 → C-002" in error and "needs_review" in error for error in result["data"]["errors"])


def test_imported_fact_cannot_use_quote_only_from_synthetic_source(cli, root, project, sample_source):
    text = "Модельный участник предпочитает записываться за час до приёма."
    original = root / "respondent.md"
    original.write_text(text, encoding="utf-8")
    synthetic = cli("source", "add", "--kind", "synthetic", "--file", original)[1]["data"]["id"]
    cli("claim", "add", "--type", "synthetic", "--source", synthetic, "--text", "Предпочтение роли", "--quote", text)
    cite_claim(root, project, "C-001")
    assert cli("strategy", "check")[0] == 0
    # Повреждённый импорт может пропустить правила claim add и оставить сохранённый quote_verified=true.
    registry = root / "projects" / project / "state" / "claims.jsonl"
    claim = read_jsonl(registry)[0]
    claim.update(type="fact", sources=[synthetic, sample_source])
    registry.write_text(json.dumps(claim, ensure_ascii=False) + "\n", encoding="utf-8")
    code, result = cli("strategy", "check")
    assert code == 1 and any("несинтетически" in message for message in result["data"]["errors"])


def test_missing_nested_record_reports_chain(cli, root, project, sample_source):
    cli("claim", "add", "--type", "hypothesis", "--text", "Окна в рабочее время", "--source", sample_source)
    cli("claim", "add", "--type", "forecast", "--text", "Число доступных окон", "--depends", "C-001")
    cite_claim(root, project, "C-002")
    # Имитируем неполный перенос реестра проекта.
    (root / "projects" / project / "state" / "sources.jsonl").write_text("", encoding="utf-8")
    code, result = cli("strategy", "check")
    assert code == 1 and any("C-002 → C-001 → S-001" in message for message in result["data"]["errors"])
