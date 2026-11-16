# Скрипты агента

Один файл — `strateg.py`. Python 3.9+, только стандартная библиотека, установка не нужна. Запуск из папки `strateg/`. Форматы файлов — `../../docs/CONTRACT.md`.

CLI пишет stdout и stderr в UTF-8, в том числе при перенаправлении в файл или pipe на Windows: кириллица, ₽ и другие Unicode-символы сохраняются без `-X utf8`. Получатель перенаправленного вывода тоже должен читать UTF-8. При импорте `strateg` как модуля настройки потоков вызывающей программы не меняются.

Агент пишет в `sources.jsonl`, `evidence.jsonl`, `decisions.jsonl`, `journal.jsonl` и `state.json` только этими командами, не руками: команда проверяет запись до того, как она попадёт в файл.

## Команды

```bash
# Проекты и состояние
python3 tools/strateg.py status                 # все проекты и где остановился каждый
python3 tools/strateg.py new podpiska           # создать проект
python3 tools/strateg.py status podpiska        # шаг, следующее действие, счётчики, расходы

# Материалы: перевести файл в текст с метками места
python3 tools/strateg.py extract podpiska materials/отчёт.docx     # → materials/_text/отчёт.docx.txt, метки [абз. N]
python3 tools/strateg.py extract podpiska materials/данные.xlsx    # → по одному CSV на лист, номер строки сохранён

# Поиск и карточки
python3 tools/strateg.py find podpiska удержание цена       # реестр, источники, решения; понимает формы слов
python3 tools/strateg.py find podpiska конкурент --files    # ещё и результаты, и разобранные материалы
python3 tools/strateg.py show podpiska E-012                # утверждение, его источники и всё, что на него опирается

# Источники и утверждения
python3 tools/strateg.py source podpiska --kind site --title "Тарифы X" --ref https://example.ru/t --local materials/x.html
python3 tools/strateg.py claim podpiska --type fact --text "Тариф X — 299 ₽" --source "S-001:таблица, строка «Базовый»" --quote "Базовый — 299 ₽ в месяц" --confidence high
python3 tools/strateg.py claim podpiska --type fact --text "У купонов платят 11% пробных" --source "S-003:лист «Каналы»" --calc calc/out/channels.txt
python3 tools/strateg.py vet podpiska                       # критичные факты без смысловой сверки — карточки для сверщика
python3 tools/strateg.py vet podpiska E-012 --verdict partial --by helper --note "в источнике март, а не весь год"
python3 tools/strateg.py claim podpiska --type hypothesis --text "Цена — главный барьер" --based-on E-001
python3 tools/strateg.py claim podpiska --type fact --text "Тариф X — 349 ₽" --source "S-004:новая таблица" --supersedes E-001
python3 tools/strateg.py revoke podpiska E-001 --reason "источник устарел"
python3 tools/strateg.py impact podpiska E-001  # какие утверждения, решения и строки результатов затронуты

# Решения
python3 tools/strateg.py decide podpiska --text "Запускаем дешёвый тариф" --based-on E-002,E-005 --owner "руководитель продукта" --metric "удержание 30-го дня" --review-if "удержание < 25% через 6 недель"

python3 tools/strateg.py review podpiska         # что решать сейчас: изменившиеся основания, гипотезы, старые данные
python3 tools/strateg.py decision podpiska D-001 --status confirmed --note "вывод не меняется"   # или revised, cancelled

# Журнал и состояние
python3 tools/strateg.py log podpiska --action "разобран сайт тарифов" --tool web --minutes 2 --cost 3 --key fetch:tariffs-x
python3 tools/strateg.py step podpiska --next "сопоставить цены с оттоком"
python3 tools/strateg.py step podpiska --done collect --next "составить план исследования"
python3 tools/strateg.py step podpiska --waiting "нужна выгрузка оттока по месяцам"
python3 tools/strateg.py step podpiska --mode fast       # режим работы: fast — быстрый, full — полный
python3 tools/strateg.py step podpiska --reopen options --reason "бюджет уменьшен до 1 млн"   # вернуться к шагу: он и следующие снова открыты, решения не трогаются

# Проверка и расходы
python3 tools/strateg.py usage ~/.claude/projects/<папка>/<сеанс>.jsonl --project podpiska   # токены по моделям и цена по прайс-листу из журнала Claude Code
python3 tools/strateg.py check podpiska
python3 tools/strateg.py cost podpiska
```

Виды источников: `doc`, `table`, `site`, `image`, `audio`, `video`, `interview`, `synthetic`, `user`.
Типы утверждений: `fact`, `hypothesis`, `forecast`, `synthetic`.
Шаги: `frame`, `collect`, `research`, `options`, `strategy`, `follow`.

## Что не пропустит `check`

- факт без источника или без указания места в источнике;
- факт из материала без дословной цитаты или расчёта (при записи); цитату, которой нет в тексте источника; число из утверждения, которого нет ни в цитате, ни в расчёте;
- факт, который смысловая сверка признала неподтверждённым (`vet … --verdict no`), пока его не отозвали;
- при закрытии шагов «Варианты» и «Стратегии» — критичный факт без цитаты или без смысловой сверки;
- факт, который опирается на ответ модельного респондента;
- ссылку `[E-…]` на несуществующее, отозванное или заменённое утверждение;
- строку, где гипотеза или прогноз поданы как факт (нет слов «гипотеза», «предположительно», «прогноз», «по оценке», «вероятно», «возможно»);
- ответ модельного респондента, не названный синтетическим;
- `findings.md` без раздела «Чего мы не знаем»;
- `options.md`, где меньше трёх вариантов («## Вариант …»), нет «оставить как есть» или нет возражений;
- утверждение, которое опирается на отозванное.

Замечания без остановки: цифра без ссылки на реестр, нет варианта «закрыть направление», решение с устаревшим основанием, утверждение с заменённым основанием.

`step --done <шаг>` сам запускает проверку и не закрывает шаг при ошибках.

## Какие материалы читает `extract`

| Формат | Что получается | Метка места для реестра |
|---|---|---|
| Word `.docx` | текст и таблицы | `абз. 12`, `таблица 2, строка 3` |
| Excel `.xlsx` | CSV на каждый лист | `лист «Отток», строка 7` |
| PowerPoint `.pptx` | текст слайдов | `слайд 3` |
| `.html` | текст страницы без скриптов | цитата |
| `.csv`, `.tsv` | CSV в UTF-8 с запятой | номер строки |
| `.pdf` | текст по страницам — собственным чтением (`pdftext.py`), `pdftotext` — запасной путь | `стр. 4`; скан без текста — предупреждение |
| `.txt`, `.md`, `.json` | текст в UTF-8 | номер строки |

Границы: старые `.doc` и `.xls`, сканы без текстового слоя, изображения, аудио и видео скрипт не читает — их разбирает среда. Даты в Excel могут прийти числом. Исходный файл не меняется; результат лежит в `materials/_text/`.

## Защита от повторов

- `extract` не разбирает файл заново, если он не менялся.

- `source` с уже известной ссылкой возвращает прежний номер и не создаёт дубль.
- `log --key <метка>`: если действие с этой меткой уже записано как успешное, команда отвечает «Уже выполнено» — повторять его не нужно. Неудачное действие (`--result error`) можно повторить.

## Тесты

```bash
python3 -m unittest discover -s strateg/tools -p "test_*.py"   # из корня репозитория
```
