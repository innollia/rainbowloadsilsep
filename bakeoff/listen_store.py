"""Blind listening: the clip manifest, the votes (sqlite on this PC) and their tally.

Used by pages/listen.py (https://olmuse.app/listen) and by tests. Model names stay in the manifest on this
PC; the page shows them only after the STUDIO_PASSWORD unlock.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import sqlite3
import statistics
import time
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "bakeoff" / "results" / "listen" / "manifest.json"
DB = Path(os.environ.get("OLMUSE_LISTEN_DB") or ROOT / ".studio-data" / "listen.sqlite")  # a local test points this elsewhere
MAX_NAME = 40


def load_manifest(path: Path = MANIFEST) -> dict | None:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def every_clip(manifest: dict) -> list[dict]:
    """Served clips and retired ones (models that left the finalists): votes on either still count."""
    out = [c for t in manifest["tasks"] for c in t["clips"]]
    out += manifest.get("retired", [])
    return out


def clean_name(name: str) -> str:
    return " ".join(str(name or "").split())[:MAX_NAME]


def order_for(voter: str, task: dict) -> list[dict]:
    """Each listener hears a task's clips in an order of their own, the same every visit."""
    clips = list(task["clips"])
    seed = int(hashlib.sha256(f"{voter}|{task['id']}".encode()).hexdigest()[:12], 16)
    random.Random(seed).shuffle(clips)
    return clips


