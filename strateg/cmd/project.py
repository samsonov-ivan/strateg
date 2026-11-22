"""Проект, этапы, ворота, допущения. T02."""
from __future__ import annotations

import argparse
import re
import shutil

from strateg.cmd import validate
from strateg.cmd._common import ORDER, load_project, records, save_project, slug_of, stage_index
from strateg.lib import clock, ids, journal, paths, store
from strateg.lib.out import CliError, Result

SLUG_RX = re.compile(r"^[a-z0-9][a-z0-9-]{2,39}$")
GATE_OF = {"S0": "G1", "S1": "G2", "S2": "G3", "S3": "G4"}
BRIEF = "# Бриф\n\n## Вопрос\n\n## Цель\n\n## Получатель результата\n\n## Ограничения\n\n## Доступные данные\n\n## Допущения\n"


def new(args: argparse.Namespace) -> Result:
    slug = args.slug
    if not SLUG_RX.match(slug):
        raise CliError("BAD_ARGS", "slug: латиница в нижнем регистре, цифры и дефис, 3–40 символов")
    d = paths.project_dir(slug)
    if d.exists():
        raise CliError("DUPLICATE_SLUG", f"Проект {slug} уже существует")
    for sub in ["materials/inbox", "materials/snapshots", "state", "docs", "out"]:
        (d / sub).mkdir(parents=True, exist_ok=True)
    now = clock.now()
    proj = {"slug": slug, "title": args.title, "created_at": now, "question": args.question, "goal": None,
            "audience": None, "constraints": [], "data_available": [], "process_type": None, "stage": "S0",
            "stage_history": [{"stage": "S0", "at": now, "note": None}],
            "gates": {g: {"status": "pending", "at": None, "note": None} for g in ["G1", "G2", "G3", "G4"]},
            "assumptions": [], "budget_usd": None}
    save_project(slug, proj)
    tpl = paths.knowledge_dir() / "templates"
    if tpl.is_dir():
        for f in tpl.glob("*.md"):
            target = d / ("brief.md" if f.name == "brief.md" else f"docs/{f.name}")
            shutil.copy(f, target)
    if not (d / "brief.md").exists():
        (d / "brief.md").write_text(BRIEF, encoding="utf-8")
    paths.set_current(slug)
    journal.log(slug, "cli", f"project new {slug}", {"command": "project new"}, stage="S0")
    return Result({"slug": slug, "path": str(d)}, human=f"Создан проект {slug}: {d}")


def use(args: argparse.Namespace) -> Result:
    slug = paths.current_slug(args.slug)
    paths.set_current(slug)
    return Result({"slug": slug})


def list_(args: argparse.Namespace) -> Result:
    rows = []
    pd = paths.projects_dir()
    for p in sorted(pd.glob("*/project.json")) if pd.exists() else []:
        proj = store.read_json(p)
        ev = store.read_jsonl(p.parent / "state" / "journal.jsonl")
        rows.append({"slug": proj["slug"], "title": proj["title"], "stage": proj["stage"],
                     "updated_at": ev[-1]["at"] if ev else proj["created_at"]})
    return Result(rows)


def _strategy_next_step(slug: str, gate: dict, claims: list[dict]) -> str:
    if gate["status"] == "changes":
        return "Внести правки руководителя на G4: " + (gate.get("note") or "уточнить запрошенные изменения")
    documents = paths.load_config("required_sections")["docs"]
    checks = validate.run(argparse.Namespace(project=slug, stage="S3")).data["checks"]
    unfinished = {item["ref"].split(":")[0] for item in checks if item["ref"]}
    drafts = [name for name, spec in documents.items() if spec["stage"] == "S3" and name in unfinished]
    if drafts:
        return "Доработать документы S3: " + ", ".join(drafts) + ". Подробности: strateg validate --stage S3."
    first_error = next((item for item in checks if item["level"] == "error"), None)
    if first_error:
        location = " ".join(filter(None, (first_error["check"], first_error["ref"])))
        return f"Исправить ошибку проверки {location}: {first_error['message']}. Полный список: strateg validate --stage S3."
    if gate["status"] == "approved":
        return "Стратегия принята на G4. Перейти к S4 и записать решение руководителя."
    forecasts = sum(claim["status"] == "needs_review" and claim["type"] == "forecast" for claim in claims)
    return f"Представить готовые стратегии и план проверки руководителю на G4. Прогнозов к пересмотру: {forecasts}."


