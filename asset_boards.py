"""The asset room's boards kept on the server: records, their history, and the sound bytes they point at.

docs/ASSET_SYNC_SPEC.md is the contract (sections A, B, D, F). The API process (asset_api.py) holds one BoardStore
and calls:

    boards(owner)                                  GET  /boards
    make(owner, board, first, home)                POST /boards
    open(owner, board)                             POST /boards/{board}/open
    sync(owner, board, dev, since, ops)            POST /boards/{board}/sync
    have(owner, board, shas)                       POST /boards/{board}/blobs
    chunk(owner, board, sha, at, size, data)       POST /boards/{board}/blobs/{sha}
    adopt(owner, board, sha, src)                  POST /boards/{board}/blobs/{sha}/job   (src: a finished render)
    blob(owner, board, sha)                        GET  /boards/{board}/blobs/{sha}       -> (path, bytes)

owner is the account key (an acct token's sub). A refusal is a GenError(status, code, **extras); TEXT words the
codes that are this file's own.

One connection, WAL, one threading.Lock, writes in `begin immediate`, as GenStore. Nothing is serialized, hashed or
read from or written to a file while that lock is held: records are made canonical before it, and the bytes of a
sound are appended, hashed and moved under a lock of their own per part file. Importing this module opens no file
and starts no thread. No streamlit import."""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
from dataclasses import dataclass, fields
from pathlib import Path

from asset_generate import GenError

MB, GB = 1000 ** 2, 1000 ** 3
DB_NAME = "asset-boards.sqlite3"
BLOBS_NAME = "asset-blobs"
PART_DIR = "part"
KINDS = ("meta", "cat", "ref", "dyn", "asset")
META_UIDS = ("game", "rules")
MAX_INT = 2 ** 53
BOARD_RE = re.compile(r"[0-9a-f]{32}")
SHA_RE = re.compile(r"[0-9a-f]{64}")
DEV_RE = re.compile(r"[0-9a-f]{16}")
UID_RE = re.compile(r"[A-Za-z0-9_.:-]{1,64}")

SCHEMA = """
create table if not exists info    (k text primary key, v text not null);
create table if not exists board   (id text primary key, owner text not null, name text not null default 'null',
                                    made integer not null, changed integer not null,
                                    head integer not null default 0, bytes integer not null default 0,
                                    text integer not null default 0);
create table if not exists member  (board text not null, owner text not null, role text not null, joined integer not null,
                                    primary key (board, owner));
create index if not exists member_owner on member (owner);
create table if not exists acct    (owner text primary key, home text);
create table if not exists rec     (board text not null, kind text not null, uid text not null, rev integer not null,
                                    born integer not null, at integer not null, dev text not null, owner text not null,
                                    gone integer not null default 0, live integer not null default 0, data text not null,
                                    size integer not null default 0, shas text not null default '',
                                    vids text not null default '',
                                    primary key (board, kind, uid));
create unique index if not exists rec_rev on rec (board, rev);
create table if not exists rec_hist(board text not null, kind text not null, uid text not null, rev integer not null,
                                    at integer not null, dev text not null, owner text not null, gone integer not null,
                                    data text not null, size integer not null default 0,
                                    primary key (board, kind, uid, rev));
create table if not exists blob    (sha text primary key, bytes integer not null, at integer not null);
create table if not exists uses    (board text not null, sha text not null, at integer not null, primary key (board, sha));
create index if not exists uses_sha on uses (sha);
"""

TEXT = {
    "en": {
        "acct_only": "Boards are kept on the server for signed-in accounts only.",
        "sync_off": "Board sync is not on for this account.",
        "no_board": "There is no such board.",
        "upgrade": "A new version is out. Reload to keep syncing.",
        "offset": "The upload goes on from where the server is.",
        "board_full": "The board is out of space.",
        "bad_blob": "The sound that came in does not match its address.",
    },
    "ko": {
        "acct_only": "보드는 로그인한 계정만 서버에 보관해요.",
        "sync_off": "이 계정은 보드 동기화가 꺼져 있어요.",
        "no_board": "그런 보드가 없어요.",
        "upgrade": "새 버전이 있어요. 새로고침하면 동기화가 이어져요.",
        "offset": "서버에 있는 곳부터 이어서 올려요.",
        "board_full": "보드 저장 공간이 찼어요.",
        "bad_blob": "받은 소리가 주소와 맞지 않아요.",
    },
}


def message(lang, code) -> str | None:
    """The sentence for one of this file's codes, or None for a code that is not this file's."""
    return TEXT.get(lang if lang in TEXT else "en", TEXT["en"]).get(str(code))


