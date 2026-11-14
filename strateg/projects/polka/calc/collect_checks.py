"""Проверка таблицы показателей и первые расчёты. Запуск: python3 calc/collect_checks.py из папки проекта."""
import csv, pathlib
T = pathlib.Path(__file__).resolve().parent.parent / "materials" / "_text"
def rows(n):
    return list(csv.reader(open(T / f"показатели-подписки.xlsx.лист{n}.csv", encoding="utf-8")))
print("== Когорты: пересчёт доли, удержание 2-го и 3-го месяца")
q3t = q3p = 0
for r in rows(1)[2:]:
    m, t, p = r[0], int(r[1]), int(r[2])
    m2 = int(r[4]) if r[4] else None; m3 = int(r[5]) if len(r) > 5 and r[5] else None
    print(m, t, p, f"доля {100*p/t:.1f}% (в таблице {r[3]})",
          f"м2/м1 {100*m2/p:.1f}%" if m2 else "", f"м3/м1 {100*m3/p:.1f}%" if m3 else "")
    if m in ("2026-07", "2026-08", "2026-09"): q3t += t; q3p += p
print("Q3 когорты: пробных", q3t, "оплатили", q3p, f"{100*q3p/q3t:.1f}%")
print("== Каналы, Q3")
st = sp = sc = 0
for r in rows(2)[2:]:
    t, p, c = int(r[1]), int(r[2]), int(r[3]); st += t; sp += p; sc += c
    print(f"{r[0]}: пробных {t}, оплатили {p}, доля {100*p/t:.1f}%, расходы {c} тыс., на оплатившего {1000*c/p:.0f} ₽" )
print("Итого каналы:", st, sp, f"{100*sp/st:.1f}%", "расходы", sc, "тыс.")
ch = {r[0]: (int(r[1]), int(r[2])) for r in rows(2)[2:]}
t = st - ch["Купонные сайты и промокоды"][0]; p = sp - ch["Купонные сайты и промокоды"][1]
print(f"Без купонных: {p}/{t} = {100*p/t:.1f}%")
print(f"Доля купонных среди пробных: {100*ch['Купонные сайты и промокоды'][0]/st:.1f}%")
print("== Пробный период, Q3")
bt = bp = 0
for r in rows(3)[2:]:
    t, p = int(r[1]), int(r[2]); bt += t; bp += p
    print(f"{r[0]}: {t} чел. ({{:.1f}}% всех), оплатили {p}, доля {100*p/t:.1f}%".format(100*t/23100))
print("Итого:", bt, bp, f"{100*bp/bt:.1f}%")
print("== Причины отмены")
rs = [(r[0], int(r[1])) for r in rows(4)[2:]]; tot = sum(n for _, n in rs)
for k, n in rs: print(f"{k}: {n} ({100*n/tot:.1f}%)")
print("Всего ответов:", tot, f"охват опроса {100*1840/8000:.0f}% отключившихся")
