"""Граф влияния: что затронуто изменением. T10."""
from __future__ import annotations

import argparse
from collections import deque

from strateg.cmd import _common as c
from strateg.lib import journal, paths
from strateg.lib.out import CliError, Result

KIND = {"S": "source", "C": "claim", "O": "option", "X": "objection", "D": "decision", "K": "commitment"}


def build_reverse(slug: str) -> tuple[dict[str, set[str]], dict[str, dict]]:
    """Обратные рёбра: узел → кто от него зависит. Узлы-разделы: 'file#heading'."""
    rev: dict[str, set[str]] = {}
    nodes: dict[str, dict] = {}

    def edge(dependent: str, on: str) -> None:
        rev.setdefault(on, set()).add(dependent)

    for name in ("sources", "claims", "options", "objections", "decisions", "commitments"):
        for r in c.records(slug, name):
            nodes[r["id"]] = r
    for r in nodes.values():
        p = r["id"][0]
        if p == "C":
            for s in r["sources"]:
                edge(r["id"], s)
            for d in r["depends_on"]:
                edge(r["id"], d)
        elif p == "O":
            for b in r["based_on"]:
                edge(r["id"], b)
        elif p == "X":
            edge(r["id"], r["option"])
            for b in r.get("based_on", []):
                edge(r["id"], b)
        elif p == "D":
            edge(r["id"], r["option"])
            for b in r.get("based_on", []):
                edge(r["id"], b)
        elif p == "K":
            edge(r["id"], r["decision"])
    for f in c.doc_files(slug):
        rel = f.relative_to(paths.project_dir(slug) / ("docs" if f.parent.name == "docs" else "")).as_posix()
        for head, _, body in c.sections(f.read_text(encoding="utf-8")):
            node = f"{rel}#{head}"
            for rid in set(c.REF_RX.findall(head + "\n" + "\n".join(body))):
                edge(node, rid)
    return rev, nodes


def run(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    changed = c.split_ids(args.changed)
    rev, nodes = build_reverse(slug)
    for x in changed:
        if x not in nodes:
            raise CliError("NOT_FOUND", f"{x} не найден")
    chain: dict[str, list[str]] = {x: [x] for x in changed}
    q = deque(changed)
    while q:
        n = q.popleft()
        for m in sorted(rev.get(n, ())):
            if m not in chain:
                chain[m] = chain[n] + [m]
                q.append(m)
    affected = [{"id": k, "kind": KIND.get(k[0], "doc_section") if "#" not in k else "doc_section", "chain": v}
                for k, v in chain.items() if k not in changed]
    rs = paths.load_config("required_sections")["docs"]
    stages = [nodes[a["id"]].get("stage") for a in affected if a["id"].startswith("C-") and nodes[a["id"]].get("stage")]
    stages += [rs[a["id"].split("#")[0]]["stage"] for a in affected if "#" in a["id"] and a["id"].split("#")[0] in rs]
    earliest = min(stages, key=c.stage_index) if stages else None
    doc_sections = [{"file": a["id"].split("#", 1)[0], "heading": a["id"].split("#", 1)[1]} for a in affected if "#" in a["id"]]
    applied = []
    if args.apply:
        reason = args.reason or f"изменились основания: {', '.join(changed)}"
        for a in affected:
            r = nodes.get(a["id"])
            if r is None:
                continue
            if a["id"].startswith("C-") and r["status"] == "active":
                c.update(slug, "claims", a["id"], {"status": "needs_review"}, reason, "cli", "impact")
                applied.append(a["id"])
            elif a["id"][0] in "OD" and not r.get("review_flag"):
                c.update(slug, "options" if a["id"][0] == "O" else "decisions", a["id"], {"review_flag": True}, reason,
                         "cli", "impact")
                applied.append(a["id"])
        if applied:
            journal.log(slug, "note", f"impact: на пересмотр {len(applied)}", {"changed": changed, "marked": applied})
    return Result({"changed": changed, "affected": affected, "earliest_stage": earliest, "doc_sections": doc_sections,
                   "applied": applied})
