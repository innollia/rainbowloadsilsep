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
    fake = Fake(); jobs = sb.Jobs(fake, daily_limit=0)
    jobs.submit("o", request())
    assert drive(jobs)["status"] == "limit" and fake.edit_calls == 0


def test_second_request_refused_while_running():
    jobs = sb.Jobs(Fake())
    jobs.submit("o", request())
    with pytest.raises(ValueError):
        jobs.submit("o", request())
    drive(jobs)


def test_signal_report_flags_silence_and_clipping():
    assert sb.signal_report(wav(0))["silent"]
    assert any("클리핑" in f for f in sb.signal_report(wav(32767))["findings"])


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
    assert any(m["kind"] == "measured" and "측정 분석" in m["text"] for m in snap["messages"])
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
