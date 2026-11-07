"""Second-round referees that hear the finished songs (bakeoff/referee2.py).

Each judge gets the request, the audio, the song's Strudel code and ear.py's measurement table, never the model name
or its self-score. One short fixed prompt, one fixed rubric. Statistics helpers for report2 live here too.

Judges (name -> how it hears):
  gemini_api  Gemini 3.8 Flash, direct API, audio as inlineData. Key: GEMINI_API_KEY / SCHOOL_GEMINI_API_KEY.
  agy         Gemini 3.8 Flash in the Antigravity CLI. The wav is copied into its folder and its read_file tool loads
              the audio (only read_file is allowed; commands are denied). A spoken-word probe was transcribed exactly.
  qwen_omni   qwen/qwen3.8-omni-flash on OpenRouter, audio as input_audio.
  gemini_or   google/gemini-3.8-flash on OpenRouter, audio as input_audio. Stands in for gemini_api when no key.
"""
from __future__ import annotations

import base64
import json
import math
import os
import random
import statistics
import tempfile
import urllib.error
import urllib.request

import core
import studio_backend as sb

SCALE = ("request", "melody_harmony", "rhythm_groove", "sound_mix", "structure")
SCHEMA = {"type": "OBJECT", "properties": {
    **{k: {"type": "INTEGER"} for k in SCALE}, "overall": {"type": "INTEGER"}, "reason": {"type": "STRING"}},
    "required": [*SCALE, "overall", "reason"]}

PROMPT = """You judge a short piece of music made for this request:
{text}

Listen to the attached audio (the real recording). The Strudel code that made it and measurements of the recording
are below for reference; trust your ears first.
Rate each 1-10: request (fits the request and genre), melody_harmony, rhythm_groove, sound_mix (sound design and
balance), structure (development and variation over time). Then overall 0-100: how good it is to listen to as an
answer to the request. reason: one sentence in Korean.

Code (BPM {bpm}):
{code}

Measurements: {metrics}
{describe}"""


def song_code(song: dict | None) -> str:
    tracks = (song or {}).get("tracks") or []
    return "\n".join(f"// {t.get('name', '')} ({t.get('role', '')})\n$: {t.get('code', '')}" for t in tracks) or "(none)"


def prompt_for(text: str, wav: bytes, final_song: dict | None) -> str:
    import ear

    report = sb.signal_report(wav, "en")
    return PROMPT.format(text=text, bpm=(final_song or {}).get("bpm", "?"), code=song_code(final_song),
                         metrics=json.dumps(report["metrics"]), describe=ear.describe(wav))


def clean(reply: dict) -> dict:
    """Clamp the rubric; a missing or non-number field becomes None."""
    def num(v, lo, hi):
        return max(lo, min(hi, int(v))) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    out = {k: num(reply.get(k), 1, 10) for k in SCALE}
    out["overall"] = num(reply.get("overall"), 0, 100)
    out["reason"] = str(reply.get("reason", ""))[:300]
    return out


def gemini_key() -> str:
    pool = core.key_pool()
    for name in ("SCHOOL_GEMINI_API_KEY", "GEMINI_API_KEY"):
        value = os.environ.get(name) or pool.get(name, "")
        if value:
            return value
    return ""


class GeminiJudge(sb.Gemini):
    """sb.Gemini hearing the wav, without the studio SYSTEM prompt."""

    def __init__(self, key: str, model: str = "gemini-3.8-flash"):
        super().__init__(key, model, effort="low")

    def judge(self, prompt: str, wav: bytes) -> dict:
        parts = [{"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(wav).decode()}}, {"text": prompt}]
        body = json.dumps({"contents": [{"role": "user", "parts": parts}], "generationConfig": {
            "responseMimeType": "application/json", "responseSchema": SCHEMA,
            "thinkingConfig": {"thinkingLevel": self.effort}}}).encode()
        req = urllib.request.Request(f"{self.base_url}/v1beta/models/{self.model}:generateContent", data=body,
                                     headers={"Content-Type": "application/json", "x-goog-api-key": self.key})
        try:
            with urllib.request.urlopen(req, timeout=180) as res:
                data = json.load(res)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                raise sb.ModelError("gemini_quota") from None
            if exc.code in (401, 403):
                raise sb.ModelError("gemini_key") from None
            raise sb.ModelError("gemini_http", code=exc.code,
                                detail=sb.redact(exc.read().decode("utf-8", "replace"), self.key)) from None
        except (OSError, ValueError) as exc:
            raise sb.ModelError("gemini_conn", detail=sb.redact(exc, self.key)) from None
        meta = data.get("usageMetadata") or {}
        self.last_usage = {"input": meta.get("promptTokenCount", 0), "output": meta.get("candidatesTokenCount", 0),
                           "reasoning": meta.get("thoughtsTokenCount", 0), "model": self.model, "provider": "google"}
        try:
            return json.loads("".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]))
        except (KeyError, IndexError, TypeError, ValueError):
            raise sb.ModelError("gemini_parse") from None


