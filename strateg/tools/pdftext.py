"""Текст из PDF без внешних программ — только стандартная библиотека Python.

Поддерживается то, из чего состоит большинство PDF, сохранённых из Word, браузера,
LibreOffice и генераторов отчётов: сжатие Flate, потоки объектов, дерево страниц
с наследованием ресурсов, шрифты с таблицей ToUnicode (так кодируется кириллица)
и простые шрифты с однобайтовой кодировкой.

Не поддерживается: сканы (текста нет — только картинка), зашифрованные файлы,
текст внутри вложенных форм (XObject), сжатие кроме Flate. В таких случаях
результат пустой или неполный — и вызывающий об этом предупреждает.
"""
import base64
import re
import zlib

OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj", re.S)
REF_RE = re.compile(rb"(\d+)\s+(\d+)\s+R")


class PdfError(Exception):
    pass


# ---------- объекты ----------

def _stream(body):
    m = re.search(rb"stream\r?\n", body)
    if not m:
        return None, body
    dic = body[:m.start()]
    data = body[m.end():]
    end = data.rfind(b"endstream")
    if end >= 0:
        data = data[:end]
    data = data.rstrip(b"\r\n")
    filt = re.search(rb"/Filter\s*(\[[^\]]*\]|/\w+)", dic)
    if filt:
        names = re.findall(rb"/(\w+)", filt.group(1))
        for name in names:
            if name in (b"ASCII85Decode", b"A85"):
                body85 = re.sub(rb"\s", b"", data)
                if body85.startswith(b"<~"):
                    body85 = body85[2:]
                body85 = body85.split(b"~>")[0]
                try:
                    data = base64.a85decode(body85)
                except ValueError:
                    return b"", dic
            elif name in (b"FlateDecode", b"Fl"):
                try:
                    data = zlib.decompress(data)
                except zlib.error:
                    d = zlib.decompressobj()
                    try:
                        data = d.decompress(data)
                    except zlib.error:
                        return b"", dic
            else:
                return b"", dic  # неизвестное сжатие — пропускаем поток
    return data, dic


def load_objects(raw):
    objs = {}
    for m in OBJ_RE.finditer(raw):
        objs[int(m.group(1))] = m.group(3)
    # Потоки объектов (PDF 1.5+): внутри сжатого потока лежат другие объекты
    for num, body in list(objs.items()):
        if b"/ObjStm" not in body[:400]:
            continue
        data, dic = _stream(body)
        if not data:
            continue
        n = re.search(rb"/N\s+(\d+)", dic)
        first = re.search(rb"/First\s+(\d+)", dic)
        if not n or not first:
            continue
        head = data[:int(first.group(1))].split()
        pairs = [(int(head[i]), int(head[i + 1])) for i in range(0, min(len(head), 2 * int(n.group(1))) - 1, 2)]
        base = int(first.group(1))
        for i, (onum, off) in enumerate(pairs):
            end = base + pairs[i + 1][1] if i + 1 < len(pairs) else len(data)
            objs.setdefault(onum, data[base + off:end])
    return objs


def deref(objs, value):
    m = REF_RE.fullmatch(value.strip()) if value else None
    return objs.get(int(m.group(1)), b"") if m else value


def dict_entry(body, key):
    """Значение ключа в словаре: ссылка, словарь <<…>>, массив […] или имя/число."""
    m = re.search(rb"/" + key + rb"\b\s*", body)
    if not m:
        return None
    rest = body[m.end():]
    r = REF_RE.match(rest)
    if r:
        return r.group(0)
    if rest.startswith(b"<<"):
        depth, i = 0, 0
        while i < len(rest) - 1:
            if rest[i:i + 2] == b"<<":
                depth += 1
                i += 2
                continue
            if rest[i:i + 2] == b">>":
                depth -= 1
                i += 2
                if depth == 0:
                    return rest[:i]
                continue
            i += 1
        return rest
    if rest.startswith(b"["):
        end = rest.find(b"]")
        return rest[:end + 1]
    v = re.match(rb"/?[^\s/<>\[\]()]+", rest)
    return v.group(0) if v else None


# ---------- шрифты ----------

