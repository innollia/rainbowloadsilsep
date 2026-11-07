"""Referees score each finished job's final song (docs/MODEL_BAKEOFF_PLAN.md 5).

A: Gemini 3.8 Flash through the agy CLI. B: Qwen 3.8 Flash through OpenRouter. Neither has audio input
here, so both judge ear.py's measurements of the real capture. Short fixed prompt: the request and
"how well and how pleasant"; no model names, no self-score, no studio SYSTEM prompt.
Writes results/referee.jsonl; already scored songs are skipped, so it can be rerun at any time.
  python bakeoff/referee.py [--judges A,B] [--workers 4]
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402
import studio_backend as sb  # noqa: E402

SCHEMA = {"type": "OBJECT", "properties": {"score": {"type": "INTEGER"}, "reason": {"type": "STRING"}},
          "required": ["score", "reason"]}
lock = threading.Lock()


def final_wav(log: Path, end: dict) -> Path | None:
    n = end.get("final_round") or end.get("rounds_listened") or 0
    path = log.with_name(f"{log.stem}-r{n}.wav")
    return path if n and path.exists() else None


def prompt_for(text: str, wav: bytes) -> str:
    import ear

    report = sb.signal_report(wav, "en")
    return ("You judge a short piece of music made for this request:\n" + text
            + "\n\nScore 0-100: how well it satisfies the request and how good it is to listen to. "
            "You have no audio input; judge only from these measurements of the real recording. "
            "Give a one-sentence reason in English.\n"
            + "Signal: " + json.dumps(report["metrics"]) + "\n" + ear.describe(wav))


def songs(config: dict, root: Path) -> list[dict]:
    out = []
    tasks = {t["id"]: t for t in config["tasks"]}
    for job in core.plan_jobs(config):
        log = core.job_log(job["model"]["id"], job["task"]["id"], job["rep"], root)
        records = core.read_jsonl(log)
        if core.outcome(records) != "success":
            continue
        wav = final_wav(log, core.end_of(records))
        if wav:
            out.append({"model": job["model"]["id"], "task": job["task"]["id"], "rep": job["rep"], "wav": wav,
                        "text": tasks[job["task"]["id"]]["text"]})
    return out


def judge_engine(judge: dict):
    if judge["via"] == "agy":
        return sb.AgyCli(model=judge.get("agy_model", ""), system="")
    return sb.OpenRouter(core.openrouter_key(), judge["id"], "low", system="")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--judges", default="A,B")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--results", default=str(core.RESULTS))
    args = ap.parse_args(argv)
    config, root = core.load_config(), Path(args.results)
    out = root / "referee.jsonl"
    done = {(r["model"], r["task"], r["rep"], r["judge"]) for r in core.read_jsonl(out) if "score" in r}
    judges = [j for j in config["referees"] if j["name"] in args.judges.split(",")]
    work = [(s, j) for s in songs(config, root) for j in judges if (s["model"], s["task"], s["rep"], j["name"]) not in done]
    print(f"{len(work)} scores to get", flush=True)
    key = core.openrouter_key()
    floor = float(config["budget"]["openrouter_floor_usd"])
    caps = {j["name"]: len(work) * float(j.get("job_max_usd", 0)) * float(config["budget"]["over_factor"]) for j in judges}
    spend = {j["name"]: 0.0 for j in judges}

    def score(item):
        song, judge = item
        if judge["via"] == "openrouter":
            with lock:
                if caps[judge["name"]] and spend[judge["name"]] >= caps[judge["name"]]:
                    return "budget"
            left = core.openrouter_left(key)
            if left is not None and left < floor:
                return "budget"
        engine = judge_engine(judge)
        record = {"model": song["model"], "task": song["task"], "rep": song["rep"], "judge": judge["name"]}
        start = time.monotonic()
        try:
            reply = engine.ask(prompt_for(song["text"], song["wav"].read_bytes()), SCHEMA, "score") \
                if judge["via"] == "openrouter" else engine._run(prompt_for(song["text"], song["wav"].read_bytes()), SCHEMA)
            value = reply.get("score")
            record.update(score=max(0, min(100, int(value))) if isinstance(value, (int, float)) else None,
                          reason=str(reply.get("reason", ""))[:300])
        except sb.ModelError as exc:
            record.update(error=core.error_key(exc))
        record.update(seconds=round(time.monotonic() - start, 2), usage=getattr(engine, "last_usage", {}), t=time.time())
        with lock:
            spend[judge["name"]] += float(record["usage"].get("cost") or 0) if isinstance(record["usage"], dict) else 0
            core.append_jsonl(out, record)
        return "ok" if "score" in record and record["score"] is not None else "error"

    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(score, work))
    print({k: results.count(k) for k in set(results)}, f"spent ${sum(spend.values()):.4f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
