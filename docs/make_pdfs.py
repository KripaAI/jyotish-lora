"""Render docs/*.md to PDF next to them, with no external tools (Markdown -> HTML -> PDF via PyMuPDF's Story).

    python docs/make_pdfs.py                      # every docs/*.md
    python docs/make_pdfs.py implementation-plan  # one file (name without .md)
"""
from __future__ import annotations

import sys
from pathlib import Path

import markdown
import pymupdf

DOCS = Path(__file__).resolve().parent
CSS = """
body { font-family: sans-serif; font-size: 9.5pt; line-height: 1.35; color: #222; }
h1 { font-size: 20pt; margin: 0 0 6pt 0; }
h2 { font-size: 14pt; margin: 16pt 0 4pt 0; border-bottom: 1px solid #999; }
h3 { font-size: 11.5pt; margin: 12pt 0 3pt 0; }
p { margin: 4pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0; font-size: 8.5pt; }
th, td { border: 1px solid #bbb; padding: 3pt 4pt; vertical-align: top; text-align: left; }
th { background-color: #eee; }
code { font-family: monospace; font-size: 8.5pt; }
pre { font-family: monospace; font-size: 8.5pt; background-color: #f3f3f3; padding: 4pt; }
li { margin: 2pt 0; }
hr { border: 0; border-top: 1px solid #999; margin: 10pt 0; }
"""


def render(md_path: Path) -> Path:
    html = markdown.markdown(md_path.read_text(encoding="utf-8"), extensions=["tables", "fenced_code", "sane_lists"])
    story = pymupdf.Story(html=html, user_css=CSS)
    out = md_path.with_suffix(".pdf")
    writer = pymupdf.DocumentWriter(str(out))
    mediabox = pymupdf.paper_rect("a4")
    where = mediabox + (40, 40, -40, -48)
    more = 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
    writer.close()
    return out


def main(argv: list[str]) -> None:
    names = argv or [p.stem for p in DOCS.glob("*.md")]
    for name in names:
        out = render(DOCS / f"{name}.md")
        print(f"{out.name}: {pymupdf.open(out).page_count} pages")


if __name__ == "__main__":
    main(sys.argv[1:])
