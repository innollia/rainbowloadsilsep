import base64
import io
import json
import struct
import threading
import time
import wave
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import studio_backend as sb

TRACKS = [
    {"id": "drums", "name": "드럼", "role": "drums", "code": 's("bd*4")'},
    {"id": "bass", "name": "베이스", "role": "bass", "code": 'note("c2")'},
]


def wav(amplitude=8000, seconds=1):
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(48000)
        n = 48000 * seconds
        w.writeframes(b"".join(struct.pack("<hh", amplitude if i % 100 < 50 else -amplitude, 0) for i in range(n)))
    return out.getvalue()


def request(**kw):
    return sb.validate_request({"text": "베이스만", "tracks": TRACKS, "bpm": 120, **kw})


def change(tid="bass", code='note("g1")'):
    return {"id": tid, "name": tid, "role": "bass", "code": code, "remove": False}


class Fake:
    def __init__(self, edits=None, verdicts=None):
        self.edits, self.verdicts = list(edits or []), list(verdicts or [])
        self.edit_calls, self.listen_calls = 0, 0

    def edit(self, prompt):
        self.edit_calls += 1
        self.last_prompt = prompt
        if self.edits:
            return self.edits.pop(0)
        return {"summary": "수정", "bpm": 120, "changes": [change()]}

    def listen(self, data, prompt):
        self.listen_calls += 1
        if self.verdicts:
            v = self.verdicts.pop(0)
            if isinstance(v, Exception):
                raise v
            return v
        return {"heard": "들림", "problems": ["약함"], "score": self.listen_calls * 10, "goal_met": False, "next_instruction": "더"}


def drive(jobs, owner="o", respond=None, timeout=10):
    """Plays the browser: answers each new candidate until the job ends."""
    seen = 0
    end = time.time() + timeout
    while time.time() < end:
        snap = jobs.snapshot(owner)
        if snap["status"] != "running":
            return snap
        cand = snap["candidate"]
        if cand and cand["seq"] > seen:
            seen = cand["seq"]
            answer = (respond or (lambda c: {"ok": True, "wav": base64.b64encode(wav()).decode(), "span": "00:00–00:01"}))(cand)
            jobs.feedback(owner, {"job_id": snap["id"], "seq": cand["seq"], **answer})
        time.sleep(0.005)
    raise AssertionError("job did not finish")


def test_music_skill_reaches_system_and_its_absence_is_harmless(tmp_path, monkeypatch):
    skill = sb.load_skill()
    assert "## Mixing" in skill and sb.SYSTEM == f"{sb.BASE_SYSTEM}\n\n{skill}"
    assert sb.with_skill(sb.BASE_SYSTEM, "") == sb.BASE_SYSTEM
    monkeypatch.setattr(sb, "__file__", str(tmp_path / "studio_backend.py"))
    assert sb.load_skill() == ""


def test_named_track_change_leaves_others_identical():
    out = sb.merge_candidate({"tracks": request()["tracks"], "bpm": 120}, {"summary": "", "bpm": 120, "changes": [change()]}, None)
    assert out["tracks"][0]["code"] == TRACKS[0]["code"]
    assert out["tracks"][1]["code"] == 'note("g1")'


def test_target_rejects_other_track_and_bpm():
    base = {"tracks": request()["tracks"], "bpm": 120}
    with pytest.raises(ValueError):
        sb.merge_candidate(base, {"bpm": 120, "changes": [change("drums")]}, "bass")
    with pytest.raises(ValueError):
        sb.merge_candidate(base, {"bpm": 140, "changes": [change()]}, "bass")


def test_global_statement_in_track_rejected():
    base = {"tracks": request()["tracks"], "bpm": 120}
    with pytest.raises(ValueError):
        sb.merge_candidate(base, {"bpm": 120, "changes": [change(code="setcpm(60)")]}, None)


@pytest.mark.parametrize("bad", [{"text": ""}, {"bpm": 9999}, {"bpm": True}, {"target": "nope"}, {"tracks": "x"}])
def test_invalid_requests(bad):
    with pytest.raises(ValueError):
        request(**bad)


