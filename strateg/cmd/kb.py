"""База знаний: BM25-поиск и связи. T09."""
from __future__ import annotations

import argparse
import math
import re
from collections import Counter

from strateg.cmd import _common as c
from strateg.cmd.source import snapshot_text
from strateg.lib import paths
from strateg.lib.out import Result

WORD = re.compile(r"[a-zа-я0-9]+")


def _cfg() -> dict:
    return paths.load_config("kb")


def tokens(text: str, cfg: dict) -> list[str]:
    stop, n = set(cfg["stopwords"]), cfg["stem_len"]
    return [w[:n] for w in WORD.findall(text.lower().replace("ё", "е")) if len(w) >= 3 and w not in stop]


def _chunks(text: str, size: int) -> list[str]:
    parts, buf = [], ""
    for block in re.split(r"\n\s*\n|\n(?=#)", text):
        block = block.strip()
        if not block:
            continue
        if buf and len(buf) + len(block) > size:
            parts.append(buf)
            buf = ""
        buf = (buf + "\n\n" + block).strip()
        while len(buf) > size:
            parts.append(buf[:size])
            buf = buf[size:]
    if buf:
        parts.append(buf)
    return parts


def _snippet(text: str, qtoks: set[str], cfg: dict) -> str:
    flat = " ".join(text.split())
    low = flat.lower().replace("ё", "е")
    pos = min((m.start() for m in WORD.finditer(low) if m.group(0)[:cfg["stem_len"]] in qtoks), default=0)
    start = max(0, pos - 60)
    return flat[start:start + 240]


def _docs(slugs: list[str], scope: str, incl: bool, cfg: dict) -> list[dict]:
    docs = []
    for slug in slugs:
        pre = ""
        if scope in ("claims", "all"):
            for cl in c.records(slug, "claims"):
                if not incl and cl["status"] in ("retracted", "superseded"):
                    continue
                docs.append({"project": slug, "ref": pre + cl["id"], "kind": "claim", "title": f"[{cl['type']}] {cl['text'][:80]}",
                             "text": cl["text"] + "\n" + (cl.get("quote") or ""), "status": cl["status"], "agent_output": False})
        if scope in ("sources", "all"):
            for s in c.records(slug, "sources"):
                if not incl and s["status"] == "retracted":
                    continue
                body = snapshot_text(slug, s)
                for i, ch in enumerate(_chunks(body, cfg["chunk_chars"]) or [""], 1):
                    docs.append({"project": slug, "ref": f"{pre}{s['id']}#{i}", "kind": "source", "title": s["title"],
                                 "text": (s["title"] + "\n" + ch) if i == 1 else ch, "status": s["status"],
                                 "agent_output": False})
        if scope in ("docs", "all"):
            for f in c.doc_files(slug):
                body = c.COMMENT_RX.sub("", f.read_text(encoding="utf-8"))
                if not any(ln.strip() and not ln.lstrip().startswith("#") for ln in body.splitlines()):
                    continue  # незаполненный шаблон — только заголовки
                for i, ch in enumerate(_chunks(body, cfg["chunk_chars"]), 1):
                    docs.append({"project": slug, "ref": f"{pre}{f.name}#{i}", "kind": "doc", "title": f.name, "text": ch,
                                 "status": "agent_output", "agent_output": True})
    if scope in ("knowledge", "all"):
        kd = paths.knowledge_dir()
        for f in sorted(kd.rglob("*.md")) if kd.exists() else []:
            if "templates" in f.parts:
                continue
            rel = f.relative_to(paths.code_dir()).as_posix()
            for i, ch in enumerate(_chunks(f.read_text(encoding="utf-8"), cfg["chunk_chars"]), 1):
                docs.append({"project": None, "ref": f"{rel}#{i}", "kind": "knowledge", "title": rel, "text": ch, "status": "active",
                             "agent_output": False})
    return docs


def search(args: argparse.Namespace) -> Result:
    cfg = _cfg()
    if args.project == "all":
        pd = paths.projects_dir()
        slugs = sorted(p.parent.name for p in pd.glob("*/project.json"))
    else:
        slug = paths.current_slug(args.project, required=args.scope not in ("knowledge",))
        slugs = [slug] if slug else []
    docs = _docs(slugs, args.scope, args.include_retracted, cfg)
    q = tokens(args.query, cfg)
    if not q or not docs:
        return Result([])
    toks = [tokens(d["text"], cfg) for d in docs]
    N, avg = len(docs), sum(map(len, toks)) / max(1, len(docs))
    df = Counter(t for ts in toks for t in set(ts))
    k1, b = 1.5, 0.75
    hits = []
    for d, ts in zip(docs, toks, strict=True):
        tf = Counter(ts)
        score = 0.0
        for t in set(q):
            if t in tf:
                idf = math.log(1 + (N - df[t] + 0.5) / (df[t] + 0.5))
                score += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(ts) / max(avg, 1)))
        if score > 0:
            hits.append({"ref": d["ref"], "project": d["project"], "kind": d["kind"], "score": round(score, 4), "title": d["title"],
                         "snippet": _snippet(d["text"], set(q), cfg), "status": d["status"], "agent_output": d["agent_output"]})
    hits.sort(key=lambda h: -h["score"])
    return Result(hits[: args.limit])


def links(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    i = args.id
    claims, opts = c.records(slug, "claims"), c.records(slug, "options")
    objs, decs = c.records(slug, "objections"), c.records(slug, "decisions")
    rec = None
    for name in ("claims", "sources", "options", "objections", "decisions", "commitments"):
        rec = c.by_id(slug, name).get(i) or rec
    if rec is None:
        from strateg.lib.out import CliError
        raise CliError("NOT_FOUND", f"{i} не найден")
    cited = []
    for f in c.doc_files(slug):
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if f"[{i}]" in line:
                cited.append({"file": f.relative_to(paths.project_dir(slug)).as_posix(), "line": n})
    return Result({
        "id": i, "kind": {"S": "source", "C": "claim", "O": "option", "X": "objection", "D": "decision",
                          "K": "commitment"}[i[0]],
        "depends_on": rec.get("depends_on", []),
        "dependents": [x["id"] for x in claims if i in x.get("depends_on", []) or i in x.get("sources", [])],
        "sources": rec.get("sources", []),
        "options": [o["id"] for o in opts if i in o.get("based_on", [])],
        "objections": [x["id"] for x in objs if x["option"] == i or i in x.get("based_on", [])],
        "decisions": [d["id"] for d in decs if d["option"] == i or i in d.get("based_on", [])],
        "cited_in": cited,
    })
