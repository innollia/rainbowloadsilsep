"""The asset room's board kept in step between two computers of one account, in a real browser (docs/ASSET_SYNC_SPEC.md
K, the browser check, and scenes 15, 19 and 22, a folder joining the board). Two browser contexts are the two computers; each page is opened at the
top level, so it is its own host page: an init script answers its asset:ready the way studio_frontend/app.js would,
with the AI switch, "signed in" and an account token for the local API (boards on, a temp folder, a free port).

Run: python tests/e2e_asset_sync.py  (not collected by pytest; needs playwright, Chrome and node)
"""
import json
import struct
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
import functools
import math
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
import os  # noqa: E402
# E2E_STUDIO: another copy of studio_frontend (with asset_studio in it), to see these checks fail without the wiring.
ROOT = Path(os.environ.get("E2E_STUDIO") or REPO / "studio_frontend") / "asset_studio"
sys.path.insert(0, str(REPO / "tests"))
from test_asset_sync_two import SyncApi  # noqa: E402


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def write_wav(path, seconds, freq):
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 48000
    n = int(rate * seconds)
    frames = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate) * min(1, i / 400, (n - i) / 400))) for i in range(n))
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(frames)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
                + b"data" + struct.pack("<I", len(frames)) + frames)


# The host page (studio_frontend/app.js's part) around the room in an iframe: on asset:ready it sends the AI switch with
# "signed in" (sessionStorage e2e-signed, '0' = signed out) and the account token; the assistant's questions are kept in
# window.asked for the test to answer with reply(message).
HOST = """<!doctype html><meta charset="utf-8"><title>host</title><body style="margin:0">
<iframe id="room" src="asset_studio/index.html?lang=ko" style="width:1440px;height:900px;border:0"></iframe>
<script>
const TOKEN = %s, room = document.getElementById('room');
window.asked = [];
window.reply = (m) => room.contentWindow.postMessage(m, location.origin);
window.signed = (on) => { sessionStorage.setItem('e2e-signed', on ? '1' : '0'); reply({ type: 'asset:ai', on: true, signed: on }); };
addEventListener('message', (e) => {
  if (e.source !== room.contentWindow) return;
  const d = e.data || {};
  if (d.type === 'asset:ready') {
    const on = sessionStorage.getItem('e2e-signed') !== '0';
    reply({ type: 'asset:ai', on: true, signed: on });
    if (on) reply(TOKEN);
  }
  if (d.type === 'asset:agent') window.asked.push(d.payload);
});
</script>"""