def test_manual_edit_finishes_without_listening():
    fake = Fake(); jobs = sb.Jobs(fake)
    jobs.submit("o", request())
    snap = drive(jobs)
    assert snap["status"] == "done" and fake.listen_calls == 0


def test_runtime_error_is_sent_back_then_limited():
    fake = Fake(); jobs = sb.Jobs(fake)
    jobs.submit("o", request())
    snap = drive(jobs, respond=lambda c: {"ok": False, "error": "boom"})
    assert snap["status"] == "failed" and fake.edit_calls == 3
    assert "boom" in fake.last_prompt


def test_loop_stops_at_three_rounds():
    fake = Fake(); jobs = sb.Jobs(fake)
    jobs.submit("o", request(auto=True))
    snap = drive(jobs)
    assert snap["status"] == "limit" and fake.listen_calls == 3 and fake.edit_calls == 3


def test_loop_stops_on_goal():
    fake = Fake(verdicts=[{"heard": "좋음", "problems": [], "score": 90, "goal_met": True, "next_instruction": ""}])
    jobs = sb.Jobs(fake)
    jobs.submit("o", request(auto=True))
    assert drive(jobs)["status"] == "done" and fake.listen_calls == 1


def test_no_heard_claim_when_audio_model_fails():
    fake = Fake(verdicts=[sb.ModelError("실패")]); jobs = sb.Jobs(fake)
    jobs.submit("o", request(auto=True))
    snap = drive(jobs)
    assert snap["status"] == "failed"
    assert not [m for m in snap["messages"] if m["kind"] == "heard"]
    assert any(m["kind"] == "signal" for m in snap["messages"])


def test_missing_capture_stops_without_model_call():
    fake = Fake(); jobs = sb.Jobs(fake)
    jobs.submit("o", request(auto=True))
    snap = drive(jobs, respond=lambda c: {"ok": True, "wav": ""})
    assert snap["status"] == "failed" and fake.listen_calls == 0


def test_cancel_stops_and_ignores_late_result():
    fake = Fake(); jobs = sb.Jobs(fake)
    jobs.submit("o", request(auto=True))
    while not jobs.snapshot("o")["candidate"]:
        time.sleep(0.005)
    snap = jobs.snapshot("o")
    jobs.cancel("o")
    jobs.feedback("o", {"job_id": snap["id"], "seq": 1, "ok": True})
    time.sleep(0.05)
    assert jobs.snapshot("o")["status"] == "cancelled" and fake.edit_calls == 1


def test_daily_limit_blocks_calls():
    fake = Fake(); jobs = sb.Jobs(fake, teacher_limit=0)
    jobs.submit("o", request())
    assert drive(jobs)["status"] == "limit" and fake.edit_calls == 0


def _member(email, **kw):
    req = request(**kw)
    req["account"] = email
    return req


def test_each_account_has_its_own_daily_limit_under_a_shared_ceiling():
    fake = Fake()
    jobs = sb.Jobs(fake, daily_limit=3, account_limit=2, teacher_limit=10, session_limit=10)
    for i in range(3):
        jobs.submit("acct:a", _member("a@example.com", lang="ko"))
        snap = drive(jobs, "acct:a")
    assert snap["status"] == "limit" and "2회" in snap["messages"][-1]["text"]
    assert jobs.calls_left("a@example.com") == 0 and jobs.calls_left("b@example.com") == 1
    jobs.submit("acct:b", _member("b@example.com"))
    assert drive(jobs, "acct:b")["status"] == "done"
    jobs.submit("acct:c", _member("c@example.com"))  # the ceiling for all accounts (3) is used up
    assert drive(jobs, "acct:c")["status"] == "limit"
    jobs.submit("teacher-1", request())  # password sessions are a separate pool
    assert drive(jobs, "teacher-1")["status"] == "done"
    assert fake.edit_calls == 4


