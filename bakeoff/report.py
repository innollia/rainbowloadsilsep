"""Bakeoff report: metrics per model, score vs cost picture, finalists (docs/MODEL_BAKEOFF_PLAN.md 5 and 7).

Writes results/report.md, results/report.json and results/score_vs_cost.svg.
  python bakeoff/report.py
"""
from __future__ import annotations

import json
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402
import studio_backend as sb  # noqa: E402
from referee import final_wav  # noqa: E402

FORMAT_ERRORS = ("openrouter_parse", "openrouter_cut", "agy_parse", "agy_failed", "codex_failed", "claude_parse",
                 "claude_cut", "gemini_parse")
CLI = ("agy", "codex")


def first_try(records: list[dict]) -> bool:
    """The first edit's result ran without any fix."""
    for r in records:
        kind = r.get("kind")
        if kind == "edit" and "error" in r:
            return False
        if kind in ("format_reject", "run_error"):
            return False
        if kind == "listen":
            return True
    return False


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.fmean(values) if values else None


def bootstrap(values, n=2000, seed=1):
    values = [v for v in values if v is not None]
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(statistics.fmean(rng.choices(values, k=len(values))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def collect(config: dict, root: Path) -> list[dict]:
    referee = {}
    for r in core.read_jsonl(root / "referee.jsonl"):
        if r.get("score") is not None:
            referee.setdefault((r["model"], r["task"], r["rep"]), {})[r["judge"]] = r["score"]
    stops = {(r["model"], r["task"], r["rep"]) for r in core.read_jsonl(root / "budget_stops.jsonl")}
    rows = []
    for job in core.plan_jobs(config):
        model, task, rep = job["model"], job["task"], job["rep"]
        log = core.job_log(model["id"], task["id"], rep, root)
        records = core.read_jsonl(log)
        result = core.outcome(records)
        if result == "missing" and (model["id"], task["id"], rep) in stops:
            result = "budget"
        end = core.end_of(records) or {}
        row = {"model": model["id"], "via": model["via"], "tier": model["tier"], "task": task["id"], "star": bool(task.get("star")),
               "rep": rep, "result": result, "status": end.get("status"), "fixes": end.get("fixes"),
               "seconds": end.get("seconds"), "cost": core.spent(records) + sum(core.spent(core.read_jsonl(p))
                                                                              for p in (log.parent / "old").glob(f"{log.stem}.try*.jsonl")),
               "call_seconds": sum(r.get("seconds", 0) for r in records if r.get("kind") in ("edit", "listen")),
               "edits": sum(1 for r in records if r.get("kind") == "edit"),
               "format_errors": sum(1 for r in records if r.get("kind") == "format_reject"
                                    or (r.get("kind") == "edit" and r.get("error") in FORMAT_ERRORS)),
               "first_try": first_try(records), "referee": referee.get((model["id"], task["id"], rep), {})}
        listens = [r for r in records if r.get("kind") == "listen" and isinstance(r.get("reply"), dict)]
        n = end.get("final_round") or 0
        row["self_score"] = listens[n - 1]["reply"].get("score") if 0 < n <= len(listens) else None
        wav = final_wav(log, end) if result == "success" else None
        if wav:
            report = sb.signal_report(wav.read_bytes(), "en")
            row["silent"], row["clipping"] = report["silent"], bool(report["metrics"].get("clipped_samples"))
        row["judged"] = mean(row["referee"].values())
        rows.append(row)
    return rows


def summarize(config: dict, rows: list[dict]) -> list[dict]:
    out = []
    for m in config["models"]:
        mine = [r for r in rows if r["model"] == m["id"]]
        ran = [r for r in mine if r["result"] in ("success", "fail")]
        ok = [r for r in ran if r["result"] == "success"]
        edits = sum(r["edits"] for r in ran)
        star = [r["judged"] for r in ok if r["star"]]
        costs = [r["cost"] for r in ran]
        row = {
            "model": m["id"], "via": m["via"], "tier": m["tier"], "billing": "구독" if m["via"] in CLI else "OpenRouter",
            "planned": len(mine), "ran": len(ran), "infra": sum(r["result"] == "infra" for r in mine),
            "budget": sum(r["result"] == "budget" for r in mine),
            "success_rate": len(ok) / len(ran) if ran else None,
            "first_try_rate": sum(r["first_try"] for r in ran) / len(ran) if ran else None,
            "fixes": mean([r["fixes"] for r in ran]),
            "format_error_rate": sum(r["format_errors"] for r in ran) / edits if edits else None,
            "silent_rate": mean([1.0 if r.get("silent") else 0.0 for r in ok]),
            "clipping_rate": mean([1.0 if r.get("clipping") else 0.0 for r in ok]),
            "referee_A": mean([r["referee"].get("A") for r in ok]), "referee_B": mean([r["referee"].get("B") for r in ok]),
            "star_score": mean(star), "star_ci": bootstrap(star),
            "self_minus_referee": mean([r["self_score"] - r["judged"] for r in ok
                                        if r["self_score"] is not None and r["judged"] is not None]),
            "job_seconds": mean([r["seconds"] for r in ran]), "call_seconds": mean([r["call_seconds"] for r in ran]),
            "cost_per_job": mean(costs) if costs else None, "spent": sum(r["cost"] for r in mine),
        }
        row["qualified"] = (row["success_rate"] or 0) >= 0.75 and (row["format_error_rate"] or 0) <= 0.25
        row["score_per_usd"] = (row["star_score"] / row["cost_per_job"]
                                if row["star_score"] is not None and row["cost_per_job"] else None)
        out.append(row)
    return out


def finalists(summary: list[dict], size: int = 6) -> list[str]:
    """Best qualified model per price tier, plus the current default and Sonnet; filled to six by score (plan 6)."""
    ranked = sorted((s for s in summary if s["qualified"] and s["star_score"] is not None), key=lambda s: -s["star_score"])
    picks = []
    for tier in ("무료", "초저가", "중가", "고가"):
        best = next((s["model"] for s in ranked if s["tier"] == tier), None)
        if best and best not in picks:
            picks.append(best)
    for must in ("gemini-3.8-flash", "anthropic/claude-sonnet-5.5"):
        if must not in picks and any(s["model"] == must and s["star_score"] is not None for s in summary):
            picks.append(must)
    for s in ranked:
        if len(picks) >= size:
            break
        if s["model"] not in picks:
            picks.append(s["model"])
    return picks[:size]


def pareto(summary: list[dict]) -> set[str]:
    pts = [s for s in summary if s["star_score"] is not None and s["cost_per_job"] is not None]
    return {s["model"] for s in pts if not any(o["star_score"] >= s["star_score"] and o["cost_per_job"] <= s["cost_per_job"]
                                               and (o["star_score"], o["cost_per_job"]) != (s["star_score"], s["cost_per_job"])
                                               for o in pts)}


def svg(summary: list[dict]) -> str:
    pts = [s for s in summary if s["star_score"] is not None and s["cost_per_job"] is not None]
    w, h, pad = 760, 460, 60
    top = max([s["cost_per_job"] for s in pts] + [0.01])
    x = lambda c: pad + (w - 2 * pad) * (c / top)  # noqa: E731
    y = lambda v: h - pad - (h - 2 * pad) * (v / 100)  # noqa: E731
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" font-family="sans-serif" font-size="12">',
             f'<rect width="{w}" height="{h}" fill="#fff"/>',
             f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="#333"/>',
             f'<line x1="{pad}" y1="{pad}" x2="{pad}" y2="{h - pad}" stroke="#333"/>',
             f'<text x="{w / 2}" y="{h - 20}" text-anchor="middle">cost per job (USD; subscription CLI = 0)</text>',
             f'<text x="16" y="{h / 2}" transform="rotate(-90 16 {h / 2})" text-anchor="middle">referee score, star tasks</text>']
    for v in (0, 25, 50, 75, 100):
        parts.append(f'<text x="{pad - 8}" y="{y(v) + 4}" text-anchor="end">{v}</text>')
    for s in pts:
        color = "#888" if s["via"] in CLI else "#1f6feb"
        parts.append(f'<circle cx="{x(s["cost_per_job"]):.1f}" cy="{y(s["star_score"]):.1f}" r="5" fill="{color}"/>')
        parts.append(f'<text x="{x(s["cost_per_job"]) + 7:.1f}" y="{y(s["star_score"]) - 6:.1f}">{s["model"].split("/")[-1]}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def fmt(v, kind=""):
    if v is None:
        return "-"
    if kind == "%":
        return f"{v * 100:.0f}%"
    if kind == "$":
        return f"${v:.4f}"
    return f"{v:.1f}" if isinstance(v, float) else str(v)


def markdown(summary: list[dict], picks: list[str], front: set[str]) -> str:
    lines = ["# 모델 대결 결과", "", "심판 점수는 측정표 기반(A: agy Gemini 3.8 Flash, B: OpenRouter Qwen 3.8 Flash). "
             "CLI 모델(agy·codex)은 구독이라 원가 $0으로 적었다. 최종 판단은 사람 블라인드 청취(/listen)로 한다.", "",
             "| 모델 | 연결 | 가격대 | 과금 | 돌린 작업 | 성공률 | 첫 시도 | 고치기 | 형식 오류 | 무음 | 클리핑 | 심판 A | 심판 B | ★점수 (95%) | 자기−심판 | 작업 초 | 작업당 원가 | 점수/$ | 자격 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in summary:
        ci = f" ({s['star_ci'][0]:.0f}–{s['star_ci'][1]:.0f})" if s["star_ci"] else ""
        mark = (" ◆" if s["model"] in front else "") + (" ★결선" if s["model"] in picks else "")
        lines.append("| " + " | ".join([
            s["model"] + mark, s["via"], s["tier"], s["billing"], f"{s['ran']}/{s['planned']}"
            + (f" (기반실패 {s['infra']})" if s["infra"] else "") + (f" (예산 {s['budget']})" if s["budget"] else ""),
            fmt(s["success_rate"], "%"), fmt(s["first_try_rate"], "%"), fmt(s["fixes"]), fmt(s["format_error_rate"], "%"),
            fmt(s["silent_rate"], "%"), fmt(s["clipping_rate"], "%"), fmt(s["referee_A"]), fmt(s["referee_B"]),
            fmt(s["star_score"]) + ci, fmt(s["self_minus_referee"]), fmt(s["job_seconds"]),
            fmt(s["cost_per_job"], "$"), "무료" if s["score_per_usd"] is None and s["star_score"] is not None else fmt(s["score_per_usd"]),
            "O" if s["qualified"] else "X"]) + " |")
    spent = sum(s["spent"] for s in summary if s["via"] == "openrouter")
    lines += ["", f"OpenRouter 실제 지출(후보): ${spent:.4f}. ◆ = 점수 대 원가 파레토 앞줄.", "",
              "결선(청취 후보): " + ", ".join(picks), "", "![score vs cost](score_vs_cost.svg)", ""]
    return "\n".join(lines)


def main():
    config, root = core.load_config(), core.RESULTS
    rows = collect(config, root)
    summary = summarize(config, rows)
    picks, front = finalists(summary), pareto(summary)
    (root / "report.json").write_text(json.dumps({"summary": summary, "finalists": picks, "jobs": rows}, ensure_ascii=False,
                                                 indent=1, default=str), encoding="utf-8")
    (root / "score_vs_cost.svg").write_text(svg(summary), encoding="utf-8")
    (root / "report.md").write_text(markdown(summary, picks, front), encoding="utf-8")
    print(f"wrote {root / 'report.md'}; finalists: {', '.join(picks) or '(none yet)'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
