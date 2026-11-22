"""Валидатор V01–V14 (T08; V14 — мнение РП на G3)."""
from __future__ import annotations

import argparse
import re

from strateg.cmd import _common as c
from strateg.lib import paths, schema
from strateg.lib.out import Result

GATE_FOR_STAGE = {"S1": ["G1"], "S2": ["G1", "G2"], "S3": ["G1", "G2", "G3"], "S4": ["G1", "G2", "G3", "G4"],
                  "S5": ["G1", "G2", "G3", "G4"]}
REGS = [("sources", "source"), ("claims", "claim"), ("options", "option"), ("objections", "objection"),
        ("decisions", "decision"), ("commitments", "commitment"), ("journal", "event"), ("routing", "routing")]


def run(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    proj = c.load_project(slug)
    cur = proj["stage"]
    upto = c.stage_index(args.stage or cur)
    checks: list[dict] = []

    def add(check: str, level: str, ref: str | None, message: str) -> None:
        checks.append({"check": check, "level": level, "ref": ref, "message": message})

    data = {name: c.records(slug, name) for name, _ in REGS}
    idx = {name: {r["id"]: r for r in recs} for name, recs in data.items()}
    claims, sources, options = idx["claims"], idx["sources"], idx["options"]

    # V01 схемы
    for e in schema.validate(proj, "project"):
        add("V01", "error", "project.json", e)
    for name, sch in REGS:
        for r in data[name]:
            for e in schema.validate(r, sch):
                add("V01", "error", r.get("id"), e)

    # V02 ссылки
    def ref(owner: str, target: str, pool: dict) -> None:
        if target not in pool:
            add("V02", "error", owner, f"ссылка на несуществующий {target}")

    for cl in claims.values():
        for s in cl["sources"]:
            ref(cl["id"], s, sources)
        for d in cl["depends_on"]:
            ref(cl["id"], d, claims)
        if cl.get("superseded_by"):
            ref(cl["id"], cl["superseded_by"], claims)
    for o in options.values():
        for b in o["based_on"]:
            ref(o["id"], b, claims)
    for x in data["objections"]:
        ref(x["id"], x["option"], options)
        for b in x.get("based_on", []):
            ref(x["id"], b, claims)
    for d in data["decisions"]:
        ref(d["id"], d["option"], options)
        for b in d.get("based_on", []):
            ref(d["id"], b, claims)
    for k in data["commitments"]:
        ref(k["id"], k["decision"], idx["decisions"])

    live = [x for x in claims.values() if x["status"] in ("active", "needs_review")]
    if upto >= 1:
        # V03 факты
        for cl in live:
            if cl["type"] != "fact":
                continue
            srcs = [sources[s] for s in cl["sources"] if s in sources]
            if not any(s["status"] == "active" and s["kind"] != "synthetic" for s in srcs):
                add("V03", "error", cl["id"], "факт без активного несинтетического источника")
            if cl.get("quote_verified") is False:
                add("V03", "error", cl["id"], "цитата факта не найдена в источнике — исправь цитату или тип утверждения")
            elif cl.get("quote_verified") is None:
                add("V03", "warn", cl["id"], "цитата факта не проверена (verify quotes)")
        # V04 отозванные источники
        for cl in claims.values():
            if cl["status"] == "active" and any(sources.get(s, {}).get("status") == "retracted" for s in cl["sources"]):
                add("V04", "error", cl["id"], "активное утверждение опирается на отозванный источник — пересмотри его")
        # V05 циклы
        g = {k: v["depends_on"] for k, v in claims.items()}
        color: dict[str, int] = {}

        def dfs(n: str) -> bool:
            color[n] = 1
            for m in g.get(n, []):
                if color.get(m) == 1 or (color.get(m) is None and m in g and dfs(m)):
                    return True
            color[n] = 2
            return False

        for n in g:
            if color.get(n) is None and dfs(n):
                add("V05", "error", n, "цикл в depends_on")
        # V13 честные пробелы
        if not any(x["type"] == "unknown" for x in live):
            add("V13", "warn", None, "нет ни одного пробела (unknown): назови честно, чего мы не знаем")

    if upto >= 2:
        act = [o for o in options.values() if o["status"] != "retracted"]  # отклонённые после G3 тоже считаются рассмотренными
        kinds = {o["kind"] for o in act}
        if len(act) < 3:
            add("V06", "error", None, f"вариантов {len(act)}, нужно не меньше 3")
        if "status_quo" not in kinds:
            add("V06", "error", None, "нет варианта «оставить как есть» (kind=status_quo)")
        if "close" not in kinds:
            add("V06", "error", None, "нет варианта «закрыть направление» (kind=close)")
        for o in act:
            if not any(x["option"] == o["id"] and x["strength"] == "strong" for x in data["objections"]):
                add("V06", "error", o["id"], "у варианта нет сильного возражения")

    # V07 обязательные разделы; V08/V10 ссылки в документах
    rs = paths.load_config("required_sections")
    pdir = paths.project_dir(slug)
    cur_i = c.stage_index(cur)
    for fname, spec in rs["docs"].items():
        si = c.stage_index(spec["stage"])
        if si > upto or si > cur_i:
            continue
        level = "error" if cur_i > si else "warn"
        f = pdir / fname if fname == "brief.md" else pdir / "docs" / fname
        if not f.exists():
            add("V07", level, fname, "документ отсутствует")
            continue
        secs = {h.lower(): body for h, _, body in c.sections(f.read_text(encoding="utf-8"))}
        for h in spec["headings"]:
            body = secs.get(h.lower())
            if body is None:
                add("V07", level, fname, f"нет раздела «## {h}»")
            elif c.body_empty(body):
                add("V07", level, fname, f"раздел «{h}» пустой")

    if upto >= 1:
        pools = {"S": sources, "C": claims, "O": options, "X": idx["objections"], "D": idx["decisions"],
                 "K": idx["commitments"]}
        for f in c.doc_files(slug):
            text = f.read_text(encoding="utf-8")
            n_refs = 0
            for n, line in enumerate(text.splitlines(), 1):
                for rid in c.REF_RX.findall(line):
                    n_refs += 1
                    obj = pools[rid[0]].get(rid)
                    where = f"{f.name}:{n}"
                    if obj is None:
                        add("V08", "error", where, f"ссылка на несуществующий {rid}")
                    elif obj.get("status") in ("retracted", "superseded"):
                        add("V08", "error", where, f"ссылка на {rid} в статусе {obj['status']}")
                    elif rid[0] == "C" and obj["type"] == "synthetic" and not re.search(r"SYNTHETIC|синтетич", line, re.I):
                        add("V10", "error", where, f"{rid} — синтетика: пометь строку SYNTHETIC")
            need = rs.get("min_refs", {}).get(f.name)
            if need and n_refs < need and not c.body_empty([x for x in text.splitlines() if not x.lstrip().startswith("#")]):
                add("V08", "warn", f.name, f"ссылок на основания {n_refs}, ожидается не меньше {need}")

    # V09 обещания = продукт
    if upto >= 3:
        f = pdir / "docs" / "strategy_comms.md"
        body = None
        if f.exists():
            body = next((b for h, _, b in c.sections(f.read_text(encoding="utf-8")) if h.lower() == "обещания и подтверждения"),
                        None)
        rows = [ln for ln in (body or []) if ln.strip().startswith("|")]
        if len(rows) < 3:
            add("V09", "error", "strategy_comms.md", "нет таблицы «Обещание | Свойство продукта | Подтверждение»")
        else:
            head = [x.strip().lower() for x in rows[0].strip().strip("|").split("|")]
            if head[:3] != ["обещание", "свойство продукта", "подтверждение"]:
                add("V09", "error", "strategy_comms.md", "колонки таблицы: Обещание | Свойство продукта | Подтверждение")
            for ln in rows[2:]:
                cells = [x.strip() for x in ln.strip().strip("|").split("|")]
                cells += [""] * (3 - len(cells))
                if not all(cells[:3]):
                    add("V09", "error", "strategy_comms.md", f"пустая ячейка: {ln.strip()}")
                ok = [r for r in c.REF_RX.findall(cells[2]) if claims.get(r, {}).get("type") == "fact"
                      and claims[r]["status"] == "active"]
                if not ok:
                    add("V09", "error", "strategy_comms.md", f"обещание без подтверждения фактом: {cells[0] or ln.strip()}")

    # V11 этап не дальше ворот
    for g in GATE_FOR_STAGE.get(cur, []):
        if proj["gates"][g]["status"] != "approved":
            add("V11", "error", "project.json", f"этап {cur}, но ворота {g} не пройдены")

    # V14 «сначала мнение РП» на G3
    g3 = proj["gates"]["G3"]
    if g3["status"] == "approved" and not g3.get("opinion"):
        add("V14", "warn", "project.json", "G3 пройдены без записанного мнения РП (project gate G3 --status opinion)")

    # V12 решения
    if upto >= 4:
        for d in data["decisions"]:
            if d["status"] == "active" and (not d["metrics"] or not d["triggers"] or not d["owner"].strip()):
                add("V12", "error", d["id"], "у решения нужны метрика, условие пересмотра и ответственный")
        for k in data["commitments"]:
            if not k["owner"].strip() or not k["due"]:
                add("V12", "error", k["id"], "у обязательства нужны ответственный и срок")

    errors = sum(x["level"] == "error" for x in checks)
    out = {"errors": errors, "warnings": sum(x["level"] == "warn" for x in checks), "checks": checks}
    if errors:
        return Result(out, exit_code=1, message=f"Валидатор нашёл ошибок: {errors}")
    return Result(out)
