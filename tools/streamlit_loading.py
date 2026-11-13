"""Puts a loading line into Streamlit's own index.html, so a first visit over a slow link shows words instead of a
black page while the scripts arrive. React replaces the root's contents when the app starts, so the line goes away
by itself. Safe to run again: it only writes when the page does not have the line yet. run_public.ps1 runs it on
every start, so a Streamlit upgrade (a fresh index.html) gets it back."""
from __future__ import annotations

import os
import sys
from pathlib import Path

MARK = 'id="olmuse-loading"'
TITLE = "olmuse"
LINE = (
    '<div id="root"><div ' + MARK + ' style="position:fixed;inset:0;display:flex;flex-direction:column;'
    'align-items:center;justify-content:center;gap:12px;background:#0f0f0f;color:#e8e8e8;'
    'font:600 18px/1.5 system-ui,-apple-system,Segoe UI,Malgun Gothic,sans-serif;text-align:center">'
    '<div style="font-size:34px;font-weight:800">olmuse</div>'
    '<div>불러오는 중이야~ 처음 열 때는 1~2분 걸릴 수 있어</div>'
    '<div style="font-weight:400;font-size:14px;color:#9a9a9a">Loading. The first visit can take a minute or two.</div>'
    "</div></div>"
)


def index_html() -> Path:
    import streamlit

    return Path(os.path.dirname(streamlit.__file__)) / "static" / "index.html"


def patch(text: str) -> str:
    if MARK in text:
        return text
    if '<div id="root"></div>' not in text:
        raise SystemExit("Streamlit's index.html has no empty root div; nothing changed")
    text = text.replace('<div id="root"></div>', LINE, 1)
    return text.replace("<title>Streamlit</title>", f"<title>{TITLE}</title>", 1)


def main() -> int:
    page = index_html()
    old = page.read_text(encoding="utf-8")
    new = patch(old)
    if new != old:
        page.write_text(new, encoding="utf-8")
        print(f"loading line added to {page}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
