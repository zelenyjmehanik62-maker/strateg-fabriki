# Скрипты агента

Один файл — `strateg.py`. Python 3.9+, только стандартная библиотека, установка не нужна. Запуск из папки `strateg/`. Форматы файлов — `../../docs/CONTRACT.md`.

Агент пишет в `sources.jsonl`, `evidence.jsonl`, `decisions.jsonl`, `journal.jsonl` и `state.json` только этими командами, не руками: команда проверяет запись до того, как она попадёт в файл.

## Команды

```bash
# Проекты и состояние
python3 tools/strateg.py status                 # все проекты и где остановился каждый
python3 tools/strateg.py new podpiska           # создать проект
python3 tools/strateg.py status podpiska        # шаг, следующее действие, счётчики, расходы

# Источники и утверждения
python3 tools/strateg.py source podpiska --kind site --title "Тарифы X" --ref https://example.ru/t --local materials/x.html
python3 tools/strateg.py claim podpiska --type fact --text "Тариф X — 299 ₽" --source "S-001:таблица, строка «Базовый»" --confidence high
python3 tools/strateg.py claim podpiska --type hypothesis --text "Цена — главный барьер" --based-on E-001
python3 tools/strateg.py claim podpiska --type fact --text "Тариф X — 349 ₽" --source "S-004:новая таблица" --supersedes E-001
python3 tools/strateg.py revoke podpiska E-001 --reason "источник устарел"
python3 tools/strateg.py impact podpiska E-001  # какие утверждения, решения и строки результатов затронуты

# Решения
python3 tools/strateg.py decide podpiska --text "Запускаем дешёвый тариф" --based-on E-002,E-005 --owner "руководитель продукта" --metric "удержание 30-го дня" --review-if "удержание < 25% через 6 недель"

# Журнал и состояние
python3 tools/strateg.py log podpiska --action "разобран сайт тарифов" --tool web --minutes 2 --cost 3 --key fetch:tariffs-x
python3 tools/strateg.py step podpiska --next "сопоставить цены с оттоком"
python3 tools/strateg.py step podpiska --done collect --next "составить план исследования"
python3 tools/strateg.py step podpiska --waiting "нужна выгрузка оттока по месяцам"

# Проверка и расходы
python3 tools/strateg.py check podpiska
python3 tools/strateg.py cost podpiska
```

Виды источников: `doc`, `table`, `site`, `image`, `audio`, `video`, `interview`, `synthetic`, `user`.
Типы утверждений: `fact`, `hypothesis`, `forecast`, `synthetic`.
Шаги: `frame`, `collect`, `research`, `options`, `strategy`, `follow`.

## Что не пропустит `check`

- факт без источника или без указания места в источнике;
- факт, который опирается на ответ модельного респондента;
- ссылку `[E-…]` на несуществующее, отозванное или заменённое утверждение;
- строку, где гипотеза или прогноз поданы как факт (нет слов «гипотеза», «предположительно», «прогноз», «по оценке», «вероятно», «возможно»);
- ответ модельного респондента, не названный синтетическим;
- `findings.md` без раздела «Чего мы не знаем»;
- `options.md`, где меньше трёх вариантов («## Вариант …»), нет «оставить как есть» или нет возражений;
- утверждение, которое опирается на отозванное.

Замечания без остановки: цифра без ссылки на реестр, нет варианта «закрыть направление», решение с устаревшим основанием.

`step --done <шаг>` сам запускает проверку и не закрывает шаг при ошибках.

## Защита от повторов

- `source` с уже известной ссылкой возвращает прежний номер и не создаёт дубль.
- `log --key <метка>`: если действие с этой меткой уже записано как успешное, команда отвечает «Уже выполнено» — повторять его не нужно. Неудачное действие (`--result error`) можно повторить.

## Тесты

```bash
python3 -m unittest discover -s strateg/tools -p "test_*.py"   # из корня репозитория
```
