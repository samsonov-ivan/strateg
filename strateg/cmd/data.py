"""Профиль качества данных и когорты. T12."""
from __future__ import annotations

import argparse
import json
import re
import shlex
from pathlib import Path

import pandas as pd

from strateg.cmd import _common as c
from strateg.lib import journal, paths
from strateg.lib.out import CliError, Result

UNITS = ["руб", "₽", "%", "шт", "тыс", "млн", "usd", "$"]


def _load(path: str, sheet: str | None = None) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise CliError("NOT_FOUND", f"Файл не найден: {path}")
    try:
        if p.suffix.lower() in (".xlsx", ".xls"):
            return pd.read_excel(p, sheet_name=sheet or 0)
        return pd.read_csv(p)
    except Exception as e:
        raise CliError("IO_ERROR", f"Не удалось прочитать таблицу: {e}") from None


def _dates(s: pd.Series) -> pd.Series | None:
    if pd.api.types.is_numeric_dtype(s):
        return None
    d = pd.to_datetime(s, errors="coerce", format="mixed")
    return d if d.notna().mean() >= 0.8 and s.notna().any() else None


def _cmd(args: argparse.Namespace, name: str) -> str:
    skip = {"json", "project", "handler", "group", "command"}
    parts = ["python -m strateg data", name]
    for k, v in vars(args).items():
        if k in skip or v is None or k == "path":
            continue
        parts += [f"--{k.replace('_', '-')}", str(v)]
    return " ".join(shlex.quote(x) for x in parts + [args.path])