@dataclass
class Limits:
    """The ceilings of section A. OLMUSE_BOARD_LIMITS "NAME=value,..." lowers or raises any of them."""
    PROTO: int = 1
    RECORD_MAX: int = 1_200_000
    OPS_MAX: int = 400
    CHANGES_MAX: int = 1_000_000
    RECORDS_PER_BOARD: int = 20_000
    TEXT_PER_BOARD: int = 64 * MB
    HISTORY_PER_RECORD: int = 20
    CHUNK_MAX: int = 1_000_000
    BLOB_MAX: int = 60 * MB
    BOARD_BYTES: int = 2 * GB
    ACCOUNT_BYTES: int = 4 * GB
    PARTS_PER_ACCOUNT: int = 4
    ALL_BYTES: int = 20 * GB
    FREE_MIN: int = 4 * GB
    BOARDS_PER_ACCOUNT: int = 20
    PART_AGE: int = 86_400
    PART_STALL: int = 600
    PEER_GONE: int = 90

    @classmethod
    def parse(cls, text: str = "") -> "Limits":
        """Limits with the "NAME=value,..." of text over the defaults. A name that is not one, or a value that is
        not a whole number of 0 or more, is skipped."""
        out, names = cls(), {spot.name for spot in fields(cls)}
        for part in str(text or "").split(","):
            name, _, value = part.partition("=")
            name, value = name.strip().upper(), value.strip().replace("_", "")
            if name in names and value.isascii() and value.isdigit():
                setattr(out, name, int(value))
        return out


