"""Проверка цитат. quote_match — T05, команда quotes — T08."""
from __future__ import annotations

import argparse
import re
from difflib import SequenceMatcher

from strateg.cmd import _common as c
from strateg.lib import store
from strateg.lib.out import Result

MATCH_THRESHOLD = 0.90
MIN_QUOTE_LEN = 15
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_PUNCT = re.compile(r"[«»\"'„“”—–\-*_#>`]")


def normalize(s: str) -> str:
    s = _LINK.sub(r"\1", s).lower().replace("ё", "е")
    s = _PUNCT.sub(" ", s)
    s = re.sub(r"\s+([,.;:!?])", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


def quote_match(quote: str, text: str) -> tuple[bool, float]:
    q, t = normalize(quote or ""), normalize(text or "")
    if len(q) < MIN_QUOTE_LEN or not t:
        return False, 0.0
    if q in t:
        return True, 1.0
    n, step, best = len(q), max(1, len(q) // 10), 0.0
    sm = SequenceMatcher(autojunk=False)
    sm.set_seq2(q)
    for i in range(0, max(1, len(t) - n + 1), step):
        for size in (n, int(n * 1.1)):
            sm.set_seq1(t[i:i + size])
            if sm.real_quick_ratio() <= best or sm.quick_ratio() <= best:
                continue
            best = max(best, sm.ratio())
    best = round(best, 4)
    return best >= MATCH_THRESHOLD, best


def check_claim_quote(slug: str, quote: str | None, source_ids: list[str]) -> tuple[bool | None, float | None]:
    """Лучшее совпадение цитаты по снимкам источников."""
    from strateg.cmd.source import snapshot_text

    if not quote or not source_ids:
        return None, None
    srcs = c.by_id(slug, "sources")
    best = (False, 0.0)
    for sid in source_ids:
        if sid in srcs:
            r = quote_match(quote, snapshot_text(slug, srcs[sid]))
            if r[1] > best[1]:
                best = r
    return best


def quotes(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    path = c.reg(slug, "claims")
    checked, verified, failed = 0, 0, []
    for cl in c.records(slug, "claims"):
        if not cl.get("quote") or cl["status"] in ("retracted", "superseded"):
            continue
        checked += 1
        ok, score = check_claim_quote(slug, cl["quote"], cl["sources"])
        if (ok, score) != (cl.get("quote_verified"), cl.get("quote_score")):
            store.update_record(path, cl["id"], {"quote_verified": ok, "quote_score": score}, "verify", "cli")
        if ok:
            verified += 1
        else:
            failed.append({"id": cl["id"], "best_score": score})
    data = {"checked": checked, "verified": verified, "failed": failed}
    if failed:
        return Result(data, exit_code=1, message=f"Цитаты не найдены в источниках: {len(failed)}")
    return Result(data)
