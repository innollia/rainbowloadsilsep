"""Second referee: judges that hear the finished songs, scored on a fixed rubric (judges.py).

Re-scores only songs that already exist: the final song of every successful (done/limit) job, finalist or not.
Each judge gets the request, the audio, the Strudel code and the measurement table; no model name, no self-score.
Songs go in random order. REPEATS songs (same for every judge) are scored a second time for self-consistency.
Writes results/referee2.jsonl (already scored songs are skipped, so it can be rerun) and results/report2.md.
The old results (model logs, wavs, referee.jsonl, report.md) are only read.
  python bakeoff/referee2.py [--judges agy,qwen_omni] [--workers 4] [--limit N] [--max-usd 2]
  python bakeoff/referee2.py --report      (report2.md only)
"""
from __future__ import annotations

import argparse
import random
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402
import judges as jd  # noqa: E402
import studio_backend as sb  # noqa: E402
from referee import final_wav  # noqa: E402

REPEATS = 20
BASELINE = "anthropic/claude-opus-5.5"
lock = threading.Lock()


def songs(config: dict, root: Path) -> list[dict]:
    tasks = {t["id"]: t for t in config["tasks"]}
    out = []
    for job in core.plan_jobs(config):
        log = core.job_log(job["model"]["id"], job["task"]["id"], job["rep"], root)
        records = core.read_jsonl(log)
        if core.outcome(records) != "success":
            continue
        end = core.end_of(records)
        wav = final_wav(log, end)
        if wav:
            out.append({"model": job["model"]["id"], "task": job["task"]["id"], "rep": job["rep"], "wav": wav,
                        "text": tasks[job["task"]["id"]]["text"], "final_song": end.get("final_song")})
    return out


def key(r: dict) -> tuple:
    return r["model"], r["task"], r["rep"]


def repeat_set(all_songs: list[dict], n: int = REPEATS) -> set:
    picked = random.Random(11).sample(sorted(key(s) for s in all_songs), min(n, len(all_songs)))
    return set(picked)


def plan(all_songs: list[dict], names: list[str], done: set, repeats: set) -> list[tuple]:
    work = [(s, j, 1) for s in all_songs for j in names] + [(s, j, 2) for s in all_songs if key(s) in repeats for j in names]
    work = [w for w in work if (*key(w[0]), w[1], w[2]) not in done]
    random.Random().shuffle(work)  # random song order every run; second passes mixed in with first passes
    first = [w for w in work if w[2] == 1]
    return first + [w for w in work if w[2] == 2]  # a repeat should not come before its own first pass


def scored(out: Path) -> list[dict]:
    return [r for r in core.read_jsonl(out) if r.get("overall") is not None]


def run(args, config, root: Path) -> dict:
    out = root / "referee2.jsonl"
    names = args.judges.split(",") if args.judges else jd.available()
    all_songs = songs(config, root)
    done = {(*key(r), r["judge"], r.get("pass", 1)) for r in scored(out)}
    work = plan(all_songs, names, done, repeat_set(all_songs))
    if args.limit:
        keep = {key(s) for s in all_songs[:args.limit]}
        work = [w for w in work if key(w[0]) in keep]
    spent_before = sum(float((r.get("usage") or {}).get("cost") or 0) for r in core.read_jsonl(out)
                       if isinstance(r.get("usage"), dict))
    spend = {"usd": spent_before}
    print(f"{len(all_songs)} songs, judges {names}, {len(work)} scores to get, OpenRouter spent so far ${spent_before:.4f}",
          flush=True)
    key_or = core.openrouter_key()
    floor = float(config["budget"]["openrouter_floor_usd"])

    def score(item):
        song, name, n = item
        if jd.JUDGES[name]["via"] == "openrouter":
            with lock:
                if spend["usd"] >= args.max_usd:
                    return "budget"
            left = core.openrouter_left(key_or)
            if left is not None and left < floor:
                return "budget"
        record = {"model": song["model"], "task": song["task"], "rep": song["rep"], "judge": name, "pass": n}
        start = time.monotonic()
        engine = None
        try:
            engine = jd.build(name)
            wav = song["wav"].read_bytes()
            record.update(jd.clean(engine.judge(jd.prompt_for(song["text"], wav, song["final_song"]), wav)))
        except sb.ModelError as exc:
            record.update(error=core.error_key(exc), detail=sb.redact(getattr(exc, "fields", {}) or exc))
        record.update(seconds=round(time.monotonic() - start, 2), usage=getattr(engine, "last_usage", {}), t=time.time())
        with lock:
            usage = record["usage"]
            spend["usd"] += float(usage.get("cost") or 0) if isinstance(usage, dict) else 0
            core.append_jsonl(out, record)
        return "ok" if record.get("overall") is not None else record.get("error", "error")

    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(score, work))
    tally = {k: results.count(k) for k in set(results)}
    print(tally, f"OpenRouter total ${spend['usd']:.4f}", flush=True)
    return tally


