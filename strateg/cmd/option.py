"""Варианты и возражения. T06."""
from __future__ import annotations

import argparse

from strateg.cmd import _common as c
from strateg.lib.out import CliError, Result

LIVE = {"active", "needs_review"}


def add(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    based = c.split_ids(args.based_on)
    c.require_existing(slug, based, "claims", LIVE)
    rec = {"title": args.title, "kind": args.kind, "summary": args.summary, "based_on": based,
           "reversibility": args.reversibility, "status": "active", "review_flag": False, "reason": None,
           "op_id": c.op_for(args, "option add"), "history": []}
    rec, existing = c.create(slug, "options", "O", rec, "option", "option add")
    return Result({"id": rec["id"], "existing": existing})


def set_(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    c.get(slug, "options", args.id)
    if args.status == "chosen":
        for o in c.records(slug, "options"):
            if o["status"] == "chosen" and o["id"] != args.id:
                c.update(slug, "options", o["id"], {"status": "active"}, f"выбран {args.id}", "agent", "option set")
    rec = c.update(slug, "options", args.id, {"status": args.status, "reason": args.reason, "review_flag": False}, args.reason,
                   "agent", "option set")  # повторная установка статуса = вариант пересмотрен
    return Result(rec)


def list_(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    obj = c.records(slug, "objections")
    rows = []
    for o in c.records(slug, "options"):
        if args.status and o["status"] != args.status:
            continue
        mine = [x for x in obj if x["option"] == o["id"]]
        rows.append({"id": o["id"], "kind": o["kind"], "title": o["title"], "status": o["status"],
                     "objections_count": len(mine), "strong_objections_count": sum(x["strength"] == "strong" for x in mine),
                     "review_flag": o.get("review_flag", False)})
    return Result(rows)


def objection_add(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    if args.option not in c.by_id(slug, "options"):
        raise CliError("NOT_FOUND", f"Вариант {args.option} не найден")
    based = c.split_ids(args.based_on)
    c.require_existing(slug, based, "claims", LIVE)
    rec = {"option": args.option, "text": args.text, "strength": args.strength, "by": args.by, "based_on": based,
           "response": None, "op_id": c.op_for(args, "objection add"), "history": []}
    rec, existing = c.create(slug, "objections", "X", rec, "objection", "objection add")
    return Result({"id": rec["id"], "existing": existing})


def objection_respond(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    c.get(slug, "objections", args.id)
    return Result(c.update(slug, "objections", args.id, {"response": args.response}, "ответ на возражение", "agent",
                           "objection respond"))


def objection_list(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    return Result([x for x in c.records(slug, "objections") if not args.option or x["option"] == args.option])
