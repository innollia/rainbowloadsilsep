"""Real-browser check of bringing existing work into the game sound asset board.

Run: python tests/e2e_asset_import.py  (not collected by pytest; needs playwright and Chrome)
A first-time visitor who already has work: a folder of sounds, a list of needed sounds,
drafts in the feel of a brought-in sound, then export and re-open the bundle in a fresh browser.
"""
import functools
import json
import math
import struct
import sys
import tempfile
import threading
import wave
import zipfile
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent / "studio_frontend" / "asset_studio"


def write_wav(path, seconds, freq, noise=0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    rate, n = 22050, int(22050 * seconds)
    frames = b"".join(struct.pack("<h", int(12000 * (math.sin(2 * math.pi * freq * i / rate) * (1 - noise) + noise * math.sin(i * i % 7919))))
                      for i in range(n))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(frames)


class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


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

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(ROOT)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html?lang=ko"
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

        # First visit: the tutorial opens and offers Import; the header and board offer it too.
        page.wait_for_selector("#dialog[open] #tutorialImport")
        check("first screen offers import", page.is_visible("#importBtn") and page.is_visible(".importHint"))
        page.click("#tutorialImport")
        page.wait_for_selector("#dialog[open] #pickFolder")

        # A whole folder of sounds.
        page.set_input_files("#importFolder", str(game))
        page.wait_for_function("document.querySelectorAll('.tile.imported').length === 4", timeout=15000)
        check("game name taken from the folder", page.inner_text("#gameTitle") == "MyGame", page.inner_text("#gameTitle"))
        g = groups(page)
        check("categories guessed from names", "Sword swing 01" in g.get("전투", []) and "Btn press" in g.get("UI", []) and "Forest loop" in g.get("환경", []), json.dumps(g, ensure_ascii=False))
        check("brought-in mark on tiles", page.locator(".tile.imported .origin").first.inner_text() == "직접 가져옴")
        check("demo board left", page.locator(".tile").count() == 4)
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
        page.click("#fillBtn")
        page.wait_for_function("!document.querySelector('.tile[data-status=pending]') && !document.querySelector('.tile[data-status=working]')", timeout=15000)
        check("slots filled", page.locator(".tile[data-status=draft]").count() == 3)

        # A reload (or closing the tab, or going to the game) loses nothing: the board is saved as it changes.
        page.wait_for_timeout(1200)
        page.reload()
        page.wait_for_function("document.querySelectorAll('.tile').length === 7", timeout=15000)
        g = groups(page)
        check("board survives a reload", page.inner_text("#gameTitle") == "MyGame" and "버튼 누름" in g.get("UI", [])
              and page.locator(".tile.imported").count() == 4 and page.locator(".tile[data-status=draft]").count() == 3, json.dumps(g, ensure_ascii=False))
        check("reload opens no tutorial again", not page.is_visible("#dialog[open]"))

        # Drafts in the feel of a brought-in sound: the prompt carries its measurements.
        page.locator(".tile.imported", has_text="Sword swing 01").focus()
        page.keyboard.press("Enter")
        page.wait_for_selector("#likeThis")
        page.click("#likeThis")
        page.wait_for_function("[...document.querySelectorAll('.tile .name')].some((n) => n.textContent.includes('느낌')) && !document.querySelector('.tile[data-status=working]')", timeout=15000)
        page.locator(".tile", has_text="느낌").focus()
        page.keyboard.press("Enter")
        page.get_by_role("tab", name="코드").click()
        prompt = page.inner_text("#promptText")
        check("prompt carries reference measurements", all(k in prompt for k in ("기준 소리", "LUFS", "저역", "Sword_Swing_01.wav")), prompt)
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
        check("no page errors", not errors, errors)
        browser.close()
    server.shutdown()
    failed = [n for n, ok in checks if not ok]
    print(f"{len(checks) - len(failed)}/{len(checks)} passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
