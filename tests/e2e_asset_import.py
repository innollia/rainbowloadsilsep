"""Real-browser check of bringing existing work into the game sound asset board.

Run: python tests/e2e_asset_import.py  (not collected by pytest; needs playwright, Chrome and node)
A first-time visitor who already has work: a folder of sounds, a list of needed sounds made while the tab is
reloaded, drafts in the feel of a brought-in sound, then export and re-open the bundle in a fresh browser.
A brought-in sound that breaks rules shows the same rule ids as `node tools/asset_lint.js --json`.

Sounds are made by the generation API (asset_api.py), started here on a port of its own by the server's own loader
with OLMUSE_GEN_FAKE=1 set for it: a scripted model and sine waves. No key, no ledger; the job database and the results
are in a temp folder. The two lines the loader logs on the way (the switch is on, no ledger) are expected.
"""
import functools
import json
import math
import os
import secrets
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import wave
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parent.parent
ROOT = REPO / "studio_frontend" / "asset_studio"
sys.path.insert(0, str(REPO))


def write_wav(path, seconds, freq, noise=0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    rate, n = 22050, int(22050 * seconds)
    frames = b"".join(struct.pack("<h", int(12000 * (math.sin(2 * math.pi * freq * i / rate) * (1 - noise) + noise * math.sin(i * i % 7919))))
                      for i in range(n))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(frames)


def write_hot_wav(path):
    """A one-shot that breaks rules on purpose: flat tops at full scale, off centre, over two seconds, silent at both ends."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rate = 44100
    body = [max(-1.0, min(1.0, 0.25 + 1.6 * math.sin(2 * math.pi * 330 * i / rate))) for i in range(int(rate * 2.4))]
    samples = [0.0] * int(rate * 0.3) + body + [0.0] * int(rate * 0.5)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(32767 * s)) for s in samples))


def lint_ids(path, tile_id):
    """The rule ids the command line gives the file, judged as the board judges a brought-in effect:
    under the id it has on the board and with no sources."""
    out = subprocess.run(["node", str(REPO / "tools" / "asset_lint.js"), str(path), "--kind", "sfx", "--id", tile_id, "--sources", "[]", "--json"],
                         capture_output=True, encoding="utf-8")
    return [x["id"] for x in json.loads(out.stdout)["issues"]]


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


class GenApi:
    """The generation API for pages of page_origin, with the scripted model and the sine engine.
    token() is the message the host page would hand the asset room: a password session's token and where the API is."""

    def __init__(self, folder, page_origin):
        import uvicorn

        import asset_api
        import asset_generate
        import asset_token
        self.sign, self.request_of = asset_token, asset_generate.request_of
        self.secret, self.sub = secrets.token_hex(32), "pw:e2e-" + secrets.token_hex(4)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        self.base = f"http://127.0.0.1:{port}/api/asset"
        # What run_api.ps1 would start with OLMUSE_GEN_FAKE=1: the server reads its own switch. Everything that could
        # reach this PC's real jobs, token key or ledger is pointed at the temp folder or left empty.
        env = dict(os.environ, OLMUSE_GEN_FAKE="1", OLMUSE_GEN_DB=str(folder / "asset-gen.db"), OLMUSE_RENDERS=str(folder / "renders"),
                   OLMUSE_API_HOSTS=f"127.0.0.1:{port}", OLMUSE_API_ORIGINS=page_origin, STRUDEL_CREDITS_URL="", STRUDEL_LOCAL_LEDGER="")
        env[asset_token.SECRET_ENV] = self.secret
        self.app = asset_api.create_app(asset_api.real_deps(env))
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=port, log_level="warning", access_log=False, proxy_headers=False))
        threading.Thread(target=self.server.run, daemon=True).start()
        deadline = time.time() + 15
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("the generation API did not start")
            time.sleep(0.05)

    def token(self):
        signed = self.sign.sign(self.sign.payload_for("pw", self.sub, "", "ko", time.time()), self.secret)
        return {"type": "asset:token", "token": signed, "ttl": self.sign.TTL - 30, "api": self.base}

    def stop(self):
        self.server.should_exit = True
        self.app.state.api.jobs.stop()
        self.app.state.api.jobs.store.close()
        self.app.state.api.close()


def hand(page, api):
    """What the host page does once the room is up. The room reads the price of a draft with a token that is new
    to it, so that answer says the token was taken. Once for every load: a reload forgets the token."""
    with page.expect_response(lambda r: "/api/asset/quote" in r.url, timeout=15000):
        page.evaluate("(m) => window.postMessage(m, location.origin)", api.token())