def test_a_password_session_has_its_own_cap():
    jobs = sb.Jobs(Fake(), teacher_limit=10, session_limit=1)
    jobs.submit("s1", request()); drive(jobs, "s1")
    jobs.submit("s1", request())
    assert drive(jobs, "s1")["status"] == "limit"
    assert jobs.calls_left(owner="s1") == 0 and jobs.calls_left(owner="s2") == 1
    jobs.submit("s2", request())
    assert drive(jobs, "s2")["status"] == "done"
    assert sb.Jobs(Fake()).calls_left(owner="x") is None


def test_project_id_is_echoed_so_the_result_lands_on_its_song():
    assert request(project_id="p-123")["project_id"] == "p-123"
    assert request(project_id="x" * 65)["project_id"] == "" and request(project_id=5)["project_id"] == ""
    assert request()["project_id"] == ""
    jobs = sb.Jobs(Fake())
    jobs.submit("o", request(project_id="song-7"))
    assert jobs.snapshot("o")["project_id"] == "song-7" and drive(jobs)["project_id"] == "song-7"


def test_a_new_session_of_the_same_account_takes_over_the_running_job():
    ledger = LocalLedger()
    jobs = sb.Jobs(Fake(), ledger=ledger, feedback_timeout=5)
    jobs.submit("acct:a@example.com", _member("a@example.com"))
    while not jobs.jobs["acct:a@example.com"].view["candidate"]:  # the first tab is gone before the result
        time.sleep(0.005)
    with pytest.raises(ValueError):
        jobs.submit("acct:a@example.com", _member("a@example.com"))  # the reloaded page sees it still running
    snap = drive(jobs, "acct:a@example.com")  # and answers its candidate
    assert snap["status"] == "done" and ledger.account("a@example.com")["credits"] == 20 - 2  # one call, unlisted model costs 2


def _wait_end(job):
    while job.view["status"] == "running":
        time.sleep(0.01)


def test_a_result_nobody_received_is_refunded():
    ledger = LocalLedger()
    jobs = sb.Jobs(Fake(), ledger=ledger, feedback_timeout=0.3)
    jobs.submit("acct:a@example.com", _member("a@example.com", lang="ko"))
    job = jobs.jobs["acct:a@example.com"]
    _wait_end(job)  # no page polls at all
    assert job.view["status"] == "failed" and "2크레딧은 돌려줬어" in job.view["messages"][-1]["text"]
    assert ledger.account("a@example.com")["credits"] == 20


def test_a_result_a_page_saw_is_not_refunded():
    ledger = LocalLedger()
    jobs = sb.Jobs(Fake(), ledger=ledger, feedback_timeout=0.3)
    jobs.submit("acct:a@example.com", _member("a@example.com"))
    job = jobs.jobs["acct:a@example.com"]
    while not job.view["candidate"]:
        time.sleep(0.005)
    jobs.snapshot("acct:a@example.com")  # a page got the candidate, then went away
    _wait_end(job)
    assert job.view["messages"][-1]["text"] == sb.msg("en", "no_browser")
    assert ledger.account("a@example.com")["credits"] == 18


def test_a_talk_reply_that_finished_unseen_waits_for_the_next_visit():
    jobs = sb.Jobs(Fake(edits=[{"intent": "talk", "reply": "hi", "summary": "", "bpm": 120, "changes": []}]))
    jobs.submit("acct:a@example.com", _member("a@example.com"))
    _wait_end(jobs.jobs["acct:a@example.com"])
    later = jobs.snapshot("acct:a@example.com")  # a later sign-in under the same account
    assert later["status"] == "done" and later["messages"][-1]["text"] == "hi"


@pytest.mark.parametrize("ua,app", [
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 KAKAOTALK 10.4.5", "KakaoTalk"),
    ("Mozilla/5.0 (Linux; Android 14; SM-S918N Build/UP1A; wv) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36 Instagram 312.0", "Instagram"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148 [FBAN/FBIOS;FBAV/440.0]", "Facebook"),
    ("Mozilla/5.0 (Linux; Android 13; Pixel 7; wv) AppleWebKit/537.36 Version/4.0 Chrome/120 Mobile Safari/537.36", "WebView"),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36", ""),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1", ""),
    (None, ""),
])
def test_in_app_browsers_are_recognised(ua, app):
    assert sb.in_app_browser(ua) == app


