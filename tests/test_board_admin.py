"""The operator's tool for the boards (tools/board_admin.py) and the backups of the boards (server_ops):
docs/ASSET_SYNC_SPEC.md J and N (O)."""
import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

import asset_boards as ab
import server_ops
from credits import email_key

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import board_admin  # noqa: E402

A = "acct:" + "a" * 64
BOARD, OTHER = "0" * 31 + "1", "0" * 31 + "2"
DEV = "1" * 16


def sha(data):
    return hashlib.sha256(data).hexdigest()


def put(store, kind, uid, base, data=None, gone=False, board=BOARD):
    op = {"kind": kind, "uid": uid, "base": base, **({"gone": True} if gone else {"data": data})}
    return store.sync(A, board, DEV, 0, [op])["results"][0]


@pytest.fixture
def served(tmp_path):
    """A store as the API holds it, and the tool's arguments for the same files."""
    store = ab.BoardStore(tmp_path / ab.DB_NAME, free=lambda path: 100 * ab.GB)
    store.make(A, BOARD)
    store.make(A, OTHER)
    yield store, ["--db", str(tmp_path / ab.DB_NAME)]
    store.close()


def tool(args, *more):
    said = []
    code = board_admin.run([*args, *more], out=said.append)
    return code, said


def test_dropping_a_board_takes_its_rows_and_files_and_keeps_a_sha_another_board_uses(served, tmp_path):
    store, args = served
    for board in (BOARD, OTHER):
        store.chunk(A, board, sha(b"shared"), 0, 6, b"shared")
    store.chunk(A, BOARD, sha(b"only mine"), 0, 9, b"only mine")
    store.chunk(A, BOARD, sha(b"half of it"), 0, 10, b"half")  # an upload that never ended
    put(store, "cat", "x", 0, {"n": 1})
    store.open(A, BOARD)
    server_ops.backup_blobs(tmp_path / "asset-blobs", tmp_path / "backups" / "asset-blobs")
    args = [*args, "--backup", str(tmp_path / "backups")]
    assert tool(args, "drop-board", BOARD) == (2, ["nothing deleted: add --yes"])
    assert tool(args, "drop-board", BOARD, "--yes") == (0, [f"board {BOARD} deleted with 1 sound file(s)"])
    assert not (tmp_path / "backups" / "asset-blobs" / sha(b"only mine")[:2] / sha(b"only mine")).exists()
    assert (tmp_path / "backups" / "asset-blobs" / sha(b"shared")[:2] / sha(b"shared")).exists()
    assert not (tmp_path / "asset-blobs" / sha(b"only mine")[:2] / sha(b"only mine")).exists()
    assert (tmp_path / "asset-blobs" / sha(b"shared")[:2] / sha(b"shared")).read_bytes() == b"shared"
    assert list((tmp_path / "asset-blobs" / "part").iterdir()) == []
    with store.lock:
        for table, key in (("board", "id"), ("member", "board"), ("rec", "board"), ("rec_hist", "board"), ("uses", "board")):
            assert store.db.execute(f"select count(*) from {table} where {key}=?", (BOARD,)).fetchone()[0] == 0
        assert [r[0] for r in store.db.execute("select sha from blob")] == [sha(b"shared")]
    assert store.boards(A) == {"epoch": store.epoch, "home": None,
                               "boards": [{"id": OTHER, "name": None, "live": 0, "changed": store.boards(A)["boards"][0]["changed"],
                                           "made": store.boards(A)["boards"][0]["made"]}]}
    assert store.blob(A, OTHER, sha(b"shared"))[0].read_bytes() == b"shared"


def test_a_record_comes_back_from_its_history_and_a_deleted_one_lives_again(served):
    store, args = served
    put(store, "cat", "x", 0, {"name": "one"})
    put(store, "cat", "x", 1, {"name": "two"})
    put(store, "cat", "x", 2, gone=True)
    code, said = tool(args, "history", BOARD, "cat", "x")
    assert code == 0 and [eval_line(line)["rev"] for line in said] == [3, 2, 1]
    assert tool(args, "restore", BOARD, "cat", "x", "--rev", "1") == (0, ["cat/x is rev 4 now"])
    kept = store.history(BOARD, "cat", "x")[0]
    assert (kept["rev"], kept["gone"], kept["data"], kept["dev"]) == (4, False, {"name": "one"}, "0" * 16)
    put(store, "cat", "x", 4, gone=True)
    assert tool(args, "restore", BOARD, "cat", "x") == (0, ["cat/x is rev 6 now"])  # the last value, live again
    assert store.history(BOARD, "cat", "x")[0]["data"] == {"name": "one"}
    assert tool(args, "restore", BOARD, "cat", "x", "--rev", "99")[0] == 1
    changes = store.sync(A, BOARD, "2" * 16, 5, [])["changes"]
    assert [(c["rev"], c["gone"]) for c in changes] == [(6, False)]  # devices take it like any other change


def eval_line(line):
    import json
    return json.loads(line)


def test_an_address_becomes_the_account_key_the_page_uses(served, monkeypatch):
    store, args = served
    owner = "acct:" + email_key("pep", "kid@example.com")
    store.make(owner, "0" * 31 + "7")
    monkeypatch.setenv("STRUDEL_CREDITS_PEPPER", "pep")
    code, said = tool(args, "boards", "--email", " Kid@Example.com ")
    assert code == 0 and [eval_line(line)["id"] for line in said] == ["0" * 31 + "7"]
    assert tool(args, "drop-account", "--owner", owner, "--yes") == (0, ["1 board(s) deleted"])
    assert store.boards(owner)["boards"] == [] and len(store.boards(A)["boards"]) == 2


def test_the_tool_opens_the_database_beside_a_running_api_without_a_new_epoch(served, tmp_path):
    store, args = served
    boots = (tmp_path / "asset-boards.boots").read_text()
    admin = board_admin.open_store(str(tmp_path / ab.DB_NAME))
    assert admin.epoch == store.epoch
    admin.close()
    assert (tmp_path / "asset-boards.boots").read_text() == boots
    with pytest.raises(FileNotFoundError):
        board_admin.open_store(str(tmp_path / "none" / ab.DB_NAME))


def test_board_sounds_are_backed_up_once_each_and_never_an_unfinished_upload(served, tmp_path):
    store, _ = served
    store.chunk(A, BOARD, sha(b"one"), 0, 3, b"one")
    store.chunk(A, BOARD, sha(b"unfinished"), 0, 10, b"unf")
    dest = tmp_path / "backup"
    assert server_ops.backup_blobs(tmp_path / "asset-blobs", dest) == 1
    assert (dest / sha(b"one")[:2] / sha(b"one")).read_bytes() == b"one" and not (dest / "part").exists()
    store.chunk(A, BOARD, sha(b"two"), 0, 3, b"two")
    assert server_ops.backup_blobs(tmp_path / "asset-blobs", dest) == 1
    assert server_ops.backup_blobs(tmp_path / "asset-blobs", dest) == 0
    assert server_ops.backup_blobs(tmp_path / "none", dest) == 0


def test_a_database_that_cannot_be_copied_does_not_stop_the_ones_after_it(tmp_path):
    (tmp_path / "a.sqlite3").write_bytes(b"this is not a database at all, but it is named like one" * 20)
    good = sqlite3.connect(tmp_path / "b.sqlite3")
    good.execute("create table t (n)")
    good.commit()
    good.close()
    out = server_ops.backup_sqlite(tmp_path, tmp_path / "backups", day="2026-11-11")
    assert [p.name for p in out.iterdir()] == ["b.sqlite3"]