# ---------- shapes (before anything touches the database or a path) ----------
def whole(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < MAX_INT


def check(value, pattern: re.Pattern, field: str) -> str:
    """value when it is a string of the pattern's shape, else GenError 400 bad_request {field}."""
    if not (isinstance(value, str) and pattern.fullmatch(value)):
        raise GenError(400, "bad_request", field=field)
    return value


def board_id(value) -> str:
    return check(value, BOARD_RE, "board")


def sha_id(value) -> str:
    return check(value, SHA_RE, "sha")


def dev_id(value) -> str:
    return check(value, DEV_RE, "dev")


def number(value, field: str) -> int:
    if not whole(value):
        raise GenError(400, "bad_request", field=field)
    return value


def canon(data) -> str:
    """The canonical text of a record's data: sorted keys, no spaces, not ASCII-escaped (board.js canon)."""
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def shas_of(kind: str, data: dict) -> set:
    """The sound addresses a record points at: the sha256 of its versions, drafts and their stems, or of a reference."""
    found = set()

    def take(value):
        if isinstance(value, str) and SHA_RE.fullmatch(value):
            found.add(value)
    if kind == "ref":
        take(data.get("sha256"))
    elif kind == "asset":
        for key in ("versions", "drafts"):
            items = data.get(key)
            for item in items if isinstance(items, list) else ():
                if isinstance(item, dict):
                    take(item.get("sha256"))
                    stems = item.get("stems")
                    for stem in stems if isinstance(stems, list) else ():
                        if isinstance(stem, dict):
                            take(stem.get("sha256"))
    return found


def version_ids(kind: str, data: dict) -> list:
    if kind != "asset":
        return []
    items = data.get("versions")
    return [str(v["id"]) for v in items if isinstance(v, dict) and isinstance(v.get("id"), (str, int))] \
        if isinstance(items, list) else []


@dataclass
class Op:
    """One write of a sync, made ready before the lock: its canonical text and what is read off it."""
    kind: str
    uid: str
    base: int
    gone: bool
    text: str = ""
    size: int = 0
    shas: frozenset = frozenset()
    vids: tuple = ()
    live: int = 0
    name: str | None = None
    bad: str = ""


def prepare(op: dict, limits: Limits) -> Op:
    """An op as the request carried it ({kind, uid, base, data} or {kind, uid, base, gone: true}; base checked
    already) made ready, or with bad set to the code it is refused with."""
    kind, uid, base, gone = op.get("kind"), op.get("uid"), op.get("base"), op.get("gone") is True
    if not isinstance(kind, str) or kind not in KINDS:
        return Op(str(kind)[:16], str(uid)[:64], base, gone, bad="kind")
    if not isinstance(uid, str) or not UID_RE.fullmatch(uid) or (kind == "meta" and uid not in META_UIDS):
        return Op(kind, str(uid)[:64], base, gone, bad="uid")
    if gone:
        return Op(kind, uid, base, True)
    data = op.get("data")
    if not isinstance(data, dict):
        return Op(kind, uid, base, False, bad="data")
    try:
        text = canon(data)
    except (ValueError, TypeError, RecursionError):
        return Op(kind, uid, base, False, bad="data")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        return Op(kind, uid, base, False, bad="text")
    if size > limits.RECORD_MAX:
        return Op(kind, uid, base, False, bad="too_large")
    if kind == "asset" and not isinstance(data.get("versions", []), list):
        return Op(kind, uid, base, False, bad="data")
    live = int(kind == "asset" and not data.get("trashedAt"))
    name = canon(data.get("game")) if (kind, uid) == ("meta", "game") else None
    return Op(kind, uid, base, False, text, size, frozenset(shas_of(kind, data)), tuple(version_ids(kind, data)), live, name)


# ---------- files ----------
def _hold(path: Path):
    """An exclusive lock on a file, kept until the handle is closed (asset_jobs._hold)."""
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


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


class StoreTaken(RuntimeError):
    """The board database already has its BoardStore, in this process or another one."""


def place_of(db_path) -> tuple[Path, Path]:
    """The lock file and the boot count file of a database: <name>.lock and <name>.boots beside it, where name is
    the file name up to its first dot. Neither has .sqlite in it, so the daily backup's *.sqlite* never opens one."""
    path = Path(db_path)
    stem = path.name.split(".")[0] or "asset-boards"
    return path.with_name(stem + ".lock"), path.with_name(stem + ".boots")


class BoardStore:
    """asset-boards.sqlite3 and the asset-blobs folder beside it. hook(name), when set, is called at the points a
    test kills or holds the process: "commit" (a sync's writes are in, the commit is not), "append" (a chunk is
    about to be written to its part file), "moved" (a finished file is in place, its rows are not).

    admin=True is the operator's tool beside a running API: no lock file, no new boot, no part sweep. SQLite's own
    file locks keep its writes and the API's apart, and the API keeps nothing of the records in memory."""

    def __init__(self, path, blobs=None, limits: Limits | None = None, clock=time.time, free=None, admin: bool = False):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.blobs = Path(blobs) if blobs else self.path.parent / BLOBS_NAME
        self.parts = self.blobs / PART_DIR
        self.limits, self.clock = limits or Limits(), clock
        self.free = free or (lambda folder: shutil.disk_usage(folder).free)
        self.hook = None
        lock_file, self.boots_file = place_of(self.path)
        if admin and not self.path.is_file():
            raise FileNotFoundError(str(self.path))
        self.held = None if admin else _hold(lock_file)
        if self.held is None and not admin:
            raise StoreTaken(self.path.name + " is already open in a running process")
        self.lock = threading.Lock()
        self.part_locks: dict[tuple, threading.Lock] = {}
        self.parts_lock = threading.Lock()
        try:
            self.parts.mkdir(parents=True, exist_ok=True)
            self.db = sqlite3.connect(str(self.path), check_same_thread=False, isolation_level=None, timeout=10)
            self.db.row_factory = sqlite3.Row
            with self.lock:
                self.db.execute("pragma journal_mode=wal")
                self.db.execute("pragma busy_timeout=10000")
                self.db.executescript(SCHEMA)
            if admin:
                self.epoch = (self.db.execute("select v from info where k='epoch'").fetchone() or [""])[0]
            else:
                self.epoch = self._boot()
                self.sweep_parts()
        except BaseException:
            if self.held is not None:
                self.held.close()
            raise

    # ---------- small things ----------
    def _boot(self) -> str:
        """The epoch (D1): the same as before when the database and the boots file agree, a new one when the database
        came back from a copy."""
        try:
            on_file = self.boots_file.read_text(encoding="ascii").strip()
        except (OSError, ValueError):
            on_file = None
        with self.lock:
            row = dict((r["k"], r["v"]) for r in self.db.execute("select k, v from info"))
            count = lambda v: int(v) if isinstance(v, str) and v.isascii() and v.isdigit() else 0  # noqa: E731
            same = on_file is not None and row.get("boots") == on_file and bool(row.get("epoch"))
            boots = max(count(on_file), count(row.get("boots"))) + 1
            epoch = row["epoch"] if same else secrets.token_hex(8)
            with self.tx() as db:
                db.execute("insert or replace into info values ('epoch', ?)", (epoch,))
                db.execute("insert or replace into info values ('boots', ?)", (str(boots),))
        tmp = self.boots_file.with_name(self.boots_file.name + ".tmp")
        tmp.write_text(str(boots), encoding="ascii")
        os.replace(tmp, self.boots_file)
        return epoch

    @contextlib.contextmanager
    def tx(self):
        self.db.execute("begin immediate")
        try:
            yield self.db
        except BaseException:
            self.db.execute("rollback")
            raise
        self.db.execute("commit")

    def _now(self) -> int:
        return int(self.clock())

    def _hook(self, name: str):
        if self.hook is not None:
            self.hook(name)

    def _member(self, owner: str, board: str):
        """Inside the lock: GenError 404 no_board when the board is not there or owner is not one of its members."""
        if self.db.execute("select 1 from member where board=? and owner=?", (board, owner)).fetchone() is None:
            raise GenError(404, "no_board")

    def member(self, owner: str, board: str):
        """GenError 404 no_board unless owner is a member of board."""
        board_id(board)
        with self.lock:
            self._member(owner, board)

    def _dest(self, sha: str) -> Path:
        return self.blobs / sha[:2] / sha

    def _part(self, board: str, sha: str, ext: str = ".part") -> Path:
        return self.parts / f"{board}-{sha}{ext}"

    def close(self):
        with self.lock:
            self.db.close()
            if self.held is not None:
                self.held.close()
                self.held = None

    # ---------- boards ----------
    def boards(self, owner: str) -> dict:
        with self.lock:
            rows = self.db.execute(
                "select b.id, b.name, b.changed, b.made, (select count(*) from rec r where r.board=b.id and r.live=1) live"
                " from board b join member m on m.board=b.id where m.owner=? order by b.changed desc, b.made desc, b.id",
                (owner,)).fetchall()
            home = self._home(owner)
        return {"epoch": self.epoch, "home": home,
                "boards": [{"id": r["id"], "name": json.loads(r["name"]), "live": r["live"], "changed": r["changed"],
                            "made": r["made"]} for r in rows]}

    def _home(self, owner: str):
        home = self.db.execute("select home from acct where owner=?", (owner,)).fetchone()
        if home is None or home["home"] is None:
            return None
        if self.db.execute("select 1 from member where board=? and owner=?", (home["home"], owner)).fetchone() is None:
            return None
        return home["home"]

    def make(self, owner: str, board: str, first: bool = False, home: bool = False) -> dict:
        """POST /boards: in one transaction, the rules of section C."""
        board_id(board)
        now = self._now()
        with self.lock, self.tx() as db:
            found = db.execute("select 1 from board where id=?", (board,)).fetchone()
            if found is not None:
                self._member(owner, board)
                return {"board": board, "created": False, "epoch": self.epoch}
            mine = db.execute("select b.id from board b join member m on m.board=b.id where m.owner=?"
                              " order by b.changed desc, b.made desc, b.id", (owner,)).fetchall()
            if first and mine:
                return {"board": self._home(owner) or mine[0]["id"], "created": False, "epoch": self.epoch}
            if len(mine) >= self.limits.BOARDS_PER_ACCOUNT:
                raise GenError(409, "board_full", limit=self.limits.BOARDS_PER_ACCOUNT)
            db.execute("insert into board (id, owner, made, changed) values (?,?,?,?)", (board, owner, now, now))
            db.execute("insert into member values (?,?,'owner',?)", (board, owner, now))
            if home or self._home(owner) is None:
                db.execute("insert into acct values (?,?) on conflict (owner) do update set home=excluded.home", (owner, board))
        return {"board": board, "created": True, "epoch": self.epoch}

    def open(self, owner: str, board: str) -> dict:
        board_id(board)
        with self.lock, self.tx() as db:
            self._member(owner, board)
            db.execute("insert into acct values (?,?) on conflict (owner) do update set home=excluded.home", (owner, board))
        return {"home": board, "epoch": self.epoch}

    # ---------- records ----------
    def sync(self, owner: str, board: str, dev: str, since: int, ops: list) -> dict:
        """POST /boards/{board}/sync (D3), less peers and up, which are the API's memory. ops are the request's,
        each a dict whose base is a whole number already."""
        board_id(board), dev_id(dev), number(since, "since")
        if len(ops) > self.limits.OPS_MAX:
            raise GenError(400, "bad_request", field="ops")
        ready = [prepare(op, self.limits) for op in ops]
        if ready and self._free() < self.limits.FREE_MIN:
            raise GenError(503, "busy", retry_after=30)
        now, results, written, taken = self._now(), [], set(), []
        with self.lock, self.tx() as db:
            self._member(owner, board)
            for op in ready:
                results.append(self._apply(db, board, op, dev, owner, now, written))
            self._hook("commit")
            head = db.execute("select head from board where id=?", (board,)).fetchone()["head"]
            total, nxt, more = 0, head, False
            for row in db.execute("select kind, uid, rev, born, at, dev, gone, data, size from rec where board=? and rev>?"
                                  " order by rev", (board, since)):
                if row["rev"] in written:
                    nxt = row["rev"]
                    continue
                if taken and total + row["size"] > self.limits.CHANGES_MAX:
                    more = True
                    break
                total += row["size"]
                taken.append(tuple(row))
                nxt = row["rev"]
            if not more:
                nxt = head
        for result in results:  # parsed outside the lock
            if "conflict" in result and isinstance(result["conflict"].get("data"), str):
                result["conflict"]["data"] = json.loads(result["conflict"]["data"])
        changes = [{"kind": k, "uid": u, "rev": rev, "born": born, "at": at, "dev": d, "gone": bool(g), "data": json.loads(data)}
                   for k, u, rev, born, at, d, g, data, _ in taken]
        return {"epoch": self.epoch, "now": now, "head": head, "next": nxt, "more": more, "results": results,
                "changes": changes}

    def _apply(self, db, board: str, op: Op, dev: str, owner: str, now: int, written: set) -> dict:
        if op.bad:
            return {"bad": op.bad}
        row = db.execute("select rev, born, gone, live, data, size, shas, vids, dev from rec where board=? and kind=? and uid=?",
                         (board, op.kind, op.uid)).fetchone()
        cur = row["rev"] if row else 0
        if row is None and op.gone:
            return {"same": 0}  # nothing to delete
        if row is not None and ((op.gone and row["gone"]) or (not op.gone and not row["gone"] and row["data"] == op.text)):
            return {"same": cur}
        if op.base != cur:
            if row is None:
                return {"conflict": {"rev": 0, "dev": "", "gone": True, "data": None}}
            return {"conflict": {"rev": cur, "dev": row["dev"], "gone": bool(row["gone"]), "data": row["data"]}}
        if op.kind == "asset" and row is not None:
            if op.gone and not (row["live"] == 0 or op.uid.startswith("s_")):
                return {"bad": "trash_first"}
            if not op.gone and not set(filter(None, row["vids"].split("\n"))) <= set(op.vids):
                return {"bad": "versions"}
        if not op.gone:
            new = op.shas - set(filter(None, row["shas"].split(" "))) if row else op.shas
            if new:
                had = {r[0] for r in db.execute("select sha from uses where board=? and sha in (%s)" % ",".join("?" * len(new)),
                                                (board, *sorted(new)))}
                need = sorted(new - had)
                if need:
                    return {"need": need}
        if row is None and db.execute("select count(*) from rec where board=?", (board,)).fetchone()[0] >= self.limits.RECORDS_PER_BOARD:
            return {"bad": "board_full"}
        if op.gone:
            text, size, shas, vids, live = row["data"], row["size"], row["shas"], row["vids"], 0
        else:
            text, size, live = op.text, op.size, op.live
            shas, vids = " ".join(sorted(op.shas)), "\n".join(op.vids)
        if not self._fit(db, board, size):
            return {"bad": "board_full"}
        rev = self._write(db, board, op.kind, op.uid, row, op.gone, text, size, shas, vids, live, dev, owner, now, op.name)
        written.add(rev)
        return {"rev": rev, "at": now}

    def _fit(self, db, board: str, size: int) -> bool:
        """Whether size more bytes of text fit in the board once all of its history could go."""
        text, hist = db.execute("select text, (select coalesce(sum(size),0) from rec_hist where board=?) from board where id=?",
                                (board, board)).fetchone()
        return text - hist + size <= self.limits.TEXT_PER_BOARD

    def _write(self, db, board, kind, uid, row, gone, text, size, shas, vids, live, dev, owner, now, name=None) -> int:
        """One new rev of a record: the row before it goes to the history, the history is cut to HISTORY_PER_RECORD
        and to TEXT_PER_BOARD, the head moves. Inside the lock and a transaction."""
        if row is not None:  # its text moves to the history and is still counted there
            db.execute("insert or replace into rec_hist select board, kind, uid, rev, at, dev, owner, gone, data, size"
                       " from rec where board=? and kind=? and uid=?", (board, kind, uid))
        rev = db.execute("update board set head=head+1, changed=?, text=text+? where id=? returning head",
                         (now, size, board)).fetchone()[0]
        db.execute("insert or replace into rec (board, kind, uid, rev, born, at, dev, owner, gone, live, data, size, shas, vids)"
                   " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (board, kind, uid, rev, row["born"] if row is not None else rev, now, dev, owner, int(gone), live, text,
                    size, shas, vids))
        if name is not None and not gone:
            db.execute("update board set name=? where id=?", (name, board))
        cut = db.execute("select rev, size from rec_hist where board=? and kind=? and uid=? order by rev desc limit -1 offset ?",
                         (board, kind, uid, self.limits.HISTORY_PER_RECORD)).fetchall()
        for old in cut:
            self._drop_hist(db, board, kind, uid, old["rev"], old["size"])
        over = db.execute("select text from board where id=?", (board,)).fetchone()[0] - self.limits.TEXT_PER_BOARD
        if over > 0:
            for old in db.execute("select kind, uid, rev, size from rec_hist where board=? order by at, rev", (board,)).fetchall():
                if over <= 0:
                    break
                self._drop_hist(db, board, old["kind"], old["uid"], old["rev"], old["size"])
                over -= old["size"]
        return rev

    @staticmethod
    def _drop_hist(db, board, kind, uid, rev, size):
        db.execute("delete from rec_hist where board=? and kind=? and uid=? and rev=?", (board, kind, uid, rev))
        db.execute("update board set text=text-? where id=?", (size, board))

    # ---------- bytes ----------
    def _free(self) -> int:
        try:
            return int(self.free(str(self.blobs)))
        except OSError:
            return 0

    def _part_lock(self, board: str, sha: str) -> threading.Lock:
        with self.parts_lock:
            return self.part_locks.setdefault((board, sha), threading.Lock())

    def _size(self, path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    def sweep_parts(self):
        """Part files older than PART_AGE go."""
        now = time.time()
        with contextlib.suppress(OSError):
            for part in self.parts.iterdir():
                with contextlib.suppress(OSError):
                    if part.is_file() and now - part.stat().st_mtime > self.limits.PART_AGE:
                        part.unlink()

    def have(self, owner: str, board: str, shas) -> dict:
        """POST /boards/{board}/blobs: which of shas this board has, and how far the unfinished ones came."""
        board_id(board)
        if not isinstance(shas, list) or len(shas) > 200:
            raise GenError(400, "bad_request", field="shas")
        shas = list(dict.fromkeys(sha_id(s) for s in shas))
        self.sweep_parts()
        with self.lock:
            self._member(owner, board)
            have = {r[0] for r in self.db.execute("select sha from uses where board=? and sha in (%s)" % ",".join("?" * len(shas)),
                                                  (board, *shas))} if shas else set()
        part = {}
        for sha in shas:
            if sha not in have:
                size = self._size(self._part(board, sha))
                if size:
                    part[sha] = size
        return {"have": [s for s in shas if s in have], "part": part, "epoch": self.epoch}

    def _room(self, owner: str, board: str, size: int):
        """Before a new part file: the ceilings of the board, the account and the folder."""
        limits = self.limits
        with self.lock:
            mine = [r[0] for r in self.db.execute("select board from member where owner=?", (owner,))]
            board_bytes = self.db.execute("select bytes from board where id=?", (board,)).fetchone()[0]
            account = self.db.execute("select coalesce(sum(b.bytes),0) from board b join member m on m.board=b.id where m.owner=?",
                                      (owner,)).fetchone()[0]
            stored = self.db.execute("select coalesce(sum(bytes),0) from blob").fetchone()[0]
        own = {b for b in mine}
        parts = [p for p in self.parts.glob("*.part")]
        own_parts = [p for p in parts if p.name[:32] in own]
        if len(own_parts) >= limits.PARTS_PER_ACCOUNT:
            gone = self._drop_stalled(own_parts)
            own_parts = [p for p in own_parts if p not in gone]
            parts = [p for p in parts if p not in gone]
        if len(own_parts) >= limits.PARTS_PER_ACCOUNT:
            raise GenError(503, "busy", retry_after=30)
        if board_bytes + size > limits.BOARD_BYTES:
            raise GenError(409, "board_full", limit=limits.BOARD_BYTES)
        if account + sum(self._size(p) for p in own_parts) + size > limits.ACCOUNT_BYTES:
            raise GenError(409, "board_full", limit=limits.ACCOUNT_BYTES)
        if stored + sum(self._size(p) for p in parts) + size > limits.ALL_BYTES:
            raise GenError(503, "busy", retry_after=60)

    def _drop_stalled(self, parts) -> set:
        """Of an account's part files at its ceiling: the ones untouched for PART_STALL seconds and not being
        appended to now go, so a cut-short upload nobody resumes does not hold the account's new bytes back."""
        now, gone = time.time(), set()
        for part in parts:
            board, _, sha = part.stem.partition("-")
            held = self._part_lock(board, sha)
            if not held.acquire(blocking=False):
                continue
            try:
                if now - part.stat().st_mtime > self.limits.PART_STALL:
                    part.unlink()
                    gone.add(part)
            except OSError:
                pass
            finally:
                held.release()
        return gone

    def _has(self, owner: str, board: str, sha: str) -> bool:
        with self.lock:
            self._member(owner, board)
            return self.db.execute("select 1 from uses where board=? and sha=?", (board, sha)).fetchone() is not None

    def _own(self, board: str, sha: str, size: int):
        """The rows of a file that is in place now: blob, uses, and the board's bytes."""
        now = self._now()
        with self.lock, self.tx() as db:
            db.execute("insert or ignore into blob values (?,?,?)", (sha, size, now))
            if db.execute("insert or ignore into uses values (?,?,?)", (board, sha, now)).rowcount:
                db.execute("update board set bytes=bytes+? where id=?", (size, board))

    def _settle(self, file: Path, board: str, sha: str, size: int):
        """A whole file whose sha256 is sha: to its place (unless the same bytes are there already), then its rows."""
        dest = self._dest(sha)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file():
            file.unlink()
        else:
            os.replace(file, dest)
        self._hook("moved")
        self._own(board, sha, size)

    def chunk(self, owner: str, board: str, sha: str, at: int, size: int, data: bytes) -> dict:
        """POST /boards/{board}/blobs/{sha}?at=&size=: data appended to the part file at offset at."""
        board_id(board), sha_id(sha), number(at, "at"), number(size, "size")
        if size > self.limits.BLOB_MAX or len(data) > self.limits.CHUNK_MAX:
            raise GenError(413, "too_large")
        if at + len(data) > size or (not data and at < size):
            raise GenError(400, "bad_request", field="at")
        if self._has(owner, board, sha):
            return {"done": True, "epoch": self.epoch}
        part, held = self._part(board, sha), self._part_lock(board, sha)
        if not held.acquire(blocking=False):
            raise GenError(409, "offset", at=self._size(part))
        try:
            cur = self._size(part) if part.is_file() else 0
            if at != cur:
                raise GenError(409, "offset", at=cur)
            if self._free() < self.limits.FREE_MIN:
                raise GenError(503, "busy", retry_after=60)
            if not part.is_file():
                self._room(owner, board, size)
            self._hook("append")
            with open(part, "ab") as out:
                out.write(data)
            end = at + len(data)
            if end < size:
                return {"at": end, "epoch": self.epoch}
            if digest(part) != sha:
                part.unlink()
                raise GenError(400, "bad_blob")
            self._settle(part, board, sha, size)
            return {"done": True, "epoch": self.epoch}
        finally:
            held.release()

    def adopt(self, owner: str, board: str, sha: str, src) -> dict:
        """POST /boards/{board}/blobs/{sha}/job: a finished render copied in, when its bytes are sha. 404 not_found
        when they are not."""
        board_id(board), sha_id(sha)
        if self._has(owner, board, sha):
            return {"done": True, "epoch": self.epoch}
        src = Path(src)
        size = self._size(src)
        if not src.is_file() or size > self.limits.BLOB_MAX:
            raise GenError(404, "not_found")
        held = self._part_lock(board, sha)
        if not held.acquire(blocking=False):
            raise GenError(503, "busy", retry_after=2)
        try:
            if self._free() < self.limits.FREE_MIN:
                raise GenError(503, "busy", retry_after=60)
            if not self._dest(sha).is_file():
                self._room(owner, board, size)
            copy = self._part(board, sha, ".job")
            shutil.copyfile(src, copy)
            if digest(copy) != sha:
                copy.unlink()
                raise GenError(404, "not_found")
            self._settle(copy, board, sha, size)
            return {"done": True, "epoch": self.epoch}
        finally:
            held.release()

    def blob(self, owner: str, board: str, sha: str) -> tuple[Path, int]:
        """GET /boards/{board}/blobs/{sha}: the file of a sha this board has. A row whose file is gone is healed
        away (its blob and uses rows go) and is 404, so the next check says it is missing and a device uploads it."""
        board_id(board), sha_id(sha)
        with self.lock:
            self._member(owner, board)
            row = self.db.execute("select b.bytes from uses u join blob b on b.sha=u.sha where u.board=? and u.sha=?",
                                  (board, sha)).fetchone()
        if row is None:
            raise GenError(404, "not_found")
        path = self._dest(sha)
        if not path.is_file():
            self.forget_blob(sha)
            raise GenError(404, "not_found")
        return path, row[0]

    def forget_blob(self, sha: str):
        """The rows of a sha whose file is gone: every board's uses (and their bytes) and the blob row."""
        with self.lock, self.tx() as db:
            for (board,) in db.execute("select board from uses where sha=?", (sha,)).fetchall():
                size = db.execute("select bytes from blob where sha=?", (sha,)).fetchone()
                db.execute("update board set bytes=max(0, bytes-?) where id=?", (size[0] if size else 0, board))
            db.execute("delete from uses where sha=?", (sha,))
            db.execute("delete from blob where sha=?", (sha,))

    # ---------- the operator's (tools/board_admin.py) ----------
    def history(self, board: str, kind: str, uid: str) -> list[dict]:
        """Every kept value of one record, newest first: the row itself, then its history."""
        board_id(board)
        with self.lock:
            rows = self.db.execute(
                "select rev, at, dev, gone, data, 1 cur from rec where board=? and kind=? and uid=?"
                " union all select rev, at, dev, gone, data, 0 cur from rec_hist where board=? and kind=? and uid=?"
                " order by rev desc", (board, kind, uid, board, kind, uid)).fetchall()
        return [{"rev": r["rev"], "at": r["at"], "dev": r["dev"], "gone": bool(r["gone"]), "current": bool(r["cur"]),
                 "data": json.loads(r["data"])} for r in rows]

    def records(self, board: str) -> list[dict]:
        board_id(board)
        with self.lock:
            rows = self.db.execute("select kind, uid, rev, gone, size from rec where board=? order by rev", (board,)).fetchall()
        return [dict(r) for r in rows]

    def restore(self, board: str, kind: str, uid: str, rev: int | None = None, dev: str = "0" * 16) -> int:
        """Writes the value the record had at rev (its last value when rev is None) as a new, live rev. Returns it."""
        kept = self.history(board, kind, uid)
        pick = next((h for h in kept if rev is None or h["rev"] == rev), None)
        if pick is None:
            raise KeyError(f"{kind}/{uid} has no rev {rev}")
        op = prepare({"kind": kind, "uid": uid, "base": 0, "data": pick["data"]}, Limits(**{**self.limits.__dict__, "RECORD_MAX": MAX_INT}))
        if op.bad:
            raise ValueError(op.bad)
        now = self._now()
        with self.lock, self.tx() as db:
            row = db.execute("select rev, born, gone, live, data, size, shas, vids, dev from rec where board=? and kind=? and uid=?",
                             (board, kind, uid)).fetchone()
            owner = db.execute("select owner from board where id=?", (board,)).fetchone()[0]
            return self._write(db, board, kind, uid, row, False, op.text, op.size, " ".join(sorted(op.shas)),
                               "\n".join(op.vids), op.live, dev, owner, now, op.name)

    def drop_board(self, board: str) -> list[str]:
        """Deletes a board: its rows, its part files, and the sound files no other board uses. Returns those shas."""
        board_id(board)
        with self.lock, self.tx() as db:
            shas = [r[0] for r in db.execute("select sha from uses where board=?", (board,))]
            alone = [s for s in shas if db.execute("select 1 from uses where sha=? and board<>?", (s, board)).fetchone() is None]
            for table, key in (("rec", "board"), ("rec_hist", "board"), ("uses", "board"), ("member", "board"), ("board", "id")):
                db.execute(f"delete from {table} where {key}=?", (board,))
            db.execute("update acct set home=null where home=?", (board,))
            for sha in alone:
                db.execute("delete from blob where sha=?", (sha,))
        for sha in alone:
            with contextlib.suppress(OSError):
                self._dest(sha).unlink()
        for part in self.parts.glob(board + "-*"):
            with contextlib.suppress(OSError):
                part.unlink()
        return alone

    def drop_account(self, owner: str) -> list[str]:
        """Deletes every board the account owns, and the account's row."""
        with self.lock:
            mine = [r[0] for r in self.db.execute("select board from member where owner=? and role='owner'", (owner,))]
        for board in mine:
            self.drop_board(board)
        with self.lock, self.tx() as db:
            db.execute("delete from member where owner=?", (owner,))
            db.execute("delete from acct where owner=?", (owner,))
        return mine
