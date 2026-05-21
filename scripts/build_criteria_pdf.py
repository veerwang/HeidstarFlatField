"""把 CRITERIA.md 转成 docs/CRITERIA.pdf。

每次 CRITERIA.md 改了之后跑一次：
    python scripts/build_criteria_pdf.py

依赖（仅构建时需要，不进运行时 requirements.txt）：
    pip install markdown weasyprint

CJK 字体：依赖系统有 Noto Sans CJK SC（或 fallback 链中其他 CJK 字体）。
Ubuntu: sudo apt install fonts-noto-cjk
Windows: 系统通常自带 Microsoft YaHei，weasyprint 也能找到
"""

from __future__ import annotations

import sys
from pathlib import Path

import markdown
from weasyprint import HTML, CSS


ROOT = Path(__file__).resolve().parent.parent
SOURCE_MD = ROOT / "CRITERIA.md"
OUTPUT_PDF = ROOT / "docs" / "CRITERIA.pdf"


CSS_STYLE = """
@page {
    size: A4;
    margin: 2cm 1.8cm;
    @bottom-center {
        content: counter(page) " / " counter(pages);
        font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif;
        font-size: 9pt;
        color: #888;
    }
}

body {
    font-family: "Noto Sans CJK SC", "Noto Sans CJK", "Microsoft YaHei",
                 "PingFang SC", "WenQuanYi Zen Hei", sans-serif;
    font-size: 10pt;
    line-height: 1.55;
    color: #222;
}

h1 {
    font-size: 22pt;
    color: #1f3a5f;
    border-bottom: 2px solid #1f3a5f;
    padding-bottom: 0.3em;
    margin-top: 0.6em;
    page-break-before: always;
}
h1:first-of-type { page-break-before: avoid; }

h2 {
    font-size: 15pt;
    color: #2a5288;
    margin-top: 1.2em;
    border-bottom: 1px solid #cdd6e0;
    padding-bottom: 0.2em;
}

h3 { font-size: 12.5pt; color: #333; margin-top: 1em; }
h4 { font-size: 11pt; color: #555; margin-top: 0.8em; }

p, li { margin: 0.35em 0; }

blockquote {
    border-left: 3px solid #2a5288;
    background: #f5f8fb;
    margin: 0.6em 0;
    padding: 0.4em 0.8em;
    color: #444;
}

code {
    font-family: "DejaVu Sans Mono", "Consolas", monospace;
    background: #f0f0f0;
    padding: 0.05em 0.3em;
    border-radius: 3px;
    font-size: 9pt;
}

pre {
    background: #f5f5f5;
    border: 1px solid #ddd;
    border-radius: 4px;
    padding: 0.5em 0.7em;
    font-size: 9pt;
    page-break-inside: avoid;
    white-space: pre-wrap;
}
pre code { background: transparent; padding: 0; font-size: 9pt; }

table {
    border-collapse: collapse;
    margin: 0.5em 0;
    font-size: 9pt;
    width: 100%;
    page-break-inside: avoid;
}
th, td {
    border: 1px solid #aaa;
    padding: 0.25em 0.5em;
    text-align: left;
    vertical-align: top;
}
th { background: #dde4ea; font-weight: bold; }

hr { border: none; border-top: 1px solid #ccc; margin: 1.2em 0; }

strong { color: #1a4d8f; }
"""


def main() -> int:
    if not SOURCE_MD.is_file():
        print(f"[ERROR] {SOURCE_MD} not found", file=sys.stderr)
        return 1

    md_text = SOURCE_MD.read_text(encoding="utf-8")

    html_body = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists"],
        output_format="html5",
    )

    html_full = (
        '<!DOCTYPE html>\n'
        '<html><head><meta charset="utf-8">'
        '<title>Heidstar 判据说明</title></head>\n'
        f'<body>{html_body}</body></html>'
    )

    OUTPUT_PDF.parent.mkdir(parents=True, exist_ok=True)
    HTML(string=html_full, base_url=str(ROOT)).write_pdf(
        OUTPUT_PDF,
        stylesheets=[CSS(string=CSS_STYLE)],
    )

    size_kb = OUTPUT_PDF.stat().st_size / 1024
    print(f"[OK] Wrote {OUTPUT_PDF} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