ON_DISK = """async (n) => {
  for (const d of await indexedDB.databases()) {
    const db = await new Promise((res, rej) => { const o = indexedDB.open(d.name); o.onsuccess = () => res(o.result); o.onerror = () => rej(o.error); });
    try {
      if (![...db.objectStoreNames].includes('audio')) continue;
      const keys = await new Promise((res) => { const q = db.transaction('audio').objectStore('audio').getAllKeys(); q.onsuccess = () => res(q.result); });
      if (keys.length >= n) return true;
    } finally { db.close(); }
  }
  return false;
}"""

BOARD_ON_DISK = """async () => {
  for (const d of await indexedDB.databases()) {
    const db = await new Promise((res, rej) => { const o = indexedDB.open(d.name); o.onsuccess = () => res(o.result); o.onerror = () => rej(o.error); });
    try {
      if (![...db.objectStoreNames].includes('board')) continue;
      const rec = await new Promise((res) => { const q = db.transaction('board').objectStore('board').get('board'); q.onsuccess = () => res(q.result); });
      if (rec) return true;
    } finally { db.close(); }
  }
  return false;
}"""


def groups(page):
    return page.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#board .group')].map((g) =>
        [g.querySelector('h2').firstChild.nextSibling.textContent, [...g.querySelectorAll('.tile .name')].map((n) => n.textContent)]))""")


def main():
    tmp = Path(tempfile.mkdtemp())
    game = tmp / "MyGame"
    write_wav(game / "UI" / "btn_press.wav", 0.12, 1500)
    write_wav(game / "Sword_Swing_01.wav", 0.35, 300, noise=0.6)
    write_wav(game / "amb_forest_loop.wav", 4, 200, noise=0.8)
    write_wav(game / "mystery.wav", 0.2, 800)
    hot = tmp / "ui_too_hot.wav"
    write_hot_wav(hot)

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    url = f"{origin}/index.html?lang=ko"
    api = GenApi(tmp / "api", origin)
    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok)))
        print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if not ok and detail else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)
        hand(page, api)

        # First visit: an empty board of the user's own, and the tutorial opens and offers Import; the header does too.
        page.wait_for_selector("#dialog[open] #tutorialImport")
        check("first screen is an empty board", page.locator(".tile").count() == 0 and page.inner_text("#gameTitle") == "새 게임", page.inner_text("#gameTitle"))
        check("first screen offers import and nothing else to start from",
              page.is_visible("#importBtn") and page.locator("#dialog[open] .dlgRow button").count() == 1 and page.locator("#tutorialBlank").count() == 0)
        page.click("#tutorialImport")
        page.wait_for_selector("#dialog[open] #pickFolder")

        # A whole folder of sounds.
        page.set_input_files("#importFolder", str(game))
        page.wait_for_function("document.querySelectorAll('.tile.imported').length === 4", timeout=15000)
        check("game name taken from the folder", page.inner_text("#gameTitle") == "MyGame", page.inner_text("#gameTitle"))
        g = groups(page)
        check("categories guessed from names", "Sword swing 01" in g.get("전투", []) and "Btn press" in g.get("UI", []) and "Forest loop" in g.get("환경", []), json.dumps(g, ensure_ascii=False))
        check("brought-in mark on tiles", page.locator(".tile.imported .origin").first.inner_text() == "직접 가져옴")
        check("the folder's sounds are the board", page.locator(".tile").count() == 4)
        page.wait_for_selector("#dialog[open] .justRow")
        check("unsure category is flagged", page.locator(".justRow .catPick.unsure").count() >= 1)
        page.locator(".justRow", has_text="btn_press.wav").locator("input.grow").fill("버튼 누름")
        check("rename applies at once", "버튼 누름" in groups(page).get("UI", []), json.dumps(groups(page), ensure_ascii=False))
        page.locator(".justRow", has_text="mystery.wav").locator(".catPick").select_option("char")
        check("category fix applies at once", "Mystery" in groups(page).get("캐릭터", []), json.dumps(groups(page), ensure_ascii=False))

        # A pasted list of what the game still needs becomes empty slots, then the AI fills them.
        page.fill("#listIn", "점프 착지, 캐릭터\nCoin pickup\nbgm_title")
        page.click("#addSlots")
        page.wait_for_function("document.querySelectorAll('.tile[data-status=pending]').length === 3")
        check("list became empty slots", True)

        # The tab is reloaded while the sounds are being made: the tiles still say so, and they finish.
        # The finished sounds are kept from arriving until then, so the reload is sure to come in the middle.
        held = "**/api/asset/jobs/*/sound"
        page.route(held, lambda route: route.abort())
        with page.expect_response(lambda r: r.url.endswith("/api/asset/jobs") and r.request.method == "POST") as sent:
            page.click("#fillBtn")
        check("the request for the slots is taken", sent.value.status == 200, sent.value.status)
        check("slots are being made", page.locator(".tile[data-status=working]").count() == 3)
        # The board record is written before the bytes of its sounds, one sound at a time, and the request above wrote
        # the record. A tab that goes in between comes back with the sounds not written yet as empty slots, so the
        # reload waits for the four that were brought in. The request starts their write itself: no page timer is due.
        deadline = time.time() + 5
        while not page.evaluate(ON_DISK, 4) and time.time() < deadline:
            page.wait_for_timeout(20)
        check("the request put the brought-in sounds on the disk of the browser", page.evaluate(ON_DISK, 4))
        page.reload()
        page.wait_for_function("document.querySelectorAll('.tile').length === 7", timeout=15000)
        check("a reload in the middle still shows the work", page.locator(".tile[data-status=working]").count() == 3)
        page.unroute(held)
        hand(page, api)
        page.wait_for_function("!document.querySelector('.tile[data-status=pending]') && !document.querySelector('.tile[data-status=working]')", timeout=30000)
        check("slots filled after the reload", page.locator(".tile[data-status=draft]").count() == 3)

        # A reload (or closing the tab, or going to the game) loses nothing: the board is saved as it changes.
        page.wait_for_timeout(1200)
        page.reload()
        page.wait_for_function("document.querySelectorAll('.tile').length === 7", timeout=15000)
        hand(page, api)
        g = groups(page)
        check("board survives a reload", page.inner_text("#gameTitle") == "MyGame" and "버튼 누름" in g.get("UI", [])
              and page.locator(".tile.imported").count() == 4 and page.locator(".tile[data-status=draft]").count() == 3, json.dumps(g, ensure_ascii=False))
        check("reload opens no tutorial again", not page.is_visible("#dialog[open]"))

        # Drafts in the feel of a brought-in sound: the prompt carries its measurements.
        page.locator(".tile.imported", has_text="Sword swing 01").focus()
        page.keyboard.press("Enter")
        page.wait_for_selector("#likeThis")
        page.click("#likeThis")
        page.wait_for_function("[...document.querySelectorAll('.tile .name')].some((n) => n.textContent.includes('느낌')) && !document.querySelector('.tile[data-status=working]')", timeout=30000)
        page.locator(".tile", has_text="느낌").focus()
        page.keyboard.press("Enter")
        page.get_by_role("tab", name="코드").click()
        prompt = page.text_content("#promptText") or ""
        try:
            style = api.request_of(prompt).get("style_ref") or {}
        except ValueError:
            style = {}
        check("prompt carries reference measurements", style.get("name") == "Sword swing 01" and "peak" in (style.get("facts") or {}), prompt)
        page.keyboard.press("Escape")

        # Export, then re-open the bundle in a fresh browser.
        page.wait_for_selector("#boardView:not([hidden])")
        page.click("#approveAll") if page.is_visible("#approveAll") else None
        page.click("#exportBtn")
        with page.expect_download() as dl:
            page.click("#exportGo")
        bundle = tmp / "bundle.zip"
        dl.value.save_as(bundle)
        with zipfile.ZipFile(bundle) as z:
            names = z.namelist()
            spec = json.loads(z.read("game-audio.spec.json"))
        imported = [a for a in spec["assets"] if a["origin"] == "imported"]
        check("bundle holds spec, credits and audio", "CREDITS.md" in names and len([n for n in names if n.startswith("audio/")]) == 8, names)
        check("bundle marks brought-in sounds, license left empty", len(imported) == 4 and all(a["license"] == "" for a in imported))

        fresh = browser.new_page(viewport={"width": 1440, "height": 900})
        fresh.on("pageerror", lambda e: errors.append(str(e)))
        fresh.goto(url)
        fresh.wait_for_selector("#dialog[open]")
        fresh.keyboard.press("Escape")
        fresh.set_input_files("#importFiles", str(bundle))
        fresh.wait_for_function("document.querySelectorAll('.tile.imported').length === 4", timeout=15000)
        check("bundle re-opens with every asset", fresh.locator(".tile").count() == len(spec["assets"]) and fresh.inner_text("#gameTitle") == "MyGame")
        check("re-opened names kept", "버튼 누름" in fresh.inner_text("#board"))
        # Odd things dropped in: a photo, a broken .wav, a file over 50 MB, and a zip from Windows Explorer (CP949 name).
        odd = tmp / "odd"
        odd.mkdir()
        (odd / "photo.jpg").write_bytes(bytes([0xFF, 0xD8, 0xFF, 0xE0]) + bytes(2000))
        (odd / "broken.wav").write_bytes(b"RIFF" + bytes(range(256)) * 8)
        with open(odd / "huge.wav", "wb") as f:
            f.truncate(51 * 1024 * 1024)
        write_wav(odd / "good.wav", 0.2, 600)
        write_wav(tmp / "inner.wav", 0.15, 900)
        with zipfile.ZipFile(odd / "explorer.zip", "w") as z:
            z.write(tmp / "inner.wav", "xxxxxx.wav")
        raw = (odd / "explorer.zip").read_bytes()
        (odd / "explorer.zip").write_bytes(raw.replace(b"xxxxxx", "발소리".encode("cp949")))
        odd_page = browser.new_page(viewport={"width": 1440, "height": 900})
        odd_page.on("pageerror", lambda e: errors.append(str(e)))
        odd_page.goto(url)
        odd_page.wait_for_selector("#dialog[open]")
        odd_page.keyboard.press("Escape")
        odd_page.set_input_files("#importFiles", [str(odd / n) for n in ("photo.jpg", "broken.wav", "huge.wav", "good.wav", "explorer.zip")])
        odd_page.wait_for_function("document.querySelectorAll('.tile.imported').length === 2", timeout=15000)
        odd_page.wait_for_function("document.querySelector('#toast').textContent.includes('건너뜀')", timeout=5000)
        note = odd_page.inner_text("#toast")
        check("odd files skipped and counted", all(k in note for k in ("3개 건너뜀", "소리 파일 아님 1", "읽지 못함 1", "1")), note)
        check("CP949 zip name read as Korean", "발소리" in odd_page.inner_text("#board"), odd_page.inner_text("#board"))

        # A brought-in sound that breaks rules: its tile names the rules the command line names for the same file.
        hot_page = browser.new_page(viewport={"width": 1440, "height": 900})
        hot_page.on("pageerror", lambda e: errors.append(str(e)))
        hot_page.goto(url)
        hot_page.wait_for_selector("#dialog[open]")
        hot_page.keyboard.press("Escape")
        hot_page.set_input_files("#importFiles", str(hot))
        hot_page.wait_for_selector(".tile.imported[data-issues]", timeout=15000)
        tile = hot_page.locator(".tile.imported")
        shown, told = (tile.get_attribute("data-issues") or "").split(), lint_ids(hot, tile.get_attribute("data-id"))
        check("a rule-breaking sound shows what asset_lint.js finds", shown == told and {"peak", "lic"} <= set(shown), f"board {shown}, command line {told}")

        # Starting over with nothing: the game window offers one way, an empty board. The one sound here is the user's
        # own, so the page asks before it goes; after the reset the board is empty and stays empty.
        asked = []
        hot_page.on("dialog", lambda d: (asked.append(d.message), d.accept()))
        hot_page.keyboard.press("Escape")  # the report of the import is still up
        hot_page.wait_for_selector("#dialog", state="hidden")
        hot_page.click("#menuBtn")
        hot_page.click("#menu [data-act=game]")
        hot_page.wait_for_selector("#dialog[open] #startBlank")
        check("the game window has one way to start again", hot_page.locator("#dialog[open] button", has_text="처음부터").count() == 1
              and hot_page.locator("#dialog[open] button", has_text="샘플").count() == 0)
        with hot_page.expect_navigation():
            hot_page.click("#startBlank")
        hot_page.wait_for_function("document.querySelector('#gameTitle').textContent === '새 게임'", timeout=15000)
        check("an empty board asks before the user's own sound goes", len(asked) == 1 and "1" in asked[0], asked)
        check("an empty board opens with no sound and no window in the way",
              hot_page.locator(".tile").count() == 0 and not hot_page.is_visible("#dialog[open]"), hot_page.inner_text("#board")[:200])
        deadline = time.time() + 10
        while not hot_page.evaluate(BOARD_ON_DISK) and time.time() < deadline:
            hot_page.wait_for_timeout(50)
        hot_page.reload()
        hot_page.wait_for_function("document.querySelector('#gameTitle').textContent === '새 게임'", timeout=15000)
        check("the empty board is what comes back", hot_page.locator(".tile").count() == 0)
        # A first screen is that empty board already: a folder brought in names it.
        first = browser.new_page(viewport={"width": 1440, "height": 900})
        first.on("pageerror", lambda e: errors.append(str(e)))
        first.on("dialog", lambda d: (asked.append(d.message), d.accept()))
        first.goto(url)
        first.wait_for_selector("#dialog[open] #tutorialImport")
        first.keyboard.press("Escape")
        check("the first screen is an empty board without asking", first.locator(".tile").count() == 0 and first.inner_text("#gameTitle") == "새 게임" and len(asked) == 1, asked)
        first.set_input_files("#importFolder", str(game))
        first.wait_for_function("document.querySelectorAll('.tile.imported').length === 4", timeout=15000)
        check("an empty board takes its name from the first folder", first.inner_text("#gameTitle") == "MyGame", first.inner_text("#gameTitle"))
        check("no page errors", not errors, errors)
        browser.close()
    api.stop()
    server.shutdown()
    failed = [n for n, ok in checks if not ok]
    print(f"{len(checks) - len(failed)}/{len(checks)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
