"""Credit accounts. The real ledger lives in the `strudel-credits` Lambda (deploy/credits);
LocalLedger keeps the same contract in SQLite for development and tests.

Prices are per AI call, so a request that stops early costs less than one that uses every round.
A call is charged before it runs and refunded if the model fails, so a failure never costs credits."""
import hashlib
import hmac
import json
import sqlite3
import threading
import time
import urllib.error
import urllib.request

FREE_CREDITS = 20
# Credits per AI call, set from measured cost (docs/CREDITS.md). One credit (4.25 cents after fees) covers the worst
# measured per-call cost of DeepSeek, Haiku and Sonnet; Gemini's worst is ~6.8 cents and Opus's ~3.8 cents (bakeoff).
MODEL_COST = {"deepseek/deepseek-v4.1-flash": 1, "claude-haiku-5-5": 1, "claude-sonnet-5-5": 1,
              "gemini-3.8-flash": 2, "claude-opus-5-5": 3}
EFFORT_EXTRA = {"low": 0, "medium": 0, "high": 1}


class LedgerError(Exception):
    """The ledger could not be reached. Never treated as permission to spend."""


def call_cost(model: str, effort: str) -> int:
    return MODEL_COST.get(model, 2) + EFFORT_EXTRA.get(effort, 0)


def price_table() -> dict:
    return {"models": MODEL_COST, "efforts": EFFORT_EXTRA}


class RemoteLedger:
    def __init__(self, url: str, token: str, timeout: float = 10):
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout

    def _post(self, path: str, body: dict, ok=(200,)) -> tuple[int, dict]:
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as exc:
            if exc.code in ok:
                return exc.code, json.load(exc)
            raise LedgerError(f"크레딧 장부 오류 {exc.code}") from None
        except (OSError, ValueError):
            raise LedgerError("크레딧 장부에 연결하지 못했어.") from None

    def account(self, email: str) -> dict:
        return self._post("/api/account", {"email": email})[1]

    def charge(self, email: str, amount: int, ref: str) -> tuple[bool, int]:
        status, body = self._post("/api/charge", {"email": email, "amount": amount, "ref": ref}, ok=(200, 402))
        return status == 200, int(body.get("credits", 0))

    def refund(self, email: str, amount: int, ref: str) -> int:
        return int(self._post("/api/refund", {"email": email, "amount": amount, "ref": ref})[1].get("credits", 0))

    def history(self, email: str) -> list:
        return self._post("/api/history", {"email": email})[1].get("items", [])

    def find_payment(self, email: str, payer_email: str, amount, day: str) -> dict:
        """A payment that reached no account, found by the email, amount and date it was paid with.
        {found, added, credits}; too_many is set when today's tries are used up."""
        status, body = self._post("/api/find", {"email": email, "payer_email": payer_email, "amount": str(amount), "date": day},
                                  ok=(200, 400, 429))
        if status == 400:
            raise ValueError(body.get("error", "bad request"))
        return {"found": int(body.get("found", 0)), "added": int(body.get("added", 0)),
                "credits": int(body.get("credits", 0)), "too_many": status == 429}


