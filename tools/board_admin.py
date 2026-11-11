"""The operator's tool for the boards kept on the server (asset_boards.py, docs/ASSET_SYNC_SPEC.md J).

  python tools/board_admin.py boards --email kid@example.com        the account's boards
  python tools/board_admin.py records BOARD                          every record of a board: kind, uid, rev, gone
  python tools/board_admin.py history BOARD KIND UID                 the kept values of one record, newest first
  python tools/board_admin.py restore BOARD KIND UID [--rev N]       that value (the last one without --rev) as a new,
                                                                     live rev: brings back a deleted record too
  python tools/board_admin.py drop-board BOARD --yes                 the board's rows, and its sound files no other
                                                                     board uses, here and in the backup copy
  python tools/board_admin.py drop-account --email kid@example.com --yes   every board the account owns

--email turns the address into the account key the way the page does (HMAC with the ledger's pepper:
STRUDEL_CREDITS_PEPPER, else ~/.all-tomorrow/strudel-credits.pepper); --owner takes the key itself ("acct:..."). The
address is never written anywhere. --db is OLMUSE_BOARD_DB, else .studio-data/asset-boards.sqlite3 (--local:
.studio-data/local/asset-boards.sqlite3); --blobs is OLMUSE_BOARD_BLOBS, else asset-blobs beside the database.

It works beside a running API: it opens the database without the API's lock file and without a new boot, and
SQLite's own locks keep the two writers apart. A device that holds a dropped board keeps its copy in the browser
and gets 404 no_board from then on."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import asset_boards as ab  # noqa: E402
from asset_generate import GenError  # noqa: E402
from credits import email_key  # noqa: E402

DATA = ROOT / ".studio-data"
LOCAL_FILES = Path.home() / ".all-tomorrow"


def pepper(env=None) -> str:
    env = os.environ if env is None else env
    value = str(env.get("STRUDEL_CREDITS_PEPPER") or "").strip()
    if value:
        return value
    try:
        return (LOCAL_FILES / "strudel-credits.pepper").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def owner_of(email: str = "", owner: str = "", env=None) -> str:
    """The account key of an address, as asset_token gives it to the API ("acct:" + HMAC(pepper, address))."""
    if owner:
        if not owner.startswith("acct:"):
            raise SystemExit("--owner is an account key that starts with acct:")
        return owner
    key = pepper(env)
    if not key:
        raise SystemExit("no pepper: set STRUDEL_CREDITS_PEPPER or put it in ~/.all-tomorrow/strudel-credits.pepper")
    return "acct:" + email_key(key, email)


def open_store(db: str = "", blobs: str = "", local: bool = False) -> ab.BoardStore:
    path = db or os.environ.get("OLMUSE_BOARD_DB") or str((DATA / "local" if local else DATA) / ab.DB_NAME)
    return ab.BoardStore(path, blobs or os.environ.get("OLMUSE_BOARD_BLOBS") or None, admin=True)


def unbackup(backup, shas):
    """The deleted sound files leave the backup copy as well (server_ops.backup_blobs never deletes there itself).
    The dated database copies keep the board's rows until they age out."""
    for sha in shas:
        try:
            (Path(backup) / "asset-blobs" / sha[:2] / sha).unlink()
        except OSError:
            pass


def run(argv=None, out=print) -> int:
    ap = argparse.ArgumentParser(description="Look at and mend the boards kept on the server.")
    ap.add_argument("--db", default="")
    ap.add_argument("--blobs", default="")
    ap.add_argument("--local", action="store_true", help="the boards of a local or scripted run")
    ap.add_argument("--backup", default=os.environ.get("OLMUSE_BACKUP_DIR") or str(DATA / "backups"),
                    help="the backup folder whose asset-blobs copy loses the deleted sound files too")
    sub = ap.add_subparsers(dest="what", required=True)
    for name in ("boards", "drop-account"):
        one = sub.add_parser(name)
        who = one.add_mutually_exclusive_group(required=True)
        who.add_argument("--email", default="")
        who.add_argument("--owner", default="")
        if name == "drop-account":
            one.add_argument("--yes", action="store_true")
    sub.add_parser("records").add_argument("board")
    for name in ("history", "restore"):
        one = sub.add_parser(name)
        one.add_argument("board")
        one.add_argument("kind", choices=ab.KINDS)
        one.add_argument("uid")
        if name == "restore":
            one.add_argument("--rev", type=int, default=None)
    drop = sub.add_parser("drop-board")
    drop.add_argument("board")
    drop.add_argument("--yes", action="store_true")
    a = ap.parse_args(argv)

    if a.what in ("drop-board", "drop-account") and not a.yes:
        out("nothing deleted: add --yes")
        return 2
    store = open_store(a.db, a.blobs, a.local)
    try:
        if a.what == "boards":
            for board in store.boards(owner_of(a.email, a.owner))["boards"]:
                out(json.dumps(board, ensure_ascii=False))
        elif a.what == "records":
            for row in store.records(a.board):
                out(json.dumps(row))
        elif a.what == "history":
            for kept in store.history(a.board, a.kind, a.uid):
                out(json.dumps(kept, ensure_ascii=False))
        elif a.what == "restore":
            out(f"{a.kind}/{a.uid} is rev {store.restore(a.board, a.kind, a.uid, a.rev)} now")
        elif a.what == "drop-board":
            gone = store.drop_board(a.board)
            unbackup(a.backup, gone)
            out(f"board {a.board} deleted with {len(gone)} sound file(s)")
        elif a.what == "drop-account":
            owner = owner_of(a.email, a.owner)
            with store.lock:
                boards = [r[0] for r in store.db.execute("select board from member where owner=? and role='owner'", (owner,))]
            for board in boards:
                unbackup(a.backup, store.drop_board(board))
            store.drop_account(owner)
            out(f"{len(boards)} board(s) deleted")
    except (KeyError, ValueError, GenError) as exc:
        out(f"not done: {getattr(exc, 'code', exc)}")
        return 1
    finally:
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
