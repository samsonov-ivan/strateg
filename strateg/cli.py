"""CLI агента «Стратег»: все группы, команды и флаги. Фаза 0 (Claude). НЕ МЕНЯТЬ — это контракт.

Обработчик — функция `handler(args: argparse.Namespace) -> out.Result | Any`,
адрес задаётся строкой "модуль:функция" и импортируется лениво.
"""
from __future__ import annotations

import argparse
import importlib
from typing import Any

from strateg.lib import out

STAGES = ["S0", "S1", "S2", "S3", "S4", "S5"]
GATES = ["G1", "G2", "G3", "G4"]


def _common() -> argparse.ArgumentParser:
    c = argparse.ArgumentParser(add_help=False)
    c.add_argument("--project", "-p", help="slug проекта (иначе STRATEG_PROJECT или projects/.current)")
    c.add_argument("--json", action="store_true", help="ответ одним JSON-объектом")
    return c


COMMON = _common()


def _group(sub: Any, name: str, help_: str) -> Any:
    return sub.add_parser(name, help=help_, description=help_).add_subparsers(
        dest="command", required=True, metavar="<команда>")


def _leaf(sub: Any, name: str, handler: str, help_: str) -> argparse.ArgumentParser:
    p = sub.add_parser(name, parents=[COMMON], help=help_, description=help_)
    p.set_defaults(handler=handler)
    return p