def status(args: argparse.Namespace) -> Result:
    slug = slug_of(args)
    proj = load_project(slug)
    stages = paths.load_config("stages")["stages"]
    claims = records(slug, "claims")
    by_type: dict[str, int] = {}
    for c in claims:
        if c["status"] in ("active", "needs_review"):
            by_type[c["type"]] = by_type.get(c["type"], 0) + 1
    commits = records(slug, "commitments")
    today = clock.today()
    cost_file = paths.project_dir(slug) / "out" / "cost.json"
    cost = store.read_json(cost_file).get("total_usd") if cost_file.exists() else None
    ev = journal.read(slug)
    next_step = stages[proj["stage"]]["next_step"]
    if proj["stage"] == "S3":
        next_step = _strategy_next_step(slug, proj["gates"]["G4"], claims)
    data = {
        "slug": slug, "title": proj["title"], "stage": proj["stage"], "stage_name": stages[proj["stage"]]["name"],
        "next_step": next_step,
        "gates": {g: v["status"] for g, v in proj["gates"].items()},
        "counts": {"sources": len(records(slug, "sources")), "claims": by_type,
                   "options": len(records(slug, "options")), "objections": len(records(slug, "objections")),
                   "decisions": len(records(slug, "decisions")),
                   "commitments_open": sum(1 for k in commits if k["status"] == "open")},
        "needs_review": sum(1 for c in claims if c["status"] == "needs_review")
        + sum(1 for r in (*records(slug, "options"), *records(slug, "decisions")) if r.get("review_flag")),  # как в review
        "overdue_commitments": sum(1 for k in commits if k["status"] == "open" and k["due"] < today),
        "opinions": {g: v["opinion"] for g, v in proj["gates"].items() if v.get("opinion")},
        "assumptions_unreviewed": sum(1 for a in proj["assumptions"] if not a["reviewed"]),
        "last_events": [{"at": e["at"], "kind": e["kind"], "summary": e["summary"]} for e in ev[-5:]],
        "cost_usd": cost,
    }
    human = (f"Проект: {proj['title']} ({slug})\nЭтап: {proj['stage']} — {data['stage_name']}\n"
             f"Следующий шаг: {data['next_step']}\nВорота: " +
             ", ".join(f"{g} {s}" for g, s in data["gates"].items()) +
             "".join(f"\nМнение РП на {g} (записано): {o}" for g, o in data["opinions"].items()) +
             f"\nТребуют пересмотра: {data['needs_review']}; просрочено обязательств: {data['overdue_commitments']}")
    return Result(data, human=human)


def set_(args: argparse.Namespace) -> Result:
    slug = slug_of(args)
    proj = load_project(slug)
    for field, val in [("question", args.question), ("goal", args.goal), ("audience", args.audience),
                       ("process_type", args.process_type), ("budget_usd", args.budget_usd)]:
        if val is not None:
            proj[field] = val
    for c in args.constraint:
        if c not in proj["constraints"]:
            proj["constraints"].append(c)
    for x in args.data:
        if x not in proj["data_available"]:
            proj["data_available"].append(x)
    save_project(slug, proj)
    journal.log(slug, "cli", "project set", {"command": "project set"})
    return Result(proj)


def stage(args: argparse.Namespace) -> Result:
    slug = slug_of(args)
    proj = load_project(slug)
    cur, to = proj["stage"], args.stage
    ci, ti = stage_index(cur), ORDER.index(to)
    if ti == ci:
        return Result({"from": cur, "to": to})
    if ti > ci:
        if ti != ci + 1:
            raise CliError("RULE_VIOLATION", f"Можно перейти только на следующий этап ({ORDER[ci + 1]})")
        gate = GATE_OF.get(cur)
        if gate and proj["gates"][gate]["status"] != "approved":
            raise CliError("RULE_VIOLATION", f"Этап {cur} закрывается воротами {gate}: нужно решение руководителя")
    elif not args.note:
        raise CliError("BAD_ARGS", "Возврат на прежний этап требует --note с причиной")
    proj["stage"] = to
    proj["stage_history"].append({"stage": to, "at": clock.now(), "note": args.note})
    save_project(slug, proj)
    journal.log(slug, "stage_change", f"{cur} → {to}", {"from": cur, "to": to}, stage=to)
    return Result({"from": cur, "to": to})


def gate(args: argparse.Namespace) -> Result:
    slug = slug_of(args)
    proj = load_project(slug)
    g = proj["gates"][args.gate]
    if args.status == "opinion":
        if not (args.note or "").strip():
            raise CliError("BAD_ARGS", "Для --status opinion нужна --note со словами РП")
        g.update(opinion=args.note, opinion_at=clock.now())
    else:
        g.update(status=args.status, at=clock.now(), note=args.note)
    save_project(slug, proj)
    journal.log(slug, "gate", f"{args.gate} {args.status}", {"gate": args.gate, "status": args.status, "note": args.note},
                actor="human")
    return Result({"gate": args.gate, "status": args.status})


def assume(args: argparse.Namespace) -> Result:
    slug = slug_of(args)
    proj = load_project(slug)
    if args.review:
        n = 0
        for a in proj["assumptions"]:
            if not a["reviewed"]:
                a["reviewed"] = True
                n += 1
        save_project(slug, proj)
        return Result({"reviewed": n})
    if not args.text:
        raise CliError("BAD_ARGS", "Нужен текст допущения или --review")
    a = {"id": ids.next_in(proj["assumptions"], "A"), "text": args.text, "at": clock.now(), "reviewed": False}
    proj["assumptions"].append(a)
    save_project(slug, proj)
    journal.log(slug, "cli", f"project assume {a['id']}", {"command": "project assume", "ids": [a["id"]]})
    return Result({"id": a["id"]})
