"""Value table: cost per song at public API prices, scores, Pareto front, and per-model music traits.

Reads only existing results (no generation, no judging). Prices come from the public OpenRouter model list
(free read; a snapshot below is used when offline). Writes docs/MODEL_VALUE.md tables to stdout or --out.
  python bakeoff/value.py                 # print the tables
  python bakeoff/value.py --json out.json # also dump the numbers
Note: docs/MODEL_VALUE.md also has a hand-written conclusion; this script prints only the tables.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import statistics
import sys
import urllib.request
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402
import judges as jd  # noqa: E402
import listen_store  # noqa: E402
from referee import final_wav  # noqa: E402

# OpenRouter model whose public price stands in for a subscription CLI model.
CLI_PRICE_ID = {"gemini-3.8-flash": "google/gemini-3.8-flash", "gpt-5.6-luna": "openai/gpt-5.6-luna",
                "gpt-5.6-terra": "openai/gpt-5.6-terra"}
# USD per token, snapshot of https://openrouter.ai/api/v1/models on 2026-11-08 (prompt, completion, cache read)
PRICE_SNAPSHOT = {
    "google/gemini-3.8-flash": (0.825e-6, 4.125e-6, 0.0825e-6),
    "openai/gpt-5.6-luna": (0.2e-6, 1.2e-6, 0.02e-6),
    "openai/gpt-5.6-terra": (2e-6, 12e-6, 0.2e-6),
    "nvidia/nemotron-3.5-super-vl": (0.15e-6, 0.5e-6, 0.02e-6),
}


def prices() -> tuple[dict, str]:
    try:
        with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=30) as res:
            data = json.load(res)["data"]
        out = {}
        for m in data:
            p = m.get("pricing") or {}
            out[m["id"]] = (float(p.get("prompt") or 0), float(p.get("completion") or 0),
                            float(p.get("input_cache_read") or p.get("prompt") or 0))
        return out, "live"
    except Exception:
        return dict(PRICE_SNAPSHOT), "snapshot"


def cli_tokens(usage: dict) -> dict:
    """input / cached / output tokens of one CLI call. agy may report two attempts (first, second): both are paid.
    agy output_tokens already include thinking_tokens; codex output includes reasoning (OpenAI convention)."""
    if "first" in usage or "second" in usage:
        parts = [usage[k] for k in ("first", "second") if isinstance(usage.get(k), dict)]
    else:
        parts = [usage]
    tot = {"input": 0, "cached": 0, "output": 0}
    for u in parts:
        if "input_tokens" in u:  # agy
            tot["input"] += u.get("input_tokens", 0)
            tot["cached"] += u.get("cache_read_tokens", 0)
            tot["output"] += u.get("output_tokens", 0)
        else:  # codex / openrouter
            tot["input"] += u.get("input", 0)
            tot["cached"] += u.get("cached", 0)
            tot["output"] += u.get("output", 0)
    return tot


def call_cost(tok: dict, price: tuple, drop_input: float = 0) -> float:
    p_in, p_out, p_cache = price
    fresh = max(tok["input"] - tok["cached"] - drop_input, 0)
    return fresh * p_in + tok["cached"] * p_cache + tok["output"] * p_out


SOUND_RE = re.compile(r'(?:^|[^\w.])s\(\s*"([^"]*)"|\.s\(\s*"([^"]*)"|\.sound\(\s*"([^"]*)"')


def sound_names(code: str) -> list[str]:
    out = []
    for m in SOUND_RE.finditer(code or ""):
        text = next(g for g in m.groups() if g is not None)
        for word in re.split(r"[\s\[\]<>{},|]+", text):
            word = re.split(r"[*:/!@?(]", word)[0].strip()
            if word and word not in ("~", "-", "_", ".") and not re.fullmatch(r"[\d.]+", word):
                out.append(word)
    return out


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a or "", b or "").ratio()


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def judge_scores(root: Path) -> dict:
    """Per song: mean of the judges' first-pass overall (same as referee2.report)."""
    first = {}
    for r in core.read_jsonl(root / "referee2.jsonl"):
        if r.get("overall") is not None and r.get("pass", 1) == 1:
            first[(r["model"], r["task"], r["rep"], r["judge"])] = r["overall"]
    per = {}
    for (m, t, rep, _), v in first.items():
        per.setdefault((m, t, rep), []).append(v)
    return {k: statistics.fmean(v) for k, v in per.items()}


