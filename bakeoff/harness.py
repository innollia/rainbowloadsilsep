"""Bakeoff patches for the real studio (app.py): every model call recorded. Imported once by harness_app.py.

run.py starts this with BAKEOFF_CONTROL pointing at a small JSON file it rewrites before each job
({"model": {...}, "effort": "medium", "log": "<job>.jsonl"}). Product code is not changed: the job loop,
limits and prompts are the studio's own; only the engine is swapped and the job's end is written down.
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import studio_backend as sb  # noqa: E402
import core  # noqa: E402


def control() -> dict:
    return json.loads(Path(os.environ["BAKEOFF_CONTROL"]).read_text(encoding="utf-8"))


class BakeoffModel:
    """Stands where the Router stands. Each job gets the engine run.py named, wrapped in a Recorder."""

    name = "Bakeoff"
    hears = False

    def __init__(self):
        self.current = None

    def choices(self, lang: str = sb.DEFAULT_LANG) -> dict:
        return {"models": [{"id": "bakeoff", "label": "bakeoff"}],
                "efforts": [{"id": e, "label": sb.msg(lang, "effort_" + e)} for e in sb.EFFORTS],
                "model": "bakeoff", "effort": sb.DEFAULT_EFFORT}

    def engine(self, model: str = "", effort: str = ""):
        spec = control()
        self.current = core.Recorder(core.build_engine(spec["model"], spec.get("effort", "medium")), Path(spec["log"]))
        self.current.note(kind="start", model=spec["model"]["id"], via=spec["model"]["via"], task=spec.get("task"),
                          rep=spec.get("rep"), effort=spec.get("effort", "medium"))
        return self.current

    def stop(self):
        if self.current:
            self.current.stop()


_Progress = sb.Progress


class Progress(_Progress):
    def __init__(self, job):
        super().__init__(job)
        job.progress = self


_merge = sb.merge_candidate


_Jobs = sb.Jobs


class BakeoffJobs(_Jobs):
    def __init__(self, model=None, **kw):
        super().__init__(BakeoffModel(), **kw)

    def _wait(self, job, seq):
        result = super()._wait(job, seq)
        recorder = self.model.current
        if recorder and not result.get("ok"):
            recorder.note(kind="run_error", seq=seq, error=str(result.get("error", ""))[:500])
        return result

    def _run(self, job):
        try:
            super()._run(job)
        finally:
            self._finish(job)

    def _finish(self, job):
        recorder = self.model.current
        if recorder is None:
            return
        p = getattr(job, "progress", None)
        view = job.snapshot()
        reverted = bool(p and p.best_state is not None and p.best_state is not p.state)
        final = (p.best_state if reverted else p.state) if p else None
        recorder.note(kind="end", status=view["status"], messages=view["messages"], rounds_listened=recorder.listens,
                      final_round=(p.best_round if reverted else recorder.listens) if p else 0, reverted=reverted,
                      edits=p.edits if p else 0, fixes=p.fixes if p else 0, final_song=final,
                      seconds=round(time.monotonic() - job.started, 1))


def merge_candidate(base, reply, target, lang=sb.DEFAULT_LANG):
    try:
        return _merge(base, reply, target, lang)
    except ValueError as exc:
        harness = getattr(sb, "_bakeoff_jobs", None)
        if harness and harness.model.current:
            harness.model.current.note(kind="format_reject", error=str(exc)[:300])
        raise


def install():
    """Swap the studio's engine for the recorded one. Called once by harness_app.py, never on import."""
    if getattr(sb, "_bakeoff_patched", False):
        return
    sb._bakeoff_patched = True
    sb.MIN_JOB_SECONDS = 900  # the same, longer wall-clock limit for every model: CLI start-up is not the model's fault
    sb.Progress = Progress
    sb.merge_candidate = merge_candidate

    def make_jobs(*args, **kw):
        sb._bakeoff_jobs = BakeoffJobs(*args, **kw)
        return sb._bakeoff_jobs

    sb.Jobs = make_jobs
