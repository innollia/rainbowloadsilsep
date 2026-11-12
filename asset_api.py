"""The asset room's generation API: FastAPI over asset_jobs.GenJobs, under /api/asset.

    python -m uvicorn asset_api:app --host 127.0.0.1 --port 8502 --workers 1 --no-access-log --no-proxy-headers

One worker, because the queue lives in that process's memory. run_api.ps1 keeps the process up. --no-proxy-headers,
because uvicorn would otherwise put the X-Forwarded-For of a request from 127.0.0.1 in the peer's place, and the
caller's address would then not be the one address() reads (CF-Connecting-IP, believed from the tunnel only).
The public API is always on 8502. OLMUSE_API_PORT names another port for an API beside it (run_local.ps1).

    GET  /health                 no token: {ok, model, engine, node, ledger, queued, running, disk_free_mb}, and claude
                                 (the lane of OLMUSE_GEN_CLAUDE_ACCOUNTS is up) when that list is set
    GET  /quote?items=N&drafts=D
    POST /jobs                   the body asset_generate.clean_request checks
    POST /jobs/status            {ids} or {request_id}
    POST /jobs/cancel            {ids} or {request_id}
    GET  /jobs/{id}/sound        the whole WAV; the result counts as received before its first byte goes out
    GET  /jobs/{id}/stems/{n}    the same for one stem

    The boards kept on the server (asset_boards.BoardStore, docs/ASSET_SYNC_SPEC.md), for account tokens only and
    only while OLMUSE_BOARD_SYNC=1 (and the account is in OLMUSE_BOARD_ACCOUNTS, when that names any):
    GET  /boards                         POST /boards                 POST /boards/{board}/open
    POST /boards/{board}/sync            POST /boards/{board}/blobs   POST /boards/{board}/blobs/{sha}?at=&size=
    POST /boards/{board}/blobs/{sha}/job GET  /boards/{board}/blobs/{sha}
    They run on worker threads of their own (Lane "board"), so a busy board never holds up the status lookups.

Every request passes the same checks in the same order (Api.serve): Host, a POST's Origin, the declared length,
the token, the caller's requests per minute (Api.counted), then the body up to its cap and the JSON object in it. An error is
always {"error": {"code", "message", ...extras}}, worded in the token's language, and every answer says
Cache-Control: no-store.

Importing this module opens no file and starts no thread. `app` builds its jobs when the server starts it
(lifespan), from the environment (real_deps); tests hand their own Deps to create_app. No streamlit import, and
nothing is read from st.secrets. Emails, tokens, keys, request text and model replies are never logged."""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import logging
import math
import os
import threading
import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import ClientDisconnect
from starlette.responses import FileResponse, Response

import asset_boards as abd
import asset_generate as ag
import asset_jobs as aj
import asset_token
import server_ops
import studio_backend as sb
from asset_engine import nkido
from asset_generate import GenError
from credits import LocalLedger, open_ledger

log = logging.getLogger("olmuse.asset.api")

ROOT = Path(__file__).resolve().parent
DATA = ROOT / ".studio-data"
LOGS = DATA / "logs" / "api"   # the public API's. Its own folder: the page's logs/olmuse.log rotates at midnight too
START_MARK = "start-failed"    # a file in the log folder: the frames of the last start that failed
LOCAL_FILES = Path.home() / ".all-tomorrow"  # this PC's keys
PREFIX = "/api/asset"
MAX_BODY = 1_600_000   # bytes of a request body
BODY_SECONDS = 30      # a body is waited for this long in all
WINDOW = 60            # seconds the request counts look back
# Requests in WINDOW seconds of one account, or of one password session. make is POST /jobs and /jobs/cancel together.
RATES = {"make": 10, "quote": 30, "status": 120, "sound": 600}
BOARD_RATES = {"board": 600, "blob": 900}  # the board routes', counted apart from RATES the same way
PW_ADDRESS_TIMES = 6   # all the password sessions of one address together get this many times RATES
ANON_RATE = 60         # 401s one address gets in WINDOW seconds; past that it gets 429
READ_PAUSE = 0.2       # seconds before a result file that could not be read is read once more
READ_RETRY = 2         # retry_after of the 503 when it could not be read then either
HEALTH_THREADS = 2     # worker threads of /health's own
LEDGER_LANE = (8, 32)  # worker threads of the requests that may ask the ledger, and how many more may wait for one
LEDGER_WORK = ("quote", "make")  # the route methods that ask the ledger for an account's balance
BOARD_LANE = (4, 16)   # worker threads of the board routes, and how many more may wait for one
RAW_ROUTES = {"board_chunk"}  # route methods whose body is the bytes themselves, not a JSON object
JOB_ID = abd.re.compile(r"[0-9a-f]{32}")
SEEN_FORGET = 86400    # a device not seen on a board for this long is forgotten
HOME = "https://olmuse.app"  # the page's own origin. The iframe asks from it, so it needs no CORS.


