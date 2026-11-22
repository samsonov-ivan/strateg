"""HTML-отчёт проекта: один самодостаточный файл projects/<slug>/out/report.html (без внешних зависимостей).

Для руководителя и жюри: где мы, что знаем и на чём основано (любая ссылка [C-…] раскрывается до цитаты и источника),
варианты с возражениями, стратегии, решения, стоимость и журнал.
"""
from __future__ import annotations

import argparse
import html
import re

from strateg.cmd import _common as c
from strateg.lib import clock, journal, paths, store
from strateg.lib.out import Result

DOCS = [("onepager.md", "Одностраничник"), ("brief.md", "Бриф"), ("situation.md", "Картина ситуации"),
        ("options.md", "Варианты"), ("strategy_product.md", "Продуктовая стратегия"),
        ("strategy_comms.md", "Коммуникационная стратегия"), ("validation_plan.md", "План проверки"),
        ("research_plan.md", "План исследования")]
TYPE_RU = {"fact": "факт", "hypothesis": "гипотеза", "forecast": "прогноз", "opinion": "мнение", "unknown": "пробел",
           "synthetic": "синтетика"}
KIND_RU = {"status_quo": "оставить как есть", "close": "закрыть", "change": "изменить", "new": "новое"}
GATE_RU = {"pending": "ожидает", "approved": "пройдены", "changes": "нужны правки"}

CSS = """
:root{--bg:#fbfaf7;--fg:#1d1d1b;--mut:#6b6a66;--line:#e4e1d9;--card:#fff;--acc:#2f5d8a;--fact:#2e7d4f;--hyp:#a8661b;
--fc:#6a4c9c;--unk:#9a3b3b;--syn:#7a7a7a;--op:#476f8a}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--mut:#a3a19a;--line:#33322e;--card:#1f1e1b;
--acc:#8db7e0;--fact:#6cc28f;--hyp:#e0a35a;--fc:#b49be0;--unk:#e08a8a;--syn:#a8a8a8;--op:#8fb3cc}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.55 -apple-system,"Segoe UI",
Roboto,"Helvetica Neue",Arial,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:24px 16px 64px}h1{font-size:26px;margin:0 0 4px}
h2{font-size:20px;margin:36px 0 12px;padding-top:8px;border-top:1px solid var(--line)}h3{font-size:16px;margin:20px 0 8px}
.mut{color:var(--mut)}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:16px 0}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tile b{display:block;font-size:22px}.tile span{color:var(--mut);font-size:13px}
nav{position:sticky;top:0;background:var(--bg);padding:8px 0;border-bottom:1px solid var(--line);z-index:2;
overflow-x:auto;white-space:nowrap}nav a{margin-right:14px;color:var(--acc);text-decoration:none;font-size:14px}
.doc{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:4px 18px 14px;margin:12px 0}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:14px;display:block;overflow-x:auto}
th,td{border:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}th{background:var(--bg)}
.b{display:inline-block;border-radius:6px;padding:0 6px;font-size:12px;color:#fff;white-space:nowrap}
.fact{background:var(--fact)}.hypothesis{background:var(--hyp)}.forecast{background:var(--fc)}.unknown{background:var(--unk)}
.synthetic{background:var(--syn)}.opinion{background:var(--op)}
a.ref{color:var(--acc);text-decoration:none;border-bottom:1px dotted var(--acc);font-size:.92em}
details{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:6px 10px;margin:6px 0}
details:target{outline:2px solid var(--acc)}summary{cursor:pointer}blockquote{margin:6px 0;padding:4px 10px;
border-left:3px solid var(--line);color:var(--mut)}.warn{color:var(--unk)}.ok{color:var(--fact)}
.gates span{margin-right:10px}code{font-size:13px}
[id]{scroll-margin-top:3.5rem}
"""

JS = """
function reveal(hash) {
  const target = document.getElementById(hash.slice(1));
  for (let node = target; node; node = node.parentElement) {
    if (node.tagName === 'DETAILS') node.open = true;
  }
}
document.querySelectorAll('a.ref').forEach(link => link.addEventListener('click', () => reveal(link.hash)));
window.addEventListener('hashchange', () => reveal(location.hash));
reveal(location.hash);
"""


def _esc(s: object) -> str:
    return html.escape("" if s is None else str(s))


def _review_notice(record: dict, guidance: str) -> tuple[str, str]:
    if not record.get("review_flag"):
        return "", ""
    reason = next((event.get("reason") for event in reversed(record.get("history", []))
                   if event.get("field") == "review_flag" and event.get("new") is True), "")
    badge = " · <strong class='warn'>требуется пересмотр</strong>"
    return badge, f"<p class='warn'>{guidance} {_esc(reason)}</p>"


