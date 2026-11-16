#!/usr/bin/env python3
"""Сравнивает вердикты сверщика фактов на разных моделях с эталоном.

Запуск из корня репозитория:  python3 bench/routing/score.py
Вердикты — bench/routing/results/<модель>.txt, строки вида «E-012 | supports | пояснение».
Эталон и происхождение эталона — bench/routing/expected.json.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LINE = re.compile(r"^\s*(E-\d+)\s*\|\s*(supports|partial|no)\b", re.I | re.M)


def main():
    exp = json.loads((HERE / "expected.json").read_text(encoding="utf-8"))
    ref, meta = exp["reference"], exp["meta"]
    must_catch = meta["planted"] + meta["real_error"]
    rows = []
    for path in sorted((HERE / "results").glob("*.txt")):
        got = {m.group(1): m.group(2).lower() for m in LINE.finditer(path.read_text(encoding="utf-8"))}
        missing = [i for i in ref if i not in got]
        caught = [i for i in must_catch if got.get(i) == "no"]
        flagged = [i for i in must_catch if got.get(i) in ("no", "partial")]
        exact = sum(1 for i in ref if got.get(i) == ref[i])
        false_alarm = [i for i in ref if ref[i] == "supports" and got.get(i) in ("no", "partial")]
        rows.append((path.stem, len(got), len(missing), len(caught), len(flagged), exact, false_alarm))
    print(f"Карточек: {len(ref)}; обязательно поймать (no): {', '.join(must_catch)}")
    print("| Модель | Ответов | Пропущено | Поймано «no» | Отмечено no/partial | Совпало с эталоном | Ложные тревоги |")
    print("|---|---|---|---|---|---|---|")
    for name, n, miss, caught, flagged, exact, fa in rows:
        print(f"| {name} | {n} | {miss} | {caught} из {len(must_catch)} | {flagged} из {len(must_catch)} | "
              f"{exact} из {len(ref)} | {len(fa)}{' (' + ', '.join(fa) + ')' if fa else ''} |")


if __name__ == "__main__":
    main()
