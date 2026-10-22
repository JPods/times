"""
mesh_mobility.gui.report_md
===========================
Convert the printable design report to Markdown, so the HTML page stays the
one source and the Markdown copy can never say something different.

Handles what the report uses: headings, paragraphs, line breaks, bold, italic,
links, tables (first row is the header) and block divs. <head>, <style> and
<script> are dropped, and so is anything between <!--no-md--> and
<!--/no-md--> (page-only links, metric tiles).
Relative links are made absolute with `base_url`.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

_BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "table", "body"}
_SKIP = {"head", "style", "script", "title"}


class _MD(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url.rstrip("/")
        self.out: list = []          # finished blocks
        self.buf: list = []          # current inline text
        self.skip = 0
        self.href = None
        self.rows = None             # list of rows while inside <table>
        self.cell = None             # list of text parts while inside <td>/<th>

    # -- helpers ---------------------------------------------------------
    def _text(self, s: str):
        if self.skip:
            return
        (self.cell if self.cell is not None else self.buf).append(s)

    def _flush(self, prefix: str = ""):
        text = re.sub(r"[ \t\r\f\v]+", " ", "".join(self.buf))
        text = "\n".join(line.strip() for line in text.split("\n")).strip()
        self.buf = []
        if text:
            self.out.append(prefix + text)

    # -- parser hooks ----------------------------------------------------
    def handle_starttag(self, tag, attrs):
        if tag in _SKIP:
            self.skip += 1
            return
        a = dict(attrs)
        if tag in _BLOCK and self.cell is None:
            self._flush()
        if tag == "table":
            self.rows = []
        elif tag == "tr" and self.rows is not None:
            self.rows.append([])
        elif tag in ("td", "th"):
            self.cell = []
        elif tag == "br":
            self._text(" " if self.cell is not None else "\n")
        elif tag in ("strong", "b"):
            self._text("**")
        elif tag in ("em", "i"):
            self._text("*")
        elif tag == "a":
            href = a.get("href", "")
            if href.startswith("/"):
                href = self.base_url + href
            self.href = href
            self._text("[")

    def handle_endtag(self, tag):
        if tag in _SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if tag in ("strong", "b"):
            self._text("**")
        elif tag in ("em", "i"):
            self._text("*")
        elif tag == "a":
            self._text(f"]({self.href})" if self.href else "]")
            self.href = None
        elif tag in ("td", "th"):
            text = re.sub(r"\s+", " ", "".join(self.cell or [])).strip()
            if self.rows:
                self.rows[-1].append(text.replace("|", "\\|"))
            self.cell = None
        elif tag == "table":
            self._emit_table()
        elif tag in ("h1", "h2", "h3", "h4"):
            self._flush("#" * int(tag[1]) + " ")
        elif tag in _BLOCK:
            self._flush()

    def handle_data(self, data):
        self._text(data)

    def _emit_table(self):
        rows = [r for r in (self.rows or []) if any(c for c in r)]
        self.rows = None
        if not rows:
            return
        width = max(len(r) for r in rows)
        rows = [r + [""] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |",
                 "|" + "---|" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        self.out.append("\n".join(lines))


def html_to_markdown(html: str, base_url: str = "https://meshmobility.com") -> str:
    html = re.sub(r"<!--no-md-->.*?<!--/no-md-->", "", html, flags=re.S)
    p = _MD(base_url)
    p.feed(html)
    p.close()
    p._flush()
    return "\n\n".join(p.out) + "\n"
