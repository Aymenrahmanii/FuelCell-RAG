"""Record the demo video (docs/demo-script.md) by driving the real web app in a browser.

Playwright opens the web app at /app, asks the scripted questions, opens a cited source, shows
the comparison, requirement checker and evaluation screens, and records the screen. The
narration from the demo script is shown as captions, so the video stands on its own; record a
voice-over on top if you prefer. Nothing is staged: every answer comes from the running API.

    uv run --with playwright playwright install chromium        # once
    uv run --with playwright python scripts/record_demo.py      # API must be running on :8000

The video lands in demo/ as a .webm (convert with `ffmpeg -i demo/x.webm demo/x.mp4` if needed).
Run it twice: the first run fills the response cache, so the second shows every answer at once.
For live generation instead, start the API with FCRAG_RESPONSE_CACHE_TTL_S=0 and keep --pause
at 10 s or more (Groq's free tier: 8,000 tokens per minute).
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# (caption, action, argument). Captions follow docs/demo-script.md.
SCRIPT: list[tuple[str, str, str]] = [
    ("FuelCell-RAG answers engineering questions over fuel cell datasheets, requirements, CAD "
     "assemblies and public reports, in German and English. Every claim cites its source.",
     "open", "chat"),
    ("Parameter lookup: answers cite a page, table cell, requirement ID or CAD part.",
     "ask", "What is the maximum air mass flow of the System A air compressor?"),
    ("This value comes from the parameter sheet: open the cited source.", "source", ""),
    ("The documents exist in several versions. The answer uses the current one; the source "
     "panel marks which is latest and which is superseded.",
     "ask", "Welche Auslegungslebensdauer gilt aktuell für System B?"),
    ("Requirement links are searchable too.",
     "ask", "Which requirements refine REQ-A-0001?"),
    ("So is the STEP assembly tree.",
     "ask", "How many tie rods hold the System C stack together?"),
    ("It says when it does not know: a calibrated relevance threshold stops it from guessing.",
     "ask", "What is the warranty period of System A?"),
    ("Parameter comparison: values per system, straight from the extracted parameters table.",
     "open", "parameters"),
    ("Requirement checker: a draft requirement is checked against the current documents.",
     "check", ""),
    ("A 70-question golden set with exact gold sources, 25 in German. The failures are listed "
     "here, not hidden.",
     "open", "evaluation"),
    ("Code, evaluation and CI gate on GitHub: Aymenrahmanii/FuelCell-RAG", "end", ""),
]  # fmt: skip

CAPTION_JS = """(text) => {
  let box = document.getElementById('demo-caption');
  if (!box) {
    box = document.createElement('div');
    box.id = 'demo-caption';
    box.style.cssText = 'position:fixed;left:50%;bottom:28px;transform:translateX(-50%);'
      + 'max-width:1100px;padding:14px 22px;border-radius:10px;z-index:99999;'
      + 'background:rgba(15,23,42,.88);color:#fff;font:500 22px/1.4 system-ui,sans-serif;'
      + 'text-align:center;box-shadow:0 6px 24px rgba(0,0,0,.25);pointer-events:none';
    document.body.appendChild(box);
  }
  box.textContent = text;
  box.style.display = text ? 'block' : 'none';
}"""


def caption(page: Any, text: str, hold_s: float) -> None:
    page.evaluate(CAPTION_JS, text)
    time.sleep(hold_s)


def ask(page: Any, question: str, timeout_s: float) -> None:
    answers = page.locator("article.answer")
    before = answers.count()
    field = page.get_by_label("Question")
    field.click()
    field.type(question, delay=35)  # visible typing, as a person would
    time.sleep(0.4)
    page.keyboard.press("Enter")
    page.wait_for_function(
        "(n) => { const a = document.querySelectorAll('article.answer');"
        " return a.length > n && a[a.length - 1].getAttribute('aria-busy') === 'false'; }",
        arg=before,
        timeout=timeout_s * 1000,
    )


def open_first_source(page: Any) -> None:
    row = page.locator("aside[aria-label='Sources'] li.part button").first
    row.click()
    time.sleep(1.5)
    show = page.get_by_role("button", name="Show page")
    if show.count():
        show.first.click()
        page.wait_for_timeout(2500)


def open_screen(page: Any, base: str, screen: str) -> None:
    """Go to a screen and wait until it has drawn its content (screens load data first)."""
    page.goto(f"{base}/#/{screen}")
    page.wait_for_function(
        "(id) => document.querySelector(`#nav a[data-route='${id}']`)"
        "?.getAttribute('aria-current') === 'page'"
        " && document.querySelector('#main .sheet') !== null",
        arg=screen,
        timeout=60_000,
    )
    page.wait_for_load_state("networkidle")
    time.sleep(0.8)  # let entry animations finish


def scroll_through(page: Any, steps: int = 3, pause_s: float = 1.6) -> None:
    """Scroll down a screen in smooth steps, then back to the top, and let it settle."""
    for _ in range(steps):
        page.evaluate("window.scrollBy({top: 420, behavior: 'smooth'})")
        time.sleep(pause_s)
    page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
    time.sleep(1.5)


def run(args: argparse.Namespace) -> Path:
    from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]

    out_dir = REPO_ROOT / "demo"
    out_dir.mkdir(exist_ok=True)
    base = args.url.rstrip("/")
    size = {"width": 1920, "height": 1080}  # video pixels
    # Page zoom as in the script: a smaller CSS viewport rendered at a higher pixel ratio.
    view = {"width": round(1920 / args.zoom), "height": round(1080 / args.zoom)}
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not args.show,
            # a Chromium already on the machine, when Playwright's own download is not wanted
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE") or None,
        )
        init = f"sessionStorage.setItem('fcrag_api_key', {args.api_key!r});" if args.api_key else ""

        if args.warm_up:  # first request loads the models; keep it out of the video
            warm = browser.new_context(viewport=view)
            warm.add_init_script(init)
            page = warm.new_page()
            page.goto(f"{base}/#/chat")
            print("warming up (the first answer loads the models)…")
            ask(page, "What is the rated net power of System A?", args.timeout)
            warm.close()

        context = browser.new_context(
            viewport=view, device_scale_factor=args.zoom,
            record_video_dir=str(out_dir), record_video_size=size,
        )  # fmt: skip
        context.add_init_script(init)
        page = context.new_page()
        page.goto(f"{base}/#/chat")
        page.wait_for_selector("#health:not([data-state='wait'])", timeout=60_000)
        if page.get_attribute("#health", "data-state") != "ok":
            print("warning: the API reports", page.inner_text("#health"), file=sys.stderr)

        for n, (text, action, arg) in enumerate(SCRIPT, 1):
            print(f"[{n}/{len(SCRIPT)}] {action} {arg}".rstrip())
            if action == "open":
                open_screen(page, base, arg)
                caption(page, text, args.hold)
                if arg in {"parameters", "evaluation"}:
                    scroll_through(page)
            elif action == "ask":
                caption(page, text, 1.5)
                ask(page, arg, args.timeout)
                time.sleep(args.hold)
                time.sleep(max(0.0, args.pause - args.hold))  # stay under the LLM rate limit
            elif action == "source":
                caption(page, text, 1.0)
                open_first_source(page)
                time.sleep(args.hold)
            elif action == "check":
                open_screen(page, base, "requirements")
                caption(page, text, 1.5)
                page.get_by_role("button", name="Check").click()
                page.wait_for_function(
                    "() => !document.body.innerText.includes('Checking against the documents')",
                    timeout=args.timeout * 1000,
                )
                time.sleep(args.hold)
            elif action == "end":
                open_screen(page, base, "chat")
                caption(page, text, args.hold + 1)
            if args.screenshots:
                page.screenshot(path=str(out_dir / f"step-{n:02d}-{action}.png"))

        video = page.video
        target = out_dir / str(args.name)
        context.close()  # the video is written when its context closes
        video.save_as(target)
        video.delete()
        browser.close()
        return target


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--url", default="http://localhost:8000/app", help="web app URL")
    parser.add_argument("--api-key", default="", help="API key, if FCRAG_API_KEY is set")
    parser.add_argument("--name", default="fuelcell-rag-demo.webm", help="file name in demo/")
    parser.add_argument("--hold", type=float, default=4.0, help="seconds to show each result")
    parser.add_argument("--pause", type=float, default=10.0,
                        help="minimum seconds between questions (LLM rate limit)")  # fmt: skip
    parser.add_argument("--timeout", type=float, default=120.0, help="seconds to wait per answer")
    parser.add_argument("--zoom", type=float, default=1.25, help="page zoom, as in the script")
    parser.add_argument("--no-warm-up", dest="warm_up", action="store_false")
    parser.add_argument("--show", action="store_true", help="show the browser while recording")
    parser.add_argument("--screenshots", action="store_true",
                        help="also save a screenshot after each step to demo/")  # fmt: skip
    args = parser.parse_args()
    try:
        path = run(args)
    except ModuleNotFoundError:
        sys.exit("Playwright is missing: run with `uv run --with playwright python ...`")
    print(f"saved {path}")


if __name__ == "__main__":
    main()
