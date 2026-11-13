"""A folder put on an account's board by tools/board_import.py opens in the asset room of that account, in a real
browser: every sound is a tile, the sounds play, and a version made from an Akkado patch keeps the patch.

Run: python tests/e2e_board_import.py [FOLDER]  (not collected by pytest; needs playwright, Chrome and node)
Without FOLDER a small folder is written here: a spec, three WAVs, one Akkado patch.
"""
import functools
import json
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tests"))
sys.path.insert(0, str(REPO / "tools"))
from e2e_asset_sync import HOST, NAMES, ROOT, Host, write_wav  # noqa: E402
from test_asset_sync_two import SyncApi  # noqa: E402
import board_import  # noqa: E402


def small_folder(tmp: Path) -> Path:
    game = tmp / "game"
    spec = {"game": "Import test", "platform": "mobile", "style": "test",
            "categories": [{"id": "ui", "name": "UI", "kind": "sfx"}, {"id": "bgm", "name": "Music", "kind": "music"}],
            "assets": [{"id": "sfx_ui_click", "name": "click", "category": "ui", "length": 0.2, "loop": False, "description": "a click"},
                       {"id": "sfx_ui_back", "name": "back", "category": "ui", "length": 0.3, "loop": False, "description": "back"},
                       {"id": "bgm_title", "name": "title", "category": "bgm", "length": None, "loop": True, "description": "a loop"}]}
    game.mkdir(parents=True)
    (game / "sound_spec.json").write_text(json.dumps(spec), encoding="utf-8")
    (game / "_src").mkdir()
    (game / "_src" / "report.json").write_text("{}", encoding="utf-8")  # a second json that is not the spec
    write_wav(game / "sfx_ui_click.wav", 0.2, 1500)
    write_wav(game / "sfx_ui_back.wav", 0.3, 600)
    write_wav(game / "bgm_title.wav", 2.0, 220)
    (game / "_src" / "sfx_ui_click.akkado").write_text("// seconds: 0.2\nsine(1500) * ar(trigger(1), 0.001, 0.1) |> out(@)\n", encoding="utf-8")
    return game


