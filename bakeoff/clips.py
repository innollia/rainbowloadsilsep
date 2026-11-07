"""Blind-listening clips (docs/MODEL_BAKEOFF_PLAN.md 6).

Takes the final song of each finalist on each star task (first successful repetition), cuts every clip to
the same length, levels loudness to the same LUFS and writes it under a random name to static/bakeoff/
(served at /app/static/bakeoff/). One clip per task is added again under another name to check listener
consistency. The model behind each name is kept only in results/listen/manifest.json on this PC.
  python bakeoff/clips.py                      # finalists from results/report.json
  python bakeoff/clips.py --models a,b,c       # or name them
"""
from __future__ import annotations

import argparse
import json
import random
import secrets
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402
import analyze_audio  # noqa: E402
from listen_store import MANIFEST  # noqa: E402
from referee import final_wav  # noqa: E402

STATIC = core.ROOT / "static" / "bakeoff"
TARGET_LUFS = -16.0
CEILING = 10 ** (-1 / 20)  # -1 dBFS sample peak after levelling


def level(src: Path, dst: Path, seconds: float):
    data, rate = analyze_audio.read_wav(str(src))
    data = data[: int(seconds * rate)]
    loud = analyze_audio.integrated_lufs(data, rate)
    gain = 10 ** ((TARGET_LUFS - loud) / 20) if np.isfinite(loud) else 1.0
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    if peak * gain > CEILING:
        gain = CEILING / peak
    out = np.clip(data * gain, -1, 1)
    pcm = (out * 32767).astype("<i2")
    with wave.open(str(dst), "wb") as w:
        w.setnchannels(pcm.shape[1]); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def encode(wav: Path, name: str) -> str:
    """mp3 when ffmpeg is here (smaller over the tunnel), otherwise the WAV itself."""
    STATIC.mkdir(parents=True, exist_ok=True)
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        target = STATIC / f"{name}.mp3"
        done = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "192k",
                               str(target)], capture_output=True)
        if done.returncode == 0:
            return target.name
    target = STATIC / f"{name}.wav"
    shutil.copyfile(wav, target)
    return target.name


def pick_song(model_id: str, task_id: str, config: dict, root: Path) -> Path | None:
    model = next(m for m in config["models"] if m["id"] == model_id)
    for rep in range(1, int(model.get("reps", 1)) + 3):
        log = core.job_log(model_id, task_id, rep, root)
        records = core.read_jsonl(log)
        if core.outcome(records) == "success":
            wav = final_wav(log, core.end_of(records))
            if wav:
                return wav
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="")
    ap.add_argument("--results", default=str(core.RESULTS))
    args = ap.parse_args(argv)
    config, root = core.load_config(), Path(args.results)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        try:
            models = json.loads((root / "report.json").read_text(encoding="utf-8"))["finalists"]
        except (OSError, ValueError, KeyError):
            sys.exit("no finalists: run bakeoff/report.py first or pass --models")
    if STATIC.exists():
        shutil.rmtree(STATIC)  # old clips would still be reachable by URL
    rng = random.Random()
    tasks = []
    with tempfile.TemporaryDirectory() as tmp:
        for task in (t for t in config["tasks"] if t.get("star")):
            found = {m: pick_song(m, task["id"], config, root) for m in models}
            found = {m: w for m, w in found.items() if w}
            if not found:
                continue
            seconds = min(analyze_audio.read_wav(str(w))[0].shape[0] / analyze_audio.read_wav(str(w))[1] for w in found.values())
            clips = []
            for model, wav in found.items():
                name = secrets.token_hex(8)
                leveled = Path(tmp) / f"{name}.wav"
                level(wav, leveled, seconds)
                clips.append({"clip": name, "file": encode(leveled, name), "model": model, "source": str(wav.relative_to(core.ROOT)),
                              "dup_of": None})
            twin = rng.choice(clips)
            name = secrets.token_hex(8)
            src = STATIC / twin["file"]
            copy = STATIC / f"{name}{src.suffix}"
            shutil.copyfile(src, copy)
            clips.append({**twin, "clip": name, "file": copy.name, "dup_of": twin["clip"]})
            tasks.append({"id": task["id"], "genre": task["genre"], "text": task["text"], "seconds": round(seconds, 1),
                          "clips": clips})
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps({"models": models, "tasks": tasks}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{sum(len(t['clips']) for t in tasks)} clips for {len(tasks)} tasks -> {STATIC}; manifest {MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
