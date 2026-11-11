"""The asset room's generation jobs: the store, the price, the queue, the workers and the sweeper.

One job is one draft of one sound. The API process (asset_api.py) holds one GenJobs and calls:

    quote_for(who, items, drafts)      GET  /quote
    submit(who, body)                  POST /jobs            (body is the parsed JSON object)
    status(who, ids)                   POST /jobs/status     {ids}
    status_request(who, request_id)    POST /jobs/status     {request_id}
    cancel(who, ids)                   POST /jobs/cancel     {ids}
    cancel_request(who, request_id)    POST /jobs/cancel     {request_id}
    sound(who, id) / stem(who, id, n)  GET  /jobs/{id}/sound, /jobs/{id}/stems/{n}  -> Sound(path, sha256, bytes)
    health()                           GET  /health

who is Who(kind, owner, email, lang, session) from a verified token: owner is asset_token.owner_of(payload, secret, ip).
A refusal is a GenError(status, code, **extras); message(lang, error) words it.

GenStore is its own file, asset-gen.db. It does not subclass JobStore and never opens jobs.sqlite3, so the music
screen's counts and charge records are out of reach, and because the name is not *.sqlite* the daily backup
(server_ops.backup_sqlite) leaves request text and sources out of the copies. One process owns the file at a
time (asset-gen.db.lock): a second GenStore on it is refused with StoreTaken, because a GenJobs that starts
fails whatever was queued or running.

Money. A draft of an account costs DRAFT_CREDITS and is charged when a worker picks it, after the pick is
committed. The `charge` column says where that stands:

    none        nothing was taken (password sessions, a job never picked, a charge the ledger turned down)
    pending     picked; the charge call has not answered yet
    charged     the ledger took the credit
    unknown     the ledger did not answer the charge call, so nobody knows
    refund_due  the credit must go back
    refunded    the ledger answered the refund
    kept        the result was received; never refunded

Only two callers refund: the worker that holds the job, after its own charge call answered, and the sweeper,
for rows no live worker holds whose last charge try is over REFUND_WAIT seconds old. The ledger answers a refund
of a ref it has no charge for with 200 and marks nothing, so a refund must never overtake a charge call that
may still be running; 90 seconds is longer than the ledger Lambda's 15 second limit plus the client's 10.

Nothing here calls the ledger, the model, the renderer or Node while holding the lock or a write transaction.
No streamlit import."""
from __future__ import annotations

import collections
import contextlib
import datetime
import hashlib
import json
import logging
import os
import secrets
import shutil
import sqlite3
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass, fields
from pathlib import Path

import asset_generate as ag
import studio_backend as sb
from asset_generate import GenError
from credits import LedgerError

log = logging.getLogger("olmuse.asset.jobs")

MB, GB = 1024 ** 2, 1024 ** 3
ROOT = Path(__file__).resolve().parent
DEFAULT_DB = ROOT / ".studio-data" / "asset-gen.db"
DEFAULT_RENDERS = ROOT / ".studio-data" / "asset-renders"

# ---------- price ----------
DRAFT_CREDITS = 1            # one draft of one sound; the AI's repair tries are inside it. Password sessions pay 0.
GEN_CALL_USD = {"deepseek/deepseek-v4.1-flash": 0.009}  # what one model call may cost, for the dollar counters
GEN_CALL_USD_OTHER = 0.03    # a model not in the table
MODEL_CALLS = ag.REPAIRS + 1

# ---------- queue and workers ----------
GEN_WORKERS = 6
RENDER_SLOTS = ag.RENDER_SLOTS
QUEUE_CAP = 400              # queued jobs in all; past it a new request is 503 busy
OWNER_ACTIVE = 64            # queued + running of one owner, and never over a quarter of the seats left
OWNER_UNFETCHED_BYTES = 512 * MB   # results not received yet, per owner
PW_UNFETCHED_BYTES = GB            # and for all password sessions together
JOB_SECONDS = ag.JOB_SECONDS
STALE_RUNNING = 360          # a running row this old that no live worker holds has lost its worker
QUEUE_WAIT = 7200            # a job that waited this long fails as busy
CHARGE_RETRY = (3, 10)       # seconds before the second and third charge try
REFUND_WAIT = 90
REFUND_LATE = 600            # refunds the ledger has turned down for this long are an ALERT in the log,
REFUND_ALERT_EVERY = 3600    # and one more this often for as long as it goes on
BALANCE_TTL = 60
BALANCE_RECHECK = 5          # a remembered balance this old is read again before it turns a request away for credits
LEDGER_REST = 5              # seconds a balance read the ledger did not answer is remembered for its account
BREAKER_STRIKES, BREAKER_SECONDS = 3, 60
SWEEP_EVERY = 60
PICK_RETRY = 1.0             # seconds a worker rests after the store refused a pick (a full disk, a locked file)
ACTIVE_RETRY = 30            # retry_after of too_many_active: about one draft's time

# ---------- how long things stay ----------
UNFETCHED_TTL = 3600         # a result nobody received is refunded and deleted this long after it finished
RESULT_TTL = 86400           # a received result is deleted this long after it finished
TRACE_TTL = 7 * 86400        # the row that stays behind (gone, failed, cancelled)
REQ_TTL = 48 * 3600
DISK_CAP = 4 * GB            # the renders folder
DISK_FREE_MIN = 2 * GB
SEEN_IDLE = 600              # over the disk cap, a received result nobody asked about for this long goes first
TEMP_STALE = 600             # an adapter temp folder this old was left by a killed process

# ---------- refunds the user caused ----------
REFUND_HOURLY = 12           # of one account, or of one password session; an address's own are in Limits
REFUND_DAILY = 24
USER_ENDS = ("make_failed", "timeout")  # with a cancel while running and a result never received

SCHEMA = """
create table if not exists gen (
    id text primary key, owner text, cls text, batch text, request_id text, ref text, k integer, n integer,
    ord integer, status text, stage text, attempt integer, error text, view text, input text,
    cancel integer default 0, charge text, charge_at real, est integer, usd real, bytes integer, created real,
    started real, finished real, delivered real, seen real, expires real, sess text);
create index if not exists gen_owner_status on gen (owner, status);
create index if not exists gen_request on gen (request_id);
create table if not exists req (
    owner text, request_id text, body_sha text, batch text, response text, cancelled integer, created real,
    primary key (owner, request_id));
create table if not exists counts (day text, name text, n integer, primary key (day, name));
"""

# Sentences for the codes of this API. A code that is not here is worded by studio_backend.msg (daily_limit,
# account_limit, session_limit, operator_limit, no_ledger, no_credits, restarted). busy, cancelled and internal
# are here although studio_backend has them: its sentences are about the music screen's one job.
TEXT = {
    "en": {
        "make_failed": "The sound did not pass the checks, even after the fixes.",
        "timeout": "Making this sound took too long, so it stopped.",
        "cancelled": "Stopped.",
        "busy": "The server is full right now.",
        "internal": "Something broke on our side.",
        "no_model": "The AI model is not answering right now.",
        "no_engine": "The sound engine is not available on this server.",
        "no_measure": "Sounds cannot be checked on this server right now.",
        "too_many_active": "Too many sounds are being made at once.",
        "fetch_first": "Finished sounds are waiting to be received.",
        "refund_limit": "Too many sounds were stopped or returned.",
        "quote_changed": "The number of credits changed.",
        "request_mismatch": "This request id was already used for another request.",
        "request_cancelled": "This request was cancelled.",
        "bad_request": "The request is not valid.",
        "too_large": "The request is too long.",
        "not_ready": "The sound is not ready yet.",
        "not_found": "There is no such sound.",
        "forbidden": "This sound belongs to someone else.",
        "rate": "Too many requests in a short time.",
        "no_token": "No access token was sent.",
        "bad_token": "The access token is not valid.",
        "token_expired": "The access token ran out.",
        "bad_host": "This address is not allowed.",
        "bad_origin": "This page is not allowed to ask.",
    },
    "ko": {
        "make_failed": "고쳐 봐도 검사를 통과한 소리가 나오지 않았어요.",
        "timeout": "소리를 만드는 데 너무 오래 걸려서 멈췄어요.",
        "cancelled": "멈췄어요.",
        "busy": "지금은 서버가 꽉 찼어요.",
        "internal": "서버 쪽에서 문제가 생겼어요.",
        "no_model": "지금은 AI 모델이 답하지 않아요.",
        "no_engine": "이 서버에서는 소리 엔진을 쓸 수 없어요.",
        "no_measure": "지금은 이 서버에서 소리를 검사할 수 없어요.",
        "too_many_active": "한꺼번에 만드는 소리가 너무 많아요.",
        "fetch_first": "다 만든 소리가 받기를 기다리고 있어요.",
        "refund_limit": "멈추거나 돌려받은 소리가 너무 많아요.",
        "quote_changed": "크레딧 수가 바뀌었어요.",
        "request_mismatch": "이 요청 번호는 이미 다른 요청에 쓰였어요.",
        "request_cancelled": "취소된 요청이에요.",
        "bad_request": "요청이 올바르지 않아요.",
        "too_large": "요청이 너무 길어요.",
        "not_ready": "소리가 아직 준비되지 않았어요.",
        "not_found": "그런 소리가 없어요.",
        "forbidden": "다른 사람의 소리예요.",
        "rate": "짧은 시간에 요청이 너무 많았어요.",
        "no_token": "접속 토큰이 없어요.",
        "bad_token": "접속 토큰이 올바르지 않아요.",
        "token_expired": "접속 토큰이 만료됐어요.",
        "bad_host": "허용되지 않은 주소예요.",
        "bad_origin": "이 페이지에서는 요청할 수 없어요.",
    },
}


