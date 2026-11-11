"""How often does the site's model write Akkado that renders? (GAME_ASSET_PLAN order 3; spends the OpenRouter key.)

For each request the model writes a patch from asset_engine/akkado_guide.md, the adapter renders it, and a failed
render is handed back with its error up to REPAIRS times. Prints the first-try and after-repair pass rates and
writes every WAV and source to --out for listening.

    python tools/akkado_trial.py --out out/akkado_trial [--model id] [--only sfx|ambience|music] [--limit n]
"""
import argparse
import array
import io
import json
import math
import os
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import studio_backend as sb  # noqa: E402
from asset_engine import nkido  # noqa: E402

REPAIRS = 2
SCHEMA = {"type": "object", "required": ["source", "seconds", "bpm"], "properties": {
    "source": {"type": "string", "description": "the whole Akkado patch"},
    "seconds": {"type": "number", "description": "render length in seconds"},
    "bpm": {"type": "number", "description": "tempo, 0 when the patch has no beat"}}}

REQUESTS = [
    ("sfx", "ui_click", "A short, soft UI button click.", 0.3),
    ("sfx", "ui_confirm", "A pleasant two-note confirm chime for a menu.", 0.6),
    ("sfx", "ui_error", "A low buzzy error blip that says 'not allowed'.", 0.4),
    ("sfx", "jump", "A cartoony jump with a rising pitch.", 0.4),
    ("sfx", "land", "A dull thud of a character landing on dirt.", 0.3),
    ("sfx", "coin", "A bright coin pickup, two quick high notes.", 0.5),
    ("sfx", "laser", "A sci-fi laser shot with a falling pitch.", 0.4),
    ("sfx", "explosion", "A medium explosion with a rumbling tail.", 1.5),
    ("sfx", "hit", "A punchy melee hit impact.", 0.3),
    ("sfx", "powerup", "A rising arpeggio power-up.", 1.0),
    ("sfx", "door", "A heavy stone door sliding shut.", 1.2),
    ("sfx", "footstep", "One footstep on gravel.", 0.25),
    ("ambience", "wind", "A seamless loop of gentle wind over an open field.", 8.0),
    ("ambience", "rain", "A seamless loop of steady rain.", 8.0),
    ("ambience", "cave", "A seamless loop of a dark cave: low drone and occasional drips.", 8.0),
    ("ambience", "machine", "A seamless loop of a humming machine room.", 8.0),
    ("ambience", "night", "A seamless loop of a calm night with crickets.", 8.0),
    ("ambience", "fire", "A seamless loop of a crackling campfire.", 8.0),
    ("music", "menu", "A calm 4-bar menu loop at 90 BPM. Stems: melody, bass, drums.", 10.667),
    ("music", "battle", "A tense 4-bar battle loop at 140 BPM. Stems: lead, bass, drums.", 6.857),
    ("music", "village", "A cheerful 4-bar village tune at 110 BPM. Stems: melody, bass.", 8.727),
    ("music", "boss", "A dark 4-bar boss loop at 120 BPM. Stems: lead, bass, drums.", 8.0),
    ("music", "victory", "A short victory fanfare, 2 bars at 120 BPM. Stems: melody, bass.", 4.0),
    ("music", "puzzle", "A light, sparse 4-bar puzzle loop at 100 BPM. Stems: melody, pad.", 9.6),
]


