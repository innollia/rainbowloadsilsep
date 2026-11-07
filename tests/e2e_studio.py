"""Real-browser scenario against a local stand-in for the Gemini HTTP API.

Run: python tests/e2e_studio.py  (not collected by pytest; needs playwright and Chrome)
Proves the wiring from the chat box to real sound and back. It does not prove Gemini's
music judgement, which needs a real key.
"""
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
PORT, FAKE = 8799, 8798
calls = {"edit": 0, "listen": 0, "audio_bytes": 0}


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        parts = body["contents"][0]["parts"]
        if "inlineData" in parts[0]:
            calls["listen"] += 1
            calls["audio_bytes"] = len(parts[0]["inlineData"]["data"])
            done = calls["listen"] >= 2
            reply = {"heard": "드럼과 베이스가 들림", "problems": [] if done else ["베이스가 약함"],
                     "score": 50 + calls["listen"], "goal_met": done, "next_instruction": "베이스를 키워"}
        else:
            calls["edit"] += 1
            code = "note(\"c2 g1\").s(\"sawtooth\")" if calls["edit"] != 2 else "this is ( broken"
            reply = {"summary": f"베이스 수정 {calls['edit']}", "bpm": 120,
                     "changes": [{"id": "bass", "name": "베이스", "role": "bass", "code": code, "remove": False}]}
        out = {"candidates": [{"content": {"parts": [{"text": json.dumps(reply, ensure_ascii=False)}]}}]}
        self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(out).encode())

    def log_message(self, *a):
        pass


server = ThreadingHTTPServer(("127.0.0.1", FAKE), Fake)
threading.Thread(target=server.serve_forever, daemon=True).start()
env = {**os.environ, "GEMINI_API_KEY": "test-key", "GEMINI_BASE_URL": f"http://127.0.0.1:{FAKE}", "STRUDEL_LOCAL_AI": "1"}
app = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(PORT), "--server.headless", "true"],
                       cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/_stcore/health"); break
        except OSError:
            time.sleep(0.5)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.goto(f"http://127.0.0.1:{PORT}")
        frame = page.frame_locator('iframe[title*="studio"]')
        frame.locator("#play").wait_for(timeout=30000)
        inner = next(f for f in page.frames if "studio_frontend" in f.url or "component" in f.url)
        inner.wait_for_function("document.querySelectorAll('iframe').length===2", timeout=20000)
        boots = inner.evaluate("window.__marker=1")
        time.sleep(4)
        frame.locator("#play").click()
        inner.wait_for_function("document.getElementById('clock').textContent!=='00:00'", timeout=15000)
        spin = "document.querySelector('#art circle').getAttribute('transform')"
        first = inner.evaluate(spin); time.sleep(0.5); art_moves = bool(first) and inner.evaluate(spin) != first
        frame.locator('.track button.pick').nth(1).click()
        frame.locator("#autoBtn").click()
        frame.locator("#ask").fill("베이스만 더 세게")
        frame.locator("#ask").press("Enter")
        inner.wait_for_function("document.querySelector('.msg.status')&&/목표/.test(document.getElementById('log').textContent)", timeout=90000)
        log = inner.evaluate("[...document.querySelectorAll('.msg')].map(m=>m.className+': '+m.textContent)")
        stored = inner.evaluate("JSON.parse(localStorage.getItem('strudel-ddalkkak-v1')).projects[0]")
        page.screenshot(path=str(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts-e2e.png"))
        same_iframe = inner.evaluate("window.__marker") == 1
        frame.locator("#settingsBtn").click()
        frame.get_by_role("button", name="게임하기").click()
        page.get_by_text("음악 작업실로 돌아가기").wait_for(timeout=15000)
    print("\n".join(log))
    checks = {
        "iframe kept across reruns": same_iframe,
        "two heard reports": sum("heard" in x for x in log) == 2,
        "broken code fixed": calls["edit"] == 3,
        "drums untouched": stored["tracks"][0]["code"].startswith("stack(s(\"bd*4\")"),
        "versions saved": len(stored["versions"]) >= 3,
        "real audio sent": calls["audio_bytes"] > 1_000_000,
        "signal not silent": not any("소리가 거의 없음" in x for x in log),
        "no clipping": not any("클리핑" in x for x in log),
        "no page errors": not errors,
        "art follows playback": art_moves,
    }
    print(calls, errors[:3])
    for name, ok in checks.items():
        print("PASS" if ok else "FAIL", name)
    sys.exit(0 if all(checks.values()) else 1)
finally:
    app.terminate()