def _inline(text: str, refs: dict[str, str]) -> str:
    t = _esc(text)
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)

    def ref(m: re.Match) -> str:
        rid = m.group(1)
        tip = _esc(refs.get(rid, ""))
        return f'<a class="ref" href="#{rid}" title="{tip}">{rid}</a>'

    return re.sub(r"\[([SCOXDK]-\d{3,})\]", ref, t)


def md_to_html(md: str, refs: dict[str, str]) -> str:
    """Минимальный Markdown: заголовки, абзацы, списки, таблицы, цитаты. HTML-комментарии удаляются."""
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        s = ln.strip()
        if not s:
            i += 1
            continue
        if s.startswith("#"):
            lvl = min(len(s) - len(s.lstrip("#")) + 1, 4)
            out.append(f"<h{lvl}>{_inline(s.lstrip('#').strip(), refs)}</h{lvl}>")
            i += 1
        elif s.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([x.strip() for x in lines[i].strip().strip("|").split("|")])
                i += 1
            body = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", x or "--") for x in r)]
            if body:
                head = "".join(f"<th>{_inline(x, refs)}</th>" for x in body[0])
                trs = "".join("<tr>" + "".join(f"<td>{_inline(x, refs)}</td>" for x in r) + "</tr>" for r in body[1:])
                out.append(f"<table><tr>{head}</tr>{trs}</table>")
        elif re.match(r"^([-*]|\d+\.)\s", s):
            tag = "ol" if s[0].isdigit() else "ul"
            items = []
            while i < len(lines) and re.match(r"^\s*([-*]|\d+\.)\s", lines[i]):
                items.append(re.sub(r"^\s*([-*]|\d+\.)\s+", "", lines[i]))
                i += 1
            out.append(f"<{tag}>" + "".join(f"<li>{_inline(x, refs)}</li>" for x in items) + f"</{tag}>")
        elif s.startswith(">"):
            out.append(f"<blockquote>{_inline(s.lstrip('>').strip(), refs)}</blockquote>")
            i += 1
        else:
            para = []
            while i < len(lines) and lines[i].strip() and not re.match(r"^\s*(#|\||>|[-*]\s|\d+\.\s)", lines[i]):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{_inline(' '.join(para), refs)}</p>")
    return "\n".join(out)