class LocalLedger:
    """Same contract as the Lambda. Purchases cannot reach it; `grant` stands in for them in tests."""

    CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

    def __init__(self, path: str = ":memory:", pepper: str = "local", free: int = FREE_CREDITS):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock, self.pepper, self.free = threading.Lock(), pepper.encode(), free
        self.db.executescript("""
            create table if not exists accounts (key text primary key, code text unique, credits integer);
            create table if not exists refs (ref text primary key, key text, amount integer, refunded integer default 0);
            create table if not exists history (key text, kind text, amount integer, credits integer, at text, note text);
            create table if not exists orphans (payer text, amount text, day text, credits integer, taken integer default 0);
        """)
        self.find_tries: dict[tuple, int] = {}

    def _key(self, email: str) -> str:
        return hmac.new(self.pepper, email.strip().lower().encode(), hashlib.sha256).hexdigest()

    def _log(self, key, kind, amount, credits, note=""):
        self.db.execute("insert into history values (?,?,?,?,?,?)", (key, kind, amount, credits, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), note))

    def _credits(self, key) -> int:
        return self.db.execute("select credits from accounts where key=?", (key,)).fetchone()[0]

    def _add(self, key, delta: int) -> int:
        self.db.execute("update accounts set credits=credits+? where key=?", (delta, key))
        return self._credits(key)

    def _opened(self, email: str) -> str:
        self.account(email)
        return self._key(email)

    def account(self, email: str) -> dict:
        key = self._key(email)
        with self.lock, self.db:
            row = self.db.execute("select code, credits from accounts where key=?", (key,)).fetchone()
            if row:
                return {"code": row[0], "credits": row[1], "free": False}
            digest, n = int(key, 16), 0
            while True:
                code = "SD-" + "".join(self.CODE_ALPHABET[(digest >> (5 * (i + n))) % 32] for i in range(6))
                if not self.db.execute("select 1 from accounts where code=?", (code,)).fetchone():
                    break
                n += 1
            self.db.execute("insert into accounts values (?,?,?)", (key, code, self.free))
            self._log(key, "free", self.free, self.free, "무료 체험")
            return {"code": code, "credits": self.free, "free": True}

    def grant(self, email: str, amount: int, note: str = "구매") -> int:
        key = self._opened(email)
        with self.lock, self.db:
            credits = self._add(key, amount)
            self._log(key, "buy", amount, credits, note)
            return credits

    def charge(self, email: str, amount: int, ref: str) -> tuple[bool, int]:
        key = self._opened(email)
        with self.lock, self.db:
            if self.db.execute("select 1 from refs where ref=?", (ref,)).fetchone():
                return True, self._credits(key)
            if self._credits(key) < amount:
                return False, self._credits(key)
            self.db.execute("insert into refs (ref, key, amount) values (?,?,?)", (ref, key, amount))
            credits = self._add(key, -amount)
            self._log(key, "charge", -amount, credits, ref.split(":")[0][:12])
            return True, credits

    def refund(self, email: str, amount: int, ref: str) -> int:
        key = self._key(email)
        with self.lock, self.db:
            row = self.db.execute("select amount, refunded from refs where ref=? and key=?", (ref, key)).fetchone()
            if row and not row[1]:
                self.db.execute("update refs set refunded=1 where ref=?", (ref,))
                self._log(key, "refund", row[0], self._add(key, row[0]), "실패한 호출")
            return self._credits(key)

    def hold(self, payer_email: str, amount: str, day: str, credits: int):
        """A payment with no code, kept until its payer finds it. Stands in for the Lambda's orphans in tests."""
        with self.lock, self.db:
            self.db.execute("insert into orphans (payer, amount, day, credits) values (?,?,?,?)",
                            (self._key(payer_email), str(amount), day, credits))

    def find_payment(self, email: str, payer_email: str, amount, day: str) -> dict:
        import datetime
        try:
            want, asked = float(str(amount).replace(",", "")), datetime.date.fromisoformat(str(day)[:10])
        except ValueError:
            raise ValueError("bad amount or date") from None
        key = self._opened(email)
        today = (key, datetime.date.today().isoformat())
        if self.find_tries.get(today, 0) >= 10:
            return {"found": 0, "added": 0, "credits": self.account(email)["credits"], "too_many": True}
        self.find_tries[today] = self.find_tries.get(today, 0) + 1
        found = added = 0
        with self.lock, self.db:
            rows = self.db.execute("select rowid, amount, day, credits from orphans where payer=? and taken=0",
                                   (self._key(payer_email),)).fetchall()
            for rowid, paid, paid_day, credits in rows:
                if abs(float(paid) - want) > 0.01 or abs((datetime.date.fromisoformat(paid_day) - asked).days) > 1:
                    continue
                self.db.execute("update orphans set taken=1 where rowid=?", (rowid,))
                self._log(key, "buy", credits, self._add(key, credits), "결제 찾기")
                found, added = found + 1, added + credits
            return {"found": found, "added": added, "credits": self._credits(key), "too_many": False}

    def history(self, email: str) -> list:
        key = self._key(email)
        rows = self.db.execute("select kind, amount, credits, at, note from history where key=? order by rowid desc limit 50", (key,)).fetchall()
        return [dict(zip(("kind", "amount", "credits", "at", "note"), r)) for r in rows]
