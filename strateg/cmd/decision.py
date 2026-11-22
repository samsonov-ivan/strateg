"""Решения, обязательства, обзор. T07."""
from __future__ import annotations

import argparse
import re
from datetime import date, timedelta

from strateg.cmd import _common as c
from strateg.lib import clock, paths
from strateg.lib.out import CliError, Result


def _date_in(text: str) -> date | None:
    """Дата проверки внутри текста метрического условия (YYYY-MM-DD или DD.MM.YYYY); до неё условие не «срабатывает»."""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})|(\d{1,2})\.(\d{1,2})\.(\d{4})", text)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3])) if m[1] else date(int(m[6]), int(m[5]), int(m[4]))
    except ValueError:
        return None


def _metric(s: str) -> dict:
    parts = [p.strip() for p in s.split("|")]
    if len(parts) != 4 or not parts[0] or not parts[2]:
        raise CliError("BAD_ARGS", f"--metric в формате имя|база|цель|YYYY-MM-DD: {s}")
    try:
        date.fromisoformat(parts[3])
    except ValueError:
        raise CliError("BAD_ARGS", f"Неверная дата в --metric: {parts[3]}") from None
    return {"name": parts[0], "baseline": parts[1], "target": parts[2], "by": parts[3]}


def _trigger(s: str) -> dict:
    kind, _, value = s.partition(":")
    if kind not in ("date", "metric", "claim") or not value.strip():
        raise CliError("BAD_ARGS", f"--trigger: date:YYYY-MM-DD | metric:<текст> | claim:C-ID, получено {s}")
    if kind == "date":
        try:
            date.fromisoformat(value.strip())
        except ValueError:
            raise CliError("BAD_ARGS", f"Неверная дата в --trigger: {value}") from None
    return {"kind": kind, "value": value.strip()}


def add(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    c.get(slug, "options", args.option)
    based = c.split_ids(args.based_on)
    c.require_existing(slug, based, "claims", {"active", "needs_review"})
    triggers = [_trigger(t) for t in args.trigger]
    for t in triggers:
        if t["kind"] == "claim":
            c.require_existing(slug, [t["value"]], "claims")
    rec = {"option": args.option, "rationale": args.rationale, "based_on": based, "owner": args.owner,
           "decided_by": args.by, "decided_at": clock.now(), "metrics": [_metric(m) for m in args.metric],
           "triggers": triggers, "status": "active", "review_flag": False, "reason": None,
           "op_id": c.op_for(args, "decision add"), "history": []}
    rec, existing = c.create(slug, "decisions", "D", rec, "decision", "decision add")
    if not existing:
        for o in c.records(slug, "options"):
            if o["status"] == "chosen" and o["id"] != args.option:
                c.update(slug, "options", o["id"], {"status": "active"}, f"решение {rec['id']}", "human", "decision add")
        c.update(slug, "options", args.option, {"status": "chosen", "reason": f"решение {rec['id']}"},
                 f"решение {rec['id']}", "human", "decision add")
    return Result({"id": rec["id"], "existing": existing})


def set_(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    c.get(slug, "decisions", args.id)
    return Result(c.update(slug, "decisions", args.id, {"status": args.status, "reason": args.reason, "review_flag": False},
                           args.reason, "human", "decision set"))


def commitment_add(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    c.get(slug, "decisions", args.decision)
    try:
        date.fromisoformat(args.due)
    except ValueError:
        raise CliError("BAD_ARGS", "--due в формате YYYY-MM-DD") from None
    rec = {"decision": args.decision, "what": args.what, "owner": args.owner, "due": args.due, "status": "open",
           "done_at": None, "reason": None, "op_id": c.op_for(args, "commitment add"), "history": []}
    rec, existing = c.create(slug, "commitments", "K", rec, "commitment", "commitment add")
    return Result({"id": rec["id"], "existing": existing})


def commitment_done(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    c.get(slug, "commitments", args.id)
    return Result(c.update(slug, "commitments", args.id, {"status": "done", "done_at": clock.now()}, "выполнено", "human",
                           "commitment done"))


def commitment_drop(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    c.get(slug, "commitments", args.id)
    return Result(c.update(slug, "commitments", args.id, {"status": "dropped", "reason": args.reason}, args.reason, "human",
                           "commitment drop"))


def review(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    today = date.fromisoformat(args.today) if args.today else date.fromisoformat(clock.today())
    stale_days = paths.load_config("stages").get("stale_days", 30)
    claims, sources = c.by_id(slug, "claims"), c.by_id(slug, "sources")
    open_k = [k for k in c.records(slug, "commitments") if k["status"] == "open"]
    overdue = [k for k in open_k if date.fromisoformat(k["due"]) < today]
    due_7d = [k for k in open_k if today <= date.fromisoformat(k["due"]) <= today + timedelta(days=7)]
    triggered, stale = [], {}
    for d in c.records(slug, "decisions"):
        if d["status"] != "active":
            continue
        for t in d["triggers"]:
            if t["kind"] == "date" and date.fromisoformat(t["value"]) <= today:
                triggered.append({"decision": d["id"], **t, "why": f"наступила дата пересмотра {t['value']}"})
            elif t["kind"] == "claim" and claims.get(t["value"], {}).get("status") != "active":
                triggered.append({"decision": d["id"], **t,
                                  "why": f"основание {t['value']} в статусе {claims.get(t['value'], {}).get('status')}"})
            elif t["kind"] == "metric":
                when = _date_in(t["value"])
                if when is None or when <= today:
                    triggered.append({"decision": d["id"], **t, "why": "проверить метрику вручную"})
        for cid in d.get("based_on", []):
            for sid in claims.get(cid, {}).get("sources", []):
                s = sources.get(sid)
                if s and (today - date.fromisoformat(s["retrieved_at"][:10])).days > stale_days:
                    stale[sid] = {"id": sid, "title": s["title"], "retrieved_at": s["retrieved_at"]}
    needs = [{"id": x["id"], "kind": "claim"} for x in claims.values() if x["status"] == "needs_review"]
    needs += [{"id": x["id"], "kind": "option"} for x in c.records(slug, "options") if x.get("review_flag")]
    needs += [{"id": x["id"], "kind": "decision"} for x in c.records(slug, "decisions") if x.get("review_flag")]
    now_list = [{"ref": k["id"], "why": f"просрочено: {k['what']} (срок {k['due']}, {k['owner']})", "urgency": "high"}
                for k in overdue]
    now_list += [{"ref": t["decision"], "why": t["why"], "urgency": "high" if t["kind"] != "metric" else "medium"}
                 for t in triggered]
    now_list += [{"ref": k["id"], "why": f"срок {k['due']}: {k['what']}", "urgency": "medium"} for k in due_7d]
    now_list += [{"ref": s["id"], "why": f"источник устарел (получен {s['retrieved_at'][:10]})", "urgency": "medium"}
                 for s in stale.values()]
    now_list += [{"ref": n["id"], "why": "требует пересмотра", "urgency": "low"} for n in needs]
    return Result({"overdue": overdue, "due_7d": due_7d, "triggered": triggered, "stale_sources": list(stale.values()),
                   "needs_review": needs, "decide_now": now_list})
