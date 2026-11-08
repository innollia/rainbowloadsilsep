"""Blind listening: telling apart two people who type the same name, and keeping choices made before tokens."""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bakeoff"))
from listen_store import Pairs  # noqa: E402

ITEM = {"task": "t1", "left": "a", "right": "b", "repeat": 0}


def test_same_name_on_two_browsers_asks_once_and_keeps_people_apart(tmp_path):
    p = Pairs(tmp_path / "l.sqlite")
    first = p.who("민지", "tok-one-aaaaaaaaaaaa")
    assert first == {"voter": "민지", "ask": False}
    p.save(first["voter"], ITEM, "left", token="tok-one-aaaaaaaaaaaa", name="민지")
    assert p.who("민지", "tok-one-aaaaaaaaaaaa") == {"voter": "민지", "ask": False}  # same browser: no question
    assert p.who("민지", "tok-two-bbbbbbbbbbbb")["ask"] is True  # another browser: ask
    other = p.claim("민지", "tok-two-bbbbbbbbbbbb", same=False)
    assert other == "민지#2"
    p.save(other, ITEM, "right", token="tok-two-bbbbbbbbbbbb", name="민지")
    assert p.who("민지", "tok-two-bbbbbbbbbbbb") == {"voter": "민지#2", "ask": False}
    assert p.done("민지") and p.done("민지#2")
    assert {x["voter"]: x["winner"] for x in p.all()} == {"민지": "left", "민지#2": "right"}
    # A third browser that says "carry on" joins the original 민지.
    assert p.claim("민지", "tok-three-cccccccccc", same=True) == "민지"


def test_choices_from_before_tokens_still_count_by_name(tmp_path):
    path = tmp_path / "old.sqlite"
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE pairs (voter TEXT NOT NULL, task TEXT NOT NULL, left_clip TEXT NOT NULL, right_clip TEXT NOT NULL,"
               " repeat INTEGER NOT NULL, winner TEXT NOT NULL, at REAL NOT NULL, PRIMARY KEY (voter, task, left_clip, right_clip, repeat))")
    db.execute("INSERT INTO pairs VALUES ('지훈', 't1', 'a', 'b', 0, 'same', 1)")
    db.commit()
    db.close()
    p = Pairs(path)
    assert p.all() == [{"voter": "지훈", "task": "t1", "left": "a", "right": "b", "repeat": 0, "winner": "same"}]
    assert p.who("지훈", "") == {"voter": "지훈", "ask": False}  # no token: name as before
    assert p.who("지훈", "tok-new-dddddddddddd")["ask"] is True
    assert p.claim("지훈", "tok-new-dddddddddddd", same=True) == "지훈"
    assert ("t1", "a", "b", 0) in p.done("지훈")
