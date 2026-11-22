"""Учебные данные для демо «Стратега»: подписочный сервис теряет пользователей после пробного периода.

Данные синтетические, сгенерированы командой (собственный материал), с ЗАЛОЖЕННЫМИ причинами оттока —
чтобы проверить, найдёт ли агент правду. Описание закладки пишется в отдельный файл (--truth-out),
который хранится вне репозитория до окончания демо-прогона, чтобы агент его не видел.

Запуск:
    .venv/bin/python examples/make_demo_data.py --out examples/demo-retention/materials --truth-out ../demo_private/GROUND_TRUTH.md
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261110
START, END = date(2026, 1, 1), date(2026, 9, 30)
OBS_END = date(2026, 10, 31)
PRICE_RUB = 299
TRIAL_DAYS = 7
ONBOARDING_V2_FROM = date(2026, 6, 15)

# Закладка (истина):
FIRST_CHARGE_CANCEL = {"organic": 0.14, "partner": 0.18, "promo": 0.46}   # причина 1: промо-канал уходит в день первого списания
ONBOARDING_V2_EXTRA_FIRST = 0.09                                           # причина 2: новый онбординг
ONBOARDING_V2_EXTRA_MONTHLY = 0.05
BASE_MONTHLY_HAZARD = 0.07


def promo_share(d: date) -> float:
    """Доля промо-канала растёт с мая (маркетинговая кампания) — сдвиг структуры."""
    return 0.12 if d < date(2026, 5, 1) else 0.38


def signups_per_day(d: date) -> float:
    """Ложный след: летом приток ниже (сезонность притока), но удержание когорт от сезона не зависит."""
    base = 26.0
    return base * (0.7 if d.month in (7, 8) else 1.0)


def generate(rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    users, events = [], []
    uid = 0
    d = START
    while d <= END:
        for _ in range(rng.poisson(signups_per_day(d))):
            uid += 1
            ps = promo_share(d)
            channel = rng.choice(["organic", "partner", "promo"], p=[0.72 - ps * 0.6, 0.28 - ps * 0.4, ps])
            onboarding = "v2" if d >= ONBOARDING_V2_FROM else "v1"
            p_first = FIRST_CHARGE_CANCEL[channel] + (ONBOARDING_V2_EXTRA_FIRST if onboarding == "v2" else 0)
            hazard = BASE_MONTHLY_HAZARD + (ONBOARDING_V2_EXTRA_MONTHLY if onboarding == "v2" else 0)
            first_charge = d + timedelta(days=TRIAL_DAYS)
            cancel = None
            trial_cancel = rng.random() < 0.06            # отмена ещё в пробный период
            if trial_cancel:
                cancel = d + timedelta(days=int(rng.integers(1, TRIAL_DAYS)))
            elif rng.random() < p_first:
                cancel = first_charge + timedelta(days=int(rng.integers(0, 2)))   # в день списания или на следующий
            else:
                m = 1
                while True:
                    charge = first_charge + timedelta(days=30 * m)
                    if charge > OBS_END:
                        break
                    if rng.random() < hazard:
                        cancel = charge + timedelta(days=int(rng.integers(-3, 1)))
                        break
                    m += 1
            uid_s = f"u{uid:05d}"
            users.append({"user_id": uid_s, "signup_date": d.isoformat(), "channel": channel, "onboarding": onboarding,
                          "trial_days": TRIAL_DAYS, "price_rub": PRICE_RUB,
                          "cancel_date": cancel.isoformat() if cancel and cancel <= OBS_END else ""})
            # активность: события в каждый месяц жизни (для когорт)
            last = min(cancel or OBS_END, OBS_END)
            day = d
            while day <= last:
                events.append({"user_id": uid_s, "signup_date": d.isoformat(), "event_date": day.isoformat()})
                day += timedelta(days=30)
        d += timedelta(days=1)
    return pd.DataFrame(users), pd.DataFrame(events)


def monthly_metrics(users: pd.DataFrame) -> pd.DataFrame:
    """Агрегаты «как в дашборде РП»: показывают падение, но не причину."""
    u = users.copy()
    u["s"] = pd.to_datetime(u["signup_date"])
    u["c"] = pd.to_datetime(u["cancel_date"].replace("", None))
    rows = []
    for m in pd.period_range("2026-01", "2026-10", freq="M"):
        ms, me = m.start_time, m.end_time
        active_start = ((u["s"] < ms) & (u["c"].isna() | (u["c"] >= ms))).sum()
        cancelled = ((u["c"] >= ms) & (u["c"] <= me)).sum()
        new = ((u["s"] >= ms) & (u["s"] <= me)).sum()
        paying = ((u["s"] + pd.Timedelta(days=TRIAL_DAYS) <= me) & (u["c"].isna() | (u["c"] > me))).sum()
        coh = u[(u["s"] >= ms) & (u["s"] <= me)]
        mature = coh["s"] + pd.Timedelta(days=37) <= pd.Timestamp(OBS_END)
        kept = (coh["c"].isna() | (coh["c"] > coh["s"] + pd.Timedelta(days=37)))[mature]
        m1 = round(100 * kept.mean(), 1) if mature.sum() >= 0.9 * max(1, len(coh)) and len(coh) else None
        rows.append({"month": str(m), "new_users": int(new), "retained_after_month1_pct": m1, "active_start": int(active_start), "cancellations": int(cancelled),
                     "churn_rate_pct": round(100 * cancelled / max(1, active_start + new), 1),
                     "paying_end": int(paying), "revenue_rub": int(paying * PRICE_RUB)})
    return pd.DataFrame(rows)


TRUTH = """# GROUND TRUTH — закладка учебных данных (не показывать агенту до конца прогона)

