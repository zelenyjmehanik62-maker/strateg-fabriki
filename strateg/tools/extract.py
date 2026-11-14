"""Перевод материалов в текст с метками места. Только стандартная библиотека.

Метки нужны, чтобы в реестре можно было указать, где именно в материале
находится сведение: «абз. 12», «Лист «Отток», строка 7», «слайд 3».
"""
import csv
import io
import re
import shutil
import subprocess
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

TEXT_SUFFIXES = {".txt", ".md", ".json", ".jsonl", ".log", ".yaml", ".yml"}
SUPPORTED = sorted(TEXT_SUFFIXES | {".docx", ".xlsx", ".pptx", ".html", ".htm", ".csv", ".tsv", ".pdf"})


class ExtractError(Exception):
    pass


def _paragraph_text(p):
    parts = []
    for node in p.iter():
        if node.tag == W + "t":
            parts.append(node.text or "")
        elif node.tag == W + "tab":
            parts.append("\t")
        elif node.tag in (W + "br", W + "cr"):
            parts.append("\n")
    return "".join(parts).strip()


def docx_to_text(path):
    with zipfile.ZipFile(path) as z:
        body = ET.fromstring(z.read("word/document.xml")).find(W + "body")
    lines, n, t = [], 0, 0
    for child in body:
        if child.tag == W + "p":
            text = _paragraph_text(child)
            if text:
                n += 1
                lines.append(f"[абз. {n}] {text}")
        elif child.tag == W + "tbl":
            t += 1
            lines.append(f"[таблица {t}]")
            for r, row in enumerate(child.iter(W + "tr"), 1):
                cells = [" ".join(filter(None, (_paragraph_text(p) for p in cell.iter(W + "p"))))
                         for cell in row.iter(W + "tc")]
                lines.append(f"[таблица {t}, строка {r}] " + " | ".join(cells))
    return "\n".join(lines) + "\n"


def pptx_to_text(path):
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                       key=lambda n: int(re.search(r"\d+", n.rsplit("/", 1)[1]).group()))
        lines = []
        for i, name in enumerate(names, 1):
            root = ET.fromstring(z.read(name))
            texts = []
            for para in root.iter(A + "p"):
                text = "".join(t.text or "" for t in para.iter(A + "t")).strip()
                if text:
                    texts.append(text)
            lines.append(f"[слайд {i}]")
            lines.extend(texts or ["(без текста)"])
    return "\n".join(lines) + "\n"


def _col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group()
    idx = 0
    for ch in letters:
        idx = idx * 26 + ord(ch) - 64
    return idx - 1


def xlsx_to_sheets(path):
    """Возвращает список (имя листа, строки), где строки — списки значений ячеек."""
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(S + "si"):
                shared.append("".join(t.text or "" for t in si.iter(S + "t")))
        rels = {r.get("Id"): r.get("Target") for r in
                ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(PKG_REL + "Relationship")}
        sheets = []
        for sheet in ET.fromstring(z.read("xl/workbook.xml")).iter(S + "sheet"):
            target = rels[sheet.get(R + "id")].lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
            rows = []
            for row in ET.fromstring(z.read(target)).iter(S + "row"):
                number = int(row.get("r") or len(rows) + 1)
                while len(rows) < number - 1:
                    rows.append([])
                values = []
                for c in row.iter(S + "c"):
                    col = _col_index(c.get("r")) if c.get("r") else len(values)
                    while len(values) < col:
                        values.append("")
                    kind, v = c.get("t"), c.find(S + "v")
                    if kind == "s" and v is not None:
                        value = shared[int(v.text)]
                    elif kind == "inlineStr":
                        value = "".join(t.text or "" for t in c.iter(S + "t"))
                    elif kind == "b" and v is not None:
                        value = "ИСТИНА" if v.text == "1" else "ЛОЖЬ"
                    else:
                        value = v.text if v is not None and v.text is not None else ""
                    values.append(value)
                rows.append(values)
            sheets.append((sheet.get("name"), rows))
    return sheets


def rows_to_csv(rows):
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()


class _HTMLText(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
             "header", "footer", "table", "ul", "ol", "blockquote", "title"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def html_to_text(raw):
    parser = _HTMLText()
    parser.feed(raw)
    lines = [re.sub(r"[ \t\xa0]+", " ", l).strip(" |") for l in "".join(parser.parts).splitlines()]
    return "\n".join(l for l in lines if l) + "\n"


def read_text(path):
    data = Path(path).read_bytes()
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def pdf_to_text(path):
    tool = shutil.which("pdftotext")
    if not tool:
        raise ExtractError(
            "PDF: на компьютере нет программы pdftotext. Либо откройте PDF средствами вашей среды "
            "(Claude Code и Cursor читают PDF сами), либо установите poppler и повторите.")
    result = subprocess.run([tool, "-layout", str(path), "-"], capture_output=True, timeout=120)
    if result.returncode != 0:
        raise ExtractError("PDF не прочитан: " + result.stderr.decode("utf-8", "replace").strip())
    pages = result.stdout.decode("utf-8", "replace").split("\f")
    return "".join(f"[стр. {i}]\n{page.strip()}\n" for i, page in enumerate(pages, 1) if page.strip())


def extract(path):
    """Возвращает список (суффикс имени, текст, пояснение). Для Excel — по одному CSV на лист."""
    path = Path(path)
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            return [(".txt", docx_to_text(path), "метки места: [абз. N], [таблица N, строка M]")]
        if suffix == ".pptx":
            return [(".txt", pptx_to_text(path), "метки места: [слайд N]")]
        if suffix == ".xlsx":
            out = []
            for i, (name, rows) in enumerate(xlsx_to_sheets(path), 1):
                out.append((f".лист{i}.csv", rows_to_csv(rows),
                            f"лист «{name}», строк {len(rows)}; номер строки файла = номер строки листа. "
                            "Даты в Excel могут быть записаны числом — сверяйте с исходником"))
            return out
        if suffix in (".html", ".htm"):
            return [(".txt", html_to_text(read_text(path)), "текст страницы без разметки")]
        if suffix == ".tsv":
            rows = list(csv.reader(io.StringIO(read_text(path)), delimiter="\t"))
            return [(".csv", rows_to_csv(rows), f"строк {len(rows)}")]
        if suffix == ".csv":
            text = read_text(path)
            first = text.splitlines()[0] if text.strip() else ""
            delimiter = ";" if first.count(";") > first.count(",") else ","
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
            return [(".csv", rows_to_csv(rows), f"строк {len(rows)}, разделитель приведён к запятой, кодировка — к UTF-8")]
        if suffix == ".pdf":
            return [(".txt", pdf_to_text(path), "метки места: [стр. N]")]
        if suffix in TEXT_SUFFIXES:
            return [(".txt", read_text(path), "текстовый файл, кодировка приведена к UTF-8")]
    except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        raise ExtractError(f"Файл {path.name} повреждён или это не {suffix}: {exc}")
    raise ExtractError(f"Формат {suffix or '(без расширения)'} не поддерживается. Умею: {', '.join(SUPPORTED)}. "
                       "Изображения, аудио и видео разбирайте средствами среды.")
