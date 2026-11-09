"""Running the public server safely: password tries, the log file, and daily copies of the SQLite files.

Nothing here calls a model or the ledger, so it stays testable without Streamlit."""
from __future__ import annotations

import datetime
import logging
import logging.handlers
import re
import shutil
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger("olmuse")

# ---------- redaction ----------
SECRET_PATTERNS = [
    (re.compile(r"sk-or-[0-9A-Za-z_-]{10,}"), "[redacted]"),
    (re.compile(r"sk-ant-[0-9A-Za-z_-]{10,}"), "[redacted]"),
    (re.compile(r"AIza[0-9A-Za-z_-]{20,}"), "[redacted]"),
    (re.compile(r"(?i)bearer\s+[0-9A-Za-z._~+/=-]{8,}"), "Bearer [redacted]"),
    (re.compile(r"[0-9a-f]{64}"), "[key]"),  # tokens, peppers and account keys are 64 hex digits
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[email]"),
]


def scrub(text) -> str:
    """Keys, tokens and emails taken out by their look, so a value is hidden whatever name it was logged under."""
    text = str(text)
    for pattern, sub in SECRET_PATTERNS:
        text = pattern.sub(sub, text)
    return text


class ScrubFilter(logging.Filter):
    def filter(self, record):
        record.msg = scrub(record.getMessage())
        record.args = ()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = scrub(record.exc_text)
        return True


def setup_logging(folder, days: int = 7) -> Path:
    """One file per day under folder (olmuse.log, olmuse.log.YYYY-MM-DD), `days` old files kept.
    Calling it again does nothing. Thread crashes are logged with their traceback."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "olmuse.log"
    root = logging.getLogger()
    if any(getattr(h, "olmuse", False) for h in root.handlers):
        return path
    handler = logging.handlers.TimedRotatingFileHandler(path, when="midnight", backupCount=days, encoding="utf-8")
    handler.olmuse = True
    handler.addFilter(ScrubFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)
    root.setLevel(min(root.level or logging.INFO, logging.INFO))
    streamlit_log = logging.getLogger("streamlit")
    if not streamlit_log.propagate:  # Streamlit keeps its own console handler; send its errors to the file too
        streamlit_log.addHandler(handler)

    def thread_crash(args):
        log.error("thread %s crashed", getattr(args.thread, "name", "?"),
                  exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    threading.excepthook = thread_crash
    return path


# ---------- password tries ----------
class PasswordGate:
    """The teacher password's tries. A session is locked for `lock_seconds` after `session_tries` wrong answers, and
    every session is locked for the rest of the hour after `hourly_tries` wrong answers in all (a new browser
    session would otherwise start a fresh count)."""

    def __init__(self, session_tries: int = 5, hourly_tries: int = 20, lock_seconds: int = 900, clock=time.time):
        self.session_tries, self.hourly_tries, self.lock_seconds, self.clock = session_tries, hourly_tries, lock_seconds, clock
        self.lock = threading.Lock()
        self.failures: list[float] = []            # times of wrong answers, all sessions
        self.sessions: dict[str, list[float]] = {}  # session -> times of its wrong answers

    def _trim(self, now):
        self.failures = [t for t in self.failures if now - t < 3600]
        for s in list(self.sessions):
            self.sessions[s] = [t for t in self.sessions[s] if now - t < self.lock_seconds]
            if not self.sessions[s]:
                del self.sessions[s]

    def locked(self, session: str) -> bool:
        with self.lock:
            now = self.clock()
            self._trim(now)
            return len(self.failures) >= self.hourly_tries or len(self.sessions.get(session, ())) >= self.session_tries

    def check(self, session: str, entered: str, password: str) -> str:
        """"ok", "wrong" or "locked". A locked gate does not even compare."""
        import hmac
        if self.locked(session):
            return "locked"
        if password and hmac.compare_digest(str(entered).encode(), password.encode()):
            return "ok"
        with self.lock:
            now = self.clock()
            self.failures.append(now)
            self.sessions.setdefault(session, []).append(now)
            total = len(self.failures)
        log.warning("wrong studio password (%d in the last hour)", total)
        if total == self.hourly_tries:
            log.error("ALERT studio password locked for the hour after %d wrong tries", total)
        return "wrong"


# ---------- SQLite backups ----------
def data_files(folder) -> list[Path]:
    """The SQLite databases in folder, without their -wal/-shm/-journal companions."""
    return sorted(p for p in Path(folder).glob("*.sqlite*")
                  if p.is_file() and not p.name.endswith(("-wal", "-shm", "-journal")))


def backup_sqlite(folder, dest, keep: int = 14, day: str = "") -> Path:
    """Copies every database in folder to dest/<day>/ with SQLite's backup API (a plain file copy can miss what is
    still in the -wal file), then keeps only the newest `keep` day folders. Returns the day folder."""
    day = day or datetime.date.today().isoformat()
    out = Path(dest) / day
    out.mkdir(parents=True, exist_ok=True)
    for src in data_files(folder):
        target = out / src.name
        part = target.with_name(target.name + ".part")
        a, b = sqlite3.connect(src), sqlite3.connect(part)
        try:
            a.backup(b)
            b.execute("pragma journal_mode=delete")  # the copy is one self-contained file
        finally:
            a.close()
            b.close()
        part.replace(target)
    days = sorted(p for p in Path(dest).iterdir() if p.is_dir() and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.name))
    for old in days[:-keep] if keep > 0 else []:
        shutil.rmtree(old, ignore_errors=True)
    return out


def start_daily_backup(folder, dest, keep: int = 14, every: float = 3600) -> threading.Thread:
    """Makes today's copy if it is missing, then checks again every `every` seconds."""
    def loop():
        while True:
            try:
                if not (Path(dest) / datetime.date.today().isoformat()).exists():
                    log.info("backup written to %s", backup_sqlite(folder, dest, keep))
            except Exception:
                log.exception("backup failed")
            time.sleep(every)
    thread = threading.Thread(target=loop, name="olmuse-backup", daemon=True)
    thread.start()
    return thread
