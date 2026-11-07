"""Second referee (bakeoff/referee2.py, bakeoff/judges.py): rubric, blind prompt, plan, statistics, report."""
import io
import json
import math
import struct
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bakeoff"))

import judges as jd  # noqa: E402
import referee2  # noqa: E402


def tone_wav(seconds=1.0, rate=16000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 220 * i / rate)))
                               for i in range(int(rate * seconds))))
    return buf.getvalue()


SONG = {"bpm": 120, "tracks": [{"id": "d", "name": "킥", "role": "drums", "code": 's("bd*4")'}]}


def test_prompt_has_request_code_measurements_and_no_model_name():
    text = jd.prompt_for("하우스 120BPM", tone_wav(), SONG)
    assert "하우스 120BPM" in text and 's("bd*4")' in text and "BPM 120" in text and "Measurements:" in text
    assert "anthropic" not in text


def test_clean_clamps_and_drops_bad_values():
    out = jd.clean({"request": 12, "melody_harmony": 0, "rhythm_groove": "x", "sound_mix": 5.7, "structure": True,
                    "overall": 140, "reason": "r" * 400})
    assert out["request"] == 10 and out["melody_harmony"] == 1 and out["rhythm_groove"] is None
    assert out["sound_mix"] == 5 and out["structure"] is None and out["overall"] == 100 and len(out["reason"]) == 300


def test_spearman_and_zscores():
    assert abs(jd.spearman([1, 2, 3, 4], [10, 20, 30, 40]) - 1) < 1e-9
    assert abs(jd.spearman([1, 2, 3, 4], [4, 3, 2, 1]) + 1) < 1e-9
    assert jd.spearman([1, 2], [1, 2]) is None
    z = jd.zscores({"a": 50, "b": 70, "c": 90})
    assert abs(z["a"] + z["c"]) < 1e-9 and z["b"] == 0


def test_openrouter_body_carries_audio_and_no_system():
    judge = jd.OpenRouterAudioJudge("k", "qwen/qwen3.8-omni-flash")
    judge.wav = b"RIFF"
    body = judge.request_body("p", jd.SCHEMA, "score")
    assert [m["role"] for m in body["messages"]] == ["user"]
    parts = body["messages"][0]["content"]
    assert parts[0]["type"] == "input_audio" and parts[0]["input_audio"]["format"] == "wav" and parts[1]["text"] == "p"


def test_gemini_judge_sends_audio_without_studio_system(monkeypatch):
    seen = {}

    class Res:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps({"overall": 70})}]}}]}).encode()

    def fake(req, timeout):
        seen["body"] = json.loads(req.data)
        return Res()

    monkeypatch.setattr(jd.urllib.request, "urlopen", fake)
    assert jd.GeminiJudge("k").judge("p", b"RIFF") == {"overall": 70}
    assert "systemInstruction" not in seen["body"]
    assert seen["body"]["contents"][0]["parts"][0]["inlineData"]["mimeType"] == "audio/wav"


def test_plan_skips_done_and_puts_repeats_last():
    songs = [{"model": "m", "task": str(i), "rep": 1} for i in range(5)]
    repeats = {("m", "0", 1), ("m", "1", 1)}
    work = referee2.plan(songs, ["a", "b"], {("m", "2", 1, "a", 1)}, repeats)
    assert len(work) == 5 * 2 - 1 + 2 * 2
    passes = [w[2] for w in work]
    assert passes == sorted(passes)
    assert referee2.repeat_set(songs, 3) == referee2.repeat_set(songs, 3)


def test_report_tables(tmp_path):
    config = {"models": [{"id": "x"}, {"id": referee2.BASELINE}]}
    lines = []
    for n, (model, a, b) in enumerate([("x", 60, 50), ("x", 70, 55), ("x", 65, 52),
                                       (referee2.BASELINE, 80, 70), (referee2.BASELINE, 85, 75)]):
        for judge, score in (("j1", a), ("j2", b)):
            lines.append({"model": model, "task": str(n), "rep": 1, "judge": judge, "pass": 1, "overall": score,
                          **{k: 5 for k in jd.SCALE}})
    lines.append({"model": "x", "task": "0", "rep": 1, "judge": "j1", "pass": 2, "overall": 62, **{k: 5 for k in jd.SCALE}})
    (tmp_path / "referee2.jsonl").write_text("\n".join(json.dumps(r) for r in lines), encoding="utf-8")
    text = referee2.report(config, tmp_path)
    assert "j1 vs j2: ρ = 1.00" in text and "j1: ρ = -, 평균 차이 2.0점 (곡 1개)" in text
    row = next(line for line in text.splitlines() if line.startswith("| x |"))
    assert "65.0" in row and "-18.8" in row
