"""Модель планового года. Запуск: .venv/bin/python examples/family-strategy/model.py."""
import csv
import json
import math
from pathlib import Path
from statistics import NormalDist

out = Path(__file__).resolve().parent
scenarios = {
    "основной": dict(may=80, june=40, avoided=.15, saved=.15, direct=12),
    "слабый": dict(may=40, june=20, avoided=.04, saved=.05, direct=18),
}
survival = .96
unit_margin = 500
monthly = []
summary = {}
for name, p in scenarios.items():
    new = {5: p['may'], 6: p['june']}
    cohorts = {}
    totals = []
    for month in range(1, 13):
        if month in new:
            cohorts[month] = (new[month], new[month])
        control = exposed = 0
        for cohort, (c, t) in list(cohorts.items()):
            if cohort < month:
                c *= survival
                transition = survival + p['avoided'] * p['saved'] if month == cohort + 1 else survival
                t *= transition
                cohorts[cohort] = c, t
            control += c
            exposed += t
        difference = exposed - control
        cost = new.get(month, 0) * p['direct']
        net = unit_margin * difference - cost
        row = dict(scenario=name, month=month, new_exposed=new.get(month,0),
                   new_control=new.get(month,0), paid_control=control, paid_exposed=exposed,
                   extra_paid_months=difference, direct_rub=cost, incremental_gross_rub=net)
        monthly.append(row)
        totals.append(row)
    def total(key, rows=totals):
        return sum(row[key] for row in rows)
    quarter = [sum(t['incremental_gross_rub'] for t in totals[i:i+3]) for i in range(0,12,3)]
    paymonths = total('extra_paid_months')
    count = sum(new.values())
    summary[name] = dict(n_exposed=count, avoided=count*p['avoided'], paid_months=paymonths,
        direct=total('direct_rub'), quarter=quarter, extra_gross=sum(quarter),
        gross=279000000+sum(quarter), investments=[90000,480000,15000,15000],
        deficit=600000-sum(quarter), paymonths_for_target=(6000000+total('direct_rub'))/500,
        upper_possible=sum(n*(12-c) for c,n in new.items()),
        unit_gross=sum(quarter)/count,
        months_at_risk_weight=paymonths/(p['avoided']*p['saved']),
        odds_break_even_direct=total('direct_rub')/(paymonths/p['saved']*unit_margin))
with (out/'monthly.csv').open('w',newline='',encoding='utf-8') as f:
    writer=csv.DictWriter(f,fieldnames=monthly[0].keys(),lineterminator="\n")
    writer.writeheader()
    writer.writerows(monthly)
z = NormalDist().inv_cdf
a,b=.25,.10
pooled=(a+b)/2
per_arm=(z(.975)*math.sqrt(2*pooled*(1-pooled))+z(.8)*math.sqrt(a*(1-a)+b*(1-b)))**2/(a-b)**2
summary['design']=dict(raw_per_arm=per_arm, with_loss=math.ceil(math.ceil(per_arm)/.95),
                       zero_upper_120=1-.05**(1/120), zero_n_2pct=math.ceil(math.log(.05)/math.log(.98)))
def probability_of_passing(n):
    """Вероятность пройти пороги клиентского исхода по всем парам биномиальных исходов."""
    critical = z(.975)
    def wilson(k):
        rate = k / n
        divisor = 1 + critical**2/n
        center = (rate + critical**2/(2*n))/divisor
        radius = critical*math.sqrt(rate*(1-rate)/n + critical**2/(4*n**2))/divisor
        return center-radius, center+radius
    def probabilities(rate):
        return [math.comb(n,k)*rate**k*(1-rate)**(n-k) for k in range(n+1)]
    intervals = [wilson(k) for k in range(n+1)]
    test = probabilities(b)
    result = 0.
    for k, mass in enumerate(probabilities(a)):
        for j in range(k+1):
            effect = (k-j)/n
            lower = effect-math.hypot(k/n-intervals[k][0], intervals[j][1]-j/n)
            if effect >= .10 and lower >= .05:
                result += mass*test[j]
    return result
summary['design']['chance_to_pass_by_n'] = {
    str(n): probability_of_passing(n) for n in (100,120,225)
}
(out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n', encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