def hosts_at(port: int) -> str:
    """The Hosts an API on this port answers to: the site's name, and its own address for a page on this PC."""
    return f"olmuse.app,127.0.0.1:{port},localhost:{port}"


DEFAULT_HOSTS = hosts_at(asset_token.API_PORT)
ROUTES = (  # path, methods, Api method, the rate it counts against, reads a body, needs a token
    ("/health", ["GET", "HEAD"], "health", "", False, False),
    ("/quote", ["GET"], "quote", "quote", False, True),
    ("/jobs", ["POST"], "make", "make", True, True),
    ("/jobs/status", ["POST"], "status", "status", True, True),
    ("/jobs/cancel", ["POST"], "cancel", "make", True, True),
    ("/jobs/{id}/sound", ["GET"], "sound", "sound", False, True),
    ("/jobs/{id}/stems/{n}", ["GET"], "stem", "sound", False, True),
    ("/boards", ["GET"], "boards", "board", False, True),
    ("/boards", ["POST"], "board_make", "board", True, True),
    ("/boards/{board}/open", ["POST"], "board_open", "board", True, True),
    ("/boards/{board}/sync", ["POST"], "board_sync", "board", True, True),
    ("/boards/{board}/blobs", ["POST"], "board_blobs", "blob", True, True),
    ("/boards/{board}/blobs/{sha}", ["POST"], "board_chunk", "blob", True, True),
    ("/boards/{board}/blobs/{sha}/job", ["POST"], "board_job", "blob", True, True),
    ("/boards/{board}/blobs/{sha}", ["GET"], "board_blob", "blob", False, True),
)
BOARD_WORK = frozenset(route[2] for route in ROUTES if route[3] in ("board", "blob"))
EVERY_METHOD = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


@dataclass
class Deps:
    """What an API is built from. secret is the key of the tokens (asset_token.load_secret()). renders is the
    folder of the result files and has no default on purpose: GenJobs deletes every folder in it that its store
    does not know. The rest is what asset_jobs.GenJobs takes; store None is a store in memory. hosts and origins
    are the two allow lists, a comma list or a sequence."""
    secret: bytes | str
    renders: object
    store: aj.GenStore | None = None
    ledger: object = None
    model: object = None
    engine: object = None
    measure: object = None
    temp: object = None
    limits: aj.Limits | None = None
    model_name: str = ""
    hosts: object = DEFAULT_HOSTS
    origins: object = HOME
    clock: object = time.time
    sleep: object = time.sleep
    free: object = None
    workers: int = aj.GEN_WORKERS
    autostart: bool = True
    boards: abd.BoardStore | None = None  # None: every board route is 404 not_found
    board_sync: bool = False               # OLMUSE_BOARD_SYNC=1; off, every board route is 403 sync_off
    board_accounts: object = ""            # OLMUSE_BOARD_ACCOUNTS: the emails that may sync; empty is every account
    claude: object = None                  # asset_generate.ClaudeCli: the model of the listed accounts
    claude_accounts: object = ""           # OLMUSE_GEN_CLAUDE_ACCOUNTS: emails made by `claude` without credits


def listed(value) -> tuple:
    """An allow list from a comma list or a sequence: trimmed, lower-cased, no slash at the end."""
    parts = value.split(",") if isinstance(value, str) else value
    return tuple(dict.fromkeys(part.strip().rstrip("/").lower() for part in parts if part.strip()))


class Stalled(GenError):
    """A body that did not come in BODY_SECONDS. It is answered as a body that is not valid, and the connection is
    not kept for the rest of it."""

    def __init__(self):
        super().__init__(400, "bad_request", field="")


# ---------- answers ----------
def answer(data: dict, status: int = 200, headers: dict | None = None) -> Response:
    """A JSON answer written in ASCII, so that whatever text a view carries can be sent."""
    return Response(json.dumps(data, separators=(",", ":"), allow_nan=False), status, headers, "application/json")


def refusal(error: GenError, lang) -> Response:
    """{"error": {"code", "message", ...extras}}. A 429 always names retry_after, and an answer that names it says
    it as Retry-After too."""
    extras, headers, lang = dict(error.extras), {}, sb.lang_of(lang)
    if error.status == 429:
        extras["retry_after"] = max(1, int(extras.get("retry_after") or WINDOW))
    if "retry_after" in extras:
        headers["Retry-After"] = str(extras["retry_after"])
    if isinstance(error, Stalled):
        headers["Connection"] = "close"
    said = abd.message(lang, error.code) or aj.message(lang, error)  # the board codes are worded there first
    return answer({"error": {"code": error.code, "message": said, **extras}}, error.status, headers)


def frames(exc: BaseException) -> str:
    """An exception for the log: its class and its frames. Its own text may quote a request or a model reply."""
    return type(exc).__name__ + "\n" + "".join(traceback.format_tb(exc.__traceback__))


