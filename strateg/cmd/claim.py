"""Реестр утверждений. T05."""
from __future__ import annotations

import argparse

from strateg.cmd import _common as c
from strateg.cmd.verify import check_claim_quote
from strateg.lib import clock
from strateg.lib.out import CliError, Result

FROZEN = {"retracted", "superseded"}


def _rule(msg: str) -> CliError:
    return CliError("RULE_VIOLATION", msg)


def _check_rules(slug: str, ctype: str, sources: list[str], quote: str | None, why: str | None) -> None:
    srcs = c.by_id(slug, "sources")
    for s in sources:
        if s not in srcs:
            raise _rule(f"Источник {s} не найден")
    kinds = {srcs[s]["kind"] for s in sources}
    if ctype == "fact":
        if not sources or not quote:
            raise _rule("Факт требует источника (--source) и дословной цитаты (--quote). Иначе это гипотеза или пробел")
        if any(srcs[s]["status"] != "active" for s in sources):
            raise _rule("Факт не может опираться на отозванный источник")
        if "synthetic" in kinds:
            raise _rule("Синтетические ответы не доказывают факты: используй тип synthetic или hypothesis")
    if "synthetic" in kinds and ctype not in ("synthetic", "hypothesis"):
        raise _rule("Утверждение из синтетического источника может быть только synthetic или hypothesis")
    if ctype == "unknown" and not why:
        raise _rule("Пробел (unknown) требует --why: почему мы этого не знаем")


def _graph(claims: list[dict]) -> dict[str, list[str]]:
    return {x["id"]: list(x.get("depends_on", [])) for x in claims}


def _has_cycle(graph: dict[str, list[str]], start: str) -> bool:
    stack, seen = list(graph.get(start, [])), set()
    while stack:
        n = stack.pop()
        if n == start:
            return True
        if n not in seen:
            seen.add(n)
            stack.extend(graph.get(n, []))
    return False


def add(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    op = c.op_for(args, "claim add")
    for r in c.records(slug, "claims"):
        if r.get("op_id") == op:
            return Result({"id": r["id"], "quote_verified": r.get("quote_verified"), "quote_score": r.get("quote_score"),
                           "existing": True})
    sources, deps = c.split_ids(args.source), c.split_ids(args.depends)
    _check_rules(slug, args.type, sources, args.quote, args.why)
    claims = c.by_id(slug, "claims")
    for d in deps:
        if d not in claims:
            raise _rule(f"Утверждение {d} не найдено")
    ok, score = check_claim_quote(slug, args.quote, sources)
    now = clock.now()
    rec = {"text": args.text, "type": args.type, "sources": sources, "quote": args.quote, "quote_verified": ok,
           "quote_score": score, "why_unknown": args.why, "confidence": args.confidence, "depends_on": deps,
           "stage": args.stage or c.stage_of(slug), "status": "active", "superseded_by": None, "reason": None,
           "created_by": args.by, "created_at": now, "updated_at": now, "op_id": op, "history": []}
    rec, existing = c.create(slug, "claims", "C", rec, "claim", "claim add")
    warnings = []
    if ok is False:
        warnings.append(f"Цитата для {rec['id']} не найдена в снимках источников (лучшее совпадение {score}). "
                        "Проверь формулировку или источник: валидатор не пропустит такой факт")
    return Result({"id": rec["id"], "quote_verified": ok, "quote_score": score, "existing": existing}, warnings=warnings)


def update(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    cur = c.get(slug, "claims", args.id)
    if cur["status"] in FROZEN:
        raise _rule(f"{args.id} в статусе {cur['status']}: правки запрещены, создай новое утверждение")
    patch: dict = {}
    for f in ("text", "type", "quote", "confidence"):
        v = getattr(args, f)
        if v is not None:
            patch[f] = v
    if args.why is not None:
        patch["why_unknown"] = args.why
    if args.source is not None:
        patch["sources"] = c.split_ids(args.source)
    if args.depends is not None:
        patch["depends_on"] = c.split_ids(args.depends)
    if cur["status"] == "needs_review" and (patch or getattr(args, "reviewed", False)):
        patch["status"] = "active"  # правка или явное «пересмотрено» снимает флаг пересмотра
    elif not patch and getattr(args, "reviewed", False):
        raise _rule(f"{args.id} не помечено «требует пересмотра»: снимать нечего")
    merged = {**cur, **patch}
    _check_rules(slug, merged["type"], merged["sources"], merged.get("quote"), merged.get("why_unknown"))
    claims = c.records(slug, "claims")
    ids_ = {x["id"] for x in claims}
    for d in merged["depends_on"]:
        if d not in ids_ or d == args.id:
            raise _rule(f"Недопустимая зависимость {d}")
    g = _graph(claims)
    g[args.id] = merged["depends_on"]
    if _has_cycle(g, args.id):
        raise _rule("Зависимости образуют цикл")
    if {"quote", "sources"} & set(patch):
        ok, score = check_claim_quote(slug, merged.get("quote"), merged["sources"])
        patch.update({"quote_verified": ok, "quote_score": score})
    rec = c.update(slug, "claims", args.id, patch, args.reason, args.by, "claim update")
    marked = []
    if {"text", "type", "sources"} & set(patch):
        for x in claims:
            if args.id in x.get("depends_on", []) and x["status"] == "active":
                c.update(slug, "claims", x["id"], {"status": "needs_review"}, f"изменилось {args.id}: {args.reason}",
                         "cli", "claim update")
                marked.append(x["id"])
    return Result({"id": rec["id"], "changed_fields": [f for f in patch if f in rec], "marked_needs_review": marked})


def retract(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    cur = c.get(slug, "claims", args.id)
    if cur["status"] in FROZEN:
        raise _rule(f"{args.id} уже в статусе {cur['status']}")
    c.update(slug, "claims", args.id, {"status": "retracted", "reason": args.reason}, args.reason, "agent", "claim retract")
    deps = [x["id"] for x in c.records(slug, "claims") if args.id in x.get("depends_on", [])]
    return Result({"id": args.id, "dependents": deps})


def supersede(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    cur = c.get(slug, "claims", args.id)
    c.get(slug, "claims", args.by_id)
    if cur["status"] in FROZEN:
        raise _rule(f"{args.id} уже в статусе {cur['status']}")
    c.update(slug, "claims", args.id, {"status": "superseded", "superseded_by": args.by_id, "reason": args.reason},
             args.reason, "agent", "claim supersede")
    return Result({"id": args.id, "superseded_by": args.by_id})


def list_(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    rows = [{"id": x["id"], "type": x["type"], "status": x["status"], "text": x["text"], "sources": x["sources"],
             "quote_verified": x.get("quote_verified")}
            for x in c.records(slug, "claims")
            if (not args.type or x["type"] == args.type) and (not args.status or x["status"] == args.status)
            and (not args.stage or x.get("stage") == args.stage) and (not args.source or args.source in x["sources"])]
    return Result(rows)


def show(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    rec = c.get(slug, "claims", args.id)
    srcs = c.by_id(slug, "sources")
    return Result({"record": rec,
                   "sources": [{"id": s, "title": srcs[s]["title"], "url": srcs[s].get("url") or srcs[s].get("file")}
                               for s in rec["sources"] if s in srcs],
                   "dependents": [x["id"] for x in c.records(slug, "claims") if args.id in x.get("depends_on", [])]})
