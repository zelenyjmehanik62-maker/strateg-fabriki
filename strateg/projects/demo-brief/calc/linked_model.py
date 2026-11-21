import sys
sys.stdout.reconfigure(encoding="utf-8")
import json
import csv
import math
from pathlib import Path

# Учебные условия E-004, E-005; остальное — явно условные допущения.
# Месяцы — относительно начала планового года, не даты обещанного запуска.
ROOT = Path(__file__).parent
INPUTS = dict(initial_groups=6500, contacts=50000, create_rate=.10,
              baseline_new_groups=3500, baseline_end_groups=8000,
              scenario_end_groups=10000, baseline_active_share=.625,
              scenario_active_share=.65, eligible_share=.20,
              paid_lines_per_eligible_group=2, launch_month=4,
              baseline_line_retention=.97, scenario_line_retention=.98,
              baseline_profit_rub=279000000, margin_per_paid_month_rub=500,
              direct_cost_rub=700000, development_budget_rub=None)

def group_retention(new, target):
    # Выход на прежний сценарный итог калибровкой, а не оценкой реального ухода.
    low, high = 0., 1.
    for _ in range(100):
        rate = (low + high) / 2
        end = INPUTS['initial_groups'] * rate**12 + sum(new / 12 * rate**k for k in range(12))
        if end < target:
            low = rate
        else:
            high = rate
    return (low + high) / 2

def run(new_groups, target, active_share, line_retention, eligible_share=None):
    q = INPUTS['eligible_share'] if eligible_share is None else eligible_share
    s = group_retention(new_groups, target)
    cohorts = [(0, INPUTS['initial_groups'])] + [(m, new_groups / 12) for m in range(1, 13)]
    # По каждой когорте один вход в доступ: доля активных и подходящих на момент входа.
    # Поздняя активация и повторный вход не моделируются. Это не все активные семьи.
    access = []
    for birth, n in cohorts:
        start = max(INPUTS['launch_month'], birth)
        families = n * s**(start - birth) * active_share * q
        access.append((start, families * INPUTS['paid_lines_per_eligible_group']))
    rows = []
    for month in range(1, 13):
        groups = sum(n * s**(month - birth) for birth, n in cohorts if birth <= month)
        extra = sum(n * (line_retention**(month-start) - INPUTS['baseline_line_retention']**(month-start))
                    for start, n in access if start <= month)
        rows.append(dict(month=month, contacts=new_groups / INPUTS['create_rate'] / 12,
                         created_groups=new_groups/12, connected_groups=groups,
                         active_groups=groups*active_share,
                         first_exposed_paid_lines=sum(n for start, n in access if start == month),
                         extra_paid_line_months=extra))
    extra = sum(row['extra_paid_line_months'] for row in rows)
    contribution = extra * INPUTS['margin_per_paid_month_rub']
    return dict(group_monthly_survival_calibrated=s, rows=rows,
                extra_paid_line_months=extra, contribution_rub=contribution,
                gross_profit_rub=INPUTS['baseline_profit_rub'] + contribution - INPUTS['direct_cost_rub'],
                direct_cost_break_even_rub=contribution)

def calculate():
    new = INPUTS['contacts'] * INPUTS['create_rate']
    base = run(INPUTS['baseline_new_groups'], INPUTS['baseline_end_groups'], INPUTS['baseline_active_share'], .97)
    main = run(new, INPUTS['scenario_end_groups'], INPUTS['scenario_active_share'], .98)
    downside = run(new, INPUTS['scenario_end_groups'], INPUTS['scenario_active_share'], .97)
    sensitivity = run(new, INPUTS['scenario_end_groups'], INPUTS['scenario_active_share'], .99)
    # Проверяемый эффект самого предупреждения при неизменном привлечении/уходе групп.
    warning_only = run(INPUTS['baseline_new_groups'], INPUTS['baseline_end_groups'], INPUTS['baseline_active_share'], .98)
    assert abs(base['rows'][-1]['connected_groups'] - 8000) < 1e-6
    assert abs(main['rows'][-1]['connected_groups'] - 10000) < 1e-6
    assert downside['extra_paid_line_months'] == 0
    assert run(new, 10000, .65, .98, eligible_share=0)['extra_paid_line_months'] == 0
    assert main['extra_paid_line_months'] < sensitivity['extra_paid_line_months']
    # Это варианты ёмкости набора, НЕ расчёт статистически достаточной выборки.
    recruitment = [dict(total_families=n, first_eligible_per_week=f,
                        weeks_including_last_followup=math.ceil(n/f)+1)
                   for n in (1000, 3000, 6000) for f in (25, 100, 250)]
    result = dict(inputs=INPUTS, baseline=base, main=main, downside=downside,
                  sensitivity=sensitivity, warning_only=warning_only,
                  target_extra_paid_months=(285000000-279000000+INPUTS['direct_cost_rub'])/500,
                  recruitment_capacity_not_power=recruitment,
                  activation_14d=dict(baseline=.45, scenario=.55, target=.60,
                                      note='Отдельная гипотеза, не равна месячной активности и не умножается на неё'))
    out = ROOT / 'out'
    out.mkdir(exist_ok=True)
    (out/'linked_model.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    with (out/'linked_monthly.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(main['rows'][0]))
        writer.writeheader()
        writer.writerows(main['rows'])
    lines = ['Все результаты ниже — условные прогнозы, не измерения.']
    for name in ('main', 'downside', 'sensitivity', 'warning_only'):
        r = result[name]
        lines.append(f"{name}: дополнительные оплаченные месяцы = {r['extra_paid_line_months']:.1f}; вклад = {r['contribution_rub']:.0f} руб.; валовая прибыль = {r['gross_profit_rub']/1e6:.3f} млн руб.")
    lines.append(f"Для цели нужно {result['target_extra_paid_months']:.0f} дополнительных оплаченных месяцев.")
    lines.append('Новые группы не считаются новыми платящими номерами. Вклад привлечения в оплату не включён.')
    (out/'linked_model.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print('\n'.join(lines))
    return result

if __name__ == '__main__':
    calculate()