def profile(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    df = _load(args.path, args.sheet)
    cfg = paths.load_config("kb")
    count_rx = re.compile(cfg["count_like"], re.I)
    cols, issues = [], []
    for name in df.columns:
        s = df[name]
        miss = int(s.isna().sum())
        col = {"name": str(name), "dtype": str(s.dtype), "missing": miss, "missing_pct": round(100 * miss / max(1, len(s)), 1),
               "unique": int(s.nunique()), "min": None, "max": None, "top5": None}
        if col["missing_pct"] > 20:
            issues.append({"column": str(name), "kind": "missing_high", "message": f"пропусков {col['missing_pct']}%"})
        types = {type(x).__name__ for x in s.dropna()}
        if s.dtype == object and len(types) > 1:
            issues.append({"column": str(name), "kind": "mixed_types", "message": f"смешанные типы: {sorted(types)}"})
        d = _dates(s)
        if pd.api.types.is_numeric_dtype(s):
            col["min"], col["max"] = (None, None) if s.dropna().empty else (float(s.min()), float(s.max()))
            if count_rx.search(str(name)) and (s < 0).any():
                issues.append({"column": str(name), "kind": "negative_count",
                               "message": f"отрицательные значения: {int((s < 0).sum())}"})
            if re.search(r"pct|percent|%|доля|процент", str(name), re.I):
                v = s.dropna()
                if (v <= 1).any() and (v > 1).any():
                    issues.append({"column": str(name), "kind": "mixed_percent_scale",
                                   "message": "смешаны доли (≤1) и проценты (>1)"})
        elif d is not None:
            dd = d.dropna().drop_duplicates().sort_values()
            col["min"], col["max"] = str(dd.min().date()), str(dd.max().date())
            freq = None
            if len(dd) >= 3:
                if all(x.day == 1 for x in dd):
                    freq = "MS"
                else:
                    step = dd.diff().dropna().dt.days.mode()
                    freq = {1: "D", 7: "W"}.get(int(step.iloc[0])) if not step.empty else None
            if freq:
                full = pd.date_range(dd.min(), dd.max(), freq=freq if freq != "W" else pd.offsets.Week(weekday=dd.min().weekday()))
                gaps = [str(x.date()) for x in full if x not in set(dd)]
                if gaps:
                    issues.append({"column": str(name), "kind": "period_gap", "message": f"пропущены периоды: {', '.join(gaps[:10])}"})
        else:
            col["top5"] = {str(k): int(v) for k, v in s.value_counts().head(5).items()}
        low = str(name).lower()
        hint = [u for u in UNITS if u in low or (u == "руб" and low.endswith("_rub"))]
        if hint or low.endswith("_rub"):
            issues.append({"column": str(name), "kind": "unit_hint", "message": f"единицы: {', '.join(hint) or 'руб'}"})
        cols.append(col)
    dup = int(df.duplicated().sum())
    if dup:
        issues.append({"column": "*", "kind": "duplicate_rows", "message": f"полных дублей строк: {dup}"})
    data = {"rows": int(len(df)), "columns": cols, "issues": issues}
    out = paths.project_dir(slug) / "out"
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.path).stem
    (out / f"profile_{stem}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    md = [f"# Профиль данных: {Path(args.path).name}", "", f"Строк: {len(df)}, колонок: {len(df.columns)}", "",
          "| Колонка | Тип | Пропуски, % | Уникальных | Мин | Макс |", "|---|---|---|---|---|---|"]
    md += [f"| {x['name']} | {x['dtype']} | {x['missing_pct']} | {x['unique']} | {x['min']} | {x['max']} |" for x in cols]
    md += ["", "## Проблемы", ""] + [f"- **{i['column']}** — {i['kind']}: {i['message']}" for i in issues]
    (out / f"profile_{stem}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    journal.log(slug, "cli", f"data profile {Path(args.path).name}", {"command": _cmd(args, "profile")})
    return Result(data)


def cohort(args: argparse.Namespace) -> Result:
    slug = c.slug_of(args)
    df = _load(args.path)
    for col in (args.user, args.start, args.event):
        if col not in df.columns:
            raise CliError("BAD_ARGS", f"Нет колонки {col}")
    df = df[[args.user, args.start, args.event]].dropna().copy()
    df["s"] = pd.to_datetime(df[args.start], errors="coerce")
    df["e"] = pd.to_datetime(df[args.event], errors="coerce")
    bad = int(df[["s", "e"]].isna().any(axis=1).sum())
    df = df.dropna(subset=["s", "e"])
    if args.period == "month":
        df["cohort"] = df["s"].dt.strftime("%Y-%m")
        df["n"] = (df["e"].dt.year - df["s"].dt.year) * 12 + (df["e"].dt.month - df["s"].dt.month)
    else:
        iso = df["s"].dt.isocalendar()
        df["cohort"] = iso["year"].astype(str) + "-W" + iso["week"].astype(str).str.zfill(2)
        ws = df["s"] - pd.to_timedelta(df["s"].dt.weekday, unit="D")
        we = df["e"] - pd.to_timedelta(df["e"].dt.weekday, unit="D")
        df["n"] = ((we.dt.normalize() - ws.dt.normalize()).dt.days // 7)
    neg = int((df["n"] < 0).sum())
    df = df[df["n"] >= 0]
    size = df.groupby("cohort")[args.user].nunique()
    active = df.groupby(["cohort", "n"])[args.user].nunique()
    maxn = int(df["n"].max()) if len(df) else 0
    last = df["e"].max()
    lines = ["cohort,size," + ",".join(str(i) for i in range(maxn + 1))]
    md = ["| Когорта | Размер | " + " | ".join(str(i) for i in range(maxn + 1)) + " |", "|---|---|" + "---|" * (maxn + 1)]
    for coh in sorted(size.index):
        start = df.loc[df["cohort"] == coh, "s"].min()
        avail = ((last.year - start.year) * 12 + last.month - start.month) if args.period == "month" else (last - start).days // 7
        vals = []
        for i in range(maxn + 1):
            vals.append("" if i > avail else f"{active.get((coh, i), 0) / size[coh]:.4f}")
        lines.append(f"{coh},{size[coh]}," + ",".join(vals))
        md.append(f"| {coh} | {size[coh]} | " + " | ".join(v or "—" for v in vals) + " |")
    out = paths.project_dir(slug) / "out"
    out.mkdir(parents=True, exist_ok=True)
    stem = Path(args.path).stem
    (out / f"cohort_{stem}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / f"cohort_{stem}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    notes = []
    if bad:
        notes.append(f"строк с нераспознанной датой: {bad}")
    if neg:
        notes.append(f"событий раньше старта (отброшены): {neg}")
    journal.log(slug, "cli", f"data cohort {Path(args.path).name}", {"command": _cmd(args, "cohort")})
    return Result({"cohorts": int(len(size)), "periods": maxn + 1, "matrix_path": f"out/cohort_{stem}.csv", "notes": notes})