def logs_beside(database) -> Path:
    """The log folder of an API on this database: logs/api beside it, which for the public database is LOGS. An
    API on a database of its own (run_local.ps1, OLMUSE_GEN_FAKE, a test) then leaves the public API's log alone:
    two processes on one log file each lose lines when the other moves the file at midnight."""
    return Path(database).parent / "logs" / "api"


def start_failure(exc: BaseException, folder=None) -> str:
    """What the log says of a start that failed: the class and the frames, and the class alone when the start
    before it failed with the same frames. run_api.ps1 starts the API again for as long as it fails, and every one
    of those starts would write the frames again. Which frames were last is kept in the log folder (START_MARK);
    without a folder nothing is kept."""
    said = frames(exc)
    if folder is None:
        return said
    mark = Path(folder) / START_MARK
    with contextlib.suppress(OSError, ValueError):
        if mark.read_text(encoding="utf-8") == said:
            return type(exc).__name__ + ", as before"
    with contextlib.suppress(OSError):
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(said, encoding="utf-8")
    return said


def parse(raw: bytes) -> dict:
    """The JSON object of a body."""
    try:
        body = json.loads(raw)
    except (ValueError, RecursionError):  # not JSON, not UTF-8, a number of thousands of digits, nested too deep
        body = None
    if not isinstance(body, dict):
        raise GenError(400, "bad_request", field="")
    return body


def whole(said: dict, name: str) -> int:
    """A count from the query string."""
    value = said.get(name) or ""
    if not (value.isascii() and value.isdigit() and len(value) <= 4):
        raise GenError(400, "bad_request", field=name)
    return int(value)


def large(said: dict, name: str) -> int:
    """A whole number of the query string under 2^53 (an offset, a size)."""
    value = said.get(name) or ""
    if not (value.isascii() and value.isdigit() and len(value) <= 16 and int(value) < abd.MAX_INT):
        raise GenError(400, "bad_request", field=name)
    return int(value)


def wav(sound: aj.Sound, sleep=time.sleep) -> Response:
    """A result file, whole. No Accept-Ranges, and a Range in the request changes nothing.

    The result is marked received by now. A file that is not there is 404. One that is there and cannot be read at
    this moment (on Windows another program can hold a file for an instant) is read once more, and then it is a
    503 with retry_after, not a 404: the sound is paid for and can still be received."""
    for last in (False, True):
        try:
            data = sound.read()
            break
        except FileNotFoundError:  # deleted since it was looked up
            raise GenError(404, "not_found") from None
        except OSError:
            if last:
                raise GenError(503, "busy", retry_after=READ_RETRY) from None
            sleep(READ_PAUSE)
    return Response(data, media_type="audio/wav", headers={"ETag": sound.sha256, "X-Content-Type-Options": "nosniff"})


def net(ip: str) -> str:
    """An address as it is counted and grouped by. IPv6 gives one line (a home, a classroom) a whole /64 of
    addresses, so an IPv6 address stands for its /64; an IPv4 address written as IPv6 is that IPv4 address."""
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return ip
    if parsed.version == 6 and parsed.ipv4_mapped is None:
        return str(ipaddress.IPv6Address(int(parsed) >> 64 << 64)) + "/64"
    return str(parsed.ipv4_mapped if parsed.version == 6 else parsed)


def address(request: Request) -> str:
    """The caller's address. The tunnel connects from 127.0.0.1 and names the visitor in CF-Connecting-IP; from
    any other peer that header is not believed. The server runs with --no-proxy-headers, so the peer is the
    socket's and never an X-Forwarded-For."""
    peer = request.client.host if request.client else ""
    if peer == "127.0.0.1":
        told = request.headers.get("cf-connecting-ip", "").strip()
        if told:
            return net(told[:64])
    return net(peer)


def bearer(request: Request) -> str:
    """The token of Authorization: Bearer, or "" when there is none."""
    scheme, _, sent = request.headers.get("authorization", "").strip().partition(" ")
    return sent.strip() if scheme.lower() == "bearer" else ""


class Rates:
    """Requests per WINDOW seconds, counted in memory: the times of each key's counted requests."""

    def __init__(self, clock):
        self.clock, self.lock = clock, threading.Lock()
        self.times: dict[tuple, deque] = {}
        self.swept = clock()

    def wait(self, key: tuple, limit: int, *more) -> int:
        """0 when one more request fits, and then it is counted. Otherwise the seconds until one fits; a request
        that is turned away is not counted. more is further (key, limit) pairs the same request is counted under:
        it has to fit in all of them, and it is counted in all of them or in none."""
        now, late, pairs = self.clock(), 0, ((key, limit), *more)
        with self.lock:
            if now - self.swept >= WINDOW:  # keys nobody used for a whole window go
                self.swept = now
                for old in [k for k, times in self.times.items() if not times or now - times[-1] >= WINDOW]:
                    del self.times[old]
            for key, limit in pairs:
                times = self.times.get(key) or ()
                while times and now - times[0] >= WINDOW:
                    times.popleft()
                if len(times) >= limit:
                    late = max(late, 1, math.ceil(times[0] + WINDOW - now) if times else WINDOW)
            if not late:
                for key, _ in pairs:
                    self.times.setdefault(key, deque()).append(now)
            return late


