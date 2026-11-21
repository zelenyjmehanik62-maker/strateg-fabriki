import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
from pathlib import Path

# Все значения, кроме учебных 279 млн и 500 руб., являются допущениями.
COHORTS = [(600, 9), (1800, 6), (3600, 3)]
BASE_RETENTION = 0.97
DIRECT_COST = 700000

def estimate(retention):
    months = sum(n * sum(retention**k - BASE_RETENTION**k for k in range(m)) for n, m in COHORTS)
    return {'extra_paid_months': months, 'contribution_rub': months * 500,
            'new_direct_cost_rub': DIRECT_COST,
            'annual_gross_profit_rub': 279000000 + months * 500 - DIRECT_COST}

if __name__ == '__main__':
    output = {'base': estimate(0.98), 'downside': estimate(0.97), 'sensitivity': estimate(0.99),
              'target_extra_months_with_cost': (6000000 + DIRECT_COST) / 500,
              'cohorts': COHORTS}
    text = json.dumps(output, ensure_ascii=False, indent=2)
    Path(__file__).with_name('recalculated.json').write_text(text, encoding='utf-8')
    print(text)