# ---------- report ----------
def fmt(v, digits=1):
    return "-" if v is None else f"{v:.{digits}f}"


def ci(pair, digits=0):
    return f" ({pair[0]:.{digits}f}~{pair[1]:.{digits}f})" if pair else ""


def report(config: dict, root: Path) -> str:
    rows = scored(root / "referee2.jsonl")
    first = {}
    second = {}
    for r in rows:
        (first if r.get("pass", 1) == 1 else second)[(*key(r), r["judge"])] = r  # a later line replaces an earlier one
    names = sorted({k[3] for k in first})
    per_judge = {j: {k[:3]: r for k, r in first.items() if k[3] == j} for j in names}
    z = {j: jd.zscores({s: r["overall"] for s, r in per_judge[j].items()}) for j in names}
    song_keys = sorted({k[:3] for k in first})
    raw = {s: statistics.fmean(per_judge[j][s]["overall"] for j in names if s in per_judge[j]) for s in song_keys}
    zz = {s: statistics.fmean(z[j][s] for j in names if s in z[j]) for s in song_keys}
    models = [m["id"] for m in config["models"]]
    lines = ["# 모델 대결 — 듣는 심판 결과 (report2)", "",
             f"심판: {', '.join(names) or '(없음)'}. 각 심판은 요청 문장·오디오·Strudel 코드·측정표를 받고 모델 이름은 모른다. "
             f"점수가 있는 곡 {len(song_keys)}개. 합산 = 심판 평균(원점수), z = 심판별 z-점수 평균.", "",
             "## 모델별 종합 (0~100, 괄호는 95% 부트스트랩 범위)", "",
             "| 모델 | 곡 | " + " | ".join(names) + " | 합산 | z 합산 | Opus 대비(합산) | Opus 대비(z) |",
             "|---|---|" + "---|" * len(names) + "---|---|---|---|"]
    base_raw = [raw[s] for s in song_keys if s[0] == BASELINE]
    base_z = [zz[s] for s in song_keys if s[0] == BASELINE]
    for m in models:
        mine = [s for s in song_keys if s[0] == m]
        if not mine:
            continue
        cells = []
        for j in names:
            vals = [per_judge[j][s]["overall"] for s in mine if s in per_judge[j]]
            cells.append(fmt(statistics.fmean(vals)) + ci(jd.bootstrap(vals)) if vals else "-")
        rv, zv = [raw[s] for s in mine], [zz[s] for s in mine]
        drv = statistics.fmean(rv) - statistics.fmean(base_raw) if base_raw and m != BASELINE else None
        dzv = statistics.fmean(zv) - statistics.fmean(base_z) if base_z and m != BASELINE else None
        lines.append(f"| {m} | {len(mine)} | " + " | ".join(cells)
                     + f" | {fmt(statistics.fmean(rv))}{ci(jd.bootstrap(rv))} | {fmt(statistics.fmean(zv), 2)}{ci(jd.bootstrap(zv), 2)}"
                     + f" | {fmt(drv)}{ci(jd.bootstrap_diff(rv, base_raw)) if drv is not None else ''}"
                     + f" | {fmt(dzv, 2)}{ci(jd.bootstrap_diff(zv, base_z), 2) if dzv is not None else ''} |")
    lines += ["", "## 항목별 점수 (1~10, 심판 평균)", "", "| 모델 | " + " | ".join(jd.SCALE) + " |",
              "|---|" + "---|" * len(jd.SCALE)]
    for m in models:
        cells = []
        for item in jd.SCALE:
            vals = [r[item] for j in names for s, r in per_judge[j].items() if s[0] == m and r.get(item) is not None]
            cells.append(fmt(statistics.fmean(vals)) if vals else "-")
        if any(c != "-" for c in cells):
            lines.append(f"| {m} | " + " | ".join(cells) + " |")
    lines += ["", "## 신뢰도", "", "심판 간 스피어만 상관(종합 점수, 같은 곡):", ""]
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            both = [s for s in per_judge[a] if s in per_judge[b]]
            rho = jd.spearman([per_judge[a][s]["overall"] for s in both], [per_judge[b][s]["overall"] for s in both])
            lines.append(f"- {a} vs {b}: ρ = {fmt(rho, 2)} (곡 {len(both)}개)")
    lines += ["", "자기 일관성(같은 심판이 같은 곡을 두 번):", ""]
    for j in names:
        pairs = [(first[k]["overall"], r["overall"]) for k, r in second.items() if k[3] == j and k in first]
        if pairs:
            rho = jd.spearman([a for a, _ in pairs], [b for _, b in pairs])
            gap = statistics.fmean(abs(a - b) for a, b in pairs)
            lines.append(f"- {j}: ρ = {fmt(rho, 2)}, 평균 차이 {gap:.1f}점 (곡 {len(pairs)}개)")
        else:
            lines.append(f"- {j}: 두 번째 채점 없음")
    old = {}
    for r in core.read_jsonl(root / "referee.jsonl"):
        if r.get("score") is not None:
            old.setdefault(key(r), {})[r["judge"]] = r["score"]
    lines += ["", "기존 측정표 심판(referee.jsonl)과의 스피어만 상관:", ""]
    for label, pick in [("기존 A", lambda o: o.get("A")), ("기존 B", lambda o: o.get("B")),
                        ("기존 평균", lambda o: statistics.fmean(o.values()) if o else None)]:
        for j, scores in [*((j, {s: r["overall"] for s, r in per_judge[j].items()}) for j in names), ("합산", raw)]:
            both = [s for s in scores if s in old and pick(old[s]) is not None]
            rho = jd.spearman([scores[s] for s in both], [pick(old[s]) for s in both])
            lines.append(f"- {j} vs {label}: ρ = {fmt(rho, 2)} (곡 {len(both)}개)")
    errors = [r for r in core.read_jsonl(root / "referee2.jsonl") if r.get("overall") is None]
    spent = sum(float((r.get("usage") or {}).get("cost") or 0) for r in core.read_jsonl(root / "referee2.jsonl")
                if isinstance(r.get("usage"), dict))
    lines += ["", f"실패한 채점 줄 {len(errors)}개(재실행하면 다시 시도). OpenRouter 지출 ${spent:.4f}.", ""]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--judges", default="", help="comma list from judges.JUDGES; default: " + ",".join(jd.JUDGES))
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="only the first N songs (trial)")
    ap.add_argument("--max-usd", type=float, default=2.0, help="OpenRouter spend cap for referee2, all runs together")
    ap.add_argument("--report", action="store_true", help="only rewrite report2.md")
    ap.add_argument("--results", default=str(core.RESULTS))
    args = ap.parse_args(argv)
    config, root = core.load_config(), Path(args.results)
    if not args.report:
        run(args, config, root)
    (root / "report2.md").write_text(report(config, root), encoding="utf-8")
    print(f"wrote {root / 'report2.md'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