def message(lang, error, **fields) -> str:
    """The sentence for a code, or for a GenError, in lang."""
    if isinstance(error, GenError):
        fields = {**error.extras, **getattr(error, "fields", {}), **fields}
        error = error.code
    lang, code = sb.lang_of(lang), str(error)
    text = TEXT[lang].get(code)
    try:
        if text is None and code in sb.MSG[lang]:
            return sb.msg(lang, code, **fields)
        return (text or code).format(**fields)
    except (KeyError, IndexError, ValueError):
        return text or sb.MSG[lang].get(code, code)


def quote(items: int, drafts: int, free: bool) -> dict:
    """The price of items x drafts. /quote and the accepting of a request both use this."""
    unit = 0 if free else DRAFT_CREDITS
    return {"items": items, "drafts": drafts, "unit": unit, "credits": items * drafts * unit, "free": free}


@dataclass(frozen=True)
class Who:
    """Who asks. kind is the token's ("acct" or "pw"); owner is "acct:<key>" or "pwip:<hash>"; email is the
    account's and stays in memory (the ledger charges by email). session is a password token's sub ("pw:<session>"):
    the API counts requests a minute by it, and here the sessions of one address take turns in its queue and each
    has its own count of refunds (lane_of). Jobs, daily counts, dollars, request ids and cancel marks go by owner."""
    kind: str
    owner: str
    email: str = ""
    lang: str = sb.DEFAULT_LANG
    session: str = ""


def lane_of(who: Who) -> str:
    """What a password session goes by inside its owner; "" for an account and for a token without a session.
    A hash of the sub, because it is written down (gen.sess, the rf: counters) and the sub is the page's own."""
    if who.kind != "pw" or not who.session:
        return ""
    return "s:" + hashlib.sha256(who.session.encode("utf-8", "replace")).hexdigest()[:16]


@dataclass
class Sound:
    """A result file to send whole, with its sha256 for the ETag."""
    path: Path
    sha256: str
    bytes: int

    def read(self) -> bytes:
        return Path(self.path).read_bytes()


@dataclass
class Limits:
    """Daily ceilings (E). Counter names: d:<owner>, d:members, d:teachers, usd:pw, usd:all, rf:<owner>."""
    account_daily: int = 200      # drafts of one account
    daily: int = 1000             # drafts of all accounts
    pw_daily: int = 120           # drafts of one password group (one address)
    pw_all_daily: int = 240       # drafts of all password sessions
    pw_daily_usd: float = 0.60    # dollars of all password sessions
    daily_usd: float = 5.00       # dollars of all generation
    pw_refund_hourly: int = 36    # refunds the users caused, of all the password sessions of one address in an hour
    pw_refund_daily: int = 72     # and in a day

    ENV = {"account_daily": "OLMUSE_GEN_ACCOUNT_DAILY", "daily": "OLMUSE_GEN_DAILY", "pw_daily": "OLMUSE_GEN_PW_DAILY",
           "pw_all_daily": "OLMUSE_GEN_PW_ALL_DAILY", "pw_daily_usd": "OLMUSE_GEN_PW_DAILY_USD",
           "daily_usd": "OLMUSE_GEN_DAILY_USD", "pw_refund_hourly": "OLMUSE_GEN_PW_REFUND_HOURLY",
           "pw_refund_daily": "OLMUSE_GEN_PW_REFUND_DAILY"}

    @classmethod
    def from_env(cls, env=None) -> "Limits":
        env, out = os.environ if env is None else env, cls()
        for spot in fields(cls):
            value = str(env.get(cls.ENV[spot.name]) or "").strip()
            if value:
                try:
                    number = type(spot.default)(value)
                    if not 0 <= number < float("inf"):  # nan, inf and a minus would break or void the ceiling
                        raise ValueError(value)
                    setattr(out, spot.name, number)
                except ValueError:
                    log.error("%s is not a number a limit can be; the default stays", cls.ENV[spot.name])
        return out

    @property
    def usd_pw(self) -> int:
        return int(round(self.pw_daily_usd * 1_000_000))

    @property
    def usd_all(self) -> int:
        return int(round(self.daily_usd * 1_000_000))


class StoreTaken(RuntimeError):
    """The database file already has its GenStore, in this process or in another one."""


def _hold(path: str):
    """An exclusive lock on a file, taken without waiting and kept until the handle is closed; a process that
    ends lets go of it too. None when somebody else holds it."""
    handle = open(path, "a+b")
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


class GenStore:
    """asset-gen.db: gen (one row per draft), req (one row per request id) and counts (daily counters).

    One connection, WAL, and one lock around every use of it. Whoever calls a method holds self.lock already;
    a write transaction (tx) holds nothing but SQL.

    A file has one GenStore at a time: it holds <file>.lock for as long as it is open, and a second one on the
    same file is refused with StoreTaken. The queue lives in the memory of the process that owns the file, and
    that process's start fails whatever is queued or running (GenJobs.recover), so a second owner would end the
    first one's paid jobs just by starting."""

    def __init__(self, path=":memory:"):
        self.path, self.held = str(path), None
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self.held = _hold(self.path + ".lock")
            if self.held is None:
                raise StoreTaken(Path(self.path).name + " is already open in a running process")
        self.lock = threading.Lock()
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=10)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.execute("pragma journal_mode=wal")
            self.db.execute("pragma busy_timeout=10000")
            self.db.executescript(SCHEMA)
            if "sess" not in [row["name"] for row in self.db.execute("pragma table_info(gen)")]:
                self.db.execute("alter table gen add column sess text")  # a file from before sessions were written down

    @contextlib.contextmanager
    def tx(self):
        self.db.execute("begin immediate")
        try:
            yield self.db
        except BaseException:
            self.db.execute("rollback")
            raise
        self.db.execute("commit")

    def one(self, sql: str, args=()):
        row = self.db.execute(sql, args).fetchone()
        return row[0] if row else None

    def all(self, sql: str, args=()) -> list:
        return self.db.execute(sql, args).fetchall()

    def count(self, day: str, name: str) -> int:
        return self.one("select n from counts where day=? and name=?", (day, name)) or 0

    def add(self, day: str, name: str, n: int):
        """Moves a counter. Taking away never goes under zero and never makes a row."""
        if n >= 0:
            self.db.execute("insert into counts values (?,?,?) on conflict (day, name) do update set n=n+?", (day, name, n, n))
        else:
            self.db.execute("update counts set n=max(0, n+?) where day=? and name=?", (n, day, name))

    def close(self):
        with self.lock:
            self.db.close()
            if self.held is not None:
                self.held.close()  # lets go of the file: another GenStore may open it now
                self.held = None


PENDING =("pending", "unknown", "refund_due")  # charges that still have a ledger call to come


def refund_of(row) -> str:
    """The view's refund: none, pending (the credit is on its way back) or done."""
    charge = row["charge"]
    if charge == "refunded":
        return "done"
    if charge in ("unknown", "refund_due"):
        return "pending"
    over = row["status"] in ("failed", "cancelled", "gone") or (row["status"] == "running" and row["cancel"])
    return "pending" if over and charge in ("pending", "charged") else "none"


SPANS = {1: (0.0, 0.6), 2: (0.6, 0.8), 3: (0.8, 0.95)}  # the share of the bar each attempt fills
PARTS = {"writing": 0.2, "fixing": 0.2, "rendering": 0.6, "checking": 0.85}


def progress_of(stage, attempt) -> float:
    low, high = SPANS.get(attempt or 1, SPANS[3])
    return round(low + (high - low) * PARTS.get(stage, 0.2), 3)


