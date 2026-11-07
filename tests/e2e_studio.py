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
        inner.wait_for_function("document.querySelectorAll('iframe[sandbox]').length===2", timeout=20000)
        boots = inner.evaluate("window.__marker=1")
        time.sleep(4)
        frame.locator("#play").click()
        inner.wait_for_function("document.getElementById('clock').textContent!=='00:00'", timeout=15000)
        spin = "document.querySelector('#art [data-spin],#art [data-flow],#art [data-pulse]').getAttribute('transform')"
        first = inner.evaluate(spin); time.sleep(0.5); art_moves = bool(first) and inner.evaluate(spin) != first
        frame.locator('.track button.pick').nth(1).click()
        frame.locator("#autoRounds").fill("3")
        frame.locator("#ask").fill("베이스만 더 세게")
        frame.locator("#ask").press("Enter")
        inner.wait_for_function("document.querySelector('.msg.status')&&/목표/.test(document.getElementById('log').textContent)", timeout=90000)
        log = inner.evaluate("[...document.querySelectorAll('.msg')].map(m=>m.className+': '+m.textContent)")
        stored = inner.evaluate("JSON.parse(localStorage.getItem('strudel-ddalkkak-v1')).projects[0]")
        page.screenshot(path=str(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts-e2e.png"))
        same_iframe = inner.evaluate("window.__marker") == 1
        # code editor: find it, break it, fix it, and confirm the song really changed
        frame.locator("#codeBtn").click()
        inner.wait_for_selector("#codeHost .cm-content", timeout=15000)
        code_visible = frame.locator("#codeHost .cm-content").is_visible() and not frame.locator("#tracks").is_visible()
        put = "t=>document.querySelector('#codeHost .cm-content').cmView?.view"
        def set_code(text):
            frame.locator("#codeHost .cm-content").click()
            page.keyboard.press("Control+a"); page.keyboard.press("Delete")
            page.keyboard.insert_text(text)
        before = inner.evaluate("JSON.parse(localStorage.getItem('strudel-ddalkkak-v1')).projects[0].versions.length")
        set_code('setcpm(90/4)\n\n$drums: s("bd*2")\n\n$bass: note("c2").oops(\n')
        page.keyboard.press("Control+Enter")
        inner.wait_for_function("/실행 실패/.test(document.getElementById('codeNote').textContent)", timeout=20000)
        bad_note = inner.evaluate("document.getElementById('codeNote').textContent")
        error_marked = inner.evaluate("document.querySelector('#codeHost .cm-errorLine')?.textContent || ''")
        set_code('// 내 메모\nsetcpm(90/4)\n\n$drums: s("bd*2") // 킥\n\n$bass: note("c2 eb2").s("sawtooth")\n')
        page.keyboard.press("Control+Enter")
        inner.wait_for_function("document.getElementById('codeNote').textContent==='적용했어.'", timeout=20000)
        time.sleep(1)
        edited = inner.evaluate("JSON.parse(localStorage.getItem('strudel-ddalkkak-v1')).projects[0]")
        head_kept = edited.get("head") == "// 내 메모"
        complete = inner.evaluate("""() => { const e = window.studioEditor(), put = (t) => { e.set(t); return t.length; };
          const labels = (t) => (e.completionsAt(put(t))?.options || []).map(o => o.label);
          const m = labels('s("bd").'), sound = labels('s("b'), top = labels('st');
          const out = { method: m.includes('gain'), noInternal: !m.includes('queryArc'), sound: sound.includes('bd'), top: top.includes('stack') };
          e.set(''); return out; }""")
        set_code('// 앞 메모\n$: s("bd*4")\n// 베이스 메모\n$: note("c2").s("sawtooth")\n')
        page.keyboard.press("Control+Enter")
        inner.wait_for_function("window.studioEditor().text().includes('$t2:')", timeout=20000)
        time.sleep(1)
        anon = inner.evaluate("JSON.parse(localStorage.getItem('strudel-ddalkkak-v1')).projects[0]")
        anon_text = inner.evaluate("window.studioEditor().text()")
        trip = inner.evaluate("""() => { const c = window.songCode, prev = {bpm: 120, tracks: []};
          const song = {bpm: 100, tracks: [{id:'a',name:'a',role:'other',code:'s("bd")'},{id:'b',name:'b',role:'other',code:'stack(\\n s("hh")\\n)'}]};
          const back = c.parseSong(c.songText(song), prev);
          return { same: JSON.stringify(back.tracks.map(t=>t.code)) === JSON.stringify(song.tracks.map(t=>t.code)) && back.bpm === 100,
                   tempo: c.parseSong('setcps(0.5)\\n$a: s("bd")', prev).bpm === 120, plainOk: c.parseSong('s("bd")', prev).tracks[0].raw === true }; }""")
        frame.locator("#codeBtn").click()
        tracks_before = inner.evaluate("JSON.stringify(JSON.parse(localStorage.getItem('strudel-ddalkkak-v1')).projects[0].tracks)")
        frame.locator("#tracks .mute").first.click()
        frame.locator("#projectBtn").click()
        hear = frame.locator("#dialog").get_by_role("button", name="듣기", exact=True).first
        hear.click()
        frame.locator("#dialog").get_by_role("button", name="정지", exact=True).wait_for(timeout=10000)
        time.sleep(.3)
        frame.locator("#dialog").get_by_role("button", name="닫기").click()
        time.sleep(1)
        audition_ok = inner.evaluate("JSON.stringify(JSON.parse(localStorage.getItem('strudel-ddalkkak-v1')).projects[0].tracks)") == tracks_before
        frame.locator("#tracks .mute").first.click()
        frame.locator("#allMute").click()
        all_off = inner.evaluate("[...document.querySelectorAll('#tracks .mute')].every(b => b.getAttribute('aria-pressed') === 'true')")
        frame.locator("#allMute").click()
        all_on = inner.evaluate("[...document.querySelectorAll('#tracks .mute')].every(b => b.getAttribute('aria-pressed') === 'false')")
        seed = lambda: inner.evaluate("document.getElementById('art').innerHTML")
        art_before = seed()
        frame.locator("#art").click()
        art_clicked = seed() != art_before
        box = frame.locator("#art").bounding_box()
        page.mouse.move(box["x"] + 50, box["y"] + 50); page.mouse.down(); time.sleep(.7); page.mouse.up()
        history_count = frame.locator(".shelf .lp").count()
        page.keyboard.press("Escape")
        time.sleep(.2)
        outside_closed = frame.locator(".shelf").count() == 0
        frame.locator("#bpmUp").click(); frame.locator("#bpmUp").click()
        time.sleep(1.2)
        bpm_step = inner.evaluate("(() => { const p = JSON.parse(localStorage.getItem('strudel-ddalkkak-v1')).projects[0]; return [p.bpm, p.versions[p.versions.length-1].summary]; })()")
        frame.locator("#tabScore").click()
        frame.locator(".score-paper svg").first.wait_for(timeout=20000)
        score_notes = inner.evaluate("document.querySelectorAll('.score-paper svg path').length")
        frame.locator("#tabTracks").click()
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
        "code editor opens from header": code_visible,
        "bad code names track and line": "베이스 5번째 줄" in bad_note and edited["bpm"] == 90,
        "error line highlighted": "oops" in error_marked,
        "head comment kept": head_kept,
        "autocomplete": all(complete.values()),
        "unnamed tracks split": [t["id"] for t in anon["tracks"]] == ["t1", "t2"] and "베이스 메모" in anon_text,
        "edited code applied as version": len(edited["versions"]) == before + 1 and edited["tracks"][0]["code"].endswith("// 킥"),
        "text round trip": all(trip.values()),
        "art follows playback": art_moves,
        "version audition leaves project alone": audition_ok,
        "score tab renders notes": score_notes > 50,
        "all tracks toggle": all_off and all_on,
        "cover click changes art": art_clicked,
        "cover long press shows history": history_count >= 2,
        "backdrop click closes dialog": outside_closed,
        "bpm steps by ten as one version": bpm_step[1] == f"BPM {bpm_step[0]}",
    }
    print(calls, errors[:3])
    for name, ok in checks.items():
        print("PASS" if ok else "FAIL", name)
    sys.exit(0 if all(checks.values()) else 1)
finally:
    app.terminate()