class Votes:
    def __init__(self, path: Path = DB):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS votes (voter TEXT NOT NULL, task TEXT NOT NULL, clip TEXT NOT NULL,"
                       " score INTEGER, mismatch INTEGER NOT NULL DEFAULT 0, at REAL NOT NULL,"
                       " PRIMARY KEY (voter, task, clip))")

    def _db(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, voter: str, task: str, clip: str, score=None, mismatch=None):
        voter = clean_name(voter)
        if not voter:
            raise ValueError("name required")
        if score is not None and not (isinstance(score, int) and 1 <= score <= 10):
            raise ValueError("score must be 1-10")
        with self._db() as db:
            db.execute("INSERT INTO votes (voter, task, clip, score, mismatch, at) VALUES (?, ?, ?, ?, ?, ?)"
                       " ON CONFLICT(voter, task, clip) DO UPDATE SET"
                       " score = CASE WHEN ? THEN excluded.score ELSE score END,"
                       " mismatch = CASE WHEN ? THEN excluded.mismatch ELSE mismatch END, at = excluded.at",
                       (voter, task, clip, score, int(bool(mismatch)), time.time(), score is not None, mismatch is not None))

    def mine(self, voter: str) -> dict:
        with self._db() as db:
            rows = db.execute("SELECT task, clip, score, mismatch FROM votes WHERE voter = ?", (clean_name(voter),)).fetchall()
        return {(t, c): {"score": s, "mismatch": bool(m)} for t, c, s, m in rows}

    def all(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT voter, task, clip, score, mismatch FROM votes").fetchall()
        return [{"voter": v, "task": t, "clip": c, "score": s, "mismatch": bool(m)} for v, t, c, s, m in rows]


def progress(manifest: dict, votes: list[dict]) -> list[dict]:
    total = sum(len(t["clips"]) for t in manifest["tasks"])
    by = {}
    for v in votes:
        if v["score"] is not None:
            by[v["voter"]] = by.get(v["voter"], 0) + 1
    return [{"voter": name, "rated": n, "total": total} for name, n in sorted(by.items())]


def bradley_terry(pairs: list[tuple[str, str, float]], iterations: int = 200) -> dict:
    """Strengths from (a, b, a's result: 1 win, 0.5 tie, 0 loss). Minorization-maximization with a small prior."""
    players = sorted({p for a, b, _ in pairs for p in (a, b)})
    if not players:
        return {}
    wins = {p: 0.5 for p in players}  # prior: half a win against an average opponent keeps everyone finite
    games: dict[tuple, float] = {}
    for a, b, r in pairs:
        wins[a] += r
        wins[b] += 1 - r
        key = tuple(sorted((a, b)))
        games[key] = games.get(key, 0) + 1
    strength = {p: 1.0 for p in players}
    for _ in range(iterations):
        new = {}
        for p in players:
            denom = 1.0 / (strength[p] + 1.0)  # the prior's average opponent
            for (a, b), n in games.items():
                if p in (a, b):
                    other = b if p == a else a
                    denom += n / (strength[p] + strength[other])
            new[p] = wins[p] / denom
        scale = statistics.fmean(new.values())
        strength = {p: v / scale for p, v in new.items()}
    return strength


def tally(manifest: dict, votes: list[dict]) -> dict:
    """Per model: mean score, Bradley-Terry strength from score comparisons, mismatch marks; per listener: consistency."""
    clip_model, dup_of = {}, {}
    for clip in every_clip(manifest):
        clip_model[clip["clip"]] = clip["model"]
        if clip.get("dup_of"):
            dup_of[clip["clip"]] = clip["dup_of"]
    scores = {}
    for v in votes:
        if v["score"] is not None and v["clip"] in clip_model:
            scores[(v["voter"], v["task"], v["clip"])] = v["score"]
    models: dict[str, dict] = {}
    for (voter, task, clip), s in scores.items():
        if clip in dup_of:
            continue
        models.setdefault(clip_model[clip], {"scores": [], "mismatch": 0})["scores"].append(s)
    for v in votes:
        if v["mismatch"] and v["clip"] in clip_model and v["clip"] not in dup_of:
            models.setdefault(clip_model[v["clip"]], {"scores": [], "mismatch": 0})["mismatch"] += 1
    pairs = []
    groups: dict[tuple, list] = {}
    for (voter, task, clip), s in scores.items():
        if clip not in dup_of:
            groups.setdefault((voter, task), []).append((clip_model[clip], s))
    for items in groups.values():
        for (ma, sa), (mb, sb) in combinations(items, 2):
            pairs.append((ma, mb, 1.0 if sa > sb else 0.0 if sa < sb else 0.5))
    strength = bradley_terry(pairs)
    table = sorted(({"model": m, "mean": statistics.fmean(d["scores"]) if d["scores"] else None, "n": len(d["scores"]),
                     "bt": strength.get(m), "mismatch": d["mismatch"]} for m, d in models.items()),
                   key=lambda r: -(r["bt"] or 0))
    consistency = []
    for (voter, task, clip), s in scores.items():
        if clip in dup_of and (voter, task, dup_of[clip]) in scores:
            consistency.append({"voter": voter, "task": task, "gap": abs(s - scores[(voter, task, dup_of[clip])])})
    return {"models": table, "consistency": consistency, "voters": len({k[0] for k in scores})}


# ---------- pairwise listening (replaces 1-10 scores: listeners need no genre knowledge) ----------
GENRE_HINT = {
    "하우스": "클럽에서 나오는 춤곡. 쿵·쿵·쿵·쿵 일정한 킥 위에 신나는 리듬이 계속 반복돼요.",
    "로파이 힙합": "공부할 때 틀어 두는 잔잔한 힙합. 느리고 살짝 뭉개진 따뜻한 소리.",
    "신스팝": "80년대 전자 팝. 반짝이는 신시사이저와 따라 부르기 쉬운 멜로디.",
    "편집(트랙 지정)": "이미 있던 곡에서 베이스만 더 그루비하게(몸이 들썩이게) 고친 결과예요.",
    "앰비언트": "드럼 없이 공간을 채우는 배경 소리. 천천히 번지고 변하는 분위기.",
    "테크노": "어둡고 단단한 반복 춤곡. 같은 리듬 위에서 소리가 조금씩 바뀌어요.",
    "칩튠": "옛날 게임기 같은 삑삑거리는 8비트 소리로 만든 음악.",
    "편집(전체)": "이미 있던 곡을 느리고 슬픈 발라드로 통째로 바꾼 결과예요.",
}


def pair_queue(voter: str, manifest: dict) -> list[dict]:
    """All pairs of a task's clips (duplicates left out), in an order of the listener's own, tasks mixed.
    Which clip sits left depends only on the listener and the pair, so a pair kept through a new manifest keeps its sides."""
    seed = int(hashlib.sha256(f"pairs|{voter}".encode()).hexdigest()[:12], 16)
    rng = random.Random(seed)
    base = []
    for task in manifest["tasks"]:
        clips = [c["clip"] for c in task["clips"] if not c.get("dup_of")]
        for a, b in combinations(clips, 2):
            x, y = sorted((a, b))
            side = hashlib.sha256(f"side|{voter}|{task['id']}|{x}|{y}".encode()).digest()[0]
            left, right = (x, y) if side < 128 else (y, x)
            base.append({"task": task["id"], "left": left, "right": right, "repeat": 0})
    rng.shuffle(base)
    return base  # no repeated pairs: the user dropped the consistency re-asks on 2026-11-08


class Pairs:
    """Choices keyed by voter. A voter key is the typed name, or "name#2", "name#3"... when a different person
    already uses that name. listeners maps (this browser's token, typed name) to the voter key, so two people
    typing the same name stay apart. Choices saved before tokens existed (voter = name, no listeners row) still count."""

    def __init__(self, path: Path = DB):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self._db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS pairs (voter TEXT NOT NULL, task TEXT NOT NULL, left_clip TEXT NOT NULL,"
                       " right_clip TEXT NOT NULL, repeat INTEGER NOT NULL, winner TEXT NOT NULL, at REAL NOT NULL,"
                       " PRIMARY KEY (voter, task, left_clip, right_clip, repeat))")
            db.execute("CREATE TABLE IF NOT EXISTS listeners (token TEXT NOT NULL, name TEXT NOT NULL, voter TEXT NOT NULL,"
                       " at REAL NOT NULL, PRIMARY KEY (token, name))")

    def _db(self):
        return sqlite3.connect(self.path, timeout=10)

    def save(self, voter: str, item: dict, winner: str, token: str = "", name: str = ""):
        voter = clean_name(voter)
        if not voter or winner not in ("left", "right", "same"):
            raise ValueError("name and a choice are required")
        with self._db() as db:
            db.execute("INSERT OR REPLACE INTO pairs VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (voter, item["task"], item["left"], item["right"], int(item["repeat"]), winner, time.time()))
            if token and clean_name(name):
                db.execute("INSERT OR IGNORE INTO listeners VALUES (?, ?, ?, ?)", (token, clean_name(name), voter, time.time()))

    def _keys_for(self, db, name: str) -> list[str]:
        """Voter keys already behind this typed name, the plain name first."""
        keys = [v for (v,) in db.execute("SELECT DISTINCT voter FROM listeners WHERE name = ?", (name,))]
        if db.execute("SELECT 1 FROM pairs WHERE voter = ? LIMIT 1", (name,)).fetchone() and name not in keys:
            keys.append(name)
        return sorted(keys, key=lambda k: (k != name, k))

    def _free_key(self, db, name: str) -> str:
        taken = {v for (v,) in db.execute("SELECT voter FROM pairs UNION SELECT voter FROM listeners")}
        if name not in taken:
            return name
        k = 2
        while f"{name[:MAX_NAME - 4]}#{k}" in taken:
            k += 1
        return f"{name[:MAX_NAME - 4]}#{k}"

    def who(self, name: str, token: str = "") -> dict:
        """{"voter": key, "ask": False} when it is clear who this is; {"voter": None, "ask": True} when someone
        on another browser (or from before tokens) already chose under this name."""
        name = clean_name(name)
        if not token:
            return {"voter": name, "ask": False}
        with self._db() as db:
            row = db.execute("SELECT voter FROM listeners WHERE token = ? AND name = ?", (token, name)).fetchone()
            if row:
                return {"voter": row[0], "ask": False}
            if self._keys_for(db, name):
                return {"voter": None, "ask": True}
            return {"voter": self._free_key(db, name), "ask": False}

    def claim(self, name: str, token: str, same: bool) -> str:
        """The answer to "carry on, or a different person?". Remembered for this browser."""
        name = clean_name(name)
        with self._db() as db:
            keys = self._keys_for(db, name)
            voter = keys[0] if same and keys else self._free_key(db, name)
            db.execute("INSERT OR REPLACE INTO listeners VALUES (?, ?, ?, ?)", (token, name, voter, time.time()))
        return voter

    def all(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute("SELECT voter, task, left_clip, right_clip, repeat, winner FROM pairs").fetchall()
        return [{"voter": v, "task": t, "left": a, "right": b, "repeat": r, "winner": w} for v, t, a, b, r, w in rows]

    def done(self, voter: str) -> set:
        return {(p["task"], p["left"], p["right"], p["repeat"]) for p in self.all() if p["voter"] == clean_name(voter)}


def tally_pairs(manifest: dict, pairs: list[dict]) -> dict:
    """Bradley-Terry strength per model from the first-time choices; repeats only measure consistency."""
    clip_model = {c["clip"]: c["model"] for c in every_clip(manifest)}
    games, wins = [], {}
    for p in pairs:
        if p["repeat"] or p["left"] not in clip_model or p["right"] not in clip_model:
            continue
        a, b = clip_model[p["left"]], clip_model[p["right"]]
        r = 1.0 if p["winner"] == "left" else 0.0 if p["winner"] == "right" else 0.5
        games.append((a, b, r))
        for m, s in ((a, r), (b, 1 - r)):
            w = wins.setdefault(m, [0.0, 0])
            w[0] += s
            w[1] += 1
    strength = bradley_terry(games)
    models = sorted(({"model": m, "bt": strength.get(m), "win_rate": w / n, "n": n} for m, (w, n) in wins.items()),
                    key=lambda r: -(r["bt"] or 0))
    first = {(p["voter"], p["task"], p["left"], p["right"]): p["winner"] for p in pairs if not p["repeat"]}
    flip = {"left": "right", "right": "left", "same": "same"}
    agree, total = {}, {}
    for p in pairs:
        if p["repeat"]:
            original = first.get((p["voter"], p["task"], p["right"], p["left"]))
            same_side = first.get((p["voter"], p["task"], p["left"], p["right"]))
            if original or same_side:
                total[p["voter"]] = total.get(p["voter"], 0) + 1
                agree[p["voter"]] = agree.get(p["voter"], 0) + (flip[p["winner"]] == original if original
                                                                else p["winner"] == same_side)
    consistency = [{"voter": v, "same": agree.get(v, 0), "repeats": n} for v, n in sorted(total.items())]
    return {"models": models, "consistency": consistency, "voters": len({p["voter"] for p in pairs}), "choices": len(games)}
