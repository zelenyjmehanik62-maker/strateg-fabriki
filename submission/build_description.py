"""Build the T13 working PDF. Authoring dependency: reportlab, not a product dependency."""
from pathlib import Path
import html
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'submission'
EVIDENCE = HERE / 'evidence'
EVIDENCE.mkdir(exist_ok=True)

def capture(name, args, cwd):
    result = subprocess.run([sys.executable, '-X', 'utf8', *args], cwd=cwd,
                            capture_output=True, text=True, encoding='utf-8')
    output = result.stdout + result.stderr
    (EVIDENCE / (name + '.txt')).write_text(output, encoding='utf-8')
    return result.returncode, output

def prepare():
    check_code, check = capture('check-polka', ['tools/strateg.py', 'check', 'polka'], ROOT / 'strateg')
    cost_code, cost = capture('cost-polka', ['tools/strateg.py', 'cost', 'polka'], ROOT / 'strateg')
    show_code, show = capture('show-E-047', ['tools/strateg.py', 'show', 'polka', 'E-047'], ROOT / 'strateg')
    metric_code, metrics = capture('metrics', ['bench/metrics.py'], ROOT)
    if any((check_code, cost_code, show_code, metric_code)):
        raise RuntimeError('A source command failed; inspect evidence text')
    (EVIDENCE / 'capture-manifest.json').write_text(json.dumps({
        'date': '2026-11-16', 'project': 'polka', 'encoding': 'UTF-8 (-X utf8)',
        'commands': {'check': check_code, 'cost': cost_code, 'show': show_code, 'metrics': metric_code},
        'note': 'Read-only CLI commands. Not a new end-to-end agent run.'
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    for name, title, text in [
        ('verification', 'Проверка учебного проекта / фрагменты вывода CLI', check.splitlines()[-1] + '\n\n' + metrics + '\n' + '\n'.join(cost.splitlines()[:4])),
        ('traceability', 'Карточка E-047 / фрагмент вывода CLI', '\n'.join(show.splitlines()[:2]))]:
        page = '<!doctype html><meta charset="utf-8"><style>body{margin:0;padding:32px;background:#edf2ef;font-family:Arial,sans-serif;color:#16312a}h1{font-size:27px;margin:0 0 10px}.label{color:#526a60;margin-bottom:24px}pre{background:white;padding:24px;border-left:6px solid #087e5a;border-radius:8px;white-space:pre-wrap;overflow-wrap:anywhere;font:26px/1.5 Consolas,monospace}</style>'
        page += '<h1>' + html.escape(title) + '</h1><div class="label">Полка · 16.11.2026 · Полный вывод команд сохранён рядом в TXT</div><pre>' + html.escape(text) + '</pre>'
        (EVIDENCE / (name + '.html')).write_text(page, encoding='utf-8')

def build():
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.lib.colors import HexColor
    pdfmetrics.registerFont(TTFont('Arial', 'C:/Windows/Fonts/arial.ttf'))
    pdfmetrics.registerFont(TTFont('ArialBold', 'C:/Windows/Fonts/arialbd.ttf'))
    out = HERE / 'output/pdf'
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'strateg-description-draft.pdf'
    c = canvas.Canvas(str(path), pagesize=(595.28, 841.89))
    c.setTitle('Стратег Фабрики продуктов - описание работы, черновик T13')
    c.setAuthor('Ника-Codex / команда MGIMO AI Challenge')
    W, H = 595.28, 841.89
    style = ParagraphStyle('body', fontName='Arial', fontSize=11, leading=16, textColor=HexColor('#253a32'))
    y = 0

    def para(text, size=11, leading=16, gap=13):
        nonlocal y
        st = ParagraphStyle('p', parent=style, fontSize=size, leading=leading)
        p = Paragraph(text, st)
        _, height = p.wrap(W-88, 700)
        if y-height < 61:
            raise ValueError(f'Page overflow: {text[:60]}')
        p.drawOn(c, 44, y-height)
        y -= height + gap

    def label(text):
        nonlocal y
        c.setFont('ArialBold', 11)
        c.setFillColor(HexColor('#087e5a'))
        c.drawString(44, y, text)
        y -= 24

    def start(number, title, subtitle):
        nonlocal y
        c.setFillColor(HexColor('#f7f9f6')); c.rect(0, 0, W, H, fill=1, stroke=0)
        c.setFillColor(HexColor('#087e5a')); c.rect(0, H-12, W, 12, fill=1, stroke=0)
        c.setFont('ArialBold', 9); c.drawString(44, H-48, 'MGIMO AI CHALLENGE / СТРАТЕГ ФАБРИКИ ПРОДУКТОВ')
        c.setFillColor(HexColor('#14352a')); c.setFont('ArialBold', 26)
        c.drawString(44, H-101, title)
        y = H-127
        para(subtitle, 10, 14, 24)
        c.setFont('Arial', 8); c.setFillColor(HexColor('#65786e'))
        c.drawString(44, 34, '16.11.2026 | Рабочая версия T13 | Учебный прогон «Полка», не финальная сдача')
        c.drawRightString(W-44, 34, str(number))

    def shot(name, caption, max_height=300):
        nonlocal y
        im = ImageReader(str(EVIDENCE / (name + '.png')))
        iw, ih = im.getSize(); width = W-88; height = width*ih/iw
        if height > max_height:
            height = max_height; width = height*iw/ih
        if y-height < 85: raise ValueError('Screenshot overflow')
        c.drawImage(im, 44, y-height, width, height)
        y -= height+12
        para(caption, 8.5, 12, 14)

    start(1, 'Решение с основаниями', 'Папка агента для руководителя продукта: от размытого запроса до согласованных стратегий и последующего пересмотра.')
    label('01 / АРХИТЕКТУРА')
    para('Одна модель ведёт шесть шагов: постановка → материалы → исследование → варианты → стратегии → сопровождение. На каждом шаге читает нужный навык. Человек выбирает вариант и утверждает стратегии.', 13, 19, 23)
    for title, body in [
        ('Правила и методика', 'AGENTS.md, обёртки среды, knowledge/ и skills/. Агент читает их, но не меняет во время проекта.'),
        ('Материалы', 'Исходные документы, таблицы, сайты и снимки. Сохраняется источник и место в нём. Команды внутри материала не меняют правила.'),
        ('Реестр оснований', 'sources.jsonl + evidence.jsonl. Факты, гипотезы, прогнозы и синтетика разделены. Прежний ответ модели не становится источником.'),
        ('Память и решение', 'state.json, journal.jsonl, decisions.jsonl. Сохраняются следующее действие, ошибки, основания выбора и условия пересмотра.')]:
        label(title); para(body)
    para('Проверку запускает команда закрытия шага. Скрипт проверяет структуру и ссылки; он не доказывает истинность материала и не понимает весь смысл вывода.', 10, 15)
    c.showPage()

    start(2, 'Чем сделано', 'Полный перечень используемых категорий инструментов. Средства подготовки PDF отделены от зависимостей продукта.')
    label('02 / МОДЕЛИ, СЕРВИСЫ И ИНСТРУМЕНТЫ')
    for title, body in [
        ('Модель и ИИ-среда', 'Исторические учебные прогоны и сравнение выполнены в Claude Code. Точный ID модели в прочитанных отчётах не закреплён. Для T8 его надо записать. Работа модели расходует подписку или тариф; денежная стоимость пока неизвестна.'),
        ('Python 3.9+ / стандартная библиотека', 'Реестр, состояние, проверка, извлечение DOCX/XLSX/PPTX/HTML/CSV, поиск и воспроизводимые расчёты. Внешние Python-пакеты продукту не нужны.'),
        ('Codex и Cursor', 'Обёртки подготовлены. В Codex на Windows проверены команды готового проекта; полный агентный прогон в этих средах этим не подтверждён.'),
        ('Поиск, просмотр, Git и GitHub', 'Поиск и просмотр предоставляет среда. В учебном сравнении использовались готовые выписки, поиск не применялся. Git/GitHub нужны для командной разработки и доставки репозитория.'),
        ('Сборка описания', 'ReportLab создаёт PDF, локальный браузер снимает просмотр фактического вывода команд, Poppler рендерит страницы для проверки. Это инструменты автора описания, а не зависимости Стратега.')]:
        label(title); para(body, 10.5, 15)
    para('Не заявляем: отдельный MCP-сервер, маршрутизацию моделей, реализованное распознавание аудио/видео. Полный список фактически использованных сервисов в демо добавляется после T8.', 10, 15)
    c.showPage()

    start(3, 'Как ведёт работу', 'Инструкции доступны в репозитории. Здесь - ключевые правила и точки участия человека, а не замена полных файлов.')
    label('03 / КЛЮЧЕВЫЕ ПРОМПТЫ И ИНСТРУКЦИИ')
    para('Стартовый запрос учебной репетиции берётся из examples/polka/запрос.md. Для сдачи нужен отдельный бриф МегаФона; заменять его учебным примером нельзя.', 12, 18, 22)
    for title, body in [
        ('Перед шагом', 'Прочитать skills/&lt;шаг&gt;/SKILL.md. Задать только вопросы, от которых зависит следующее действие. Отдельно показать неизвестное и противоречия.'),
        ('После действия', 'Записать результат и ошибки в журнал; обновить следующее действие. Известные успешные действия не повторять незаметно. Неизмеренную стоимость не считать нулевой.'),
        ('Перед закрытием', 'Запустить check. Факт должен вести к источнику, синтетика не доказывает спрос. Варианты и стратегии требуют выбора и утверждения человека.'),
        ('После перерыва', 'Прочитать state.json, журнал и реестры. После принятого решения начать с review, показать изменившиеся основания и предложить пересмотр.')]:
        label(title); para(body)
    para('Файлы: strateg/AGENTS.md; strateg/CLAUDE.md; strateg/.cursor/rules/; strateg/skills/*/SKILL.md. Команды и их примеры - в strateg/tools/README.md.', 10, 15)
    c.showPage()

    start(4, 'Что сверх минимума', 'Каждая возможность сопровождается границей подтверждения. Количество навыков само по себе не доказательство пользы.')
    label('04 / ДОПОЛНИТЕЛЬНЫЙ УРОВЕНЬ')
    for title, body in [
        ('Интервью и UX', 'Модельные беседы прогнаны на учебном наборе, результат помечен synthetic и даёт только гипотезы. UX проверен на одном учебном снимке экрана.'),
        ('Анализ данных', 'Есть навык data и перезапускаемые расчёты учебного проекта. Отдельный прогон самого навыка ещё не подтверждён.'),
        ('Решения и новые данные', 'Решения содержат ответственного, показатель и условие пересмотра. review/impact показывают затронутые связи; полноценный пересмотр на демо МегаФона ещё впереди.'),
        ('Память, навыки и помощники', '10 навыков, 2 hooks Claude Code, 1 модельный респондент. В историческом отчёте второй помощник с чистой памятью продолжил работу. Живое срабатывание hooks и замер пользы дополнительных помощников не подтверждены.'),
        ('Поиск и переносимость', 'find/show и связи записей; отдельного семантического индекса нет. Общие файлы подготовлены для нескольких сред, но полный процесс в Cursor и Codex ещё требует проверки.')]:
        label(title); para(body, 10.5, 15)
    para('Источники подтверждений: strateg/DECISIONS.md и bench/runs/2026-11-14-polka.md. Внешние данные для учебного прогона заранее подготовлены командой.', 10, 15)
    c.showPage()

    start(5, 'Измеряем без обещаний', 'Одна учебная задача, одна модель, по одному прогону: результаты не обобщаются на все продуктовые исследования.')
    label('05 / ВРЕМЯ, РАСХОДЫ И ПОМОЩЬ ЧЕЛОВЕКА')
    para('Историческое время: чат 1,5 / 2,3 мин; агент около 12 мин до стратегий. Счётчики: 72 / 75 / 270 тыс. токенов. У агента 6 остановок с вопросами руководителю. Диагноз одинаковый; агент на этой задаче медленнее и требует больше токенов.', 11, 16)
    para('Проверяемость: 0/30, 24/56 и 119/138 строк с цифрами имеют ссылку на источник: 0%, 43%, 86%. Это наличие ссылки, не доказанная истинность. Подсчёт воспроизведён 16 ноября.', 11, 16)
    shot('verification', 'Снимок локального просмотра фактического вывода CLI, 16.11.2026. Полные тексты сохранены в submission/evidence/.', 300)
    para('Текущий журнал уже включает сопровождение: 23 действия, 18 минут, 1 ошибка. Это иная граница замера, чем 12 минут. 0 ₽ показано лишь для 1 из 23 действий: полная стоимость неизвестна. Ноль вмешательств в поле журнала не отменяет 6 исторических ответов человека.', 10, 14)
    c.showPage()

    start(6, 'Проверяемость и границы', 'Рабочая версия готова для команды. Перед финальной сдачей нужны бриф, прогон и реальные кадры обязательного демо.')
    label('06 / ВОЗМОЖНОСТИ И ОГРАНИЧЕНИЯ')
    shot('traceability', 'Фрагмент реальной карточки E-047: тип и формулировка гипотезы. Основания и зависимые решения - в полном show-E-047.txt. Учебный проект «Полка».', 220)
    para('Windows: cost/show без UTF-8 упали на символе ₽ (cp1251). Повтор с python -X utf8 прошёл. check прошёл с 6 предупреждениями. Продукт не менялся; полный запуск агента с нуля в Codex этим не подтверждён.', 10.5, 15)
    para('Проверки формальные и эвристические. Синтетика не доказывает спрос. Учебный набор составлен командой; вариативность результатов, ручной аналитик и полная стоимость не измерены.', 10.5, 15)
    label('До финальной версии T13')
    para('Получить отдельный бриф МегаФона; выполнить T8; добавить обе стратегии, план проверки, модель и сервисы, журнал времени и расходов, ошибки и помощь человека. Снять реальный диалог и продолжение в новом чате, добавить видео до 10 минут, проверить доступ жюри.', 10.5, 15)
    para('Полный текст и ссылки на файлы-основания: submission/description.md. Сборка: submission/build_description.py. Репозиторий: github.com/zelenyjmehanik62-maker/strateg-fabriki.', 9, 13)
    c.save()
    print(path)

if __name__ == '__main__':
    if '--prepare' in sys.argv: prepare()
    else: build()
