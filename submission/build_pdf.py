#!/usr/bin/env python3
"""Сборка описания работы в PDF: description.md → HTML → PDF через Chrome.

Без дополнительных пакетов: нужен только установленный Google Chrome или Chromium.
Запуск из корня репозитория:

    python3 submission/build_pdf.py              # собрать PDF из description.md
    python3 submission/build_pdf.py --evidence   # сначала заново снять снимки вывода команд

Снимки — это настоящий вывод команд агента: текст сохраняется рядом (*.txt), картинка
делается из этого текста, чтобы её можно было проверить.
"""
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / "submission"
EVID = HERE / "evidence"
OUT = HERE / "output" / "pdf" / "strateg-description.pdf"
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "chromium", "chromium-browser", "chrome",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]

CSS = """
@page { size: A4; margin: 16mm 15mm 16mm 15mm; }
body { font-family: Arial, Helvetica, sans-serif; color: #1f2d27; font-size: 10.2pt; line-height: 1.42; }
h1 { font-size: 22pt; color: #14352a; margin: 0 0 4pt; }
h2 { font-size: 14pt; color: #087e5a; border-bottom: 1.5px solid #cfe3da; padding-bottom: 3pt; margin: 16pt 0 6pt;
     page-break-after: avoid; }
h2.section { page-break-before: always; }
h3 { font-size: 11pt; color: #14352a; margin: 10pt 0 4pt; page-break-after: avoid; }
p { margin: 4pt 0 6pt; }
table { border-collapse: collapse; width: 100%; margin: 5pt 0 9pt; font-size: 8.9pt; page-break-inside: avoid; }
tr { page-break-inside: avoid; }
th { background: #e8f3ee; color: #14352a; text-align: left; }
th, td { border: 1px solid #c9d8d1; padding: 3.5pt 5pt; vertical-align: top; }
blockquote { margin: 6pt 0; padding: 5pt 9pt; border-left: 3px solid #087e5a; background: #f4f8f6; }
code { font-family: Menlo, Consolas, monospace; font-size: 8.6pt; background: #eef2f0; padding: 0 2pt; border-radius: 2px; }
pre { font-family: Menlo, Consolas, monospace; font-size: 8.4pt; background: #f4f6f5; padding: 7pt 9pt;
      border: 1px solid #dbe3df; white-space: pre-wrap; page-break-inside: avoid; }
img { max-width: 100%; max-height: 62mm; width: auto; display: block; margin: 6pt auto 2pt; border: 1px solid #dbe3df; page-break-inside: avoid; }
img[src$=".svg"] { max-height: 80mm; border: none; }
.caption { font-size: 8.4pt; color: #5b6e66; text-align: center; margin: 0 0 9pt; }
.figure { page-break-inside: avoid; }
ul { margin: 3pt 0 6pt 16pt; padding: 0; }
li { margin: 1.5pt 0; }
"""


def find_chrome():
    for c in CHROME_CANDIDATES:
        path = c if os.path.isabs(c) else shutil.which(c)
        if path and os.path.exists(path):
            return path
    raise SystemExit("Не найден Google Chrome или Chromium — он нужен для сборки PDF.")


def inline(text):
    text = html.escape(text, quote=False)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    return text


def md_to_html(md):
    lines, out, i = md.splitlines(), [], 0
    section = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre>" + html.escape("\n".join(lines[i + 1:j])) + "</pre>")
            i = j + 1
            continue
        m = re.match(r"(#{1,3}) (.*)", line)
        if m:
            level = len(m.group(1))
            cls = ""
            if level == 2 and (re.match(r"\d\.", m.group(2)) or m.group(2) == "Кадры живого демо"):
                section += 1
                cls = ' class="section"'
            out.append(f"<h{level}{cls}>{inline(m.group(2))}</h{level}>")
            i += 1
            continue
        m = re.match(r"!\[(.*?)\]\((.*?)\)", line)
        if m:
            out.append(f'<div class="figure"><img src="{(HERE / m.group(2)).as_uri()}" alt="{html.escape(m.group(1))}">'
                       f'<div class="caption">{inline(m.group(1))}</div></div>')
            i += 1
            continue
        if line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], [r for r in rows[1:] if not all(re.fullmatch(r":?-+:?", c) for c in r)]
            out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in head) + "</tr>"
                       + "".join("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body)
                       + "</table>")
            continue
        if line.startswith(">"):
            block = []
            while i < len(lines) and lines[i].startswith(">"):
                block.append(lines[i][1:].strip())
                i += 1
            out.append("<blockquote>" + inline(" ".join(block)) + "</blockquote>")
            continue
        if re.match(r"\s*- ", line):
            items = []
            while i < len(lines) and re.match(r"\s*- ", lines[i]):
                items.append(re.sub(r"^\s*- ", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(x)}</li>" for x in items) + "</ul>")
            continue
        if line.strip():
            para = [line]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r"(#|\||>|!\[|```|\s*- )", lines[i]):
                para.append(lines[i])
                i += 1
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            continue
        i += 1
    return "\n".join(out)