def main():
    tmp = Path(tempfile.mkdtemp())
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else small_folder(tmp)
    made = board_import.records_of(str(folder))
    want = [r[2]["id"] for r in made["records"] if r[0] == "asset"]
    patched = [r[2]["id"] for r in made["records"] if r[0] == "asset" and r[2]["versions"] and r[2]["versions"][0]["engine"] == "nkido"]

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Host, directory=str(ROOT.parent)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    api = SyncApi(tmp / "api", origin)
    Host.page = (HOST % json.dumps({"type": "asset:token", "token": api.token(), "ttl": 900, "api": api.base})).encode()
    board, written, bad = board_import.put(api.boards, api.sub, made, home=True)
    checks, errors = [], []

    def check(name, ok, detail=""):
        checks.append(bool(ok))
        print(("PASS " if ok else "FAIL ") + name + (f"  {detail}" if not ok and detail else ""), flush=True)

    check("every record was written", not bad and written == len(made["records"]), bad[:3])
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{origin}/e2e-host.html")
            page.wait_for_selector("#room")
            room = next(f for f in page.frames if f.parent_frame is page.main_frame)
            room.wait_for_function(f"localStorage.getItem('asset-sync.who') === '{api.who}'", timeout=30000)
            try:
                room.wait_for_function("(n) => document.querySelectorAll('#board .tile').length >= n", arg=len(want), timeout=60000)
            except Exception:
                pass
            room = next(f for f in page.frames if f.parent_frame is page.main_frame)
            shown = dict(room.evaluate(NAMES))
            check(f"all {len(want)} sounds are tiles", set(want) <= set(shown), sorted(set(want) - set(shown))[:5])
            check("the board has the spec's game name", room.inner_text("#gameTitle").strip() == made["game"], room.inner_text("#gameTitle"))
            # Every version's bytes come from the board store and decode: the page plays each kept sound.
            played = room.evaluate("""async (ids) => {
                const out = {};
                for (const id of ids) {
                  const t = document.querySelector(`#board .tile[data-id='${id}']`);
                  out[id] = !!t && t.dataset.status === 'approved' && !!t.querySelector('canvas');
                }
                return out;
            }""", want)
            check("every tile draws its sound", all(played.values()), [k for k, v in played.items() if not v][:5])
            if patched:
                sid = patched[0]
                room.focus(f".tile[data-id='{sid}']")
                page.keyboard.press("Enter")
                room.wait_for_selector(".dName", state="visible", timeout=10000)
                room.get_by_role("tab", name="코드").click()
                room.wait_for_selector(".codeView", timeout=10000)
                code = room.inner_text(".codeView")
                source = next(r[2]["versions"][0]["source"] for r in made["records"] if r[0] == "asset" and r[2]["id"] == sid)
                first = next(line for line in source.splitlines() if line.strip())
                check("a patched sound shows its Akkado patch in the code tab", first.strip() in code, code[:200])
            # The same folder dropped on the page by hand (no account): the spec is found among other .json files and
            # the Akkado patches come along as the versions' source.
            local = browser.new_page(viewport={"width": 1440, "height": 900})
            local.on("pageerror", lambda e: errors.append("local: " + str(e)))
            local.goto(f"{origin}/asset_studio/index.html?lang=ko")
            local.wait_for_selector("#tour")  # the guide of a first visit, put away
            local.keyboard.press("Escape")
            local.set_input_files("#importFolder", str(folder))
            try:
                local.wait_for_function("(n) => document.querySelectorAll('#board .tile').length >= n", arg=len(want), timeout=60000)
            except Exception:
                pass
            check("the folder opens as a bundle on the page", local.locator("#board .tile").count() == len(want) and local.inner_text("#gameTitle").strip() == made["game"],
                  [local.locator("#board .tile").count(), local.inner_text("#gameTitle")])
            if patched:
                sid = patched[0]
                local.focus(f".tile[data-id='{sid}']")
                local.keyboard.press("Enter")
                local.wait_for_selector(".dName", state="visible", timeout=10000)
                local.get_by_role("tab", name="코드").click()
                local.wait_for_selector(".codeView", timeout=10000)
                check("the dropped folder keeps the Akkado patch as the source", first.strip() in local.inner_text(".codeView"), local.inner_text(".codeView")[:200])
            # --into: a board made from the same list with no sounds yet is open on a page of the account; filling it
            # puts every sound on that page without a reload, approved.
            api2 = SyncApi(tmp / "api2", origin, email="fill@test.example")
            try:
                bare = dict(made, records=[[k, u, dict(d, versions=[], cur=None, status="pending")] if k == "asset" else [k, u, d] for k, u, d in made["records"]], blobs=[])
                board2, _, bad2 = board_import.put(api2.boards, api2.sub, bare, home=True)
                Host.page = (HOST % json.dumps({"type": "asset:token", "token": api2.token(), "ttl": 900, "api": api2.base})).encode()
                ctx = browser.new_context(viewport={"width": 1440, "height": 900})
                fp = ctx.new_page()
                fp.on("pageerror", lambda e: errors.append("fill: " + str(e)))
                fp.goto(f"{origin}/e2e-host.html")
                fp.wait_for_selector("#room")
                fr = next(f for f in fp.frames if f.parent_frame is fp.main_frame)
                fr.wait_for_function(f"localStorage.getItem('asset-sync.who') === '{api2.who}'", timeout=30000)
                fr.wait_for_function("(n) => document.querySelectorAll('#board .tile').length >= n", arg=len(want), timeout=60000)
                fr = next(f for f in fp.frames if f.parent_frame is fp.main_frame)
                check("the bare board opens with every sound waiting", fr.locator("#board .tile[data-status='pending']").count() == len(want))
                written2, bad3, skipped = board_import.fill(api2.boards, api2.sub, board2, made)
                check("filling writes every sound", not bad2 and not bad3 and written2 == len(want) and not skipped, [bad3[:2], skipped[:2]])
                try:
                    fr.wait_for_function("(n) => document.querySelectorAll(\"#board .tile[data-status='approved'] canvas\").length >= n", arg=len(want), timeout=60000)
                except Exception:
                    pass
                check("the open page shows the filled sounds without a reload", fr.locator("#board .tile[data-status='approved'] canvas").count() == len(want),
                      fr.locator("#board .tile[data-status='approved']").count())
                again = board_import.fill(api2.boards, api2.sub, board2, made)
                check("filling twice adds nothing", again[0] == 0 and len(again[2]) == len(want), again[:2])
                ctx.close()
            finally:
                api2.stop()
            check("no page errors", not errors, errors[:3])
        finally:
            browser.close()
            api.stop()
            server.shutdown()
    print(f"{sum(checks)}/{len(checks)} checks passed")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