class Host(Quiet):
    page = b""

    def do_GET(self):
        if self.path.startswith("/e2e-host.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(self.page)))
            self.end_headers()
            self.wfile.write(self.page)
            return
        super().do_GET()


NAMES = "() => [...document.querySelectorAll('#board .tile')].map((t) => [t.dataset.id, t.querySelector('.name')?.textContent || ''])"


def main():
    tmp = Path(tempfile.mkdtemp())
    game = tmp / "Folder"
    write_wav(game / "UI" / "btn_press.wav", 0.12, 1500)
    write_wav(game / "door_open.wav", 0.3, 400)
    bundle = tmp / "bundle.zip"
    with zipfile.ZipFile(bundle, "w") as z:
        z.writestr("game-audio.spec.json", json.dumps({"game": "Bundle", "assets": []}))

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Host, directory=str(ROOT.parent)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    url = f"{origin}/e2e-host.html"
    api = SyncApi(tmp / "api", origin)
    Host.page = (HOST % json.dumps({"type": "asset:token", "token": api.token(), "ttl": 900, "api": api.base})).encode()
    checks, errors = [], []

    def check(name, ok, detail=""):
        if errors and not any(n == "page errors so far" for n, _ in checks):
            print("  (page error before this check:", errors[0], ")", flush=True)
            checks.append(("page errors so far", True))
        checks.append((name, bool(ok)))
        print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if not ok and detail else ""), flush=True)

    def boards():
        req = urllib.request.Request(api.base + "/boards", headers={"Authorization": "Bearer " + api.token(), "Origin": origin})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read())

    def room(page):
        """The asset room inside the host page: the same frame across its reloads."""
        page.wait_for_selector("#room")
        fr = page.frame_locator("#room")  # waits for the frame to exist
        del fr
        return next(f for f in page.frames if f.parent_frame is page.main_frame)

    def names(page):
        return dict(page.evaluate(NAMES))

    def shows(page, text, ms=8000):
        try:
            page.wait_for_function("(s) => document.querySelector('#board').textContent.includes(s)", arg=text, timeout=ms)
            return True
        except Exception:
            return False

    def open_sound(page, sid):
        page.focus(f".tile[data-id='{sid}']")
        page.page.keyboard.press("Enter")
        page.wait_for_selector(".dName", state="visible")

    def rename(page, sid, text):
        open_sound(page, sid)
        page.fill(".dName", text)
        page.click("#boardBack")
        page.wait_for_selector("#board .tile", state="visible")

    def ask(page, text, actions):
        """The assistant is asked in the dock and answers with these actions (the host page's part)."""
        host = page.page
        had = host.evaluate("() => window.asked.length")
        page.fill("#ask", text)
        page.press("#ask", "Enter")
        host.wait_for_function("(n) => window.asked.length > n", arg=had, timeout=10000)
        n = host.evaluate("() => window.asked.at(-1).n")
        host.evaluate("(m) => reply(m)", {"type": "asset:agent_reply", "n": n, "status": "done", "reply": "했어", "actions": actions})

    def account_board(page, ms=20000, mark=None):
        """The page has reloaded onto a board of the account and its first receiving is over. mark: the page was
        marked before the step that reloads it (moving()), so the wait is for a new page."""
        if mark:
            page.wait_for_function("() => !window.__before", timeout=ms)
        page.wait_for_function(f"localStorage.getItem('asset-sync.who') === '{api.who}'", timeout=ms)
        page.wait_for_load_state("load")
        page.wait_for_selector("#board .tile, #board .emptyBoard, #board", timeout=ms)
        page.wait_for_timeout(2500)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            ctx_a, ctx_b = browser.new_context(viewport={"width": 1440, "height": 900}), browser.new_context(viewport={"width": 1440, "height": 900})
            pa, pb = ctx_a.new_page(), ctx_b.new_page()
            pa.on("pageerror", lambda e: errors.append("A: " + str(e)))
            pb.on("pageerror", lambda e: errors.append("B: " + str(e)))

            # A: a visitor with an untouched empty board signs in; the first sounds put on it make it the account's first board.
            pa.goto(url)
            a = room(pa)
            a.wait_for_selector("#dialog[open]")
            a.page.keyboard.press("Escape")
            check("the first screen is an empty board", a.locator("#board .tile").count() == 0 and a.inner_text("#gameTitle") == "새 게임", a.inner_text("#gameTitle"))
            check("signed in with an untouched empty board, nothing is made yet", boards()["boards"] == [], boards())
            a.wait_for_timeout(3000)
            check("an untouched empty board alone makes no board", boards()["boards"] == [], boards())
            # Work: a list of what the game needs becomes eight empty slots. The board becomes the account's first board.
            a.click("#importBtn")
            a.fill("#listIn", "\n".join(["하나", "둘", "셋", "넷", "다섯", "여섯", "일곱", "여덟"]))
            a.click("#addSlots")
            account_board(a)
            listed = boards()
            check("the first sounds made the empty board the account's first board", len(listed["boards"]) == 1 and listed["home"] == listed["boards"][0]["id"], listed)
            ids = [i for i, _ in a.evaluate(NAMES)]
            start_names = names(a)
            check("the board is still the one that was worked on", len(ids) == 8 and "여덟" in start_names.values(), start_names)
            rename(a, ids[0], "A가 바꾼 이름")

            # B: another computer of the account, on an empty board of its own, opens the account's board.
            pb.goto(url)
            b = room(pb)
            account_board(b)
            check("the second computer opens the account's board", shows(b, "A가 바꾼 이름"), names(b))
            check("joining made no second board", len(boards()["boards"]) == 1)

            # A rename on one computer is on the other within 5 s.
            rename(b, ids[1], "B가 바꾼 이름")
            t0 = time.time()
            check("a rename shows on the other computer within 5 s", shows(a, "B가 바꾼 이름", 5000), f"{time.time() - t0:.1f}s")

            # Typing is not cut off by what comes in meanwhile; it shows once the field is let go.
            open_sound(a, ids[2])
            a.click(".dName")
            a.page.keyboard.press("End")
            a.page.keyboard.type("가나", delay=80)
            rename(b, ids[3], "입력 중에 온 이름")
            a.wait_for_timeout(5000)
            a.page.keyboard.type("다", delay=80)
            held = a.evaluate("() => [document.activeElement?.className, document.activeElement?.value]")
            check("typing goes on while a change comes in", held == ["dName", start_names[ids[2]] + "가나다"], held)
            a.click("#boardBack")
            check("what came in shows once the field is let go", shows(a, "입력 중에 온 이름", 6000), names(a))

            # A sound open in detail shows a change made elsewhere.
            open_sound(a, ids[4])
            a.click(".dWave") if a.locator(".dWave").count() else None
            rename(b, ids[4], "열린 채로 받은 이름")
            try:
                a.wait_for_function("() => document.querySelector('.dName')?.value === '열린 채로 받은 이름'", timeout=6000)
                seen = True
            except Exception:
                seen = False
            check("a sound open in detail shows a change made elsewhere", seen, a.evaluate("() => document.querySelector('.dName')?.value"))
            a.click("#boardBack")

            # Scene 15: the assistant's answer is taken back, but a field a teammate changed since stays theirs.
            ask(a, "이름 두 개 바꿔", [{"op": "rename", "assets": [ids[5]], "name": "에이전트5"}, {"op": "rename", "assets": [ids[6]], "name": "에이전트6"}])
            a.wait_for_selector("#toast button", state="attached", timeout=5000)
            shows(b, "에이전트6", 8000)
            rename(b, ids[6], "팀원6")
            shows(a, "팀원6", 8000)
            a.evaluate("() => document.querySelector('#toast button').click()")
            a.wait_for_timeout(500)
            got = names(a)
            check("scene 15: undo puts back what still holds the answer", got.get(ids[5]) == start_names[ids[5]], got.get(ids[5]))
            check("scene 15: a teammate's later edit stays", got.get(ids[6]) == "팀원6", got.get(ids[6]))
            check("scene 15: the other computer ends the same", shows(b, start_names[ids[5]], 8000) and names(b).get(ids[6]) == "팀원6", names(b))

            # Scene 19: a bundle does not replace a board that has sounds.
            before = names(a)
            a.set_input_files("#importFiles", str(bundle))
            try:
                a.wait_for_function("() => document.querySelector('#toast').textContent.includes('묶음은 빈 보드에서')", timeout=5000)
                said = True
            except Exception:
                said = False
            check("scene 19: a bundle on a board with sounds is refused and says so", said and names(a) == before, a.inner_text("#toast"))

            # A brings a folder in: its sounds join the board, on both computers.
            a.set_input_files("#importFolder", str(game))
            a.wait_for_function("document.querySelectorAll('.tile.imported').length === 2", timeout=15000)
            a.page.keyboard.press("Escape")
            try:
                b.wait_for_function("document.querySelectorAll('#board .tile').length === 10", timeout=10000)
                both = True
            except Exception:
                both = False
            check("a folder brought in joins the board on the other computer too", both and shows(b, "팀원6", 1000), names(b))

            # The game info dialog lists the boards; an empty board is a new board once a sound is on it, and the old one opens again.
            a.click("#menuBtn")
            a.click("[data-act='game']")
            a.wait_for_selector("#dialog[open] .boardRow.here", timeout=10000)
            state = a.inner_text("#dialog .boardRow.here")
            check("the board list shows this board and how far it is sent", all(x in state for x in ("Folder", "소리 10개", "동기화됨")), state)
            check("the game window has one way to start again", a.locator("#dialog[open] button", has_text="샘플").count() == 0)
            first = boards()["home"]
            a.evaluate("() => { window.__before = 1; }")
            a.click("#startBlank")
            account_board(a, mark=True)
            a.wait_for_timeout(2500)
            check("an untouched empty board is not a board of the account yet", len(boards()["boards"]) == 1 and a.locator("#board .tile").count() == 0, [len(boards()["boards"]), names(a), a.inner_text("#gameTitle")])
            a.click("#importBtn")
            a.fill("#listIn", "새 소리")
            a.click("#addSlots")
            for _ in range(20):  # the new board goes up with the engine's next round
                if len(boards()["boards"]) == 2:
                    break
                time.sleep(0.5)
            check("with a sound on it the empty board is a new board of the account; the other board stays", len(boards()["boards"]) == 2 and boards()["home"] == first, boards())
            check("the other computer keeps its board", b.locator("#board .tile").count() == 10)
            a.click("#menuBtn")
            a.click("[data-act='game']")
            a.wait_for_selector("#dialog[open] .boardRow:not(.here) button", timeout=10000)
            a.evaluate("() => { window.__before = 1; }")
            a.click("#dialog .boardRow:not(.here) button")
            account_board(a, mark=True)
            check("the first board opens again from the list", a.locator(".tile.imported").count() == 2 and boards()["home"] == first, boards())

            # Signing out: the page shows a board without an account, which is an empty one.
            pa.evaluate("() => signed(false)")
            a.wait_for_function("localStorage.getItem('asset-sync.who') === ''", timeout=10000)
            a.wait_for_load_state("load")
            a.wait_for_timeout(2500)
            check("signed out, the page shows a board without the account's sounds", a.locator("#board .tile").count() == 0, names(a))

            check("no page errors", not errors, errors[:3])
        finally:
            browser.close()
            api.stop()
            server.shutdown()
    passed = sum(ok for _, ok in checks)
    print(f"{passed}/{len(checks)} passed")
    sys.exit(0 if passed == len(checks) else 1)


if __name__ == "__main__":
    main()