def parse_cmap(data):
    mapping, width = {}, 1
    cs = re.search(rb"begincodespacerange\s*<([0-9A-Fa-f]+)>", data)
    if cs:
        width = len(cs.group(1)) // 2
    for block in re.findall(rb"beginbfchar(.*?)endbfchar", data, re.S):
        for src, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]*)>", block):
            mapping[int(src, 16)] = _utf16(dst)
    for block in re.findall(rb"beginbfrange(.*?)endbfrange", data, re.S):
        for lo, hi, dst in re.findall(rb"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<[0-9A-Fa-f]*>|\[[^\]]*\])", block):
            lo, hi = int(lo, 16), int(hi, 16)
            if dst.startswith(b"["):
                for i, d in enumerate(re.findall(rb"<([0-9A-Fa-f]*)>", dst)):
                    mapping[lo + i] = _utf16(d)
            else:
                start = dst[1:-1]
                base = int(start, 16) if start else 0
                for code in range(lo, min(hi, lo + 65535) + 1):
                    mapping[code] = _utf16(b"%0*X" % (len(start), base + code - lo))
    return mapping, width


def _utf16(hexbytes):
    try:
        return bytes.fromhex(hexbytes.decode()).decode("utf-16-be")
    except (ValueError, UnicodeDecodeError):
        return ""


class Font:
    def __init__(self, objs, body):
        self.map, self.width = {}, 1
        enc = dict_entry(body, b"Encoding") or b""
        enc = deref(objs, enc) if REF_RE.fullmatch(enc.strip() or b"-") else enc
        self.codec = "mac_roman" if b"MacRoman" in enc else "cp1252"
        if b"/Type0" in body:
            self.width = 2
        tu = dict_entry(body, b"ToUnicode")
        if tu:
            data, _ = _stream(deref(objs, tu))
            if data:
                self.map, self.width = parse_cmap(data)

    def decode(self, raw):
        if self.map:
            out, w = [], self.width
            for i in range(0, len(raw) - w + 1, w):
                out.append(self.map.get(int.from_bytes(raw[i:i + w], "big"), ""))
            return "".join(out)
        if self.width == 2:
            return ""  # двухбайтовый шрифт без таблицы — расшифровать нельзя
        return raw.decode(self.codec, errors="replace")


# ---------- содержимое страницы ----------

TOKEN_RE = re.compile(rb"\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>|\[|\]|/[^\s/<>\[\]()]+|[-+]?\d*\.?\d+|[A-Za-z'\"*]+|\(", re.S)


def _literal(tok):
    s = tok[1:-1]
    out, i = bytearray(), 0
    esc = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f"}
    while i < len(s):
        c = s[i:i + 1]
        if c == b"\\" and i + 1 < len(s):
            n = s[i + 1:i + 2]
            if n in esc:
                out += esc[n]
                i += 2
            elif n.isdigit():
                m = re.match(rb"[0-7]{1,3}", s[i + 1:])
                out.append(int(m.group(0), 8) & 0xFF)
                i += 1 + len(m.group(0))
            else:
                out += n
                i += 2
        else:
            out += c
            i += 1
    return bytes(out)


def _string(tok):
    if tok.startswith(b"("):
        return _literal(tok)
    h = re.sub(rb"\s", b"", tok[1:-1])
    if len(h) % 2:
        h += b"0"
    return bytes.fromhex(h.decode())


def page_text(content, fonts):
    """Сначала без догадок о пробелах: многие PDF (Chrome, Word) хранят пробелы символами,
    а слова режут на куски сдвигами. Если своих пробелов на странице почти нет (так пишет,
    например, LaTeX), повторяем и вставляем пробел по сдвигам."""
    text = _page_text(content, fonts, synth=False)
    letters = sum(1 for ch in text if not ch.isspace())
    if letters > 40 and text.count(" ") < 0.03 * letters:
        text = _page_text(content, fonts, synth=True)
    return text