def build(slug: str) -> str:
    proj = c.load_project(slug)
    stages = paths.load_config("stages")["stages"]
    srcs, claims = c.by_id(slug, "sources"), c.records(slug, "claims")
    opts, objs = c.records(slug, "options"), c.records(slug, "objections")
    decs, coms = c.records(slug, "decisions"), c.records(slug, "commitments")
    pdir = paths.project_dir(slug)
    refs: dict[str, str] = {}
    for cl in claims:
        refs[cl["id"]] = f"{TYPE_RU.get(cl['type'], cl['type'])}: {cl['text']}"
    for s in srcs.values():
        refs[s["id"]] = f"источник: {s['title']}"
    for o in opts:
        refs[o["id"]] = ("вариант к пересмотру: " if o.get("review_flag") else "вариант: ") + o["title"]
    for x in objs:
        refs[x["id"]] = f"возражение: {x['text']}"
    for d in decs:
        refs[d["id"]] = ("исходное решение, требуется пересмотр: " if d.get("review_flag") else "решение: ") + d["rationale"]
    for k in coms:
        refs[k["id"]] = f"обязательство: {k['what']}"
    live = [x for x in claims if x["status"] in ("active", "needs_review")]
    cnt = {t: sum(1 for x in live if x["type"] == t) for t in TYPE_RU}
    verified = sum(1 for x in live if x["type"] == "fact" and x.get("quote_verified"))
    cost_f = pdir / "out" / "cost.json"
    cost = store.read_json(cost_f) if cost_f.exists() else None

    h: list[str] = [f"<h1>{_esc(proj['title'])}</h1>",
                    f"<div class='mut'>Проект <code>{_esc(slug)}</code> · этап {proj['stage']} — {_esc(stages[proj['stage']]['name'])}"
                    f" · отчёт собран {clock.now()}</div>",
                    "<div class='gates mut'>" + "".join(f"<span>{g}: {GATE_RU[v['status']]}</span>" for g, v in proj["gates"].items())
                    + "</div>"]
    tiles = [(len(srcs), "источников"), (f"{verified}/{cnt['fact']}", "фактов с проверенной цитатой"),
             (cnt["hypothesis"], "гипотез"), (cnt["forecast"], "прогнозов"), (cnt["unknown"], "честных пробелов"),
             (cnt["synthetic"], "синтетических (не доказательство)"), (len(opts), "вариантов"),
             (f"${cost['total_usd']:.2f}" if cost else "—", "стоимость (API-эквивалент)")]
    h.append("<div class='grid'>" + "".join(f"<div class='tile'><b>{_esc(v)}</b><span>{_esc(k)}</span></div>" for v, k in tiles)
             + "</div>")
    nav = ["<a href='#docs'>Документы</a>", "<a href='#options'>Варианты</a>", "<a href='#decisions'>Решения</a>",
           "<a href='#claims'>Утверждения</a>", "<a href='#sources'>Источники</a>", "<a href='#cost'>Стоимость</a>",
           "<a href='#journal'>Журнал</a>"]
    h.append("<nav>" + "".join(nav) + "</nav>")

    h.append("<h2 id='docs'>Документы</h2>")
    for fname, title in DOCS:
        f = pdir / fname if fname == "brief.md" else pdir / "docs" / fname
        if f.exists():
            body = md_to_html(f.read_text(encoding="utf-8"), refs)
            if re.sub(r"<[^>]+>", "", body).strip() and any(t in body for t in ("<p>", "<li>", "<td>")):
                h.append(f"<details class='doc' {'open' if fname == 'onepager.md' else ''}><summary><b>{title}</b></summary>{body}</details>")

    h.append("<h2 id='options'>Варианты и возражения</h2>")
    for o in opts:
        mine = [x for x in objs if x["option"] == o["id"]]
        st = {"chosen": "<b class='ok'>выбран</b>", "rejected": "отклонён", "active": "", "retracted": "отозван"}[o["status"]]
        badge, notice = _review_notice(o, "Ниже исходное предложение. Руководителю нужно пересмотреть его основания.")
        chosen_in = ", ".join(_inline(f"[{d['id']}]", refs) for d in decs if d["option"] == o["id"])
        decision_link = f"<p>Согласованные условия выбора см. в решении {chosen_in}.</p>" if chosen_in else ""
        h.append(f"<details id='{o['id']}' open><summary><b>{o['id']}</b> {_esc(o['title'])} "
                 f"<span class='mut'>({KIND_RU[o['kind']]}, обратимость {o.get('reversibility', '—')})</span> {st}{badge}</summary>"
                 f"{notice}<p>{_inline(o['summary'], refs)}</p>{decision_link}<p class='mut'>Основания: "
                 + ", ".join(f"<a class='ref' href='#{b}' title='{_esc(refs.get(b, ''))}'>{b}</a>" for b in o["based_on"]) + "</p>"
                 + "".join(f"<div id='{x['id']}'><b>{x['id']}</b> <span class='b {'unknown' if x['strength'] == 'strong' else 'opinion'}'>"
                           f"{'сильное' if x['strength'] == 'strong' else 'среднее'}</span> {_esc(x['text'])}"
                           + (f"<blockquote>Ответ: {_esc(x['response'])}</blockquote>" if x.get("response") else "") + "</div>"
                           for x in mine) + "</details>")

    h.append("<h2 id='decisions'>Решения и обязательства</h2>")
    for d in decs:
        badge, notice = _review_notice(d, "Ниже зафиксированы исходное обоснование и пороги. "
                                         "Руководителю нужно повторно оценить их по новым данным.")
        h.append(f"<details id='{d['id']}' open><summary><b>{d['id']}</b> вариант {d['option']} · ответственный {_esc(d['owner'])}"
                 f" · {d['status']}{badge}</summary>{notice}<p>{_inline(d['rationale'], refs)}</p>"
                 "<table><tr><th>Метрика</th><th>База</th><th>Цель</th><th>Срок</th></tr>"
                 + "".join(f"<tr><td>{_esc(m['name'])}</td><td>{_esc(m['baseline'])}</td><td>{_esc(m['target'])}</td><td>{m['by']}</td></tr>"
                           for m in d["metrics"]) + "</table><p class='mut'>Пересмотр: "
                 + "; ".join(f"{t['kind']}: {_esc(t['value'])}" for t in d["triggers"]) + "</p></details>")
    if coms:
        today = clock.today()
        h.append("<table><tr><th>ID</th><th>Что</th><th>Кто</th><th>Срок</th><th>Статус</th></tr>" + "".join(
            f"<tr id='{k['id']}'><td>{k['id']}</td><td>{_esc(k['what'])}</td><td>{_esc(k['owner'])}</td><td>{k['due']}</td>"
            f"<td class='{'warn' if k['status'] == 'open' and k['due'] < today else ''}'>{k['status']}"
            f"{' (просрочено)' if k['status'] == 'open' and k['due'] < today else ''}</td></tr>" for k in coms) + "</table>")
    if not decs:
        h.append("<p class='mut'>Решение ещё не принято.</p>")

    h.append("<h2 id='claims'>Утверждения</h2><p class='mut'>Каждое утверждение раскрывается до цитаты и источника.</p>")
    for cl in sorted(claims, key=lambda x: list(TYPE_RU).index(x["type"])):
        badge = f"<span class='b {cl['type']}'>{TYPE_RU[cl['type']]}</span>"
        flag = {"needs_review": " <span class='warn'>требует пересмотра</span>", "retracted": " <s>отозвано</s>",
                "superseded": f" <s>заменено {cl.get('superseded_by')}</s>"}.get(cl["status"], "")
        qv = {True: "<span class='ok'>цитата найдена в источнике</span>", False: "<span class='warn'>цитата не найдена</span>"}.get(
            cl.get("quote_verified"), "")
        src = "".join(f"<div class='mut'><a class='ref' href='#{s}'>{s}</a> {_esc(srcs[s]['title'])}"
                      + (f" · <a href='{_esc(srcs[s]['url'])}'>{_esc(srcs[s]['url'][:70])}</a>" if srcs[s].get("url") else "")
                      + f" · надёжность {srcs[s].get('reliability') or '—'}</div>" for s in cl["sources"] if s in srcs)
        h.append(f"<details id='{cl['id']}'><summary><b>{cl['id']}</b> {badge} {_esc(cl['text'])}{flag}</summary>"
                 + (f"<blockquote>«{_esc(cl['quote'])}» {qv}</blockquote>" if cl.get("quote") else "")
                 + (f"<p class='mut'>Почему не знаем: {_esc(cl['why_unknown'])}</p>" if cl.get("why_unknown") else "")
                 + (f"<p class='mut'>Опирается на: {', '.join(cl['depends_on'])}</p>" if cl["depends_on"] else "")
                 + src + f"<p class='mut'>Уверенность: {cl['confidence']}</p></details>")

    h.append("<h2 id='sources'>Источники</h2><table><tr><th>ID</th><th>Название</th><th>Тип</th><th>Надёжность</th><th>Получен</th>"
             "<th>Флаги</th></tr>" + "".join(
                 f"<tr id='{s['id']}'><td>{s['id']}</td><td>" + (f"<a href='{_esc(s['url'])}'>{_esc(s['title'])}</a>" if s.get("url")
                                                                else _esc(s["title"]))
                 + f"</td><td>{s['kind']}</td><td>{s.get('reliability') or '—'}</td><td>{s['retrieved_at'][:10]}</td>"
                 f"<td class='warn'>{'внедрённые инструкции: ' + str(len(s['injection_flags'])) if s.get('injection_flags') else ''}"
                 f"{' отозван' if s['status'] == 'retracted' else ''}</td></tr>" for s in srcs.values()) + "</table>")

    h.append("<h2 id='cost'>Стоимость и время</h2>")
    if cost:
        h.append("<table><tr><th>Этап</th><th>$</th><th>Вызовов</th><th>Вход</th><th>Выход</th><th>Кэш</th></tr>" + "".join(
            f"<tr><td>{k} {_esc(stages.get(k, {}).get('name', ''))}</td><td>{v['usd']:.3f}</td><td>{v['calls']}</td>"
            f"<td>{v['input_tokens']}</td><td>{v['output_tokens']}</td><td>{v['cache_read']}</td></tr>"
            for k, v in sorted(cost["by_stage"].items())) + "</table>"
            f"<p>Сохранённый расчёт <b>${cost['total_usd']:.2f}</b> (маршрутизация ${cost['routing_usd']:.3f}). "
            f"Активное время модели: {cost.get('agent_min', '—')} мин. Всего по календарю: {cost['wall_time_min']} мин. "
            f"Ожидание решений человека: {cost['human_gate_min']} мин.</p>")
    else:
        h.append("<p class='mut'>Нет данных: выполните <code>python -m strateg cost</code>.</p>")

    ev = journal.read(slug)[-40:]
    h.append("<h2 id='journal'>Журнал (последние 40 действий)</h2><table><tr><th>Время</th><th>Этап</th><th>Кто</th><th>Что</th></tr>"
             + "".join(f"<tr><td>{e['at'][:16].replace('T', ' ')}</td><td>{e.get('stage') or ''}</td><td>{e['actor']}</td>"
                       f"<td>{_esc(e['summary'])}</td></tr>" for e in reversed(ev)) + "</table>")
    return ("<!doctype html><html lang='ru'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Стратег: {_esc(proj['title'])}</title><style>{CSS}</style></head><body><div class='wrap'>"
            + "\n".join(h) + f"</div><script>{JS}</script></body></html>")


def run(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    out = paths.project_dir(slug) / "out" / "report.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(slug), encoding="utf-8")
    journal.log(slug, "cli", "report", {"command": "report", "path": "out/report.html"})
    return Result({"path": str(out)}, human=f"Отчёт: {out}")