def test_second_request_refused_while_running():
    jobs = sb.Jobs(Fake())
    jobs.submit("o", request())
    with pytest.raises(ValueError):
        jobs.submit("o", request())
    drive(jobs)


def test_signal_report_flags_silence_and_clipping():
    assert sb.signal_report(wav(0))["silent"]
    assert any("clipping" in f for f in sb.signal_report(wav(32767))["findings"])
    assert any("클리핑" in f for f in sb.signal_report(wav(32767), "ko")["findings"])


def test_gemini_sends_audio_and_keeps_key_out_of_url_and_errors():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"], seen["key"] = self.path, self.headers["x-goog-api-key"]
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            reply = {"candidates": [{"content": {"parts": [{"text": '{"heard":"x"}'}]}}]}
            self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(reply).encode())

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.handle_request, daemon=True).start()
    client = sb.Gemini("KEY123", "m", f"http://127.0.0.1:{server.server_port}")
    assert client.listen(b"RIFF", "p") == {"heard": "x"}
    assert "KEY123" not in seen["path"] and seen["key"] == "KEY123"
    assert seen["body"]["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "audio/wav"
    assert "[redacted]" in sb.redact("bad AIza" + "x" * 30)


def test_agy_reads_structured_output_and_rejects_failure():
    ok = json.dumps({"status": "SUCCESS", "structured_output": {"summary": "x"}}).encode()
    assert sb.AgyCli.parse(ok) == {"summary": "x"}
    with pytest.raises(sb.ModelError):
        sb.AgyCli.parse(json.dumps({"status": "ERROR"}).encode())


def test_agy_verdict_is_labelled_as_measurement_not_hearing():
    fake = Fake(verdicts=[{"heard": "저음이 큼", "problems": [], "score": 90, "goal_met": True, "next_instruction": ""}])
    cli = sb.AgyCli(); cli.edit = fake.edit
    prompts = []
    cli._run = lambda prompt, schema: prompts.append(prompt) or fake.listen(b"", prompt)
    jobs = sb.Jobs(cli)
    jobs.submit("o", request(auto=True))
    snap = drive(jobs)
    assert snap["status"] == "done"
    assert not [m for m in snap["messages"] if m["kind"] == "heard"]
    assert any(m["kind"] == "measured" and "Measurement analysis" in m["text"] for m in snap["messages"])
    assert "측정 템포" in prompts[0] or "무음" in prompts[0]


def test_plain_schema_lowercases_types_only():
    assert sb.plain_schema({"type": "OBJECT", "enum": ["DRUMS"]}) == {"type": "object", "enum": ["DRUMS"]}


class FakeBlock:
    type = "text"
    def __init__(self, text):
        self.text = text


class FakeReply:
    def __init__(self, text, stop="end_turn"):
        self.content, self.stop_reason = [FakeBlock(text)], stop


class FakeClaudeClient:
    def __init__(self, reply):
        self.reply, self.calls = reply, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return self.reply


def test_claude_requests_closed_schema_and_parses_reply():
    client = FakeClaudeClient(FakeReply('{"summary":"x","bpm":120,"changes":[]}'))
    assert sb.Claude("k", client=client).edit("p")["summary"] == "x"
    call = client.calls[0]
    schema = call["output_config"]["format"]["schema"]
    assert call["model"] == "claude-sonnet-5-5" and schema["additionalProperties"] is False
    assert schema["properties"]["changes"]["items"]["additionalProperties"] is False
    assert schema["type"] == "object" and "temperature" not in call


def test_claude_refusal_and_truncation_are_errors():
    for stop in ("refusal", "max_tokens"):
        with pytest.raises(sb.ModelError):
            sb.Claude("k", client=FakeClaudeClient(FakeReply("", stop))).edit("p")


def test_claude_listen_uses_measurements_and_is_not_hearing():
    verdict = '{"heard":"저음 큼","problems":[],"score":90,"goal_met":true,"next_instruction":""}'
    client = FakeClaudeClient(FakeReply(verdict))
    model = sb.Claude("k", client=client)
    assert model.hears is False and model.listen(wav(), "p")["goal_met"] is True
    assert "측정 템포" in client.calls[0]["messages"][0]["content"]


def test_talk_turn_changes_nothing_and_replies():
    fake = Fake(edits=[{"intent": "talk", "reply": "지금 곡은 어두운 편이야.", "summary": "", "bpm": 120, "changes": []}])
    jobs = sb.Jobs(fake)
    jobs.submit("o", request(auto=True))
    snap = drive(jobs)
    assert snap["status"] == "done" and snap["candidate"] is None and fake.listen_calls == 0
    assert [m["text"] for m in snap["messages"] if m["kind"] == "reply"] == ["지금 곡은 어두운 편이야."]


def test_history_reaches_the_prompt_and_is_bounded():
    items = [{"role": "user", "text": f"말{i}"} for i in range(15)] + ["bad", {"role": "x", "text": ""}]
    clean = sb.clean_history(items)
    assert len(clean) <= sb.MAX_HISTORY and sb.clean_history("nope") == []
    prompt = sb.edit_prompt({"bpm": 120, "tracks": []}, "안녕", "", None, clean)
    assert "user: 말14" in prompt and prompt.index("Recent conversation") < prompt.index("User message:")


def test_later_rounds_keep_the_original_goal_and_earlier_tries():
    fake = Fake(); jobs = sb.Jobs(fake)
    jobs.submit("o", request(auto=True))
    drive(jobs)
    assert "베이스만" in fake.last_prompt and "round 2" in fake.last_prompt


def test_song_ends_on_the_best_scoring_round():
    verdict = lambda score: {"heard": "들림", "problems": ["약함"], "score": score, "goal_met": False, "next_instruction": "더"}
    fake = Fake(verdicts=[verdict(30), verdict(80), verdict(40)])
    fake.edits = [{"summary": str(i), "bpm": 120, "changes": [change(code=f'note("c{i}")')]} for i in range(3)]
    jobs = sb.Jobs(fake)
    jobs.submit("o", request(auto=True))
    snap = drive(jobs)
    last = snap["candidate"]
    assert snap["status"] == "limit" and last["listen"] is False
    assert any('note("c1")' in t["code"] for t in last["tracks"])


def _round(score, problems=("약함",), met=False):
    return {"heard": "들림", "problems": list(problems), "score": score, "goal_met": met, "next_instruction": "더"}


def _rounds(fake, rounds):
    fake.edits = [{"summary": str(i), "bpm": 120, "changes": [change(code=f'note("c{i}")')]} for i in range(8)]
    jobs = sb.Jobs(fake)
    jobs.submit("o", request(auto=True, rounds=rounds))
    return drive(jobs)


def test_slider_sets_how_many_more_fixes_run():
    fake = Fake(verdicts=[_round(10 + i * 10) for i in range(8)])
    snap = _rounds(fake, 5)
    assert snap["limit"] == 6 and fake.listen_calls == 6 and snap["status"] == "limit"


def test_slider_is_capped_by_python():
    fake = Fake(verdicts=[_round(10 + i * 10) for i in range(8)])
    assert _rounds(fake, 99)["limit"] == sb.MAX_ROUNDS + 1


def test_stops_as_soon_as_a_round_stops_paying():
    fake = Fake(verdicts=[_round(60), _round(61), _round(90)])
    snap = _rounds(fake, 5)
    assert fake.listen_calls == 2 and snap["status"] == "done"


def test_no_problems_left_ends_the_job_early():
    fake = Fake(verdicts=[_round(50), _round(70, problems=())])
    snap = _rounds(fake, 5)
    assert fake.listen_calls == 2 and snap["status"] == "done"


def test_good_score_ends_the_job_early():
    fake = Fake(verdicts=[_round(sb.GOOD_SCORE)])
    snap = _rounds(fake, 5)
    assert fake.listen_calls == 1 and snap["status"] == "done"


def test_browser_cannot_name_an_unlisted_model_or_effort():
    req = sb.validate_request(request(model="claude-mythos", effort="max"))
    assert req["model"] == "" and req["effort"] == ""


def test_router_builds_the_engine_the_request_picked():
    router = sb.Router(gemini_key="g", claude_key="c")
    engine = router.engine("claude-opus-5-5", "high")
    assert isinstance(engine, sb.Claude) and engine.model == "claude-opus-5-5" and engine.effort == "high"
    assert isinstance(router.engine("gemini-3.8-flash", "low"), sb.Gemini)


def test_router_only_offers_models_it_has_a_key_for():
    router = sb.Router(claude_key="c")
    assert [m["id"] for m in router.choices()["models"]] == ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"]
    assert isinstance(router.engine("gemini-3.8-flash", ""), sb.Claude)


def test_effort_reaches_claude():
    seen = {}

    class Messages:
        def create(self, **kw):
            seen.update(kw)
            block = type("B", (), {"type": "text", "text": '{"intent":"talk","reply":"hi"}'})
            return type("R", (), {"stop_reason": "end_turn", "content": [block]})

    client = type("C", (), {"messages": Messages()})
    sb.Claude("k", "claude-opus-5-5", client, "high").edit("p")
    assert seen["model"] == "claude-opus-5-5" and seen["output_config"]["effort"] == "high"


from credits import LocalLedger  # noqa: E402


def test_local_ledger_finds_a_payment_by_payer_email_amount_and_date():
    ledger = LocalLedger()
    ledger.hold("bmc@example.com", "3", "2026-11-01", 60)
    assert ledger.find_payment("me@example.com", "bmc@example.com", "4", "2026-11-01")["found"] == 0
    assert ledger.find_payment("me@example.com", "bmc@example.com", "3", "2026-11-02") == {
        "found": 1, "added": 60, "credits": 80, "too_many": False}
    assert ledger.find_payment("me@example.com", "bmc@example.com", "3", "2026-11-01")["found"] == 0
    with pytest.raises(ValueError):
        ledger.find_payment("me@example.com", "bmc@example.com", "x", "2026-11-01")


def _paid(fake, ledger, **kw):
    jobs = sb.Jobs(fake, ledger=ledger)
    req = sb.validate_request(request(**kw))
    req["account"] = "a@example.com"
    jobs.submit("o", req)
    return drive(jobs)


def test_each_call_is_charged_at_its_model_price():
    ledger = LocalLedger()
    snap = _paid(Fake(verdicts=[_round(90, problems=())]), ledger, auto=True, rounds=2, model="claude-opus-5-5", effort="high")
    assert snap["status"] == "done" and snap["credits"] == 20 - 2 * 4 and ledger.account("a@example.com")["credits"] == 12


def test_out_of_credits_stops_before_the_call():
    ledger = LocalLedger(free=1)
    fake = Fake()
    snap = _paid(fake, ledger, model="claude-opus-5-5")
    assert snap["status"] == "limit" and fake.edit_calls == 0


def test_a_failed_call_costs_nothing():
    ledger = LocalLedger()
    fake = Fake(verdicts=[sb.ModelError("boom")])
    snap = _paid(fake, ledger, auto=True, model="claude-sonnet-5-5")
    assert snap["status"] == "failed"
    assert ledger.account("a@example.com")["credits"] == 20 - 1
    assert [h["kind"] for h in ledger.history("a@example.com")][:2] == ["refund", "charge"]


def test_teacher_requests_are_not_charged():
    ledger = LocalLedger()
    jobs = sb.Jobs(Fake(), ledger=ledger)
    jobs.submit("o", sb.validate_request(request()))
    drive(jobs)
    assert ledger.history("x@example.com") == []


def test_lang_picks_message_language_and_falls_back_to_english():
    assert request()["lang"] == "en" and request(lang="xx")["lang"] == "en" and request(lang="ko")["lang"] == "ko"
    with pytest.raises(ValueError, match="BPM must be"):
        request(bpm=9999)
    with pytest.raises(ValueError, match="BPM은"):
        request(bpm=9999, lang="ko")
    for lang, done in (("en", "Updated."), ("ko", "수정했어.")):
        fake = Fake(edits=[{"summary": "", "bpm": 120, "changes": [change()]}])
        jobs = sb.Jobs(fake)
        jobs.submit("o", request(lang=lang))
        assert [m["text"] for m in drive(jobs)["messages"]] == [done]
        assert fake.last_prompt.endswith(sb.MSG[lang]["reply_lang"])
    assert "Korean" not in sb.BASE_SYSTEM  # the reply language comes only from reply_lang
    fake = Fake(); jobs = sb.Jobs(fake)
    jobs.submit("o", request(auto=True, lang="ko"))
    while not jobs.snapshot("o")["candidate"]:
        time.sleep(0.005)
    jobs.cancel("o")
    assert jobs.snapshot("o")["messages"][-1]["text"] == "중단했어. 마지막 정상 버전을 유지해."
    assert sb.ModelError("claude_key").text("ko") == "Claude 키를 확인해 줘." and str(sb.ModelError("x")) == "x"


def test_browser_cannot_charge_someone_else():
    assert "account" not in sb.validate_request(request(account="victim@example.com"))


def openrouter_server(status=200, reply=None, finish="stop", content=None, seen=None):
    """A stand-in for https://openrouter.ai/api/v1 that answers one request."""
    seen = {} if seen is None else seen

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            seen["path"], seen["auth"] = self.path, self.headers["Authorization"]
            seen["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            text = content if content is not None else json.dumps(reply or {"summary": "x", "changes": []})
            out = {"id": "gen-1", "model": seen["body"]["model"], "provider": "P",
                   "choices": [{"finish_reason": finish, "message": {"content": text}}],
                   "usage": {"prompt_tokens": 100, "completion_tokens": 50, "cost": 0.0012,
                             "completion_tokens_details": {"reasoning_tokens": 20}}}
            body = json.dumps(out if status == 200 else {"error": {"message": "no sk-or-v1-abcdefabcdef123 here"}}).encode()
            self.send_response(status); self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=server.handle_request, daemon=True).start()
    return f"http://127.0.0.1:{server.server_port}", seen


def test_openrouter_sends_strict_schema_and_records_cost():
    url, seen = openrouter_server(reply={"summary": "ok", "changes": []})
    client = sb.OpenRouter("sk-or-v1-secretsecret", "anthropic/claude-haiku-5.5", "medium", base_url=url)
    assert client.edit("p") == {"summary": "ok", "changes": []}
    body = seen["body"]
    assert seen["path"] == "/chat/completions" and seen["auth"] == "Bearer sk-or-v1-secretsecret"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["response_format"]["json_schema"]["schema"]["additionalProperties"] is False
    assert body["provider"] == {"require_parameters": True} and body["reasoning"] == {"effort": "medium"}
    assert "models" not in body  # no silent fallback to another model
    assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert client.last_usage["cost"] == 0.0012 and client.last_usage["reasoning"] == 20


def test_openrouter_listen_is_measurement_not_hearing():
    url, seen = openrouter_server(reply={"heard": "x"})
    client = sb.OpenRouter("k", "qwen/qwen3.8-flash", base_url=url)
    assert client.listen(wav(), "goal") == {"heard": "x"} and client.hears is False
    assert "You have no audio input" in seen["body"]["messages"][-1]["content"]
    assert isinstance(seen["body"]["messages"][0]["content"], str)


@pytest.mark.parametrize("status,key", [(402, "openrouter_credits"), (429, "openrouter_quota"), (401, "openrouter_key"),
                                        (500, "openrouter_http")])
def test_openrouter_status_errors(status, key):
    url, _ = openrouter_server(status=status)
    with pytest.raises(sb.ModelError) as err:
        sb.OpenRouter("k", "m", base_url=url).edit("p")
    assert err.value.key == key and "sk-or-v1-abcdef" not in err.value.text("en")


def test_openrouter_cut_and_broken_replies_fail():
    url, _ = openrouter_server(finish="length")
    with pytest.raises(sb.ModelError) as err:
        sb.OpenRouter("k", "m", base_url=url).edit("p")
    assert err.value.key == "openrouter_cut"
    url, _ = openrouter_server(content="not json {")
    with pytest.raises(sb.ModelError) as err:
        sb.OpenRouter("k", "m", base_url=url).edit("p")
    assert err.value.key == "openrouter_parse"


def test_openrouter_key_is_redacted():
    assert "sk-or-" not in sb.redact("key sk-or-v1-0123456789abcdef leaked")


def test_bakeoff_models_hidden_on_the_public_server(monkeypatch):
    monkeypatch.delenv("STRUDEL_LOCAL_AI", raising=False)
    router = sb.Router(gemini_key="g", openrouter_key="or")
    ids = [m["id"] for m in router.choices()["models"]]
    assert ids == ["deepseek/deepseek-v4.1-flash", "gemini-3.8-flash"]
    assert router.choices()["model"] == "deepseek/deepseek-v4.1-flash"
    assert sb.Router(gemini_key="g").choices()["model"] == "gemini-3.8-flash"
    assert isinstance(router.engine("qwen/qwen3.8-flash"), sb.Gemini)
    assert sb.validate_request(request(model="qwen/qwen3.8-flash"))["model"] == ""


def test_bakeoff_models_offered_locally_only_with_a_key(monkeypatch):
    monkeypatch.setenv("STRUDEL_LOCAL_AI", "1")
    assert "qwen/qwen3.8-flash" not in [m["id"] for m in sb.Router(gemini_key="g").choices()["models"]]
    router = sb.Router(gemini_key="g", openrouter_key="or")
    assert "qwen/qwen3.8-flash" in [m["id"] for m in router.choices()["models"]]
    engine = router.engine("qwen/qwen3.8-flash", "low")
    assert isinstance(engine, sb.OpenRouter) and engine.model == "qwen/qwen3.8-flash" and engine.effort == "low"
    assert sb.validate_request(request(model="qwen/qwen3.8-flash"))["model"] == "qwen/qwen3.8-flash"


def test_agy_falls_back_to_the_json_in_its_response():
    out = json.dumps({"status": "SUCCESS", "response": 'thinking\n{"summary": "y", "changes": []}\n'}).encode()
    assert sb.AgyCli.parse(out) == {"summary": "y", "changes": []}
    with pytest.raises(sb.ModelError):
        sb.AgyCli.parse(json.dumps({"status": "SUCCESS", "response": "no json here"}).encode())


def test_agy_asks_again_only_when_a_denied_tool_call_left_the_turn_empty():
    denied = json.dumps({"status": "SUCCESS", "response": "", "conversation_id": "c1",
                         "denied_actions": [{"action": "command"}]}).encode()
    assert sb.AgyCli.denied_conversation(denied) == "c1"
    answered = json.dumps({"status": "SUCCESS", "response": "x", "conversation_id": "c1", "denied_actions": [1]}).encode()
    assert sb.AgyCli.denied_conversation(answered) == ""
    assert sb.AgyCli.denied_conversation(json.dumps({"status": "SUCCESS", "response": ""}).encode()) == ""


def test_accepted_marks_the_candidate_a_browser_ran():
    """A page that reloads after the job ended still knows which candidate to apply."""
    jobs = sb.Jobs(Fake())
    jobs.submit("o", request())
    snap = drive(jobs)
    assert snap["status"] == "done" and snap["accepted"] == snap["candidate"]["seq"] == 1

    jobs = sb.Jobs(Fake(edits=[{"summary": "", "bpm": 120, "changes": [change()]}]), feedback_timeout=5)
    jobs.submit("p", request())
    snap = drive(jobs, owner="p", respond=lambda c: {"ok": False, "error": "x"} if c["seq"] == 1 else {"ok": True})
    assert snap["accepted"] == snap["candidate"]["seq"] == 2