class Lane:
    """Worker threads of its own for one kind of request, beside the threads every other request shares.

    A request that asks the ledger can wait as long as the ledger's timeout. On the shared threads a few accounts'
    worth of those would hold every one of them, and /health, the status lookups and the sounds would stop
    answering together with them. Here they hold only their own, and when `waiting` requests are already in line
    for one, the next is 503 busy at once. Without `waiting` there is no such end to the line: /health takes no
    token, and anybody could fill a short line and so make the server watch read a 503."""

    def __init__(self, name: str, threads: int, waiting: int | None = None):
        self.pool = ThreadPoolExecutor(threads, thread_name_prefix="olmuse-api-" + name)
        self.room = None if waiting is None else threading.BoundedSemaphore(threads + waiting)

    async def run(self, work, *args):
        if self.room is not None and not self.room.acquire(blocking=False):
            raise GenError(503, "busy")
        try:
            return await asyncio.get_running_loop().run_in_executor(self.pool, work, *args)
        finally:
            if self.room is not None:
                self.room.release()

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)


# ---------- the API ----------
class Api:
    """What the routes share: the jobs, the token key, the two allow lists and the request counts."""

    def __init__(self, deps: Deps):
        self.secret, self.clock, self.sleep = deps.secret, deps.clock, deps.sleep
        self.hosts, self.origins = frozenset(listed(deps.hosts)), frozenset(listed(deps.origins))
        self.rates = Rates(deps.clock)
        self.health_lane, self.ledger_lane = Lane("health", HEALTH_THREADS), Lane("ledger", *LEDGER_LANE)
        self.board_lane = Lane("board", *BOARD_LANE)
        self.board_store, self.sync_on = deps.boards, bool(deps.board_sync)
        self.board_accounts = frozenset(listed(deps.board_accounts))  # in memory only
        self.seen: dict[str, dict[str, float]] = {}  # board -> device -> when it last synced; memory only
        self.seen_lock, self.up_since = threading.Lock(), deps.clock()
        self.jobs = aj.GenJobs(aj.GenStore() if deps.store is None else deps.store, ledger=deps.ledger, model=deps.model,
                               engine=deps.engine, measure=deps.measure, renders=deps.renders, temp=deps.temp,
                               limits=deps.limits, model_name=deps.model_name, clock=deps.clock, sleep=deps.sleep,
                               free=deps.free, workers=deps.workers, autostart=deps.autostart, claude=deps.claude,
                               claude_accounts=listed(deps.claude_accounts))

    def close(self):
        """Lets the lanes' threads go. The jobs and their store are stopped and closed by whoever made them."""
        self.health_lane.close()
        self.ledger_lane.close()
        self.board_lane.close()

    async def serve(self, request: Request, name: str, bucket: str = "", body: bool = False, token: bool = True) -> Response:
        """One request for the route method `name`: the checks in the order of the spec's section C, then
        work(who, raw body, said) in a worker thread, because the store's lock and the ledger can make it wait.
        said is the path's and the query's values. work gives the answer's dict or a Response, or raises GenError.

        /health has threads of its own and so have an account's quote and POST /jobs, the two that may wait for
        the ledger (Lane); everything else runs on the server's shared ones."""
        work, who = getattr(self, name), None

        def worked(who, raw, said) -> Response:
            made = work(who, raw, said)
            return made if isinstance(made, Response) else answer(made)  # a long answer is written out here too

        def lang() -> str:
            return who.lang if who is not None else self.spoken(request)

        try:
            who = self.caller(request, token)
            if who is not None and bucket:
                wait = self.rates.wait(*self.counted(who, bucket))
                if wait:
                    raise GenError(429, "rate", retry_after=wait)
            if name in BOARD_WORK:
                self.board_gate(who)
            raw = await self.read(request) if body else b""
            said = {**request.query_params, **request.path_params}
            if name == "health":
                return await self.health_lane.run(worked, who, raw, said)
            if name in BOARD_WORK:
                return await self.board_lane.run(worked, who, raw, said)
            if name in LEDGER_WORK and who.kind == "acct":
                return await self.ledger_lane.run(worked, who, raw, said)
            return await run_in_threadpool(worked, who, raw, said)
        except GenError as exc:
            return refusal(exc, lang())
        except ClientDisconnect:
            return Response(status_code=400)  # nobody is left to read it
        except Exception as exc:  # a 500 never carries what went wrong
            log.error("asset api %s crashed: %s", name, frames(exc))
            return refusal(GenError(500, "internal"), lang())

    @staticmethod
    def counted(who: aj.Who, bucket: str) -> tuple:
        """What Rates.wait takes for one request: whose requests a minute it is counted in, and how many fit.

        An account's are counted by the account. A password session's are counted by the session (the token's sub),
        so everybody in a classroom has the whole count although they share one address and one owner; and,
        PW_ADDRESS_TIMES as many, by that owner, because a reload is a new session and an address could otherwise
        have as many counts as it has reloads. The daily counts and the dollars are the owner's; a session's turn
        in its address's queue and its own count of refunds are asset_jobs' (lane_of)."""
        limit = RATES.get(bucket) or BOARD_RATES[bucket]
        if who.kind == "pw":
            return (bucket, who.session), limit, ((bucket, who.owner), limit * PW_ADDRESS_TIMES)
        return (bucket, who.owner), limit

    def hosted(self, headers) -> bool:
        """Whether the request names a Host this API answers to."""
        return headers.get("host", "").strip().lower() in self.hosts

    def spoken(self, request: Request) -> str:
        """The language for a request that was turned away before its token was judged (a wrong Host, a wrong
        Origin, a body declared too long) or whose token has run out: the token's own, when the token is one we
        signed. Nothing is counted here and nothing is allowed by it."""
        try:
            return asset_token.verify(bearer(request), self.secret, float("-inf"))["lang"]  # run out or not
        except asset_token.TokenError:
            return sb.DEFAULT_LANG

    def caller(self, request: Request, token: bool = True):
        """Host, a POST's Origin, the declared length and the token, in that order. Who asks; None for /health."""
        headers = request.headers
        if not self.hosted(headers):
            raise GenError(403, "bad_host")
        if request.method == "POST" and headers.get("origin", "").strip().lower() not in self.origins:
            raise GenError(403, "bad_origin")
        declared = headers.get("content-length", "").strip().lstrip("0")
        if declared.isascii() and declared.isdigit() and (len(declared) > 7 or int(declared) > MAX_BODY):
            raise GenError(413, "too_large")
        if not token:
            return None
        ip = address(request)
        try:
            payload = asset_token.verify(bearer(request), self.secret, self.clock())
        except asset_token.TokenError as exc:
            # Only failed tries are counted by address. A request with a good token never is.
            wait = self.rates.wait(("anon", ip), ANON_RATE)
            raise (GenError(429, "rate", retry_after=wait) if wait else GenError(401, exc.code)) from None
        owner = asset_token.owner_of(payload, self.secret, ip)
        session = payload["sub"] if payload["kind"] == "pw" else ""
        return aj.Who(payload["kind"], owner, payload.get("email") or "", payload["lang"], session)

    @staticmethod
    async def read(request: Request) -> bytes:
        """The body, read only as far as its cap and waited for only BODY_SECONDS in all. The request was counted
        before this, so a caller cannot keep more requests open here than its count a minute."""
        async def read_all() -> bytes:
            got = bytearray()
            async for chunk in request.stream():
                got += chunk
                if len(got) > MAX_BODY:
                    raise GenError(413, "too_large")
            return bytes(got)
        try:
            return await asyncio.wait_for(read_all(), BODY_SECONDS)
        except asyncio.TimeoutError:
            raise Stalled() from None

    # ---------- what each route does, in a worker thread ----------
    def health(self, who, raw, said) -> dict:
        return self.jobs.health()

    def quote(self, who, raw, said) -> dict:
        return self.jobs.quote_for(who, whole(said, "items"), whole(said, "drafts"))

    def make(self, who, raw, said) -> dict:
        return self.jobs.submit(who, parse(raw))

    def status(self, who, raw, said) -> dict:
        body = parse(raw)
        if "ids" in body:
            return self.jobs.status(who, body["ids"])
        if "request_id" in body:
            return self.jobs.status_request(who, body["request_id"])
        raise GenError(400, "bad_request", field="ids")

    def cancel(self, who, raw, said) -> dict:
        body = parse(raw)
        if "ids" in body:
            return self.jobs.cancel(who, body["ids"])
        if "request_id" in body:
            return self.jobs.cancel_request(who, body["request_id"])
        raise GenError(400, "bad_request", field="ids")

    def sound(self, who, raw, said) -> Response:
        return wav(self.jobs.sound(who, said["id"]), self.sleep)  # marked received in there, before the file is read

    def stem(self, who, raw, said) -> Response:
        n = said["n"]
        if not (n.isascii() and n.isdigit() and len(n) <= 2):
            raise GenError(404, "not_found")
        return wav(self.jobs.stem(who, said["id"], int(n)), self.sleep)

    def lost(self, who, raw, said):
        raise GenError(404, "not_found")

    # ---------- the boards (asset_boards.BoardStore) ----------
    def board_gate(self, who):
        """Whether a board route may run for who, before its body is read: the switch, a store, an account token,
        an account on the allow list. The list is compared with the token's email in memory; nothing writes it down."""
        if not self.sync_on:
            raise GenError(403, "sync_off")
        if self.board_store is None:
            raise GenError(404, "not_found")
        if who.kind != "acct":
            raise GenError(403, "acct_only")
        if self.board_accounts and who.email.strip().lower() not in self.board_accounts:
            raise GenError(403, "sync_off")

    @staticmethod
    def board_body(raw: bytes) -> dict:
        """The JSON object of a board request. A v that is not this server's PROTO is 409 upgrade."""
        body = parse(raw)
        if "v" in body and (type(body["v"]) is not int or body["v"] != abd.Limits.PROTO):
            raise GenError(409, "upgrade")
        return body

    def boards(self, who, raw, said) -> dict:
        return self.board_store.boards(who.owner)

    def board_make(self, who, raw, said) -> dict:
        body = self.board_body(raw)
        first, home = body.get("first", False), body.get("home", False)
        for field, value in (("first", first), ("home", home)):
            if not isinstance(value, bool):
                raise GenError(400, "bad_request", field=field)
        made = self.board_store.make(who.owner, abd.board_id(body.get("board")), first, home)
        log.info("board_make %s created=%s", made["board"], made["created"])
        return made

    def board_open(self, who, raw, said) -> dict:
        self.board_body(raw)
        return self.board_store.open(who.owner, abd.board_id(said["board"]))

    def board_sync(self, who, raw, said) -> dict:
        body = self.board_body(raw)
        board, dev = abd.board_id(said["board"]), abd.dev_id(body.get("dev"))
        since, ops = abd.number(body.get("since"), "since"), body.get("ops", [])
        if not isinstance(ops, list) or len(ops) > self.board_store.limits.OPS_MAX:
            raise GenError(400, "bad_request", field="ops")
        for op in ops:
            if not isinstance(op, dict):
                raise GenError(400, "bad_request", field="ops")
            abd.number(op.get("base"), "base")
        out = self.board_store.sync(who.owner, board, dev, since, ops)
        now = self.clock()
        with self.seen_lock:
            for old in [b for b, devs in self.seen.items() if all(now - t > SEEN_FORGET for t in devs.values())]:
                del self.seen[old]
            devs = self.seen.setdefault(board, {})
            devs[dev] = now
            out["peers"] = [{"dev": d, "age": max(0, int(now - t))} for d, t in devs.items() if d != dev]
        out["up"] = max(0, int(now - self.up_since))
        if ops:
            log.info("board_sync %s ops=%d changes=%d", board, len(ops), len(out["changes"]))
        return out

    def board_blobs(self, who, raw, said) -> dict:
        body = self.board_body(raw)
        return self.board_store.have(who.owner, abd.board_id(said["board"]), body.get("shas"))

    def board_chunk(self, who, raw, said) -> dict:
        """The one route whose body is not JSON (RAW_ROUTES): the bytes from offset at of a file of size bytes."""
        board, sha = abd.board_id(said["board"]), abd.sha_id(said["sha"])
        at, size = large(said, "at"), large(said, "size")
        out = self.board_store.chunk(who.owner, board, sha, at, size, raw)
        if out.get("done"):
            log.info("board_chunk %s done bytes=%d", board, size)
        return out

    def board_job(self, who, raw, said) -> dict:
        """A finished render of this account's copied into the board without its bytes being sent again. A job that
        is not this account's finished one, or whose file is not sha, is 404 not_found."""
        body = self.board_body(raw)
        board, sha = abd.board_id(said["board"]), abd.sha_id(said["sha"])
        job, stem = body.get("job"), body.get("stem")
        if not (isinstance(job, str) and JOB_ID.fullmatch(job)):
            raise GenError(400, "bad_request", field="job")
        if stem is not None and not (abd.whole(stem) and 1 <= stem <= 99):
            raise GenError(400, "bad_request", field="stem")
        self.board_store.member(who.owner, board)
        try:
            sound = self.jobs._send(who, job, stem)  # marks the result received: the board keeps it from now on
        except GenError:
            raise GenError(404, "not_found") from None
        if sound.sha256 != sha:
            raise GenError(404, "not_found")
        return self.board_store.adopt(who.owner, board, sha, sound.path)

    def board_blob(self, who, raw, said) -> Response:
        board, sha = abd.board_id(said["board"]), abd.sha_id(said["sha"])
        path, size = self.board_store.blob(who.owner, board, sha)
        return FileResponse(path, media_type="application/octet-stream",
                            headers={"ETag": sha, "X-Content-Type-Options": "nosniff"})