class GenJobs:
    """The queue in memory over GenStore, its workers and its sweeper.

    model is a callable giving a new model for one job (asset_generate.model_factory or a fake's), engine has
    render_mended (asset_engine.nkido or FakeEngine), measure is asset_generate.NodeLint or a test's own, ledger is
    credits.RemoteLedger or LocalLedger (None: accounts get 503 no_ledger, password sessions still work).
    clock and sleep are injected so tests own the time. With autostart=False no thread starts: drain() runs the
    queue in the caller's thread and sweep() is called by hand."""

    def __init__(self, store: GenStore, *, ledger=None, model=None, engine=None, measure=None, renders=None,
                 temp=None, limits: Limits | None = None, model_name: str = "", clock=time.time, sleep=time.sleep,
                 free=None, workers: int = GEN_WORKERS, autostart: bool = True):
        self.store, self.ledger, self.model, self.engine, self.measure = store, ledger, model, engine, measure
        self.renders = Path(renders or DEFAULT_RENDERS)
        self.temp = Path(temp or tempfile.gettempdir())
        self.limits, self.model_name = limits or Limits(), model_name
        self.clock, self.sleep, self.workers = clock, sleep, workers
        self.free = free or (lambda path: shutil.disk_usage(path).free)
        call_usd = GEN_CALL_USD.get(model_name, GEN_CALL_USD_OTHER)
        self.est = int(round(MODEL_CALLS * call_usd * 1_000_000))
        # Ceilings and waits a test may lower.
        self.pick_retry = PICK_RETRY
        self.queue_cap, self.owner_active = QUEUE_CAP, OWNER_ACTIVE
        self.unfetched_cap, self.pw_unfetched_cap, self.disk_cap = OWNER_UNFETCHED_BYTES, PW_UNFETCHED_BYTES, DISK_CAP
        self.refund_hourly, self.refund_daily = REFUND_HOURLY, REFUND_DAILY
        # Memory, all under store.lock. A restart loses it, which is why a restart fails what was queued.
        self.wake = threading.Condition(store.lock)
        self.waiting: dict[str, list[tuple]] = {}   # owner -> [(batch order, k, item order, id, lane)], sorted
        self.kinds: dict[str, str] = {}             # owner -> acct | pw
        self.active: dict[str, int] = {}            # owner -> jobs a worker holds
        self.served: dict[str, int] = {}            # owner -> the count of picks when it was last served
        self.lane_active: dict[tuple, int] = {}     # (owner, lane) -> jobs a worker holds, of one session of an address
        self.lane_served: dict[tuple, int] = {}     # (owner, lane) -> the count of picks when it was last served
        self.held: dict[str, threading.Thread] = {}  # job id -> the worker that holds it
        self.mail: dict[str, str] = {}              # owner -> email; never written to disk
        self.balances: dict[str, tuple[int, float]] = {}  # owner -> (the ledger's last answer, when)
        self.unread: dict[str, float] = {}          # owner -> when the ledger last left a balance read unanswered
        self.refunds: dict[str, list[float]] = {}   # owner, or owner/lane -> times of refunds the user caused, last hour
        self.refunds_down = None                    # since when the ledger has turned the sweeper's refunds down
        self.refunds_said = 0.0                     # when the log was last told so
        self.seen: dict[str, float] = {}            # job id -> last status lookup; the sweeper writes it down
        self.batches = self.picks = self.strikes = 0
        self.breaker_until = 0.0
        self.disk_paused, self.stopping = False, False
        exe = getattr(engine, "EXE", "")
        self.engine_ok = engine is not None and (not exe or Path(exe).is_file())
        self.boot = clock()
        self.halt, self.threads = threading.Event(), []
        self.deps = ag.Deps(model=model, engine=engine, measure=measure, slots=threading.Semaphore(RENDER_SLOTS),
                            clock=clock, sleep=sleep, cancelled=self._stopped, free=self._free, model_name=model_name,
                            call_usd=call_usd, model_ok=self._model_ok, model_down=self._model_down,
                            engine_missing=self._engine_missing)
        self.renders.mkdir(parents=True, exist_ok=True)
        self.recover()
        if autostart:
            self.start()

    # ---------- small things ----------
    def _day(self, at: float | None = None) -> str:
        return datetime.date.fromtimestamp(self.clock() if at is None else at).isoformat()

    def _free(self, path) -> int:
        try:
            return int(self.free(str(path)))
        except OSError:
            return 0  # a volume that cannot be asked counts as full

    def _is_held(self, job_id: str) -> bool:
        worker = self.held.get(job_id)
        return worker is not None and worker.is_alive()

    def _set_balance(self, owner: str, credits):
        """A balance the ledger gave, from a read, a charge or a refund. The ledger answers this account again."""
        with self.store.lock:
            self.balances[owner] = (int(credits), self.clock())
            self.unread.pop(owner, None)

    def count(self, name: str, day: str = "") -> int:
        """Today's value of a counter: d:<owner>, d:members, d:teachers, usd:pw, usd:all, rf:<owner>."""
        with self.store.lock:
            return self.store.count(day or self._day(), name)

    def _model_ok(self):
        with self.store.lock:
            self.strikes = 0

    def _model_down(self):
        """The provider turned a call down: the key, its credit, a quota, or a 4xx for a model id or a parameter it
        does not take. BREAKER_STRIKES in a row and picking rests for BREAKER_SECONDS."""
        with self.store.lock:
            self.strikes += 1
            if self.strikes >= BREAKER_STRIKES:
                self.strikes, self.breaker_until = 0, self.clock() + BREAKER_SECONDS
                log.error("ALERT asset generation model refused %d calls in a row; resting %d seconds",
                          BREAKER_STRIKES, BREAKER_SECONDS)

    def _engine_missing(self):
        """The engine is not installed: nothing waiting can be made, so it fails now, uncharged."""
        with self.wake:
            self.engine_ok = False
            self._fail_waiting(list(self.waiting), "no_engine")
        log.error("ALERT nkido is missing; asset generation is off")

    def _measures(self) -> bool:
        """Whether sounds can be measured: there is a measure, and it has not said that Node is gone."""
        return self.measure is not None and bool(getattr(self.measure, "ok", True))

    def health(self) -> dict:
        """True, false and counts only. ok is also false when the workers were started and none is alive, and
        while the renders are out of room."""
        with self.store.lock:
            queued = self.store.one("select count(*) from gen where status='queued'")
            running = self.store.one("select count(*) from gen where status='running'")
            model = self.model is not None and self.clock() >= self.breaker_until
            engine = self.engine is not None and self.engine_ok
            workers = not self.threads or any(t.is_alive() for t in self.threads[1:])
            room = not self.disk_paused
        node = self._measures()
        return {"ok": bool(model and engine and node and workers and room), "model": model, "engine": engine, "node": node,
                "ledger": self.ledger is not None, "queued": queued, "running": running,
                "disk_free_mb": self._free(self.renders) // MB}

    # ---------- price, balance, admission ----------
    def _gate(self, who: Who):
        """Why no request can be taken at all right now."""
        if self.model is None or self.clock() < self.breaker_until:
            raise GenError(503, "no_model")
        if self.engine is None or not self.engine_ok:
            raise GenError(503, "no_engine")
        if not self._measures():
            # A sound that cannot be measured can never be a result, and its model calls would be paid for.
            raise GenError(503, "no_measure")
        if self.disk_paused:
            raise GenError(503, "busy")
        if who.kind == "acct" and self.ledger is None:
            raise GenError(503, "no_ledger")

    def _balance(self, who: Who, fresh: bool = False):
        """The account's credits from the cache, asking the ledger when the cache is over BALANCE_TTL old, or
        whatever the cache holds when fresh. None for a password session. Called without the lock: the ledger may
        take seconds.

        A read the ledger did not answer is remembered for LEDGER_REST seconds, and until then this account is told
        no_ledger at once: a ledger that is down would only make each of its requests wait out the timeout again.
        Any balance the ledger gives ends that (_set_balance)."""
        if who.kind != "acct":
            return None
        if self.ledger is None:
            raise GenError(503, "no_ledger")
        now = self.clock()
        with self.store.lock:
            self.mail[who.owner] = who.email
            held, failed = self.balances.get(who.owner), self.unread.get(who.owner)
        if held and not fresh and 0 <= now - held[1] < BALANCE_TTL:
            return held[0]
        if failed is not None and 0 <= now - failed < LEDGER_REST:
            raise GenError(503, "no_ledger")
        try:
            credits = int(self.ledger.account(who.email).get("credits", 0))
        except LedgerError:
            now = self.clock()  # the rest starts when the wait for the ledger ended
            with self.store.lock:
                self.unread = {owner: at for owner, at in self.unread.items() if 0 <= now - at < LEDGER_REST}
                self.unread[who.owner] = now
            raise GenError(503, "no_ledger") from None
        self._set_balance(who.owner, credits)
        return credits

    def _short(self, owner: str, cost: int, balance, queued: int) -> bool:
        """Lock held. Whether the account cannot pay `cost` more. Reserved: what waits and what is being charged
        right now will each take a credit."""
        pending = self.store.one("select count(*) from gen where owner=? and charge='pending'", (owner,))
        return (balance or 0) - (queued + pending) * DRAFT_CREDITS < cost

    def _balance_for(self, who: Who, cost: int):
        """The balance a request for `cost` credits is judged by. When the remembered one would turn the request
        away and is BALANCE_RECHECK seconds old, the ledger is asked once more first: credits bought on the page
        reach the ledger without passing here. A ledger that does not answer that second look leaves the
        remembered balance to decide."""
        balance = self._balance(who)
        if who.kind != "acct":
            return balance
        now = self.clock()
        with self.store.lock:
            held = self.balances.get(who.owner)
            queued = self.store.one("select count(*) from gen where owner=? and status='queued'", (who.owner,))
            short = bool(held) and now - held[1] >= BALANCE_RECHECK and self._short(who.owner, cost, balance, queued)
        if short:
            with contextlib.suppress(GenError):
                balance = self._balance(who, fresh=True)
        return balance

    def _refund_limits(self, who: Who) -> list[tuple[str, int, int]]:
        """(whose refunds, how many an hour, how many a day). An account's are its own. A password session's are
        its own too, so one person in a classroom cannot close the door on everybody at the address; and the
        address has a wider count, because a reload is a new session."""
        names = self._refunds_of(who.owner, lane_of(who))
        if len(names) == 1:
            return [(who.owner, self.refund_hourly, self.refund_daily)]
        return [(names[1], self.refund_hourly, self.refund_daily),
                (who.owner, self.limits.pw_refund_hourly, self.limits.pw_refund_daily)]

    @staticmethod
    def _refunds_of(owner: str, lane) -> list[str]:
        """The names a refund the user caused is counted under: the owner, and a password session's own."""
        return [owner, owner + "/" + lane] if lane else [owner]

    def _buckets(self, who: Who) -> list[tuple[str, int, str, str]]:
        """(counter, limit, code, whose waiting jobs count against it) for the two draft counts of this owner."""
        if who.kind == "pw":
            return [("d:" + who.owner, self.limits.pw_daily, "session_limit", "owner"),
                    ("d:teachers", self.limits.pw_all_daily, "daily_limit", "cls")]
        return [("d:" + who.owner, self.limits.account_daily, "account_limit", "owner"),
                ("d:members", self.limits.daily, "daily_limit", "cls")]

    def _unfetched(self, owner: str) -> int:
        return self.store.one("select coalesce(sum(bytes), 0) from gen where owner=? and status='done' and delivered is null", (owner,))

    def _unfetched_pw(self) -> int:
        return self.store.one("select coalesce(sum(bytes), 0) from gen where cls='pw' and status='done' and delivered is null")

    def _standing(self, who: Who, now: float) -> dict:
        """Lock held, reads only. Where this owner stands against the queue and today's counts."""
        day, one = self._day(now), self.store.one
        queued_all = one("select count(*) from gen where status='queued'")
        mine = {row[0]: row[1] for row in self.store.all(
            "select status, count(*) from gen where owner=? and status in ('queued','running') group by status", (who.owner,))}
        queued, running = mine.get("queued", 0), mine.get("running", 0)
        waiting = {"owner": queued, "cls": one("select count(*) from gen where cls=? and status='queued'", (who.kind,))}
        # Drafts are counted when they are picked, so what waits is added to what today already used.
        lefts = [(limit - self.store.count(day, name) - waiting[scope], code, limit)
                 for name, limit, code, scope in self._buckets(who)]
        cap = min(self.owner_active, max(4, (self.queue_cap - queued_all) // 4))
        return {"day": day, "queued_all": queued_all, "queued": queued, "lefts": lefts,
                "left_today": max(0, min(left for left, _, _ in lefts)),
                "room": max(0, min(cap - queued - running, self.queue_cap - queued_all))}

    @staticmethod
    def _to_tomorrow(now: float) -> int:
        """Seconds until the day's counts start again, for retry_after."""
        tomorrow = datetime.datetime.combine(datetime.date.fromtimestamp(now) + datetime.timedelta(days=1), datetime.time())
        return max(1, int(tomorrow.timestamp() - now) + 1)

    def _refusal(self, who: Who, new: int, cost: int, balance, now: float, at: dict):
        """Lock held, reads only. The GenError that turns `new` more drafts down, or None. In the order of E.
        Every 429 names retry_after: the seconds after which asking again can have another answer."""
        one, day, owner = self.store.one, at["day"], who.owner
        if who.kind == "acct" and self._short(owner, cost, balance, at["queued"]):
            return GenError(402, "no_credits", balance=balance or 0, credits=cost)
        for left, code, limit in at["lefts"]:
            if new > left:
                error = GenError(429, code, left_today=at["left_today"], retry_after=self._to_tomorrow(now))
                error.fields = {"n": limit}  # for the sentence, not for the answer
                return error
        if at["queued_all"] + new > self.queue_cap:
            return GenError(503, "busy")
        if new > at["room"]:
            return GenError(429, "too_many_active", room=at["room"], retry_after=ACTIVE_RETRY)
        if self._unfetched(owner) >= self.unfetched_cap or (who.kind == "pw" and self._unfetched_pw() >= self.pw_unfetched_cap):
            oldest = one("select min(finished) from gen where status='done' and delivered is null and "
                         + ("cls='pw'" if who.kind == "pw" else "owner=?"), () if who.kind == "pw" else (owner,))
            return GenError(429, "fetch_first", retry_after=max(1, int((oldest or now) + UNFETCHED_TTL - now) + 1))
        # The limits are passed, not met: the refund after the twelfth in an hour is the one that closes the door.
        for name, hourly, daily in self._refund_limits(who):
            recent = sorted(t for t in self.refunds.get(name, ()) if now - t < 3600)
            over = len(recent) - hourly
            if over > 0:
                return GenError(429, "refund_limit", retry_after=max(1, int(recent[over - 1] + 3600 - now) + 1))
            if self.store.count(day, "rf:" + name) > daily:
                return GenError(429, "refund_limit", retry_after=self._to_tomorrow(now))
        if self.store.count(day, "usd:all") + self.est > self.limits.usd_all or (
                who.kind == "pw" and self.store.count(day, "usd:pw") + self.est > self.limits.usd_pw):
            return GenError(429, "operator_limit", left_today=at["left_today"], retry_after=self._to_tomorrow(now))
        return None

    def quote_for(self, who: Who, items, drafts) -> dict:
        """GET /quote. May ask the ledger for the balance (503 no_ledger when it does not answer)."""
        for name, value, top in (("items", items, ag.MAX_ITEMS), ("drafts", drafts, ag.MAX_DRAFTS)):
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= top:
                raise GenError(400, "bad_request", field=name)
        price = quote(items, drafts, who.kind == "pw")
        reason = None
        try:
            self._gate(who)
        except GenError as exc:
            if exc.code == "no_ledger":
                raise
            reason = exc.code
        balance = self._balance_for(who, price["credits"])
        now = self.clock()
        with self.store.lock:
            at = self._standing(who, now)
            refusal = self._refusal(who, items * drafts, price["credits"], balance, now, at)
        reason = reason or (refusal.code if refusal else None)
        return {**price, "balance": balance, "left_today": at["left_today"], "room": at["room"],
                "ok": reason is None, "reason": reason}

    # ---------- taking a request ----------
    def _replay(self, owner: str, request_id: str, sha: str):
        """Lock held. The first answer to this request id again, or None when the id is new."""
        row = self.store.db.execute("select body_sha, response, cancelled from req where owner=? and request_id=?",
                                    (owner, request_id)).fetchone()
        if row is None:
            return None
        if row["response"] is None or row["cancelled"]:  # cancelled, before the request came or after it was taken
            raise GenError(410, "request_cancelled")
        if row["body_sha"] != sha:
            raise GenError(409, "request_mismatch")
        return {**json.loads(row["response"]), "replayed": True}

    def submit(self, who: Who, body) -> dict:
        """POST /jobs: all of the drafts or none. Returns {batch, replayed, quote, jobs: [{id, ref, k, n, status}]}.

        The same (owner, request_id) again gets the first answer and makes nothing; with another body it is 409
        request_mismatch, and once the request id was cancelled (before it came or after) 410 request_cancelled."""
        req = ag.clean_request(body, who.lang)
        sha = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
        new = len(req["items"]) * req["drafts"]
        price = quote(len(req["items"]), req["drafts"], who.kind == "pw")
        with self.store.lock:
            played = self._replay(who.owner, req["request_id"], sha)
        if played:
            return played
        if req["expect_credits"] != price["credits"]:
            raise GenError(409, "quote_changed", quote=price)
        self._gate(who)
        balance = self._balance_for(who, price["credits"])  # the ledger, outside the lock
        now, lane = self.clock(), lane_of(who)
        with self.wake:
            with self.store.tx() as db:
                played = self._replay(who.owner, req["request_id"], sha)
                if played:
                    return played
                refusal = self._refusal(who, new, price["credits"], balance, now, self._standing(who, now))
                if refusal:
                    raise refusal
                batch, entries, made = secrets.token_hex(8), [], []
                self.batches += 1
                held = json.dumps({"lang": req["lang"]})
                for order, item in enumerate(req["items"]):
                    task = json.dumps({"lang": req["lang"], "project": req["project"], "examples": req["examples"], "item": item},
                                      ensure_ascii=False)
                    for k in range(1, req["drafts"] + 1):
                        job_id = secrets.token_hex(16)
                        db.execute(
                            "insert into gen (id, owner, cls, batch, request_id, ref, k, n, ord, status, attempt, view, input,"
                            " cancel, charge, est, usd, bytes, created, sess) values (?,?,?,?,?,?,?,?,?,'queued',0,?,?,0,'none',0,0,0,?,?)",
                            (job_id, who.owner, who.kind, batch, req["request_id"], item["ref"], k, req["drafts"], order,
                             held, task, now, lane))
                        entries.append((self.batches, k, order, job_id, lane))
                        made.append({"id": job_id, "ref": item["ref"], "k": k, "n": req["drafts"], "status": "queued"})
                answer = {"batch": batch, "replayed": False, "quote": price, "jobs": made}
                db.execute("insert into req values (?,?,?,?,?,0,?)",
                           (who.owner, req["request_id"], sha, batch, json.dumps(answer), now))
            self.kinds[who.owner] = who.kind
            self.waiting.setdefault(who.owner, []).extend(entries)
            self.waiting[who.owner].sort()
            self.wake.notify_all()
        return answer

    # ---------- looking, cancelling, receiving ----------
    @staticmethod
    def _visible(row, who: Who) -> bool:
        """An account's job is its owner's. A password job is any password token's that knows its 128-bit id."""
        return who.kind == "pw" if row["cls"] == "pw" else who.kind == "acct" and row["owner"] == who.owner

    def _position(self, row) -> int:
        """About how many picks until this one, 1 being next: owners are served in turn, and so are the sessions
        of one address."""
        mine, lane = self.waiting.get(row["owner"], []), row["sess"] or ""
        ahead = [entry for entry in mine if entry[4] == lane]
        at = next((i for i, entry in enumerate(ahead) if entry[3] == row["id"]), len(ahead))
        others = collections.Counter(entry[4] for entry in mine if entry[4] != lane)
        at += sum(min(count, at + 1) for count in others.values())
        return 1 + at + sum(min(len(q), at + 1) for owner, q in self.waiting.items() if owner != row["owner"])

    def _view(self, row, job_id: str, who: Who) -> dict:
        if row is None:
            return {"id": job_id, "status": "unknown", "refund": "none"}
        if not self._visible(row, who):
            return {"id": job_id, "status": "forbidden", "refund": "none"}
        if row["status"] == "gone":
            return {"id": job_id, "status": "gone", "refund": refund_of(row)}
        held = json.loads(row["view"] or "{}")
        status = "cancelled" if row["status"] == "running" and row["cancel"] else row["status"]
        view = {"id": row["id"], "ref": row["ref"], "k": row["k"], "n": row["n"], "batch": row["batch"],
                "status": status, "refund": refund_of(row), "expires": row["expires"]}
        if status == "queued":
            view.update(position=self._position(row), progress=0.0)
        elif status == "running":
            stage, attempt = row["stage"] or "writing", row["attempt"] or 1
            view.update(stage=stage, attempt=attempt, progress=progress_of(stage, attempt))
        elif status == "done":
            result, more = dict(held.get("result") or {}), held.get("more") or {}
            if row["delivered"] is not None:  # the source, the prompt and the stem names only after the sound went out
                result.update({key: value for key, value in more.items() if key != "labels"})
                result["stems"] = [{**stem, "label": label} for stem, label in zip(result.get("stems", []), more.get("labels", []))]
            view.update(progress=1.0, result=result)
        elif status == "failed":
            code = row["error"] or "internal"
            view["error"] = {"code": code, "message": message(held.get("lang"), code)}
        return view

    @staticmethod
    def _ids(ids) -> list[str]:
        if not isinstance(ids, list) or len(ids) > 256 or not all(
                isinstance(i, str) and 0 < len(i) <= 64 and ag.writable(i) for i in ids):
            raise GenError(400, "bad_request", field="ids")
        return ids

    @staticmethod
    def _request_id(request_id) -> str:
        if not isinstance(request_id, str) or not 0 < len(request_id) <= 64 or not ag.writable(request_id):
            raise GenError(400, "bad_request", field="request_id")
        return request_id

    def _rows(self, ids: list[str]) -> dict:
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        return {row["id"]: row for row in self.store.all(f"select * from gen where id in ({marks})", ids)}

    def _views(self, who: Who, ids: list[str]) -> list[dict]:
        """Lock held. A lookup is also what keeps a received result from the disk clean-up."""
        rows, now = self._rows(ids), self.clock()
        for job_id, row in rows.items():
            if self._visible(row, who):
                self.seen[job_id] = now
        return [self._view(rows.get(job_id), job_id, who) for job_id in ids]

    def status(self, who: Who, ids) -> dict:
        """POST /jobs/status {ids}. credits is the cached balance; the ledger is not asked."""
        ids = self._ids(ids)
        with self.store.lock:
            held = self.balances.get(who.owner) if who.kind == "acct" else None
            return {"credits": held[0] if held else None, "jobs": self._views(who, ids)}

    def _of_request(self, who: Who, request_id: str):
        """Lock held. (the req row or None, the ids of its jobs)."""
        row = self.store.db.execute("select response, cancelled from req where owner=? and request_id=?",
                                    (who.owner, request_id)).fetchone()
        ids = [r["id"] for r in self.store.all("select id from gen where owner=? and request_id=? order by ord, k",
                                               (who.owner, request_id))]
        return row, ids

    def status_request(self, who: Who, request_id) -> dict:
        """POST /jobs/status {request_id}: known is False when no such request was ever taken."""
        request_id = self._request_id(request_id)
        with self.store.lock:
            row, ids = self._of_request(who, request_id)
            return {"known": bool(row and row["response"] is not None), "cancelled": bool(row and row["cancelled"]),
                    "jobs": self._views(who, ids)}

    def _cancel(self, who: Who, ids: list[str]) -> list[dict]:
        """Lock held. A waiting job is cancelled here and now; a running one only gets its flag, and the worker
        that holds it ends it and refunds. The ledger is not called."""
        now, rows, ended = self.clock(), self._rows(ids), []
        with self.store.tx() as db:
            for job_id in ids:
                row = rows.get(job_id)
                if row is None or not self._visible(row, who):
                    continue
                if db.execute("update gen set status='cancelled', finished=?, input=null, expires=? where id=?"
                              " and status='queued'", (now, now + TRACE_TTL, job_id)).rowcount:
                    ended.append((row["owner"], job_id))
                else:
                    db.execute("update gen set cancel=1 where id=? and status='running'", (job_id,))
        self._forget(ended)
        return self._views(who, ids)

    def _forget(self, entries):
        """Lock held. Takes (owner, job id) pairs out of the memory queue, after the rows were committed: a
        transaction that fails must leave the queue as the store has it."""
        for owner in {owner for owner, _ in entries}:
            gone = {job_id for o, job_id in entries if o == owner}
            left = [e for e in self.waiting.get(owner, []) if e[3] not in gone]
            if left:
                self.waiting[owner] = left
            else:
                self.waiting.pop(owner, None)

    def cancel(self, who: Who, ids) -> dict:
        """POST /jobs/cancel {ids}. Asking again changes nothing."""
        ids = self._ids(ids)
        with self.wake:
            return {"jobs": self._cancel(who, ids)}

    def cancel_request(self, who: Who, request_id) -> dict:
        """POST /jobs/cancel {request_id}. For a request never taken, a mark stays so that the request itself,
        arriving late, gets 410."""
        request_id = self._request_id(request_id)
        with self.wake:
            row, ids = self._of_request(who, request_id)
            with self.store.tx() as db:
                if row is None:
                    db.execute("insert into req values (?,?,null,null,null,1,?)", (who.owner, request_id, self.clock()))
                else:
                    db.execute("update req set cancelled=1 where owner=? and request_id=?", (who.owner, request_id))
            return {"jobs": self._cancel(who, ids)}

    def _send(self, who: Who, job_id: str, stem=None) -> Sound:
        now = self.clock()
        if not isinstance(job_id, str) or not ag.writable(job_id):
            raise GenError(404, "not_found")
        with self.store.lock:
            row = self.store.db.execute("select * from gen where id=?", (job_id,)).fetchone()
            if row is None:
                raise GenError(404, "not_found")
            if not self._visible(row, who):
                raise GenError(403, "forbidden")
            if row["status"] in ("queued", "running"):
                raise GenError(409, "not_ready")
            if row["status"] != "done":
                raise GenError(404, "not_found")
            result = json.loads(row["view"])["result"]
            if stem is None:
                name, meta = "master.wav", result
            else:
                name, meta = f"stem-{stem}.wav", next((s for s in result["stems"] if s["n"] == stem), None)
            path = self.renders / job_id / name
            if meta is None or not path.is_file():
                raise GenError(404, "not_found")
            # The mark and the sweeper's unfetched expiry are both conditional on the same row: one of them wins.
            with self.store.tx() as db:
                db.execute("update gen set delivered=?, expires=?, charge=case when charge='charged' then 'kept' else charge end"
                           " where id=? and status='done' and delivered is null", (now, row["finished"] + RESULT_TTL, job_id))
            if self.store.one("select status from gen where id=?", (job_id,)) != "done":
                raise GenError(404, "not_found")
            self.seen[job_id] = now
        return Sound(path, meta["sha256"], meta["bytes"])

    def sound(self, who: Who, job_id: str) -> Sound:
        """GET /jobs/{id}/sound. Marks the result received before a byte goes out; from then on it is not refunded.
        It can be received again until it expires. GenError 409 not_ready, 404 not_found, 403 forbidden."""
        return self._send(who, job_id)

    def stem(self, who: Who, job_id: str, n: int) -> Sound:
        """GET /jobs/{id}/stems/{n}. One stem alone marks the result received too."""
        return self._send(who, job_id, int(n))

    # ---------- the workers ----------
    def start(self):
        """The sweeper (now and every SWEEP_EVERY seconds) and the workers. Before the first pick the measure is
        asked whether it works, so that a server without Node takes no request at all."""
        if not self.threads:
            self._check_measure()
        with self.wake:
            if self.threads:
                return
            self.stopping = False
            self.halt.clear()
            self.threads = [threading.Thread(target=self._sweeper, name="olmuse-gen-sweep", daemon=True)]
            self.threads += [threading.Thread(target=self._worker, name=f"olmuse-gen-{i}", daemon=True)
                             for i in range(self.workers)]
        for thread in self.threads:
            thread.start()

    def stop(self, timeout: float = 5.0):
        with self.wake:
            self.stopping = True
            self.wake.notify_all()
        self.halt.set()
        for thread in self.threads:
            thread.join(timeout)
        self.threads = []

    def drain(self, limit: int = 100_000) -> int:
        """Runs waiting jobs in the caller's thread until none can be picked. Returns how many ran."""
        ran = 0
        while ran < limit:
            job = self._next(block=False)
            if job is None:
                break
            self._serve(job)
            ran += 1
        return ran

    def _worker(self):
        """Picks and serves until the queue is stopped. A pick the store refuses (the disk is full, the file is
        locked) is tried again after a rest: a worker that ended here would leave the queue to nobody."""
        while True:
            try:
                job = self._next()
            except Exception as exc:
                log.error("asset worker could not pick: %s\n%s", type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)))
                if self.halt.wait(self.pick_retry):
                    return
                continue
            if job is None:
                return
            self._serve(job)

    def _sweeper(self):
        while not self.halt.is_set():
            try:
                self.sweep()
            except Exception as exc:
                log.error("asset sweep failed: %s\n%s", type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)))
            self.halt.wait(SWEEP_EVERY)

    def _next(self, block: bool = True):
        with self.wake:
            while not self.stopping:
                job = self._pick()
                if job is not None or not block:
                    return job
                self.wake.wait(1.0)
        return None

    def _fail_waiting(self, owners, code: str):
        """Lock held, no transaction open. The waiting jobs of these owners end uncharged and uncounted."""
        now, owners = self.clock(), list(owners)
        with self.store.tx() as db:
            for owner in owners:
                for entry in self.waiting.get(owner, []):
                    db.execute("update gen set status='failed', error=?, finished=?, input=null, expires=? where id=?"
                               " and status='queued'", (code, now, now + TRACE_TTL, entry[3]))
        for owner in owners:  # only once the rows are committed
            self.waiting.pop(owner, None)

    def _pick(self):
        """Lock held. The next job, now `running` and counted, or None.

        The owner with the fewest jobs in a worker's hands goes first, then the one served longest ago. Inside an
        owner the order is (request, draft number, item), so every sound's draft 1 comes before any draft 2, and
        the sessions of one address take turns in the same way (_turn). An owner whose results wait to be
        received is passed over. The pick and today's counts are one transaction;
        the charge comes after it, in the worker."""
        now = self.clock()
        if self.model is None or self.engine is None or not self.engine_ok or self.disk_paused or now < self.breaker_until:
            return None
        if not self._measures():
            return None  # nothing can be measured: what waits stays until Node is back (the sweeper asks)
        day, pw_waiting = self._day(now), None
        while True:
            chosen = None
            for owner in sorted((o for o, q in self.waiting.items() if q),
                                key=lambda o: (self.active.get(o, 0), self.served.get(o, 0), self.waiting[o][0])):
                if self._unfetched(owner) >= self.unfetched_cap:
                    continue
                if self.kinds.get(owner) == "pw":
                    pw_waiting = self._unfetched_pw() if pw_waiting is None else pw_waiting
                    if pw_waiting >= self.pw_unfetched_cap:
                        continue
                chosen = owner
                break
            if chosen is None:
                return None
            pw = self.kinds.get(chosen) == "pw"
            if self.store.count(day, "usd:all") + self.est > self.limits.usd_all:
                return None  # the day's dollars are spent: picking rests
            if pw and self.store.count(day, "usd:pw") + self.est > self.limits.usd_pw:
                self._fail_waiting([o for o in self.waiting if self.kinds.get(o) == "pw"], "operator_limit")
                continue
            job_id, lane = self._turn(chosen)[3:5]
            with self.store.tx() as db:
                took = db.execute(
                    "update gen set status='running', stage='writing', attempt=1, charge=?, charge_at=?, started=?, est=?"
                    " where id=? and status='queued' and cancel=0", ("none" if pw else "pending", now, now, self.est, job_id)).rowcount
                if took:
                    self.store.add(day, "d:" + chosen, 1)
                    self.store.add(day, "d:teachers" if pw else "d:members", 1)
                    self.store.add(day, "usd:all", self.est)
                    if pw:
                        self.store.add(day, "usd:pw", self.est)
            # Out of the memory queue only now: had the transaction failed, the row would still say queued and
            # the job has to be there for the next pick.
            self._forget([(chosen, job_id)])
            if not took:
                continue  # cancelled or failed while it waited
            self.picks += 1
            self.served[chosen] = self.picks
            self.active[chosen] = self.active.get(chosen, 0) + 1
            if lane:
                self.lane_served[chosen, lane] = self.picks
                self.lane_active[chosen, lane] = self.lane_active.get((chosen, lane), 0) + 1
            self.held[job_id] = threading.current_thread()
            return dict(self.store.db.execute("select * from gen where id=?", (job_id,)).fetchone())

    def _turn(self, owner: str) -> tuple:
        """Lock held. The owner's next waiting job. Its sessions take turns the way owners do: the one with the
        fewest jobs in a worker's hands, then the one served longest ago. An account has one."""
        first = {}
        for entry in self.waiting[owner]:
            first.setdefault(entry[4], entry)
        return min(first.values(), key=lambda entry: (self.lane_active.get((owner, entry[4]), 0),
                                                      self.lane_served.get((owner, entry[4]), 0), entry))

    def _serve(self, job: dict):
        """One picked job to its end. Whatever it raises, the worker goes on to the next job."""
        try:
            self._run(job)
        except BaseException as exc:  # noqa: B902 - a worker must outlive anything a job raises
            # The class and the frames only: an exception's own text may quote a request or a model reply.
            log.error("asset job %s crashed: %s\n%s", job["id"], type(exc).__name__, "".join(traceback.format_tb(exc.__traceback__)))
            try:
                self._close(job, "failed", "internal")
                with self.store.lock:
                    kept = self.store.one("select status from gen where id=?", (job["id"],)) == "done"
                if not kept:
                    shutil.rmtree(self.renders / job["id"], ignore_errors=True)
            except Exception as again:
                log.error("asset job %s could not be closed: %s", job["id"], type(again).__name__)
        finally:
            with self.wake:
                self.held.pop(job["id"], None)
                self.active[job["owner"]] = max(0, self.active.get(job["owner"], 0) - 1)
                lane = (job["owner"], job.get("sess") or "")
                if lane in self.lane_active:
                    self.lane_active[lane] -= 1
                    if self.lane_active[lane] <= 0:
                        del self.lane_active[lane]
                self.wake.notify_all()

    def _run(self, job: dict):
        if job["cls"] == "acct" and not self._charge(job):
            return
        if self._stopped(job["id"]):  # cancelled while the charge was out
            self._close(job, "cancelled")
            return
        task = json.loads(job["input"])
        outcome = ag.run(ag.Job(id=job["id"], project=task["project"], item=task["item"], examples=task["examples"],
                                k=job["k"], n=job["n"], lang=task.get("lang"), deadline=job["started"] + JOB_SECONDS),
                         self.deps, lambda **told: self._report(job["id"], **told))
        if outcome.status != "done":
            self._close(job, outcome.status, outcome.error)
        elif not self._keep(job, outcome, task.get("lang")):
            # The update lost to a cancel or to the sweeper. A cancel still has to be ended; the sweeper's end stands.
            self._close(job, "cancelled")

    def _stopped(self, job_id: str) -> bool:
        """Whether the job should stop: its cancel flag is up, or it is not running any more."""
        with self.store.lock:
            row = self.store.db.execute("select status, cancel from gen where id=?", (job_id,)).fetchone()
        return row is None or row["status"] != "running" or bool(row["cancel"])

    def _report(self, job_id: str, stage=None, attempt=None, usd=None):
        with self.store.lock:
            self.store.db.execute("update gen set stage=coalesce(?, stage), attempt=coalesce(?, attempt), usd=coalesce(?, usd)"
                                  " where id=? and status='running'", (stage, attempt, usd, job_id))

    def _charge(self, job: dict) -> bool:
        """The charge of a picked account job: up to three tries with the same ref (the ledger is idempotent by
        ref). True when the credit was taken; otherwise the job has ended here."""
        owner, ref = job["owner"], "gen:" + job["id"]
        with self.store.lock:
            email = self.mail.get(owner, "")
        if self.ledger is None or not email:
            self._close(job, "failed", "no_ledger", charge="none")  # the ledger was never asked
            return False
        waits = list(CHARGE_RETRY)
        while True:
            with self.store.lock:
                self.store.db.execute("update gen set charge_at=? where id=? and charge='pending'", (self.clock(), job["id"]))
            try:
                paid, credits = self.ledger.charge(email, DRAFT_CREDITS, ref)
                break
            except LedgerError:
                if not waits:
                    # Nobody knows whether a credit left. The sweeper refunds REFUND_WAIT after this last try.
                    self._close(job, "failed", "no_ledger", charge="unknown")
                    return False
                self.sleep(waits.pop(0))
        self._set_balance(owner, credits)
        if not paid:
            self._close(job, "failed", "no_credits", charge="none")
            with self.wake:
                self._fail_waiting([owner], "no_credits")
            return False
        with self.store.lock:
            self.store.db.execute("update gen set charge='charged' where id=? and charge='pending'", (job["id"],))
        return True

    def _right_dollars(self, row):
        """Lock and transaction held. The estimate added at the pick becomes what the calls really cost. The row's
        usd already holds GEN_CALL_USD for every answered call that named no cost (asset_generate._cost), so a
        provider that reports nothing cannot empty the counters; only a job that never reached the model gives
        its whole estimate back."""
        if row["started"] is None:
            return
        day, off = self._day(row["started"]), int(round((row["usd"] or 0) * 1_000_000)) - (row["est"] or 0)
        if off:
            self.store.add(day, "usd:all", off)
            if row["cls"] == "pw":
                self.store.add(day, "usd:pw", off)

    def _give_back(self, row, now: float, user: bool):
        """Lock and transaction held. A picked draft that leaves no result goes out of the shared count. When the
        user caused it, it stays in the owner's count and is counted against the refund limits (the owner's, and
        a password session's own); otherwise it leaves the owner's count too."""
        if row["started"] is None:
            return
        day = self._day(row["started"])
        self.store.add(day, "d:teachers" if row["cls"] == "pw" else "d:members", -1)
        if user:
            for name in self._refunds_of(row["owner"], row["sess"]):
                self.store.add(self._day(now), "rf:" + name, 1)
                self.refunds[name] = [t for t in self.refunds.get(name, []) if now - t < 3600] + [now]
        else:
            self.store.add(day, "d:" + row["owner"], -1)

    def _end(self, job_id: str, status: str, code: str = "", charge=None) -> tuple[bool, bool]:
        """A running job to failed or cancelled: one conditional update, and the next `charge` in the same
        statement (a taken credit becomes refund_due unless the caller names the value). Returns (won, a refund
        is due). Whoever loses the update leaves the ledger alone."""
        now = self.clock()
        with self.wake:
            with self.store.tx() as db:
                won = db.execute(
                    "update gen set status=?, error=?, stage=null, input=null, finished=?, expires=?,"
                    " charge=case when ? is not null then ? when charge='charged' then 'refund_due' else charge end"
                    " where id=? and status='running'",
                    (status, code or None, now, now + TRACE_TTL, charge, charge, job_id)).rowcount
                row = db.execute("select owner, cls, sess, started, est, usd, charge from gen where id=?", (job_id,)).fetchone()
                if won:
                    self._right_dollars(row)
                    self._give_back(row, now, user=status == "cancelled" or code in USER_ENDS)
            self.wake.notify_all()
        return bool(won), bool(won) and row["charge"] == "refund_due"

    def _close(self, job: dict, status: str, code: str = "", charge=None):
        won, due = self._end(job["id"], status, code, charge)
        if won:
            log.info("asset job %s %s %s", job["id"], status, code)
        if due:
            self._refund(job["id"], job["owner"])  # this worker holds the job and its own charge call has answered

    def _refund(self, job_id: str, owner: str) -> bool:
        """One refund call. On an answer the row is `refunded`; on LedgerError it stays as it is for the sweeper."""
        if self.ledger is None or not owner.startswith("acct:"):
            return False
        try:
            credits = self.ledger.refund_key(owner[len("acct:"):], DRAFT_CREDITS, "gen:" + job_id)
        except LedgerError:
            return False
        with self.store.lock:
            self.store.db.execute("update gen set charge='refunded' where id=? and charge in ('pending','unknown','refund_due')", (job_id,))
        self._set_balance(owner, credits)
        return True

    def _keep(self, job: dict, outcome, lang) -> bool:
        """Writes the result's files, then takes the job to done with one conditional update. False when the
        update lost (a cancel or the sweeper was first): the files are deleted again."""
        folder = self.renders / job["id"]
        folder.mkdir(parents=True, exist_ok=True)
        digest = lambda data: hashlib.sha256(data).hexdigest()  # noqa: E731
        (folder / "master.wav").write_bytes(outcome.wav)
        stems = []
        for n, (label, data) in enumerate(outcome.stems, 1):
            (folder / f"stem-{n}.wav").write_bytes(data)
            stems.append({"n": n, "bytes": len(data), "sha256": digest(data)})
        got = outcome.result
        result = {"seconds": got.get("seconds"), "rate": got.get("rate"), "channels": got.get("channels"), "bits": got.get("bits"),
                  "bytes": len(outcome.wav), "sha256": digest(outcome.wav), "stems": stems}
        if got.get("stems_lowered_db"):  # the stems were written this many dB under the master's gain (asset_generate.trim)
            result["stems_lowered_db"] = got["stems_lowered_db"]
        more = {"engine": "nkido", "model": got.get("model"), "prompt": got.get("prompt"), "source": got.get("source"),
                "bpm": got.get("bpm"), "labels": [label for label, _ in outcome.stems], "measure": got.get("measure"),
                "issues": got.get("issues"), "repairs": got.get("repairs"), "sources": ag.sources_for(lang)}
        view = json.dumps({"lang": lang, "result": result, "more": more}, ensure_ascii=False)
        size, now = len(outcome.wav) + sum(s["bytes"] for s in stems), self.clock()
        with self.wake:
            with self.store.tx() as db:
                won = db.execute(
                    "update gen set status='done', stage=null, error=null, input=null, view=?, bytes=?, usd=?, finished=?, expires=?"
                    " where id=? and status='running' and cancel=0",
                    (view, size, outcome.usd, now, now + UNFETCHED_TTL, job["id"])).rowcount
                if won:
                    self._right_dollars(db.execute("select cls, started, est, usd from gen where id=?", (job["id"],)).fetchone())
            self.wake.notify_all()
        if not won:
            shutil.rmtree(folder, ignore_errors=True)
        else:
            log.info("asset job %s done", job["id"])
        return bool(won)

    # ---------- the sweeper ----------
    def _gone(self, db, job_id: str, now: float, received: bool) -> bool:
        """Lock and transaction held. A done row to its `gone` trace, by the update the row's state allows."""
        if received:
            return bool(db.execute("update gen set status='gone', view=null, input=null, expires=? where id=?"
                                   " and status='done' and delivered is not null", (now + TRACE_TTL, job_id)).rowcount)
        return bool(db.execute(
            "update gen set status='gone', view=null, input=null, expires=?,"
            " charge=case when charge='charged' then 'refund_due' else charge end"
            " where id=? and status='done' and delivered is null", (now + TRACE_TTL, job_id)).rowcount)

    def sweep(self):
        """What time undoes, in the order of D: rows that lost their worker, jobs that waited too long, refunds
        still owed, the two expiries, and the disk. Before those, whether sounds can still be made and measured.
        Runs at the start and every SWEEP_EVERY seconds."""
        now, drop = self.clock(), []
        self._check_engine()
        self._check_measure()
        with self.wake:
            lost = [r["id"] for r in self.store.all("select id from gen where status='running' and started<=?", (now - STALE_RUNNING,))
                    if not self._is_held(r["id"])]
            late = self.store.all("select id, owner from gen where status='queued' and created<=?", (now - QUEUE_WAIT,))
            with self.store.tx() as db:
                for job_id, at in self.seen.items():
                    db.execute("update gen set seen=? where id=?", (at, job_id))
                for row in late:
                    db.execute("update gen set status='failed', error='busy', finished=?, input=null, expires=? where id=?"
                               " and status='queued'", (now, now + TRACE_TTL, row["id"]))
            self.seen.clear()
            self._forget([(row["owner"], row["id"]) for row in late])
            # What is only kept for a while: the turns of sessions with nothing left, refunds over an hour old.
            live = {(owner, entry[4]) for owner, queue in self.waiting.items() for entry in queue} | set(self.lane_active)
            self.lane_served = {lane: at for lane, at in self.lane_served.items() if lane in live}
            self.refunds = {name: times for name, times in self.refunds.items() if any(now - t < 3600 for t in times)}
        for job_id in lost:
            if self._end(job_id, "failed", "timeout")[0]:
                log.warning("asset job %s lost its worker", job_id)
        with self.wake:
            with self.store.tx() as db:
                for row in self.store.all("select id, owner, cls, sess, started from gen where status='done' and delivered is null"
                                          " and finished<=?", (now - UNFETCHED_TTL,)):
                    if self._gone(db, row["id"], now, received=False):
                        self._give_back(row, now, user=True)
                        drop.append(row["id"])
                for row in self.store.all("select id from gen where status='done' and delivered is not null and finished<=?",
                                          (now - RESULT_TTL,)):
                    if self._gone(db, row["id"], now, received=True):
                        drop.append(row["id"])
                db.execute("delete from gen where status in ('gone','failed','cancelled') and expires<=?"
                           " and charge not in ('pending','unknown','refund_due')", (now,))
                db.execute("delete from req where created<=?", (now - REQ_TTL,))
                db.execute("delete from counts where day<?", (self._day(now),))
        for job_id in drop:
            shutil.rmtree(self.renders / job_id, ignore_errors=True)
        self._sweep_refunds(now)
        self._sweep_disk(now)
        with self.wake:
            self.wake.notify_all()

    def _check_engine(self):
        """No lock held. Looks whether the engine's program is still where the engine says (nkido.EXE). Gone, what
        waits fails uncharged and requests are turned away before a draft finds it out; back, generation is on
        again without a restart. An engine that names no file (a test's own) is left as the last render found it."""
        exe = getattr(self.engine, "EXE", "")
        if not exe:
            return
        there = Path(exe).is_file()
        with self.store.lock:
            was = self.engine_ok
        if was and not there:
            self._engine_missing()
        elif there and not was:
            with self.wake:
                self.engine_ok = True
                self.wake.notify_all()
            log.warning("nkido is back; asset generation is on again")

    def _check_measure(self):
        """No lock held. Asks the measure whether measuring works (NodeLint.check runs Node on a short tone), so
        that requests are turned away before a draft pays for model calls whose sound nobody can measure, and
        taken again once Node is back. A measure without check (a test's own) is left alone."""
        check = getattr(self.measure, "check", None)
        if not callable(check):
            return
        was = self._measures()
        try:
            check()
        except Exception as exc:
            log.error("asset measure check failed: %s", type(exc).__name__)
        if was and not self._measures():
            log.error("ALERT asset sounds cannot be measured (Node); generation rests")

    def _sweep_refunds(self, now: float):
        """Refunds for rows no live worker holds, once their last charge try is REFUND_WAIT old. Which rows is
        told by `charge`, never by status. The ledger is called without the lock, one row at a time. A ledger
        that turns a refund down is asked again at the next sweep, and nothing else tells anybody: REFUND_LATE
        of sweeps that all ended that way is an ALERT in the log, and one more every REFUND_ALERT_EVERY."""
        if self.ledger is None:
            return
        with self.store.lock:
            rows = [(r["id"], r["owner"]) for r in self.store.all(
                "select id, owner from gen where charge in ('pending','unknown','refund_due') and coalesce(charge_at, 0)<=?",
                (now - REFUND_WAIT,)) if not self._is_held(r["id"])]
        down = False
        for job_id, owner in rows:
            if owner.startswith("acct:") and not self._refund(job_id, owner):
                down = True
                break  # the ledger is not answering; the next sweep tries again
        if not down:
            self.refunds_down = None
            return
        if self.refunds_down is None:
            self.refunds_down = now
        if now - self.refunds_down >= REFUND_LATE and now - self.refunds_said >= REFUND_ALERT_EVERY:
            self.refunds_said = now
            log.error("ALERT the credit ledger has turned asset refunds down for %d minutes; credits still to go back: %d",
                      (now - self.refunds_down) // 60, len(rows))

    def _used(self) -> int:
        total = 0
        for base, _, names in os.walk(self.renders):
            for name in names:
                with contextlib.suppress(OSError):
                    total += os.path.getsize(os.path.join(base, name))
        return total

    def _sweep_disk(self, now: float):
        """Over DISK_CAP, received results nobody asked about for SEEN_IDLE seconds go, oldest first. A result
        not received yet is never deleted before it expires. Still over, or the volume nearly full: picking
        rests and new requests get 503 busy."""
        used = self._used()
        if used > self.disk_cap:
            with self.store.lock:
                rows = self.store.all("select id, bytes, seen, delivered from gen where status='done' and delivered is not null")
            # Right after a restart nobody has been seen yet, so everything counts as seen at the start.
            idle = sorted((max(r["seen"] or r["delivered"], self.boot), r["id"], r["bytes"] or 0) for r in rows)
            for seen, job_id, held in idle:
                if used <= self.disk_cap or now - seen <= SEEN_IDLE:
                    break
                with self.store.lock, self.store.tx() as db:
                    went = self._gone(db, job_id, now, received=True)
                if went:
                    shutil.rmtree(self.renders / job_id, ignore_errors=True)
                    used -= held
        paused = used > self.disk_cap or self._free(self.renders) < DISK_FREE_MIN
        if paused and not self.disk_paused:
            log.error("ALERT asset renders are out of room; generation rests")
        with self.store.lock:
            self.disk_paused = paused

    # ---------- restart ----------
    def recover(self):
        """Before any worker starts: whatever was queued or running failed as `restarted`, and its charge says
        what the sweeper owes (pending -> unknown, charged -> refund_due). Finished results stay. Nothing is put
        back in the queue, because the emails were only in memory. Then the folders nobody owns are deleted."""
        now = self.clock()
        with self.store.lock:
            with self.store.tx() as db:
                for row in self.store.all("select id, owner, cls, started, est, usd from gen where status in ('queued','running')"):
                    done = db.execute(
                        "update gen set status='failed', error='restarted', stage=null, input=null, finished=?, expires=?,"
                        " charge=case charge when 'pending' then 'unknown' when 'charged' then 'refund_due' else charge end"
                        " where id=? and status in ('queued','running')", (now, now + TRACE_TTL, row["id"])).rowcount
                    if done:
                        self._right_dollars(row)
                        self._give_back(row, now, user=False)
            keep = {r["id"] for r in self.store.all("select id from gen where status='done'")}
        with contextlib.suppress(OSError):
            for folder in self.renders.iterdir():
                if folder.is_dir() and folder.name not in keep:
                    shutil.rmtree(folder, ignore_errors=True)
        with contextlib.suppress(OSError):
            for folder in self.temp.glob("olmuse-nkido-*"):
                with contextlib.suppress(OSError):
                    if folder.is_dir() and time.time() - folder.stat().st_mtime > TEMP_STALE:
                        shutil.rmtree(folder, ignore_errors=True)