def key() -> str:
    found = os.environ.get("OPENROUTER_API_KEY", "")
    if found:
        return found
    try:
        lines = (Path.home() / ".all-tomorrow" / "key-pool.env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        name, _, value = line.removeprefix("export ").partition("=")
        if name.strip() == "OPENROUTER_API_KEY":
            return value.strip().strip("'\"")
    return ""


def levels(data: bytes) -> dict:
    """Peak and tail level in dBFS from a 16-bit WAV."""
    with wave.open(io.BytesIO(data)) as w:
        frames, rate, channels = w.readframes(w.getnframes()), w.getframerate(), w.getnchannels()
    samples = array.array("h", frames)
    if not samples:
        return {"peak": -120.0, "tail": -120.0, "clipped": 0}
    db = lambda v: round(20 * math.log10(max(v, 1e-6)), 1)  # noqa: E731
    peak = max(abs(s) for s in samples) / 32768.0
    tail = samples[-int(rate * channels * 0.05):]
    rms = math.sqrt(sum(s * s for s in tail) / len(tail)) / 32768.0
    return {"peak": db(peak), "tail": db(rms), "clipped": sum(1 for s in samples if abs(s) >= 32767)}


def judge(kind: str, made: nkido.Rendered) -> list[str]:
    """Faults a render can have even though it compiled."""
    got, faults = levels(made.wav), []
    if got["peak"] < -40:
        faults.append(f"silent (peak {got['peak']} dBFS)")
    if got["clipped"] > 8:
        faults.append(f"clipped ({got['clipped']} samples)")
    if kind == "sfx" and got["tail"] > -40:
        faults.append(f"one-shot does not end (tail {got['tail']} dBFS)")
    if kind == "music" and len(made.stems) < 2:
        faults.append(f"music needs 2+ labelled stems, got {sorted(made.stems)}")
    return faults


def ask_text(kind: str, text: str, seconds: float) -> str:
    return (f"Write one Akkado patch for a game sound asset.\nKind: {kind}\nRequest: {text}\n"
            f"Target length: about {seconds:g} seconds.\nReturn the whole patch in `source`, the render length in "
            "`seconds`, and the tempo in `bpm` (0 when there is no beat).")


def run(model, kind: str, name: str, text: str, seconds: float, out: Path) -> dict:
    prompt, row = ask_text(kind, text, seconds), {"kind": kind, "name": name, "tries": [], "cost": 0.0}
    for attempt in range(REPAIRS + 1):
        try:
            reply = model.ask(prompt, SCHEMA, "akkado_patch")
        except sb.ModelError as exc:
            # A cut-off or broken reply spends a try like a failed render does; the same request is asked again.
            row["cost"] += float(model.last_usage.get("cost") or 0)
            row["tries"].append({"faults": [f"model: {exc}"], "seconds": 0, "stems": []})
            continue
        row["cost"] += float(model.last_usage.get("cost") or 0)
        source = str(reply.get("source") or "")
        length = min(max(float(reply.get("seconds") or seconds), 0.1), 30.0)
        (out / f"{name}.{attempt}.akkado").write_text(source, encoding="utf-8")
        try:
            made, used = nkido.render_mended(source, length, float(reply.get("bpm") or 0) or None)
            if used != source:
                row["mended"] = row.get("mended", 0) + 1
                (out / f"{name}.{attempt}.akkado").write_text(used, encoding="utf-8")
            faults = judge(kind, made)
        except nkido.RenderError as exc:
            made, faults = None, [f"{exc.kind}: line {exc.line}: {exc.message}"]
        row["tries"].append({"faults": faults, "seconds": length, "stems": sorted(made.stems) if made else []})
        if made:
            (out / f"{name}.{attempt}.wav").write_bytes(made.wav)
        if not faults:
            break
        prompt = (ask_text(kind, text, seconds) + "\n\nYour previous patch:\n```\n" + source + "\n```\nIt failed: "
                  + "; ".join(faults) + "\nFix it and return the whole patch again.")
    last = row["tries"][-1] if row["tries"] else {}
    row["passed"] = bool(row["tries"]) and last.get("faults") == []
    row["first_try"] = row["passed"] and len(row["tries"]) == 1
    return row


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--out", default=str(ROOT / "out" / "akkado_trial"))
    args.add_argument("--model", default=sb.DEFAULT_CHOICE)
    args.add_argument("--only", default="")
    args.add_argument("--limit", type=int, default=0)
    args.add_argument("--effort", default="")
    opts = args.parse_args()
    secret = key()
    if not secret:
        sys.exit("no OpenRouter key")
    guide = (ROOT / "asset_engine" / "akkado_guide.md").read_text(encoding="utf-8")
    model = sb.OpenRouter(secret, opts.model, effort=opts.effort, system=guide, timeout=180)
    out = Path(opts.out)
    out.mkdir(parents=True, exist_ok=True)
    todo = [r for r in REQUESTS if not opts.only or r[0] == opts.only]
    todo = todo[:opts.limit] if opts.limit else todo
    rows, started = [], time.time()
    for kind, name, text, seconds in todo:
        row = run(model, kind, name, text, seconds, out)
        rows.append(row)
        why = "" if row["passed"] else " | " + "; ".join((row["tries"][-1] if row["tries"] else {}).get("faults", ["?"]))[:160]
        print(f"{kind:9}{name:12}{'pass' if row['passed'] else 'FAIL'} tries={len(row['tries'])}{why}", flush=True)
    total = len(rows) or 1
    summary = {"model": opts.model, "effort": opts.effort, "requests": len(rows),
               "first_try": sum(r["first_try"] for r in rows), "after_repair": sum(r["passed"] for r in rows),
               "cost_usd": round(sum(r["cost"] for r in rows), 4), "mended": sum(r.get("mended", 0) for r in rows), "seconds": round(time.time() - started)}
    for kind in ("sfx", "ambience", "music"):
        some = [r for r in rows if r["kind"] == kind]
        if some:
            summary[kind] = f"{sum(r['first_try'] for r in some)}/{sum(r['passed'] for r in some)}/{len(some)}"
    (out / "result.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")
    print(json.dumps(summary), f"first-try {summary['first_try'] / total:.0%}, after repair {summary['after_repair'] / total:.0%}")


if __name__ == "__main__":
    main()