def human(root: Path) -> dict:
    manifest = listen_store.load_manifest()
    if not manifest or not Path(listen_store.DB).exists():
        return {}
    pairs = listen_store.Pairs().all()
    t = listen_store.tally_pairs(manifest, pairs)
    return {r["model"]: r for r in t["models"]} | {"_voters": t["voters"], "_choices": t["choices"]}


def loudness(wav: Path) -> dict | None:
    try:
        sys.path.insert(0, str(core.ROOT))
        import analyze_audio

        m = analyze_audio.measure(str(wav))
        return {"lufs": m.get("integrated_lufs"), "tp": m.get("true_peak_dbfs"), "clipped": m.get("clipped_samples", 0)}
    except Exception:
        return None


def collect(config: dict, root: Path, price_table: dict, overhead: dict) -> list[dict]:
    fixed = {t["id"]: t["code"] for t in config["fixed_song"]["tracks"]}
    fixed_bpm = config["fixed_song"]["bpm"]
    scores = judge_scores(root)
    rows = []
    for m in config["models"]:
        mid, via = m["id"], m["via"]
        price = price_table.get(CLI_PRICE_ID.get(mid, mid))
        paid_price = price_table.get(mid.removesuffix(":free")) if mid.endswith(":free") else None
        r = {"model": mid, "via": via, "jobs": 0, "ok": 0, "fail": 0, "infra": 0, "fail_reasons": Counter(),
             "cost": [], "cost_adj": [], "cost_paid": [], "input_per_call": [], "calls": [], "seconds": [],
             "rounds": [], "reverted": [], "self_minus": [], "judged": [], "sounds": Counter(), "sound_sets": [],
             "tracks": [], "lufs": [], "tp": [], "clip": [], "t7_other": [], "t7_bass_change": [], "t7_bpm_ok": [],
             "t8_bpm50": [], "t8_change": [], "price": price}
        for job in core.plan_jobs(config, models=[mid]):
            tid, rep = job["task"]["id"], job["rep"]
            log = core.job_log(mid, tid, rep, root)
            records = core.read_jsonl(log)
            result = core.outcome(records)
            if result == "infra":
                r["infra"] += 1
                continue
            if result not in ("success", "fail"):
                continue
            r["jobs"] += 1
            calls = [x for x in records if x.get("kind") in ("edit", "listen") and x.get("usage")]
            cost = cost_adj = cost_paid = 0.0
            for c in calls:
                u = c["usage"]
                if via == "openrouter":
                    cost += float(u.get("cost") or 0)
                    if paid_price:
                        cost_paid += call_cost(cli_tokens(u), paid_price)
                    r["input_per_call"].append(u.get("input", 0))
                else:
                    tok = cli_tokens(u)
                    r["input_per_call"].append(tok["input"])
                    if price:
                        cost += call_cost(tok, price)
                        cost_adj += call_cost(tok, price, drop_input=overhead.get(via, 0))
            r["cost"].append(cost)
            r["cost_adj"].append(cost_adj if via != "openrouter" else cost)
            r["cost_paid"].append(cost_paid if paid_price else cost)
            r["calls"].append(len(calls))
            end = core.end_of(records) or {}
            r["seconds"].append(end.get("seconds"))
            if result == "fail":
                r["fail"] += 1
                errs = [x.get("error") for x in records if x.get("error")]
                text = (end.get("messages") or [{}])[-1].get("text", "")
                reason = errs[-1] if errs else text[:40]
                if "WinError 32" in str(reason):
                    reason = "하네스 파일 잠금(WinError 32)"
                r["fail_reasons"][str(reason)[:40]] += 1
                continue
            r["ok"] += 1
            r["rounds"].append(end.get("rounds_listened"))
            r["reverted"].append(1.0 if end.get("reverted") else 0.0)
            listens = [x for x in records if x.get("kind") == "listen" and isinstance(x.get("reply"), dict)]
            n = end.get("final_round") or 0
            selfs = listens[n - 1]["reply"].get("score") if 0 < n <= len(listens) else None
            judged = scores.get((mid, tid, rep))
            r["judged"].append(judged)
            if selfs is not None and judged is not None:
                r["self_minus"].append(selfs - judged)
            song = end.get("final_song") or {}
            tracks = song.get("tracks") or []
            names = [w for t in tracks for w in sound_names(t.get("code", ""))]
            r["sounds"].update(names)
            r["sound_sets"].append(len(set(names)))
            if job["task"].get("start") == "empty":
                r["tracks"].append(len(tracks))
            wav = final_wav(log, end)
            meas = loudness(wav) if wav else None
            if meas:
                r["lufs"].append(meas["lufs"])
                r["tp"].append(meas["tp"])
                r["clip"].append(1.0 if meas["clipped"] else 0.0)
            codes = {t.get("id"): t.get("code", "") for t in tracks}
            if tid == "7":
                others = [k for k in fixed if k != "bass"]
                r["t7_other"].append(1.0 if any(codes.get(k) != fixed[k] for k in others) or set(codes) != set(fixed) else 0.0)
                r["t7_bass_change"].append(1 - similarity(codes.get("bass", ""), fixed["bass"]))
                r["t7_bpm_ok"].append(1.0 if float(song.get("bpm") or 0) == fixed_bpm else 0.0)
            if tid == "8":
                r["t8_bpm50"].append(1.0 if abs(float(song.get("bpm") or 0) - fixed_bpm / 2) < 0.5 else 0.0)
                r["t8_change"].append(mean([1 - similarity(codes.get(k, ""), fixed[k]) for k in fixed]))
        rows.append(r)
    return rows


