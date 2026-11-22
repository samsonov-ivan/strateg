"""Каскад маршрутизации: primary → fallback по ошибке или низкой уверенности. T13."""
from __future__ import annotations

import argparse

from strateg.cmd import _common as c
from strateg.lib import clock, ids, journal, paths, store
from strateg.lib.out import CliError, Result
from strateg.route.clients import Client


def decide(slug: str, task: str, input_ref: str | None, state: dict, questions: dict,
           primary: Client, fallback: Client, tau: float) -> dict:
    cost, lat = 0.0, 0
    route, reason, res = "primary", None, None
    try:
        res = primary.ask(state, questions)
        cost += res["cost_usd"]
        lat += res["latency_ms"]
        conf = min((a["confidence"] for a in res["answers"].values()), default=0.0)
        if conf < tau:
            reason = "low_confidence"
    except Exception as e:  # сбой основной модели не должен ронять работу
        reason = "error"
        journal.log(slug, "error", f"route {task}: {primary.name} недоступен", {"error": str(e)[:300]})
    if reason:
        route = "fallback"
        try:
            res = fallback.ask(state, questions)
        except Exception as e:
            journal.log(slug, "error", f"route {task}: {fallback.name} недоступен", {"error": str(e)[:300]})
            raise CliError("FETCH_FAILED", f"Обе модели маршрутизатора недоступны ({primary.name}, {fallback.name})") from None
        cost += res["cost_usd"]
        lat += res["latency_ms"]
    assert res is not None
    first = next(iter(res["answers"].values()), {"answer": None, "confidence": 0.0})
    path = c.reg(slug, "routing")
    with store.lock(path):
        recs = store.read_jsonl(path)
        rec = {"id": ids.next_in(recs, "R"), "at": clock.now(), "task": task, "input_ref": input_ref, "route": route,
               "model": res["model"], "answer": first["answer"], "confidence": float(first["confidence"]),
               "escalated": route == "fallback", "escalation_reason": reason, "cost_usd": round(cost, 8),
               "latency_ms": int(lat), "corrected": False, "correct_answer": None,
               "op_id": ids.op_id("route", {"task": task, "ref": input_ref, "at": clock.now(), "n": len(recs)})}
        recs.append(rec)
        store._atomic_write(path, "".join(store._dumps(r) + "\n" for r in recs))
    return {"answers": res["answers"], "record": rec}


def _clients() -> tuple[Client, Client]:
    from strateg.route.clients import make

    cfg = paths.load_config("routing")
    return make(cfg["primary"]), make(cfg["fallback"])


def cli_classify_claim(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    cl = c.get(slug, "claims", args.id)
    task = paths.load_config("routing")["tasks"]["claim_type"]
    primary, fallback = _clients()
    r = decide(slug, "claim_type", cl["id"], {"step": "Классифицировать утверждение", "text": cl["text"],
                                              "quote": cl.get("quote")}, task["questions"], primary, fallback, task["tau"])
    ans = r["answers"].get("claim_type", {}).get("answer")
    return Result({"id": cl["id"], "current": cl["type"], "suggestion": ans if ans != cl["type"] else None,
                   "routing": r["record"]})


def cli_correct(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    c.get(slug, "routing", args.id)
    rec = store.update_record(c.reg(slug, "routing"), args.id, {"corrected": True, "correct_answer": args.answer},
                              args.reason, "human")
    journal.log(slug, "cli", f"route correct {args.id}", {"command": "route correct", "ids": [args.id]})
    return Result(rec)


def cli_stats(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    out: dict[str, dict] = {}
    for r in c.records(slug, "routing"):
        s = out.setdefault(r["task"], {"n": 0, "esc": 0, "corr": 0, "cost_usd": 0.0, "lat": 0})
        s["n"] += 1
        s["esc"] += r["escalated"]
        s["corr"] += r["corrected"]
        s["cost_usd"] += r["cost_usd"]
        s["lat"] += r["latency_ms"]
    return Result({t: {"n": s["n"], "escalation_rate": round(s["esc"] / s["n"], 4), "error_rate": round(s["corr"] / s["n"], 4),
                       "cost_usd": round(s["cost_usd"], 6), "avg_latency_ms": round(s["lat"] / s["n"], 1)}
                   for t, s in out.items()})


def cli_tune(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    cfg = paths.load_config("routing")
    target = cfg.get("target_accuracy", 0.9)
    recs = [r for r in c.records(slug, "routing") if r["task"] == args.task and r["route"] == "primary"]
    if not recs:
        raise CliError("NOT_FOUND", f"Нет решений маршрутизатора по задаче {args.task}")
    grid = [round(0.5 + 0.05 * i, 2) for i in range(10)]
    table = []
    for tau in grid:
        acc = [r for r in recs if r["confidence"] >= tau]
        accuracy = (sum(not r["corrected"] for r in acc) / len(acc)) if acc else None
        table.append({"tau": tau, "accepted": len(acc), "accuracy": None if accuracy is None else round(accuracy, 4)})
    best = next((t["tau"] for t in table if t["accuracy"] is not None and t["accuracy"] >= target), None)
    cur = cfg["tasks"].get(args.task, {}).get("tau")
    return Result({"task": args.task, "current_tau": cur, "recommended_tau": best, "target_accuracy": target, "grid": table})
