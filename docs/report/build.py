"""Render the report (and any other paper-styled HTML) to PDF with headless Chrome.

    uv run --with playwright python docs/report/build.py \
        docs/report/report.html docs/report/report.pdf "FuelCell-RAG"

Needs Google Chrome (or set CHROME) and network access for the Computer Modern web fonts.
"""

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
]


def main(src: str, dst: str, running_title: str) -> None:
    chrome = os.environ.get("CHROME") or next((p for p in CHROME_PATHS if Path(p).exists()), None)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=chrome) if chrome else pw.chromium.launch()
        page = browser.new_page()
        page.goto(Path(src).resolve().as_uri(), wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        footer = (
            '<div style="width:100%;font-family:serif;font-size:9px;display:flex;'
            'justify-content:space-between;padding:0 25mm;color:#444">'
            f"<span>{running_title}</span>"
            '<span><span class="pageNumber"></span></span></div>'
        )
        page.pdf(
            path=dst,
            format="A4",
            print_background=True,
            display_header_footer=True,
            header_template="<span></span>",
            footer_template=footer,
            margin={"top": "25mm", "bottom": "27mm", "left": "25mm", "right": "25mm"},
        )
        browser.close()
    print(f"wrote {dst}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
