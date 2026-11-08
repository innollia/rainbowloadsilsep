"""Blind-listening clips (docs/MODEL_BAKEOFF_PLAN.md 6).

Takes the final songs of each finalist on every task (first TAKES successful repetitions, one clip set per take),
cuts every clip to
the same length, levels loudness to the same LUFS and writes it under a random name to static/bakeoff/
(served at /app/static/bakeoff/). One clip per task is added again under another name to check listener
consistency. The model behind each name is kept only in results/listen/manifest.json on this PC.
  python bakeoff/clips.py                      # finalists from results/report2.md (listening referees)
  python bakeoff/clips.py --source report      # finalists from results/report.json (old measurement-table referees)
  python bakeoff/clips.py --models a,b,c       # or name them

A rerun keeps the clip name of every (task, model, source song) that stays, so votes already cast on it still
line up. Clips of models that leave go to the manifest's "retired" list: no longer served, still counted.
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
from listen_store import MANIFEST, load_manifest  # noqa: E402
from referee import final_wav  # noqa: E402

STATIC = core.ROOT / "static" / "bakeoff"
BASELINE = "anthropic/claude-opus-5.5"  # the user's baseline: always a finalist
SIZE = 6
TAKES = 3  # songs per (task, model) served: every finalist song already recorded, no new generation cost
MIN_MODELS = 3
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


def pick_songs(model_id: str, task_id: str, config: dict, root: Path) -> list[Path]:
    """Final songs of the model's successful repetitions of a task, in repetition order."""
    model = next(m for m in config["models"] if m["id"] == model_id)
    songs = []
    for rep in range(1, int(model.get("reps", 1)) + 3):
        log = core.job_log(model_id, task_id, rep, root)
        records = core.read_jsonl(log)
        if core.outcome(records) == "success":
            wav = final_wav(log, core.end_of(records))
            if wav:
                songs.append(wav)
    return songs


def pick_song(model_id: str, task_id: str, config: dict, root: Path) -> Path | None:
    songs = pick_songs(model_id, task_id, config, root)
    return songs[0] if songs else None


def clip_sets(task: dict, models: list[str], config: dict, root: Path) -> list[tuple[str, dict]]:
    """(set id, model -> song) for each take of a task. Take 1 keeps the task id (votes cast on it stay put),
    take k > 1 is "<id>-<k>". A take needs MIN_MODELS finalists with that many successful songs to be worth comparing."""
    songs = {m: pick_songs(m, task["id"], config, root) for m in models}
    sets = []
    for take in range(1, TAKES + 1):
        found = {m: s[take - 1] for m, s in songs.items() if len(s) >= take}
        if len(found) >= MIN_MODELS:
            sets.append((task["id"] if take == 1 else f'{task["id"]}-{take}', found))
    return sets


def report2_finalists(root: Path, size: int = SIZE) -> list[str]:
    """Top models by the listening referees' combined score (report2.md "합산"), qualified models only
    (results/report.json), the baseline always in."""
    text = (root / "report2.md").read_text(encoding="utf-8")
    section = text.split("## 모델별 종합", 1)[1].split("\n## ", 1)[0]
    rows = [[c.strip() for c in line.strip().strip("|").split("|")] for line in section.splitlines() if line.startswith("|")]
    header, body = rows[0], [r for r in rows[2:] if len(r) == len(rows[0])]
    col = header.index("합산")
    score = {r[0]: float(r[col].split()[0]) for r in body}
    try:
        summary = json.loads((root / "report.json").read_text(encoding="utf-8"))["summary"]
        unqualified = {s["model"] for s in summary if not s.get("qualified")}
    except (OSError, ValueError, KeyError):
        unqualified = set()
    ranked = sorted((m for m in score if m not in unqualified), key=lambda m: -score[m])
    picks = [BASELINE] if BASELINE in score else []
    picks += [m for m in ranked if m not in picks]
    return picks[:size]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="")
    ap.add_argument("--source", choices=("report2", "report"), default="report2")
    ap.add_argument("--results", default=str(core.RESULTS))
    args = ap.parse_args(argv)
    config, root = core.load_config(), Path(args.results)
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        try:
            if args.source == "report2":
                models = report2_finalists(root)
            else:
                models = json.loads((root / "report.json").read_text(encoding="utf-8"))["finalists"]
        except (OSError, ValueError, KeyError, IndexError):
            sys.exit(f"no finalists in {args.source}: write it first or pass --models")
    previous = load_manifest() or {"tasks": [], "retired": []}
    keep = {(t["id"], c["model"], c["source"]): c["clip"] for t in previous["tasks"] for c in t["clips"] if not c.get("dup_of")}
    old_dup = {t["id"]: c for t in previous["tasks"] for c in t["clips"] if c.get("dup_of")}
    STATIC.mkdir(parents=True, exist_ok=True)
    rng = random.Random()
    tasks = []
    with tempfile.TemporaryDirectory() as tmp:
        for task, set_id, found in ((t, i, f) for t in config["tasks"] for i, f in clip_sets(t, models, config, root)):
            seconds = min(analyze_audio.read_wav(str(w))[0].shape[0] / analyze_audio.read_wav(str(w))[1] for w in found.values())
            clips = []
            for model, wav in found.items():
                name = keep.get((set_id, model, str(wav.relative_to(core.ROOT)))) or secrets.token_hex(8)
                leveled = Path(tmp) / f"{name}.wav"
                level(wav, leveled, seconds)
                clips.append({"clip": name, "file": encode(leveled, name), "model": model, "source": str(wav.relative_to(core.ROOT)),
                              "dup_of": None})
            dup = old_dup.get(set_id)
            twin = next((c for c in clips if dup and c["clip"] == dup["dup_of"]), None) or rng.choice(clips)
            name = dup["clip"] if dup and dup["dup_of"] == twin["clip"] else secrets.token_hex(8)
            src = STATIC / twin["file"]
            copy = STATIC / f"{name}{src.suffix}"
            shutil.copyfile(src, copy)
            clips.append({**twin, "clip": name, "file": copy.name, "dup_of": twin["clip"]})
            tasks.append({"id": set_id, "genre": task["genre"], "text": task["text"], "seconds": round(seconds, 1),
                          "clips": clips})
    served = {c["clip"] for t in tasks for c in t["clips"]}
    retired = [r for r in previous.get("retired", []) if r["clip"] not in served]
    seen = {r["clip"] for r in retired}
    for t in previous["tasks"]:
        for c in t["clips"]:
            if c["clip"] not in served and c["clip"] not in seen:
                retired.append({"task": t["id"], "clip": c["clip"], "model": c["model"], "source": c.get("source"),
                                "dup_of": c.get("dup_of")})
    files = {c["file"] for t in tasks for c in t["clips"]}
    for f in STATIC.iterdir():
        if f.name not in files:
            f.unlink()  # retired clips must not stay reachable by URL
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    staged = MANIFEST.with_suffix(".tmp")
    staged.write_text(json.dumps({"models": models, "tasks": tasks, "retired": retired}, ensure_ascii=False, indent=1),
                      encoding="utf-8")
    staged.replace(MANIFEST)
    print(f"models: {', '.join(models)}")
    print(f"{sum(len(t['clips']) for t in tasks)} clips for {len(tasks)} tasks -> {STATIC}; {len(retired)} retired; "
          f"manifest {MANIFEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