class NoStore:
    """Cache-Control: no-store on every answer, whoever wrote it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def stamped(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                MutableHeaders(scope=message)["Cache-Control"] = "no-store"
            await send(message)
        await self.app(scope, receive, stamped if scope["type"] == "http" else send)


class HostGate:
    """The Host check once more, outside the CORS middleware. That middleware answers a preflight by itself, before
    Api.serve sees the request, and Host comes first for every request."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            api, request = scope["app"].state.api, Request(scope)
            if api is not None and not api.hosted(request.headers):
                await refusal(GenError(403, "bad_host"), api.spoken(request))(scope, receive, send)
                return
        await self.app(scope, receive, send)


# ---------- the server's own settings ----------
def local_file(name: str) -> str:
    try:
        return (LOCAL_FILES / name).read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return ""


def pooled(name: str) -> str:
    """A value of ~/.all-tomorrow/key-pool.env, read the way tools/akkado_trial.py key() reads it."""
    for line in local_file("key-pool.env").splitlines():
        found, _, value = line.removeprefix("export ").partition("=")
        if found.strip() == name:
            return value.strip().strip("'\"")
    return ""


def real_deps(env=None, log_to=None) -> Deps:
    """The server's Deps, from the environment. What is a secret is looked for in this PC's ~/.all-tomorrow files
    after that: the model key in key-pool.env (OLMUSE_GEN_KEY, and when there is none OPENROUTER_API_KEY, each in
    the environment first), the ledger's token and pepper in their two files. Everything else is the
    environment's alone, so that a run script that removes a switch (OLMUSE_GEN_FAKE, STRUDEL_LOCAL_LEDGER) has
    really turned it off.

    With OLMUSE_BOARD_SYNC=1 the board store opens too: OLMUSE_BOARD_DB, else asset-boards.sqlite3 beside the
    database (so a local or scripted run keeps its boards in .studio-data/local), its bytes in OLMUSE_BOARD_BLOBS,
    else asset-blobs beside that, with OLMUSE_BOARD_LIMITS over its ceilings.

    With OLMUSE_GEN_CLAUDE_ACCOUNTS (emails, comma separated) those accounts are made by the Claude Code CLI on this PC
    (asset_generate.ClaudeCli): OLMUSE_GEN_CLAUDE_EXE (claude), OLMUSE_GEN_CLAUDE_MODEL (sonnet, never fable),
    OLMUSE_GEN_CLAUDE_SLOTS (2); their daily cap is Limits.claude_daily (OLMUSE_GEN_CLAUDE_DAILY). With
    OLMUSE_GEN_FAKE=1 the scripted model stands in for it too.

    The database is OLMUSE_GEN_DB, else .studio-data/asset-gen.db. A run that is not the public one, on the
    scripted model or over this PC's own ledger file, gets .studio-data/local/asset-gen.db instead: whoever opens
    a database fails what is queued or running in it and expires what nobody received, and a local ledger answers
    a refund it never charged without an error, so a paid row would end up refunded with no credit given back.
    The results are OLMUSE_RENDERS, else the folder asset-renders beside the database, so the two always move
    together (GenJobs deletes every result folder its database does not know).

    The Hosts are OLMUSE_API_HOSTS, else the site's name and this PC's address with the API's port, which is
    OLMUSE_API_PORT, else 8502 (asset_token.api_port): an API that run_local.ps1 starts on a port of its own
    answers the page that asks it there.

    The log is kept beside the database too (logs_beside). log_to, when given, is called once with that folder,
    before anything is logged from here: the server sets its log file up with it.

    Raises OSError when the token key can be neither read nor made, and asset_jobs.StoreTaken when another process
    has the database. The API does not start then."""
    env = os.environ if env is None else env

    def get(name: str, default="") -> str:
        return str(env.get(name) or default).strip()

    name, fake = get("OLMUSE_GEN_MODEL", sb.DEFAULT_CHOICE), get("OLMUSE_GEN_FAKE") == "1"
    key = "" if fake else (get("OLMUSE_GEN_KEY") or pooled("OLMUSE_GEN_KEY") or get("OPENROUTER_API_KEY")
                           or pooled("OPENROUTER_API_KEY"))
    local = get("STRUDEL_LOCAL_LEDGER") == "1"
    if local:
        DATA.mkdir(exist_ok=True)
    ledger, problem = open_ledger(get("STRUDEL_CREDITS_URL"), get("STRUDEL_CREDITS_TOKEN") or local_file("strudel-credits.token"),
                                  get("STRUDEL_CREDITS_PEPPER") or local_file("strudel-credits.pepper"), local,
                                  str(DATA / "credits.sqlite"))
    apart = fake or isinstance(ledger, LocalLedger)
    database = get("OLMUSE_GEN_DB") or str(DATA / "local" / aj.DEFAULT_DB.name if apart else aj.DEFAULT_DB)
    renders = get("OLMUSE_RENDERS") or str(Path(database).parent / aj.DEFAULT_RENDERS.name)
    if log_to is not None:
        log_to(logs_beside(database))
    if fake:
        log.warning("OLMUSE_GEN_FAKE=1: a scripted model and sine waves stand in for the model and the engine")
        model, engine, name = ag.FakeModel, ag.FakeEngine(), ag.FakeModel.name
    else:
        model, engine = (ag.model_factory(key, name, get("OLMUSE_GEN_BASE_URL")) if key else None), nkido
        if not key:
            log.error("ALERT no model key (OLMUSE_GEN_KEY or OPENROUTER_API_KEY); asset generation is off")
    if problem:
        log.error("ALERT %s; asset generation for signed-in accounts is off", problem)
    accounts, claude = get("OLMUSE_GEN_CLAUDE_ACCOUNTS"), None
    if accounts:
        try:
            slots = max(1, int(get("OLMUSE_GEN_CLAUDE_SLOTS") or ag.CLAUDE_SLOTS))
        except ValueError:
            log.error("OLMUSE_GEN_CLAUDE_SLOTS is not a number; %d stays", ag.CLAUDE_SLOTS)
            slots = ag.CLAUDE_SLOTS
        claude = ag.FakeModel if fake else ag.ClaudeCli(command=[get("OLMUSE_GEN_CLAUDE_EXE", "claude")],
                                                       model=ag.claude_model(get("OLMUSE_GEN_CLAUDE_MODEL")), slots=slots)
    secret, store = asset_token.load_secret(env=env), aj.GenStore(database)
    sync, boards = get("OLMUSE_BOARD_SYNC") == "1", None
    if sync:  # off, the board database is not even opened
        try:
            boards = abd.BoardStore(get("OLMUSE_BOARD_DB") or str(Path(database).parent / abd.DB_NAME),
                                    get("OLMUSE_BOARD_BLOBS") or None, abd.Limits.parse(get("OLMUSE_BOARD_LIMITS")))
        except BaseException:
            store.close()
            raise
    return Deps(secret=secret, renders=renders, store=store, ledger=ledger,
                model=model, engine=engine, measure=ag.NodeLint(get("OLMUSE_NODE", "node")), limits=aj.Limits.from_env(env),
                model_name=name, hosts=get("OLMUSE_API_HOSTS") or hosts_at(asset_token.api_port(env)),
                origins=get("OLMUSE_API_ORIGINS", HOME), boards=boards, board_sync=sync,
                board_accounts=get("OLMUSE_BOARD_ACCOUNTS"), claude=claude, claude_accounts=accounts)