def _page_text(content, fonts, synth):
    out, font, stack = [], None, []
    last_y = None

    def newline():
        if out and not out[-1].endswith("\n"):
            out.append("\n")

    for m in TOKEN_RE.finditer(content):
        tok = m.group(0)
        if tok == b"[" or tok.startswith((b"(", b"<")) or tok.startswith(b"/") or re.fullmatch(rb"[-+]?\d*\.?\d+", tok):
            stack.append(tok)
            continue
        op = tok
        if op == b"]":
            arr, depth = [], 0
            while stack and stack[-1] != b"[":
                arr.insert(0, stack.pop())
            if stack:
                stack.pop()
            stack.append(("ARR", arr))
            continue
        if op == b"Tf" and len(stack) >= 2:
            font = fonts.get(stack[-2][1:] if isinstance(stack[-2], bytes) else None)
        elif op in (b"Tj", b"'", b'"') and stack:
            if op != b"Tj":
                newline()
            s = stack[-1]
            if isinstance(s, bytes) and s[:1] in (b"(", b"<") and font:
                out.append(font.decode(_string(s)))
        elif op == b"TJ" and stack and isinstance(stack[-1], tuple):
            for item in stack[-1][1]:
                if item[:1] in (b"(", b"<") and font:
                    out.append(font.decode(_string(item)))
                else:
                    try:
                        if synth and float(item) < -200 and out and not out[-1].endswith((" ", "\n")):
                            out.append(" ")
                    except ValueError:
                        pass
        elif op in (b"Td", b"TD") and len(stack) >= 2:
            try:
                tx, ty = float(stack[-2]), float(stack[-1])
            except (ValueError, TypeError):
                tx, ty = 0, 0
            if abs(ty) > 0.5:
                newline()
            elif synth and tx > 0.5 and out and not out[-1].endswith((" ", "\n")):
                out.append(" ")
        elif op == b"Tm" and len(stack) >= 6:
            try:
                y = float(stack[-1])
            except (ValueError, TypeError):
                y = None
            if last_y is not None and y is not None and abs(y - last_y) > 0.5:
                newline()
            elif out and not out[-1].endswith((" ", "\n")):
                out.append(" ")  # новая текстовая матрица на той же строке — обычно новый столбец или ячейка
            last_y = y
        elif op == b"T*":
            newline()
        elif op == b"ET":
            pass
        stack = [] if op not in (b"BT",) else stack
    text = "".join(out)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------- страницы ----------

def _fonts(objs, resources, cache):
    fonts = {}
    res = deref(objs, resources) if resources else b""
    fdict = dict_entry(res, b"Font") if res else None
    fdict = deref(objs, fdict) if fdict else b""
    for name, ref in re.findall(rb"/([^\s/<>\[\]()]+)\s+(\d+\s+\d+\s+R)", fdict or b""):
        if ref not in cache:
            cache[ref] = Font(objs, deref(objs, ref))
        fonts[name] = cache[ref]
    return fonts


def pages(raw):
    if b"/Encrypt" in raw[-4096:] or re.search(rb"/Encrypt\s+\d+\s+\d+\s+R", raw):
        raise PdfError("PDF зашифрован — откройте его в программе просмотра и сохраните без защиты")
    objs = load_objects(raw)
    roots = REF_RE.findall(b"".join(re.findall(rb"/Root\s+\d+\s+\d+\s+R", raw)))
    if not roots:
        raise PdfError("не найден каталог документа")
    catalog = objs.get(int(roots[-1][0]), b"")
    pages_ref = dict_entry(catalog, b"Pages")
    result, cache = [], {}

    def walk(node, inherited, depth=0):
        if depth > 50:
            return
        res = dict_entry(node, b"Resources") or inherited
        if re.search(rb"/Type\s*/Pages\b", node):
            kids = dict_entry(node, b"Kids") or b""
            for ref in REF_RE.findall(kids):
                walk(objs.get(int(ref[0]), b""), res, depth + 1)
            return
        contents = dict_entry(node, b"Contents")
        data = b""
        refs = REF_RE.findall(contents) if contents else []
        for ref in refs:
            body = objs.get(int(ref[0]), b"")
            if body.lstrip().startswith(b"["):  # массив ссылок в отдельном объекте
                for r2 in REF_RE.findall(body):
                    data += (_stream(objs.get(int(r2[0]), b""))[0] or b"") + b"\n"
            else:
                data += (_stream(body)[0] or b"") + b"\n"
        result.append(page_text(data, _fonts(objs, res, cache)))

    walk(deref(objs, pages_ref) if pages_ref else b"", None)
    return result


def pdf_text(path):
    raw = open(path, "rb").read()
    if not raw.startswith(b"%PDF"):
        raise PdfError("это не PDF")
    return pages(raw)
