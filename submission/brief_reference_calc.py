"""Контрольные расчёты по предоставленному учебному примеру, не прогноз демо.

Запуск: python submission/brief_reference_calc.py
Числа явно взяты со стр. 3, 6, 9 PDF; исходный файл и проект агента не меняются.
"""
import json
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def reference_values():
    # Все числа — учебные условия, а не измерения клиентов или допущения о результате.
    baseline_profit = 279_000_000
    target_profit = 285_000_000
    contribution_per_extra_paid_month = 500
    family_start, family_bau, family_target = 6500, 8000, 12000
    owner_start, owner_bau, owner_target = 800, 1000, 2000
    return {
        "status": "Учебные контрольные значения; достижимость целей не доказана",
        "profit_gap_rub": target_profit - baseline_profit,
        "extra_paid_months_if_no_other_income_or_new_direct_cost":
            (target_profit - baseline_profit) // contribution_per_extra_paid_month,
        "extra_paid_months_formula":
            "(6000000 + новые прямые расходы - другие дополнительные вклады) / 500; "
            "при положительном разрыве округлить вверх до целого оплаченного месяца",
        "family_net_growth_from_start": family_target - family_start,
        "family_increment_over_bau": family_target - family_bau,
        "owner_net_growth_from_start": owner_target - owner_start,
        "owner_increment_over_bau": owner_target - owner_bau,
        "active_share_at_family_target_pct": 8000 / family_target * 100,
        "active_share_bau_pct": 5000 / family_bau * 100,
        "family_target_share_of_accessible_base_pct": family_target / 100000 * 100,
        "owner_target_share_of_accessible_base_pct": owner_target / 40000 * 100,
        "activation_gap_pp": 60 - 45,
        "illustrative_restriction_change_pp": 12 - 9,
        "illustrative_restriction_relative_drop_pct": (12 - 9) / 12 * 100,
        "cautions": [
            "Снижение 12% до 9% — пример определения эффекта, не измеренный результат",
            "Активность и активация за 14 дней имеют разные определения",
            "Разработка считается отдельно при расчёте окупаемости",
            "Нет исходной частоты, потока и дисперсии: выборка и сроки пилота не рассчитаны",
        ],
    }


if __name__ == "__main__":
    print(json.dumps(reference_values(), ensure_ascii=False, indent=2))