def cli_overhead(config: dict, root: Path) -> dict:
    """Median input tokens per call of each CLI route minus the median over OpenRouter models: the part that is
    the CLI's own system prompt and tool setup (rough: tokenizers differ)."""
    per_via = {}
    for m in config["models"]:
        for job in core.plan_jobs(config, models=[m["id"]]):
            for x in core.read_jsonl(core.job_log(m["id"], job["task"]["id"], job["rep"], root)):
                if x.get("kind") in ("edit", "listen") and x.get("usage"):
                    per_via.setdefault(m["via"], []).append(cli_tokens(x["usage"])["input"])
    base = statistics.median(per_via.get("openrouter", [0]))
    return {v: max(statistics.median(xs) - base, 0) for v, xs in per_via.items() if v != "openrouter"} | {"_base": base}


def fmt(v, d=1, pre=""):
    return "-" if v is None else f"{pre}{v:.{d}f}"


def usd(v):
    return "-" if v is None else (f"${v:.4f}" if v < 0.1 else f"${v:.3f}")


def tables(config: dict, rows: list[dict], hum: dict, overhead: dict, source: str) -> str:
    for r in rows:
        r["score"] = mean(r["judged"])
        r["ci"] = jd.bootstrap([v for v in r["judged"] if v is not None])
        r["per_job"] = mean(r["cost"])
        r["per_ok"] = sum(r["cost"]) / r["ok"] if r["ok"] else None
        r["per_ok_adj"] = sum(r["cost_adj"]) / r["ok"] if r["ok"] else None
        r["per_ok_paid"] = sum(r["cost_paid"]) / r["ok"] if r["ok"] else None
    for r in rows:  # Pareto: no other model is cheaper-or-equal per successful song with a higher-or-equal score
        r["front"] = r["score"] is not None and not any(
            o is not r and o["score"] is not None and o["per_ok"] <= r["per_ok"] and o["score"] >= r["score"]
            and (o["per_ok"] < r["per_ok"] or o["score"] > r["score"]) for o in rows)
    out = [f"단가 출처: OpenRouter 공개 모델 목록({source}). CLI 입력 토큰 중앙값이 OpenRouter 호출 중앙값"
           f"({overhead['_base']:.0f})보다 큰 몫: agy {overhead.get('agy', 0):.0f}, codex {overhead.get('codex', 0):.0f} 토큰/호출.", "",
           "### 표 1 — 가성비 (곡 하나당 원가, 공개 API 요금 기준)", "",
           "| 모델 | 연결 | 작업당 원가 | 성공 곡당 원가 | 성공 곡당(CLI 몫 뺀 추정) | 성공률 | 심판 합산 (95%) | 사람 블라인드 승률 (n) | 점수 1점당 원가 | 파레토 |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: r["per_ok"] if r["per_ok"] is not None else 9):
        h = hum.get(r["model"])
        hs = f"{h['win_rate'] * 100:.0f}% ({h['n']})" if h else "-"
        note = ""
        if r["via"] != "openrouter":
            note = " *"
        if r["model"].endswith(":free"):
            note = f" (유료판 {usd(r['per_ok_paid'])})"
        adj = usd(r["per_ok_adj"]) if r["via"] != "openrouter" else "-"
        ci = f" ({r['ci'][0]:.0f}~{r['ci'][1]:.0f})" if r["ci"] else ""
        per_point = r["per_ok"] / r["score"] if r["score"] else None
        out.append(f"| {r['model']} | {r['via']}{note} | {usd(r['per_job'])} | {usd(r['per_ok'])} | {adj} | "
                   f"{r['ok']}/{r['jobs']} | {fmt(r['score'])}{ci} | {hs} | {'-' if per_point is None else f'${per_point:.6f}'} | {'앞줄' if r['front'] else ''} |")
    out += ["", "\\* 구독 CLI라 기록 원가가 0: 기록된 토큰 x OpenRouter 같은 모델 단가로 환산. CLI 자체 시스템 프롬프트·도구 설명이 "
            "입력 토큰에 섞여 있어 실제 API 직접 호출보다 비싸게 나온다. 'CLI 몫 뺀 추정'은 호출마다 위 차이만큼 입력을 뺀 값(토크나이저가 달라 대략).",
            f"사람 블라인드: 투표자 {hum.get('_voters', 0)}명, 첫 선택 {hum.get('_choices', 0)}개. 결승 5개 모델만 들었다.", "",
            "### 표 2 — 모델별 음악 특징 (기존 기록)", "",
            "| 모델 | 실패 원인 | 7번 다른 트랙 건드림 / 베이스 변화율 | 8번 bpm 50 / 전체 변화율 | 소리 이름 종류 (곡당) | 자주 쓰는 소리 | 트랙 수 | LUFS / 클리핑 곡 | 라운드 / 되돌림 | 자기-심판 | 작업 시간(초) |",
            "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        fails = ", ".join(f"{k} {v}" for k, v in r["fail_reasons"].most_common()) or "-"
        if r["infra"]:
            fails += f" (하네스 장애 {r['infra']} 제외)"
        t7 = f"{fmt(mean(r['t7_other']) and mean(r['t7_other']) * 100, 0)}% / {fmt(mean(r['t7_bass_change']) and mean(r['t7_bass_change']) * 100, 0)}% (n={len(r['t7_other'])})" if r["t7_other"] else "-"
        t8 = f"{fmt(mean(r['t8_bpm50']) * 100, 0)}% / {fmt(mean(r['t8_change']) * 100, 0)}% (n={len(r['t8_bpm50'])})" if r["t8_bpm50"] else "-"
        top = ", ".join(k for k, _ in r["sounds"].most_common(5))
        lufs = f"{fmt(mean(r['lufs']))} / {fmt(mean(r['clip']) and mean(r['clip']) * 100, 0)}%" if r["lufs"] else "-"
        rounds = f"{fmt(mean(r['rounds']))} / {fmt(mean(r['reverted']) and mean(r['reverted']) * 100, 0)}%"
        out.append(f"| {r['model']} | {fails} | {t7} | {t8} | {len(r['sounds'])} ({fmt(mean(r['sound_sets']))}) | {top} | "
                   f"{fmt(mean(r['tracks']))} | {lufs} | {rounds} | {fmt(mean(r['self_minus']), 1, '+' if (mean(r['self_minus']) or 0) > 0 else '')} | "
                   f"{fmt(statistics.median([s for s in r['seconds'] if s] or [0]), 0)} |")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", default=str(core.RESULTS))
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    root = Path(args.results)
    config = core.load_config()
    table, source = prices()
    overhead = cli_overhead(config, root)
    rows = collect(config, root, table, overhead)
    text = tables(config, rows, human(root), overhead, source)
    print(text)
    if args.json:
        dump = [{k: (dict(v) if isinstance(v, Counter) else v) for k, v in r.items()} for r in rows]
        Path(args.json).write_text(json.dumps(dump, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