Сгенерировано `examples/make_demo_data.py`, seed {seed}.

## Настоящие причины роста оттока
1. **Сдвиг структуры притока к промо-каналу с 1 мая 2026** (доля промо {p0:.0%} → {p1:.0%}). Промо-пользователи
   массово отменяют подписку в день первого списания: вероятность отмены при первом списании
   organic {fo:.0%}, partner {fp:.0%}, **promo {fpr:.0%}**.
2. **Новый онбординг v2 с {v2}**: +{e1:.0%} к отмене при первом списании и +{e2:.0%} к ежемесячному оттоку для всех каналов.

## Ложный след
- **Сезонность**: летом (июль–август) приток новых пользователей ниже на 30%, из-за чего падают общие активные
  пользователи и выручка. На удержание внутри когорт сезон **не влияет**.

## Что должен найти агент (критерии проверки)
- [ ] Отток концентрируется в день первого списания (≈ день 7–8).
- [ ] Промо-канал удерживается заметно хуже других; его доля выросла с мая.
- [ ] Когорты с онбордингом v2 (с 15.06) удерживаются хуже v1 при одинаковом канале.
- [ ] Сезонность отвергнута как причина оттока (влияет на приток, а не на удержание).
- [ ] Данные учебные — агент не выдаёт их за реальные данные МегаФона.
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--truth-out", required=True)
    a = ap.parse_args()
    users, events = generate(np.random.default_rng(SEED))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    users.to_csv(out / "users.csv", index=False)
    events.to_csv(out / "activity.csv", index=False)
    monthly_metrics(users).to_csv(out / "dashboard_monthly.csv", index=False)
    t = Path(a.truth_out)
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text(TRUTH.format(seed=SEED, p0=promo_share(date(2026, 1, 1)), p1=promo_share(date(2026, 6, 1)),
                              fo=FIRST_CHARGE_CANCEL["organic"], fp=FIRST_CHARGE_CANCEL["partner"],
                              fpr=FIRST_CHARGE_CANCEL["promo"], v2=ONBOARDING_V2_FROM.strftime("%d.%m.%Y"),
                              e1=ONBOARDING_V2_EXTRA_FIRST, e2=ONBOARDING_V2_EXTRA_MONTHLY), encoding="utf-8")
    print(f"users: {len(users)}, activity rows: {len(events)} → {out}; truth → {t}")


if __name__ == "__main__":
    main()