def chrome(args):
    subprocess.run([find_chrome(), "--headless=new", "--disable-gpu", "--hide-scrollbars", *args],
                   check=True, capture_output=True, timeout=180)


def terminal_png(name, title, text):
    (EVID / f"{name}.txt").write_text(text, encoding="utf-8")
    lines = text.splitlines()
    height = 70 + 19 * sum(1 + len(l) // 118 for l in lines)
    page = (f'<!doctype html><meta charset="utf-8"><style>body{{margin:0;background:#1f2b26;font:13px/19px Menlo,Consolas,monospace;'
            f'color:#e8efe9}}.t{{background:#2c3b35;color:#b9cfc4;padding:8px 14px;font:12px Arial}}pre{{margin:0;padding:12px 14px;'
            f'white-space:pre-wrap;word-break:break-word}}</style><div class="t">{html.escape(title)}</div><pre>{html.escape(text)}</pre>')
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "t.html"
        src.write_text(page, encoding="utf-8")
        chrome([f"--window-size=980,{height}", f"--screenshot={EVID / (name + '.png')}", src.as_uri()])


def run(*args, env=None):
    r = subprocess.run([sys.executable, "tools/strateg.py", *args], cwd=ROOT / "strateg", capture_output=True,
                       text=True, encoding="utf-8", env=env)
    return (r.stdout + r.stderr).rstrip()


def evidence():
    EVID.mkdir(exist_ok=True)
    terminal_png("show", "python3 tools/strateg.py show semya E-028", "$ python3 tools/strateg.py show semya E-028\n" + run("show", "semya", "E-028"))
    # Опыт Ники: источник прямо говорит «данных нет», а факт утверждает число — во временной папке
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, STRATEG_PROJECTS=tmp)
        steps = [("new", "probe"), None]
        log = [run("new", "probe", env=env)]
        (Path(tmp) / "probe" / "materials" / "source.md").write_text(
            "Учебный источник. Размер рынка неизвестен. Данных о 900 млрд рублей здесь нет.\n", encoding="utf-8")
        log.append("$ source … --local materials/source.md\n" + run("source", "probe", "--kind", "doc", "--title", "Источник",
                                                                   "--ref", "materials/source.md", "--local", "materials/source.md", env=env))
        log.append('$ claim --type fact --text "Размер рынка — 900 млрд рублей" --quote "Размер рынка составляет 900 млрд рублей"\n'
                   + run("claim", "probe", "--type", "fact", "--text", "Размер рынка — 900 млрд рублей", "--source", "S-001:строка 1",
                         "--quote", "Размер рынка составляет 900 млрд рублей", env=env))
        log.append('$ claim … --quote "Данных о 900 млрд рублей здесь нет"   # настоящая цитата, обратный смысл\n'
                   + run("claim", "probe", "--type", "fact", "--text", "Размер рынка — 900 млрд рублей", "--source", "S-001:строка 1",
                         "--quote", "Данных о 900 млрд рублей здесь нет", env=env))
        log.append('$ vet probe E-001 --verdict no --by helper --note "источник говорит, что данных нет"\n'
                   + run("vet", "probe", "E-001", "--verdict", "no", "--by", "helper", "--note", "источник говорит, что данных нет", env=env))
        log.append("$ check probe\n" + run("check", "probe", env=env))
    terminal_png("check", "Выдуманная цитата не записывается; настоящая цитата с обратным смыслом ловится сверкой", "\n\n".join(log[1:]))
    usage = (HERE / "evidence" / "usage-semya.txt")
    if usage.exists():
        terminal_png("cost", "python3 tools/strateg.py usage <журнал сеанса Claude Code>", usage.read_text(encoding="utf-8"))
    print("Снимки обновлены в", EVID)


def build():
    md = (HERE / "description.md").read_text(encoding="utf-8")
    page = (f'<!doctype html><html lang="ru"><meta charset="utf-8"><title>Стратег Фабрики продуктов — описание работы</title>'
            f"<style>{CSS}</style><body>{md_to_html(md)}</body></html>")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "description.html"
        src.write_text(page, encoding="utf-8")
        chrome(["--no-pdf-header-footer", f"--print-to-pdf={OUT}", src.as_uri()])
    print("PDF:", OUT.relative_to(ROOT))


if __name__ == "__main__":
    if "--evidence" in sys.argv:
        evidence()
    build()
