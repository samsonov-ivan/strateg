"""Проверка передаваемой записки. Оценка доводов и сверка исходных данных остаются у читателя."""
from __future__ import annotations

import argparse
import ast
import operator
import re
from collections import deque
from decimal import ROUND_HALF_UP, Decimal, DecimalException, localcontext
from graphlib import CycleError, TopologicalSorter

from strateg.cmd import _common as c
from strateg.cmd.source import snapshot_text
from strateg.cmd.verify import quote_match
from strateg.lib import paths
from strateg.lib.out import CliError, Result

_FIELDS = ("Альтернатива", "Проверка", "Условие пересмотра")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_OPERATORS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
_DECIMAL = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)", re.ASCII)


def _calculate(expression: str) -> Decimal:
    """Разрешает только арифметические узлы и читает десятичные числа из исходной строки."""
    if len(expression) > 800 or not re.fullmatch(r"[0-9.+*/()\s-]+", expression):
        raise ValueError("допустимы десятичные числа, скобки и операции + - * / **")
    tree = ast.parse(expression, mode="eval")
    if not any(isinstance(node, ast.BinOp) for node in ast.walk(tree)):
        raise ValueError("покажите действие, связывающее исходные числа с результатом")

    def value(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            return Decimal(ast.get_source_segment(expression, node))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            number = value(node.operand)
            return -number if isinstance(node.op, ast.USub) else number
        if isinstance(node, ast.BinOp):
            left, right = value(node.left), value(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) <= 120:
                return left ** right
            if type(node.op) in _OPERATORS:
                return _OPERATORS[type(node.op)](left, right)
        raise ValueError("неподдерживаемое действие или слишком большая степень")

    return value(tree.body)


def _equation(line: str) -> str | None:
    parts = [part.strip() for part in line.split("|")]
    if len(parts) != 4 or not all(parts):
        return "ожидается строка «название | выражение | результат | единица»"
    label, expression, displayed, _unit = parts
    if not _DECIMAL.fullmatch(displayed) or len(displayed) > 50:
        return f"{label} — результат запишите десятичным числом с точкой"
    try:
        with localcontext() as ctx:
            ctx.prec, ctx.Emin, ctx.Emax = 60, -1000, 1000
            expected = Decimal(displayed)
            calculated = _calculate(expression).quantize(expected, rounding=ROUND_HALF_UP)
    except (DecimalException, ValueError, SyntaxError, RecursionError) as exc:
        return f"{label} — ошибка выражения ({exc})"
    if expected != calculated:
        return f"{label} — записано {displayed}, расчёт даёт {calculated}"
    return None


def _parts(text: str) -> tuple[list[str], list[tuple[str, int, list[str]]], list[str]]:
    """Из обычного Markdown выбирает текст и размеченные расчёты, исключая примеры в других блоках."""
    visible, blocks, errors = [], [], []
    fence, kind, start, body = "", "", 0, []
    for n, line in enumerate(text.splitlines(), 1):
        marker = _FENCE.match(line)
        if not fence:
            if marker:
                fence, kind, start, body = marker[1], marker[2].strip(), n, []
            else:
                visible.append(line)
        elif marker and marker[1][0] == fence[0] and len(marker[1]) >= len(fence) and not marker[2].strip():
            if kind in ("calc", "no-calc"):
                blocks.append((kind, start, body))
            fence = ""
        else:
            body.append(line)
    if fence:
        errors.append(f"Строка {start} — не закрыт блок Markdown")
    return visible, blocks, errors


def _evidence_errors(slug: str, refs: list[str]) -> list[str]:
    """Проверяет только основания записки, включая источники и предшественников её выводов."""
    claims, sources = c.by_id(slug, "claims"), c.by_id(slug, "sources")
    snapshots, errors = {}, []
    graph = TopologicalSorter()
    pending = deque(refs)
    parent = dict.fromkeys(refs)
    project = paths.project_dir(slug).resolve()

    def error(ref: str, message: str) -> None:
        chain = [ref]
        while parent[chain[-1]] is not None:
            chain.append(parent[chain[-1]])
        errors.append(" → ".join(reversed(chain)) + " — " + message)

    def read_source(sid: str) -> str:
        if sid not in snapshots:
            try:
                path = (project / sources[sid]["snapshot"]).resolve()
                if not path.is_relative_to(project) or not path.is_file():
                    raise OSError
                snapshots[sid] = snapshot_text(slug, sources[sid])
            except (OSError, UnicodeError, ValueError, RuntimeError):
                error(sid, "снимок отсутствует или недоступен в папке проекта")
                snapshots[sid] = ""
        return snapshots[sid]

    while pending:
        ref = pending.popleft()
        item = (claims if ref.startswith("C-") else sources).get(ref)
        if item is None:
            error(ref, "запись отсутствует")
            continue
        if item["status"] != "active":
            error(ref, f"статус {item['status']}, требуется пересмотр")
        if ref not in claims:
            read_source(ref)
            continue
        source_ids = item.get("sources", [])
        deps = item.get("depends_on", [])
        graph.add(ref, *deps)
        for target in [*deps, *source_ids]:
            if target not in parent:
                parent[target] = ref
                pending.append(target)
        if item["type"] != "fact":
            continue
        eligible = [sid for sid in source_ids if sid in sources
                    and sources[sid]["kind"] != "synthetic" and sources[sid]["status"] == "active"]
        if not eligible or item.get("quote_verified") is not True:
            error(ref, "у факта нет проверенной цитаты из активного несинтетического источника")
            continue
        if not any(quote_match(item.get("quote"), read_source(sid))[0] for sid in eligible):
            error(ref, "цитата факта больше не подтверждается снимками активных несинтетических источников")
    try:
        graph.prepare()
    except CycleError as exc:
        errors.append("Цикл в основаниях записки — " + " → ".join(exc.args[1]))
    return errors


def check(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    path = paths.project_dir(slug) / "out" / "strategy.md"
    if not path.is_file():
        raise CliError("NOT_FOUND", "Сохраните записку в out/strategy.md и повторите проверку")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CliError("IO_ERROR", "Не удалось прочитать out/strategy.md в UTF-8") from exc
    visible, blocks, errors = _parts(c.COMMENT_RX.sub(lambda m: "\n" * m[0].count("\n"), text))
    prose = "\n".join(visible)
    for field in _FIELDS:
        if not re.search(rf"^[ \t]*(?:[-*] )?\*\*{field}\*\*[ \t]*[—–-][^\n]*\w", prose, re.M):
            errors.append(f"Добавьте отдельную строку «**{field}** — …» и её обоснование")

    refs = sorted({ref for ref in c.REF_RX.findall(prose) if ref[0] in "CS"})
    if not refs:
        errors.append("Укажите источник или утверждение в тексте записки, например [S-001]")
    errors.extend(_evidence_errors(slug, refs))

    modes = {kind for kind, _, _ in blocks}
    if len(modes) != 1:
        errors.append("Используйте calc с расчётами либо no-calc с объяснением отсутствия чисел")
    count = 0
    for kind, start, body in blocks:
        rows = [(n, line) for n, line in enumerate(body, start + 1) if line.strip()]
        if not rows:
            errors.append(f"Строка {start} — пустой блок {kind}")
        if kind == "no-calc":
            if not re.search(r"\w", " ".join(body)):
                errors.append(f"Строка {start} — укажите, каких данных не хватает")
            continue
        for n, line in rows:
            message = _equation(line)
            if message:
                errors.append(f"Строка {n} — {message}")
            else:
                count += 1
    data = {"file": "out/strategy.md", "valid_equations": count, "references": refs, "errors": errors}
    return Result(data, exit_code=int(bool(errors)), message="Исправьте ошибки в итоговой записке" if errors else None)