def _op(p: argparse.ArgumentParser) -> None:
    p.add_argument("--op-id", help="ключ идемпотентности; по умолчанию считается из аргументов")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m strateg", description="Стратег: детерминированные команды агента")
    top = parser.add_subparsers(dest="group", required=True, metavar="<группа>")

    # --- project ---------------------------------------------------------------
    g = _group(top, "project", "проект, этапы, ворота, допущения")
    p = _leaf(g, "new", "strateg.cmd.project:new", "создать проект")
    p.add_argument("slug")
    p.add_argument("--title", required=True)
    p.add_argument("--question")
    p = _leaf(g, "use", "strateg.cmd.project:use", "сделать проект текущим")
    p.add_argument("slug")
    _leaf(g, "list", "strateg.cmd.project:list_", "список проектов")
    _leaf(g, "status", "strateg.cmd.project:status", "статус текущего проекта")
    p = _leaf(g, "set", "strateg.cmd.project:set_", "изменить поля брифа")
    p.add_argument("--question")
    p.add_argument("--goal")
    p.add_argument("--audience")
    p.add_argument("--process-type", choices=["diagnosis", "go_to_market", "value_message", "fork", "other"])
    p.add_argument("--budget-usd", type=float)
    p.add_argument("--constraint", action="append", default=[])
    p.add_argument("--data", action="append", default=[])
    p = _leaf(g, "stage", "strateg.cmd.project:stage", "перейти на этап")
    p.add_argument("stage", choices=STAGES)
    p.add_argument("--note")
    p = _leaf(g, "gate", "strateg.cmd.project:gate", "записать решение человека на воротах")
    p.add_argument("gate", choices=GATES)
    p.add_argument("--status", required=True, choices=["approved", "changes", "opinion"],
                   help="opinion — мнение РП до рекомендации агента (G3); ворота остаются открытыми")
    p.add_argument("--note")
    p = _leaf(g, "assume", "strateg.cmd.project:assume", "записать допущение или отметить все просмотренными")
    p.add_argument("text", nargs="?")
    p.add_argument("--review", action="store_true")

    # --- source ----------------------------------------------------------------
    g = _group(top, "source", "реестр источников")
    p = _leaf(g, "add", "strateg.cmd.source:add", "добавить источник (URL или файл) со снимком")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--url")
    src.add_argument("--file")
    p.add_argument("--title")
    p.add_argument("--publisher")
    p.add_argument("--published", help="YYYY-MM-DD")
    p.add_argument("--kind", choices=["url", "file", "image", "dataset", "interview", "synthetic"])
    p.add_argument("--reliability", choices=list("ABCDEF"))
    p.add_argument("--reliability-by", choices=["jev", "claude", "human"])
    _op(p)
    p = _leaf(g, "list", "strateg.cmd.source:list_", "список источников")
    p.add_argument("--status", choices=["active", "retracted"])
    p.add_argument("--kind")
    p = _leaf(g, "show", "strateg.cmd.source:show", "запись и кусок снимка")
    p.add_argument("id")
    p.add_argument("--lines", help="диапазон строк, например 1-80")
    p = _leaf(g, "rate", "strateg.cmd.source:rate", "оценить надёжность A–F")
    p.add_argument("id")
    p.add_argument("--reliability", required=True, choices=list("ABCDEF"))
    p.add_argument("--by", required=True, choices=["jev", "claude", "human"])
    p = _leaf(g, "retract", "strateg.cmd.source:retract", "отозвать источник")
    p.add_argument("id")
    p.add_argument("--reason", required=True)

    # --- claim -----------------------------------------------------------------
    g = _group(top, "claim", "реестр утверждений")
    types = ["fact", "hypothesis", "forecast", "opinion", "unknown", "synthetic"]
    p = _leaf(g, "add", "strateg.cmd.claim:add", "добавить утверждение")
    p.add_argument("--text", required=True)
    p.add_argument("--type", required=True, choices=types)
    p.add_argument("--source", help="S-001,S-002")
    p.add_argument("--quote")
    p.add_argument("--why", help="для unknown: почему не знаем")
    p.add_argument("--confidence", choices=["low", "medium", "high"], default="medium")
    p.add_argument("--depends", help="C-001,C-002")
    p.add_argument("--stage", choices=STAGES)
    p.add_argument("--by", choices=["agent", "human"], default="agent")
    _op(p)
    p = _leaf(g, "update", "strateg.cmd.claim:update", "исправить утверждение (с историей)")
    p.add_argument("id")
    p.add_argument("--text")
    p.add_argument("--type", choices=types)
    p.add_argument("--source")
    p.add_argument("--quote")
    p.add_argument("--confidence", choices=["low", "medium", "high"])
    p.add_argument("--depends")
    p.add_argument("--why")
    p.add_argument("--reviewed", action="store_true", help="пересмотрено, менять нечего: снять флаг «требует пересмотра»")
    p.add_argument("--reason", required=True)
    p.add_argument("--by", choices=["agent", "human"], default="agent")
    p = _leaf(g, "retract", "strateg.cmd.claim:retract", "отозвать утверждение")
    p.add_argument("id")
    p.add_argument("--reason", required=True)
    p = _leaf(g, "supersede", "strateg.cmd.claim:supersede", "заменить утверждение новым")
    p.add_argument("id")
    p.add_argument("--by", required=True, dest="by_id", metavar="C-ID")
    p.add_argument("--reason", required=True)
    p = _leaf(g, "list", "strateg.cmd.claim:list_", "список утверждений")
    p.add_argument("--type", choices=types)
    p.add_argument("--status", choices=["active", "needs_review", "retracted", "superseded"])
    p.add_argument("--stage", choices=STAGES)
    p.add_argument("--source")
    p = _leaf(g, "show", "strateg.cmd.claim:show", "утверждение, источники, зависимые")
    p.add_argument("id")

    # --- option / objection ----------------------------------------------------
    g = _group(top, "option", "варианты")
    p = _leaf(g, "add", "strateg.cmd.option:add", "добавить вариант")
    p.add_argument("--title", required=True)
    p.add_argument("--kind", required=True, choices=["status_quo", "close", "change", "new"])
    p.add_argument("--summary", required=True)
    p.add_argument("--based-on")
    p.add_argument("--reversibility", choices=["high", "medium", "low"], default="medium")
    _op(p)
    p = _leaf(g, "set", "strateg.cmd.option:set_", "сменить статус варианта")
    p.add_argument("id")
    p.add_argument("--status", required=True, choices=["active", "chosen", "rejected", "retracted"])
    p.add_argument("--reason", required=True)
    p = _leaf(g, "list", "strateg.cmd.option:list_", "список вариантов")
    p.add_argument("--status", choices=["active", "chosen", "rejected", "retracted"])

    g = _group(top, "objection", "возражения к вариантам")
    p = _leaf(g, "add", "strateg.cmd.option:objection_add", "добавить возражение")
    p.add_argument("--option", required=True)
    p.add_argument("--text", required=True)
    p.add_argument("--strength", required=True, choices=["strong", "medium"])
    p.add_argument("--by", required=True, choices=["red_team", "human", "agent"])
    p.add_argument("--based-on")
    _op(p)
    p = _leaf(g, "respond", "strateg.cmd.option:objection_respond", "ответить на возражение")
    p.add_argument("id")
    p.add_argument("--response", required=True)
    p = _leaf(g, "list", "strateg.cmd.option:objection_list", "список возражений")
    p.add_argument("--option")

    # --- decision / commitment / review ---------------------------------------
    g = _group(top, "decision", "решения")
    p = _leaf(g, "add", "strateg.cmd.decision:add", "записать решение")
    p.add_argument("--option", required=True)
    p.add_argument("--rationale", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--by", required=True, help="кто решил, например «РП»")
    p.add_argument("--based-on")
    p.add_argument("--metric", action="append", required=True, help="имя|база|цель|YYYY-MM-DD")
    p.add_argument("--trigger", action="append", required=True, help="date:YYYY-MM-DD | metric:<текст> | claim:C-ID")
    _op(p)
    p = _leaf(g, "set", "strateg.cmd.decision:set_", "пересмотреть или отменить решение")
    p.add_argument("id")
    p.add_argument("--status", required=True, choices=["revised", "revoked"])
    p.add_argument("--reason", required=True)

    g = _group(top, "commitment", "обязательства")
    p = _leaf(g, "add", "strateg.cmd.decision:commitment_add", "добавить обязательство")
    p.add_argument("--decision", required=True)
    p.add_argument("--what", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--due", required=True, help="YYYY-MM-DD")
    _op(p)
    p = _leaf(g, "done", "strateg.cmd.decision:commitment_done", "отметить выполненным")
    p.add_argument("id")
    p = _leaf(g, "drop", "strateg.cmd.decision:commitment_drop", "снять обязательство")
    p.add_argument("id")
    p.add_argument("--reason", required=True)

    p = _leaf(top, "review", "strateg.cmd.decision:review", "что решать сейчас: просрочки, триггеры, устаревшее")
    p.add_argument("--today", help="YYYY-MM-DD (для тестов)")

    # --- проверки ----------------------------------------------------------------
    g = _group(top, "verify", "проверка цитат")
    _leaf(g, "quotes", "strateg.cmd.verify:quotes", "перепроверить все цитаты по снимкам")

    g = _group(top, "strategy", "записка для руководителя")
    _leaf(g, "check", "strateg.cmd.strategy:check", "сверить ссылки, опорные строки и расчёты в out/strategy.md")

    p = _leaf(top, "validate", "strateg.cmd.validate:run", "проверки целостности V01–V14")
    p.add_argument("--stage", choices=STAGES)

    # --- база знаний и влияние ----------------------------------------------------
    g = _group(top, "kb", "база знаний")
    p = _leaf(g, "search", "strateg.cmd.kb:search", "поиск по утверждениям, источникам, знаниям")
    p.add_argument("query")
    p.add_argument("--scope", choices=["claims", "sources", "knowledge", "docs", "all"], default="all")
    p.add_argument("--limit", type=int, default=10)
    p.add_argument("--include-retracted", action="store_true")
    p = _leaf(g, "links", "strateg.cmd.kb:links", "связи объекта")
    p.add_argument("id")

    p = _leaf(top, "impact", "strateg.cmd.impact:run", "что затронуто изменением")
    p.add_argument("--changed", required=True, help="S-003,C-010")
    p.add_argument("--apply", action="store_true")
    p.add_argument("--reason")

    # --- стоимость и данные -----------------------------------------------------
    p = _leaf(top, "cost", "strateg.cmd.cost:run", "стоимость и время по этапам")
    p.add_argument("--transcripts", help="папка транскриптов Claude Code")
    p.add_argument("--prices", help="путь к таблице цен (по умолчанию config/prices.json)")

    g = _group(top, "data", "анализ данных")
    p = _leaf(g, "profile", "strateg.cmd.data:profile", "профиль качества таблицы")
    p.add_argument("path")
    p.add_argument("--sheet")
    p = _leaf(g, "cohort", "strateg.cmd.data:cohort", "матрица удержания по когортам")
    p.add_argument("path")
    p.add_argument("--user", required=True)
    p.add_argument("--start", required=True)
    p.add_argument("--event", required=True)
    p.add_argument("--period", choices=["week", "month"], default="month")

    # --- защита -------------------------------------------------------------------
    g = _group(top, "guard", "сканеры и обезличивание")
    p = _leaf(g, "scan-injection", "strateg.cmd.guard:cli_scan_injection", "поиск внедрённых инструкций")
    p.add_argument("path")
    p = _leaf(g, "secrets", "strateg.cmd.guard:cli_secrets", "поиск секретов")
    p.add_argument("paths", nargs="*")
    p.add_argument("--staged", action="store_true")
    p.add_argument("--history", action="store_true")
    p = _leaf(g, "redact", "strateg.cmd.guard:cli_redact", "обезличить расшифровку")
    p.add_argument("path")
    p.add_argument("--out")
    p.add_argument("--names", help="«Имя Фамилия,Имя2»")

    # --- маршрутизация ------------------------------------------------------------
    g = _group(top, "route", "маршрутизация моделей")
    p = _leaf(g, "classify-claim", "strateg.route.cascade:cli_classify_claim", "проверить тип утверждения каскадом")
    p.add_argument("id")
    p = _leaf(g, "correct", "strateg.route.cascade:cli_correct", "исправить решение маршрутизатора")
    p.add_argument("id")
    p.add_argument("--answer", required=True)
    p.add_argument("--reason", required=True)
    _leaf(g, "stats", "strateg.route.cascade:cli_stats", "статистика маршрутизации")
    p = _leaf(g, "tune", "strateg.route.cascade:cli_tune", "подобрать порог уверенности")
    p.add_argument("--task", required=True)

    # --- окружение и отчёт ---------------------------------------------------------
    _leaf(top, "doctor", "strateg.cmd.doctor:run", "проверка окружения")
    _leaf(top, "report", "strateg.report.build:run", "HTML-отчёт проекта (фаза 2)")
    return parser


def _resolve(spec: str):
    module, func = spec.split(":")
    try:
        return getattr(importlib.import_module(module), func)
    except (ImportError, AttributeError):
        raise out.not_implemented(spec) from None


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:  # argparse: --help или неверные аргументы
        return int(e.code or 0)
    as_json = bool(getattr(args, "json", False))
    try:
        result = _resolve(args.handler)(args)
    except out.CliError as err:
        out.emit_error(err, as_json)
        return err.exit_code
    if not isinstance(result, out.Result):
        result = out.Result(data=result)
    out.emit(result, as_json)
    return result.exit_code
