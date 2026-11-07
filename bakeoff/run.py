"""Model bakeoff runner (docs/MODEL_BAKEOFF_PLAN.md 3.3).

Starts the real studio locally (bakeoff/harness_app.py), drives it in headless Chrome like a user would,
and lets the studio's own loop edit, play, record and listen. Each job leaves
results/<model>/<task>-<rep>.jsonl (every call, its time, usage and reply) and -r<round>.wav captures.

Partial runs and resuming: jobs whose log already ends are skipped; an infrastructure failure
(network, rate limit, browser) is run once more. Examples:
  python bakeoff/run.py --dry-run
  python bakeoff/run.py --models qwen/qwen3.8-flash --tasks 1 --reps 1
  python bakeoff/run.py --workers 4 --finish   # everything, then referees, report and /listen clips
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import core  # noqa: E402

STORE = "strudel-ddalkkak-v1"
JOB_TIMEOUT = 25 * 60
print_lock = threading.Lock()


def say(*parts):
    with print_lock:
        print(time.strftime("%H:%M:%S"), *parts, flush=True)


def start_song(task: dict, config: dict) -> dict:
    song = config["fixed_song"] if task.get("start") == "fixed" else {"bpm": 120, "tracks": []}
    tracks = [{"raw": False, "lead": "", **t} for t in song["tracks"]]
    version = {"id": "v0", "at": int(time.time() * 1000), "summary": "start", "by": "user", "bpm": song["bpm"], "head": "",
               "tracks": tracks}
    project = {"id": "bakeoff", "name": f"task {task['id']}", "bpm": song["bpm"], "head": "", "tracks": tracks, "mix": {},
               "chat": [], "versions": [version], "versionId": "v0"}
    return {"current": "bakeoff", "projects": [project], "autoRounds": config["settings"]["rounds"]}


def job_state(model: dict, task: dict, rep: int, root: Path) -> str:
    """done, retry (an infra failure that gets its one rerun) or todo."""
    log = core.job_log(model["id"], task["id"], rep, root)
    records = core.read_jsonl(log)
    if not records:
        return "todo"
    result = core.outcome(records)
    if result in ("success", "fail"):
        return "done"
    tries = len(list((log.parent / "old").glob(f"{log.stem}.try*.jsonl")))
    if tries >= 1:  # an infrastructure failure gets one rerun, not more
        return "done"
    return "retry"


def set_aside(log: Path):
    """Keeps a failed attempt (its spend still counts) and frees the job name for the rerun."""
    old = log.parent / "old"
    old.mkdir(exist_ok=True)
    n = len(list(old.glob(f"{log.stem}.try*.jsonl"))) + 1
    for path in log.parent.glob(f"{log.stem}*"):
        if path.is_file() and (path == log or path.name.startswith(f"{log.stem}-r")):
            shutil.move(str(path), str(old / path.name.replace(log.stem, f"{log.stem}.try{n}", 1)))


class Budget:
    """Plan 8.4: a model stops at 1.3x its planned maximum; every OpenRouter job stops near an empty account."""

    def __init__(self, config: dict, root: Path):
        self.config, self.root = config, root
        self.key = core.openrouter_key()
        self.lock = threading.Lock()
        self.stops: set[str] = set()

    def allows(self, model: dict) -> tuple[bool, str]:
        if model["via"] != "openrouter":
            return True, ""
        with self.lock:
            if model["id"] in self.stops:
                return False, "stopped earlier"
            cap = core.model_cap(model, self.config)
            used = core.model_spent(model["id"], self.root)
            if cap and used >= cap:
                self.stops.add(model["id"])
                return False, f"model budget: spent ${used:.3f} of cap ${cap:.3f}"
            left = core.openrouter_left(self.key)
            if left is not None and left < float(self.config["budget"]["openrouter_floor_usd"]):
                return False, f"OpenRouter credits nearly empty (${left:.2f} left)"
        return True, ""


def server_env(control: Path, port: int) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("STUDIO_PASSWORD", "STRUDEL_DEV_EMAIL", "AI_PROVIDER", "STRUDEL_ENGINE", "STRUDEL_CREDITS_URL")}
    env.update(STRUDEL_LOCAL_AI="1", BAKEOFF_CONTROL=str(control), STRUDEL_DAILY_CALLS="1000000", PYTHONUTF8="1")
    return env


def start_server(port: int, control: Path, logfile: Path):
    stream = open(logfile, "ab")
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(HERE / "harness_app.py"), "--server.port", str(port),
                             "--server.address", "127.0.0.1", "--server.headless", "true", "--secrets.files", "no-secrets.toml"],
                            cwd=core.ROOT, env=server_env(control, port), stdout=stream, stderr=subprocess.STDOUT)
    for _ in range(120):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2)
            return proc
        except OSError:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError(f"studio did not start on port {port}; see {logfile}")


def drive(browser, port: int, job: dict, config: dict, log: Path) -> str:
    """One job in a fresh browser context, so it starts from its own song and its own server session."""
    task = job["task"]
    db = start_song(task, config)
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    errors = []
    try:
        context.add_init_script(
            "try { if (!sessionStorage.getItem('bakeoff')) { localStorage.setItem(%s, %s); sessionStorage.setItem('bakeoff', '1'); } }"
            " catch (e) {}" % (json.dumps(STORE), json.dumps(json.dumps(db, ensure_ascii=False))))
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)[:200]))
        page.goto(f"http://127.0.0.1:{port}/?lang={config['settings']['lang']}")
        frame = page.frame_locator('iframe[title*="studio"]')
        frame.locator("#ask").wait_for(timeout=60000)
        inner = next(f for f in page.frames if "studio_frontend" in f.url or "component" in f.url)
        inner.wait_for_function("document.querySelectorAll('iframe[sandbox]').length===2", timeout=60000)
        inner.wait_for_function("!document.getElementById('send').disabled", timeout=60000)
        time.sleep(3)  # the Strudel frames finish loading samples
        if task.get("target"):
            ids = [t["id"] for t in db["projects"][0]["tracks"]]
            frame.locator(".track button.pick").nth(ids.index(task["target"])).click()
        frame.locator("#ask").fill(task["text"])
        frame.locator("#ask").press("Enter")
        deadline = time.monotonic() + JOB_TIMEOUT
        while time.monotonic() < deadline:
            if core.end_of(core.read_jsonl(log)):
                break
            page.wait_for_timeout(2000)
        else:
            core.append_jsonl(log, {"kind": "end", "status": "failed", "error": "harness", "detail": "job timed out",
                                    "messages": [], "page_errors": errors})
    except Exception as exc:  # the browser side broke: an infrastructure failure, rerun once
        if not core.end_of(core.read_jsonl(log)):
            core.append_jsonl(log, {"kind": "end", "status": "failed", "error": "harness", "detail": str(exc)[:300],
                                    "messages": [], "page_errors": errors})
    finally:
        context.close()
    return core.outcome(core.read_jsonl(log))


def worker(n: int, jobs: "queue.Queue", config: dict, args, budget: Budget, tally: dict):
    from playwright.sync_api import sync_playwright

    port = args.port + n
    root = Path(args.results)
    control = root / f".control-{n}.json"
    server = start_server(port, control, root / f".server-{n}.log")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=not args.headful,
                                        args=["--autoplay-policy=no-user-gesture-required"])
            while True:
                try:
                    job = jobs.get_nowait()
                except queue.Empty:
                    return
                model, task, rep = job["model"], job["task"], job["rep"]
                label = f"{model['id']} task {task['id']} rep {rep}"
                ok, why = budget.allows(model)
                if not ok:
                    say(f"[w{n}] SKIP {label}: {why}")
                    core.append_jsonl(root / "budget_stops.jsonl", {"t": time.time(), "model": model["id"], "task": task["id"],
                                                                   "rep": rep, "why": why})
                    tally["budget"] += 1
                    continue
                log = core.job_log(model["id"], task["id"], rep, root)
                if job_state(model, task, rep, root) == "retry" or (log.exists() and not core.end_of(core.read_jsonl(log))):
                    set_aside(log)
                log.parent.mkdir(parents=True, exist_ok=True)
                control.write_text(json.dumps({"model": model, "effort": config["settings"]["effort"], "log": str(log),
                                               "task": task["id"], "rep": rep}), encoding="utf-8")
                start = time.monotonic()
                result = drive(browser, port, job, config, log)
                records = core.read_jsonl(log)
                end = core.end_of(records) or {}
                tally[result] = tally.get(result, 0) + 1
                say(f"[w{n}] {result.upper():8} {label}: {end.get('status')} in {time.monotonic() - start:.0f}s, "
                    f"${core.spent(records):.4f}, {end.get('rounds_listened', 0)} listens")
            browser.close()
    finally:
        server.terminate()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default="", help="comma-separated model ids (default: all in tasks.json)")
    ap.add_argument("--tasks", default="", help="comma-separated task ids (default: each model's assignment)")
    ap.add_argument("--reps", type=int, default=0, help="repetitions per task (default: each model's assignment)")
    ap.add_argument("--workers", type=int, default=2, help="studio servers and browsers running side by side")
    ap.add_argument("--port", type=int, default=8810)
    ap.add_argument("--results", default=str(core.RESULTS))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="show the jobs and the most they can cost, run nothing")
    ap.add_argument("--finish", action="store_true",
                    help="afterwards score with the referees, write the report and make the /listen clips")
    args = ap.parse_args(argv)
    config = core.load_config()
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]  # noqa: E731
    planned = core.plan_jobs(config, split(args.models) or None, split(args.tasks) or None, args.reps or None)
    if args.models and not planned:
        sys.exit("no such model in bakeoff/tasks.json: " + args.models)
    root = Path(args.results)
    root.mkdir(parents=True, exist_ok=True)
    todo = [j for j in core.shuffled(planned, args.seed) if job_state(j["model"], j["task"], j["rep"], root) != "done"]
    worst = sum(float(j["model"].get("job_max_usd", 0)) for j in todo)
    say(f"{len(planned)} jobs planned, {len(planned) - len(todo)} already done, {len(todo)} to run; "
        f"OpenRouter worst case ${worst:.2f}")
    if args.dry_run:
        for m in config["models"]:
            mine = [j for j in todo if j["model"]["id"] == m["id"]]
            if mine:
                say(f"  {m['id']:38} {m['via']:10} {len(mine):3} jobs  cap ${core.model_cap(m, config):.2f}  "
                    f"spent ${core.model_spent(m['id'], root):.3f}")
        return 0
    jobs: queue.Queue = queue.Queue()
    for j in todo:
        jobs.put(j)
    tally = {"success": 0, "fail": 0, "infra": 0, "budget": 0}
    budget = Budget(config, root)
    threads = [threading.Thread(target=worker, args=(n, jobs, config, args, budget, tally), daemon=True)
               for n in range(max(1, min(args.workers, len(todo))))]
    for t in threads:
        t.start()
        time.sleep(3)  # stagger studio start-ups
    for t in threads:
        t.join()
    say("finished:", json.dumps(tally))
    if args.finish:
        import clips
        import referee
        import report

        referee.main(["--results", args.results])
        report.main()
        clips.main(["--results", args.results])
    return 0


if __name__ == "__main__":
    sys.exit(main())