# ---------- the app ----------
def create_app(deps: Deps | None = None) -> FastAPI:
    """The API. With deps (tests) its jobs exist at once, as app.state.api.jobs, and whoever passed them stops
    them. Without, only the origins are read now (the middleware has to be in place before the app starts) and
    everything that opens a file or starts a thread waits until the server starts the app."""
    origins = listed(deps.origins if deps is not None else os.environ.get("OLMUSE_API_ORIGINS") or HOME)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        if deps is not None:
            yield
            return
        folder = []  # the log folder, once real_deps knows where the database is

        def log_to(path):
            folder.append(Path(path))
            server_ops.setup_logging(path)
        try:
            api = await run_in_threadpool(lambda: Api(real_deps(log_to=log_to)))
        except Exception as exc:
            if not folder:
                server_ops.setup_logging(LOGS)  # it failed before it knew where: the public API's folder gets the line
            log.error("ALERT the asset api could not start: %s", start_failure(exc, folder[0] if folder else None))
            raise
        with contextlib.suppress(OSError, IndexError):
            (folder[0] / START_MARK).unlink()  # the next start that fails writes its frames again
        app.state.api = api
        log.info("asset api up: %s", json.dumps(api.jobs.health()))
        try:
            yield
        finally:
            await run_in_threadpool(api.jobs.stop)
            api.jobs.store.close()
            if api.board_store is not None:
                api.board_store.close()
            api.close()

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.api = Api(deps) if deps is not None else None

    def route(path: str, methods: list, name: str, bucket: str = "", body: bool = False, token: bool = True):
        async def endpoint(request: Request) -> Response:
            return await request.app.state.api.serve(request, name, bucket, body, token)
        app.add_api_route(path, endpoint, methods=methods, include_in_schema=False, response_model=None)

    for path, *rest in ROUTES:
        route(PREFIX + path, *rest)
    route("/{rest:path}", EVERY_METHOD, "lost")  # every other address: the same checks, then 404

    async def unrouted(request: Request, exc: HTTPException) -> Response:
        # A method no route takes (TRACE, a made-up one): the same checks, then 404.
        return await request.app.state.api.serve(request, "lost")

    async def crashed(request: Request, exc: Exception) -> Response:
        log.error("asset api crashed outside a route: %s", frames(exc))
        return answer({"error": {"code": "internal", "message": aj.message(sb.DEFAULT_LANG, "internal")}}, 500,
                      {"Cache-Control": "no-store"})

    app.add_exception_handler(HTTPException, unrouted)
    app.add_exception_handler(Exception, crashed)
    if any(origin != HOME for origin in origins):  # a local run: the page is on another port than the API
        app.add_middleware(CORSMiddleware, allow_origins=list(origins), allow_methods=["GET", "POST"],
                           allow_headers=["Authorization", "Content-Type"], expose_headers=["ETag", "Retry-After"])
        app.add_middleware(HostGate)  # added after it, so it stands outside it
    app.add_middleware(NoStore)
    return app


app = create_app()
