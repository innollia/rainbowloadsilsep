"""Real-browser walk through the asset room's guide, on the empty board a first visit opens on.

Run: python tests/e2e_asset_tour.py [screenshot folder]  (not collected by pytest; needs playwright and Chrome)
A first-time visitor with nothing of their own follows the guide note by note: an empty tile, its name, opening it,
the words the AI makes it from, listening, approving, back to the board, where export is, and the optional import
note. Each note is pressed through the control it points at. Then How to use starts it again and Esc puts it away,
and a visit without the AI is told so at the making step and goes on with Next.

Sounds are made by the generation API with OLMUSE_GEN_FAKE=1, as in e2e_asset_import.py (its GenApi and hand()).
"""
import functools
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from e2e_asset_import import ROOT, GenApi, Quiet, hand  # noqa: E402

STEPS = 10


def main():
    tmp = Path(tempfile.mkdtemp())
    shots = Path(sys.argv[1]) if len(sys.argv) > 1 else tmp / "shots"
    shots.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    url = f"{origin}/index.html?lang=ko"
    api = GenApi(tmp / "api", origin)
    checks, errors = [], []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok)))
        print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if not ok and detail else ""))

    def at(page, n, timeout=15000):
        """Waits for note n; says what it reads and saves a picture of it."""
        page.wait_for_function("(s) => { const b = document.querySelector('#tour'); return b && !b.hidden && b.querySelector('.tourStep').textContent === s; }",
                               arg=f"{n} / {STEPS}", timeout=timeout)
        page.wait_for_timeout(150)  # the note is placed on the next frame
        page.screenshot(path=str(shots / f"{page.tag}-{n:02d}.png"))
        return page.inner_text("#tour .tourText")

    def points_at(page, selector):
        return page.evaluate("(s) => { const m = document.querySelector('.tourMark'); return !!m && m.matches(s); }", selector)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.tag = "ai"
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(url)
            hand(page, api)

            text = at(page, 1)
            check("a first visit opens the guide on an empty board, not a dialog",
                  page.locator(".tile").count() == 0 and not page.is_visible("#dialog[open]") and "+" in text, text)
            check("note 1 points at a group's add button", points_at(page, ".addSound"))
            page.click(".tourMark")

            text = at(page, 2)
            check("note 2 asks for a name, beside the name being typed", points_at(page, ".renameIn") and "이름" in text, text)
            page.keyboard.type("점프")
            page.keyboard.press("Enter")

            text = at(page, 3)
            check("note 3 points at the new tile", points_at(page, ".tile") and page.inner_text(".tourMark .name") == "점프", text)
            page.dblclick(".tourMark")

            text = at(page, 4)
            check("note 4 asks for the words, at the request box", points_at(page, ".detailDock textarea") and "AI" in text, text)
            page.fill(".detailDock textarea", "가볍게 톡 튀는 점프 소리")
            page.keyboard.press("Enter")

            text = at(page, 6, timeout=60000)
            check("once it is made, note 6 points at play", points_at(page, "#dPlay"), text)
            page.click("#dPlay")

            text = at(page, 7)
            check("note 7 points at approve or keep", points_at(page, ".dApprove, .keep"), text)
            page.click(".tourMark")

            text = at(page, 8)
            check("note 8 points back to the board", points_at(page, "#boardBack"), text)
            page.click("#boardBack")

            text = at(page, 9)
            check("note 9 shows export, with Next", points_at(page, "#exportBtn") and page.is_visible("#tourNext"), text)
            check("the sound is made and approved", page.locator(".tile[data-status=approved]").count() == 1)
            page.click("#tourNext")

            text = at(page, 10)
            check("the last note is import and the spec, optional", points_at(page, "#importBtn") and "가져오기" in text and "명세" in text, text)
            page.click("#tourNext")
            page.wait_for_timeout(100)
            check("done puts the guide away", page.is_hidden("#tour") and page.locator(".tourMark").count() == 0)

            page.click("#menuBtn")
            page.click("#menu [data-act=help]")
            at(page, 1)
            check("How to use starts it again", True)
            page.keyboard.press("Escape")
            page.wait_for_timeout(100)
            check("Esc puts it away", page.is_hidden("#tour"))
            page.reload()
            page.wait_for_selector("#board .group")
            page.wait_for_timeout(500)
            check("a later visit does not open it by itself", page.is_hidden("#tour"))

            # No AI for this visit (no token from the host): the making step says so and Next goes on past it.
            off = browser.new_page(viewport={"width": 1440, "height": 900})
            off.tag = "off"
            off.on("pageerror", lambda e: errors.append("off: " + str(e)))
            off.goto(url)
            at(off, 1)
            off.click(".tourMark")
            at(off, 2)
            off.keyboard.type("코인")
            off.keyboard.press("Enter")
            at(off, 3)
            off.dblclick(".tourMark")
            text = at(off, 4)
            check("without the AI, note 4 says so plainly and has Next", "꺼져" in text and off.is_visible("#tourNext"), text)
            off.click("#tourNext")
            text = at(off, 8)
            check("Next skips making, listening and approving", points_at(off, "#boardBack"), text)
            check("no page errors", not errors, errors)
        finally:
            browser.close()
            api.stop()
            server.shutdown()
    print(f"screenshots: {shots}")
    passed = sum(ok for _, ok in checks)
    print(f"{passed}/{len(checks)} passed")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