class OpenRouterAudioJudge(sb.OpenRouter):
    """sb.OpenRouter with the wav sent as an input_audio part."""

    def __init__(self, key: str, model: str):
        super().__init__(key, model, "low", system="")
        self.wav = b""

    def request_body(self, prompt, schema, name):
        body = super().request_body(prompt, schema, name)
        body["messages"][-1]["content"] = [
            {"type": "input_audio", "input_audio": {"data": base64.b64encode(self.wav).decode(), "format": "wav"}},
            {"type": "text", "text": prompt}]
        return body

    def judge(self, prompt: str, wav: bytes) -> dict:
        self.wav = wav
        return self.ask(prompt, SCHEMA, "score")


class AgyAudioJudge(sb.AgyCli):
    """agy with the wav in its folder; only read_file is allowed, so it can load the audio and nothing else."""

    SETTINGS = json.dumps({"permissions": {"allow": ["read_file(*)"], "deny": ["command(*)"]}})

    def __init__(self, model: str = "gemini-3.8-flash-medium"):
        super().__init__(model=model, system="")

    def judge(self, prompt: str, wav: bytes) -> dict:
        with tempfile.TemporaryDirectory(prefix="olmuse-judge-") as folder:
            path = os.path.join(folder, "song.wav")
            with open(path, "wb") as stream:
                stream.write(wav)
            schema = os.path.join(folder, "schema.json")
            with open(schema, "w", encoding="utf-8") as stream:
                json.dump(sb.plain_schema(SCHEMA), stream)
            text = (f"First call read_file on {path} to hear the song. Use no other tool and run no commands. "
                    "Then reply only with the JSON object.\n\n" + prompt)
            base = [self.executable, "--output-format", "json", "--json-schema", schema, "--disable-slash-commands",
                    "--sandbox", "--print-timeout", f"{self.TIMEOUT}s", "--add-dir", folder, "--settings", self.SETTINGS,
                    "--model", self.model]
            out, err = self._exec(base + ["-p", text], folder)
            self.last_usage = self.usage_of(out)
            try:
                return self.parse(out, err)
            except sb.ModelError:
                conversation = self.denied_conversation(out)
                if not conversation:
                    raise
            out, err = self._exec(base + ["--conversation", conversation, "-p", self.AFTER_DENIAL], folder)
            self.last_usage = {"first": self.last_usage, "second": self.usage_of(out)}
            return self.parse(out, err)


JUDGES = {
    "gemini_api": {"via": "gemini", "model": "gemini-3.8-flash"},
    "agy": {"via": "agy", "model": "gemini-3.8-flash-medium"},
    "qwen_omni": {"via": "openrouter", "model": "qwen/qwen3.8-omni-flash"},
    "gemini_or": {"via": "openrouter", "model": "google/gemini-3.8-flash"},
}


def build(name: str):
    spec = JUDGES[name]
    if spec["via"] == "gemini":
        key = gemini_key()
        if not key:
            raise sb.ModelError("gemini_key")
        return GeminiJudge(key, spec["model"])
    if spec["via"] == "agy":
        return AgyAudioJudge(spec["model"])
    return OpenRouterAudioJudge(core.openrouter_key(), spec["model"])


# ---------- statistics ----------
def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def pearson(xs, ys) -> float | None:
    if len(xs) < 3:
        return None
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if not sx or not sy:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (sx * sy)


def spearman(xs, ys) -> float | None:
    return pearson(ranks(list(xs)), ranks(list(ys))) if len(xs) >= 3 else None


def zscores(values: dict) -> dict:
    """key -> z of the value within this judge's own scores."""
    vals = list(values.values())
    if len(vals) < 2:
        return {k: 0.0 for k in values}
    m, s = statistics.fmean(vals), statistics.pstdev(vals) or 1.0
    return {k: (v - m) / s for k, v in values.items()}


def bootstrap(values, n=2000, seed=1):
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def bootstrap_diff(a, b, n=2000, seed=2):
    if len(a) < 2 or len(b) < 2:
        return None
    rng = random.Random(seed)
    diffs = sorted(statistics.fmean(rng.choices(a, k=len(a))) - statistics.fmean(rng.choices(b, k=len(b)))
                   for _ in range(n))
    return diffs[int(0.025 * n)], diffs[int(0.975 * n) - 1]


def available() -> list[str]:
    """Default judges: Gemini hearing the wav (direct API when a key exists, else through OpenRouter), agy, Qwen omni."""
    return ["gemini_api" if gemini_key() else "gemini_or", "agy", "qwen_omni"]

