"""deploy/credits/lambda_function.py 시험. DynamoDB 저수준 클라이언트를 메모리 가짜로 바꾼다."""
import base64
import hashlib
import hmac
import importlib.util
import json
import pathlib
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SECRET = "whsec-test"
TOKEN = "app-token-test"


class Canceled(Exception):
    def __init__(self, codes):
        super().__init__("TransactionCanceledException")
        self.response = {"Error": {"Code": "TransactionCanceledException"},
                         "CancellationReasons": [{"Code": c} for c in codes]}


class FakeDDB:
    """lambda가 쓰는 조건식만 해석한다: attribute_exists(a) / attribute_not_exists(a) / a = :v (AND)."""

    def __init__(self):
        self.items = {}
        self.lock = threading.Lock()

    @staticmethod
    def _k(key):
        return key["pk"]["S"], key["sk"]["S"]

    def _ok(self, cur, cond, vals):
        if not cond:
            return True
        for part in cond.split(" AND "):
            part = part.strip()
            if part.startswith("attribute_exists("):
                if not cur or part[17:-1] not in cur:
                    return False
            elif part.startswith("attribute_not_exists("):
                if cur and part[21:-1] in cur:
                    return False
            else:
                name, val = [s.strip() for s in part.split("=")]
                if not cur or cur.get(name) != vals[val]:
                    return False
        return True

    def get_item(self, TableName, Key, ConsistentRead=False):
        with self.lock:
            it = self.items.get(self._k(Key))
            return {"Item": dict(it)} if it else {}

    def delete_item(self, TableName, Key):
        with self.lock:
            self.items.pop(self._k(Key), None)
        return {}

    def query(self, TableName, KeyConditionExpression, ExpressionAttributeValues, ScanIndexForward=True,
              Limit=None, ConsistentRead=False):
        pk = ExpressionAttributeValues[":p"]["S"]
        pre = ExpressionAttributeValues.get(":h", {}).get("S", "")
        with self.lock:
            rows = sorted((k, v) for k, v in self.items.items() if k[0] == pk and k[1].startswith(pre))
        rows = [dict(v) for _, v in rows]
        if not ScanIndexForward:
            rows.reverse()
        return {"Items": rows[:Limit] if Limit else rows}

    def transact_write_items(self, TransactItems):
        with self.lock:
            codes, plan = [], []
            for op in TransactItems:
                (kind, p), = op.items()
                key = self._k(p["Item"] if kind == "Put" else p["Key"])
                ok = self._ok(self.items.get(key), p.get("ConditionExpression"), p.get("ExpressionAttributeValues", {}))
                codes.append("None" if ok else "ConditionalCheckFailed")
                plan.append((kind, key, p))
            if any(c != "None" for c in codes):
                raise Canceled(codes)
            for kind, key, p in plan:
                if kind == "Put":
                    self.items[key] = dict(p["Item"])
                else:
                    self.items.pop(key, None)
        return {}

    def dump(self):
        return json.dumps(list(self.items.values()), default=str, ensure_ascii=False)


@pytest.fixture
def lf(monkeypatch):
    monkeypatch.setenv("TABLE", "strudel-credits")
    monkeypatch.setenv("APP_TOKEN", TOKEN)
    monkeypatch.setenv("PEPPER", "pepper-test")
    monkeypatch.setenv("BMC_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("CREDITS_PER_USD", "20")
    monkeypatch.setenv("FREE_CREDITS", "20")
    spec = importlib.util.spec_from_file_location("credits_lambda", ROOT / "deploy" / "credits" / "lambda_function.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.DDB = FakeDDB()
    return mod


def api(lf, path, body, token=TOKEN):
    ev = {"requestContext": {"http": {"method": "POST"}}, "rawPath": path,
          "headers": {"authorization": f"Bearer {token}"}, "body": json.dumps(body)}
    r = lf.lambda_handler(ev, None)
    return r["statusCode"], json.loads(r["body"])


def hook(lf, payload, secret=SECRET, b64=False):
    raw = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    ev = {"requestContext": {"http": {"method": "POST"}}, "rawPath": "/webhooks/bmc",
          "headers": {"x-signature-sha256": sig},
          "body": base64.b64encode(raw).decode() if b64 else raw.decode(), "isBase64Encoded": b64}
    r = lf.lambda_handler(ev, None)
    return r["statusCode"], json.loads(r["body"])


def donation(pid, amount=5, email="buyer@example.com", note=None, live=True, kind="donation.created"):
    return {"event_id": 1, "type": kind, "live_mode": live, "created": 1719825600, "attempt": 1,
            "data": {"id": pid, "object": "payment", "amount": amount, "currency": "USD", "supporter_name": "Kim",
                     "supporter_email": email, "support_note": note, "message": "Kim bought you a coffee",
                     "created_at": 1719825600, "status": "succeeded", "refunded": "false"}}


def credits(lf, email):
    return api(lf, "/api/account", {"email": email})[1]["credits"]


def test_bad_signature_and_auth(lf):
    assert hook(lf, donation(1), secret="wrong")[0] == 403
    assert api(lf, "/api/account", {"email": "a@b.c"}, token="nope")[0] == 401
    assert api(lf, "/api/history", {"email": "a@b.c"}, token="")[0] == 401


def test_account_free_once_and_code_format(lf):
    s, a = api(lf, "/api/account", {"email": "  User@Example.com "})
    assert s == 200 and a["free"] is True and a["credits"] == 20
    assert lf.CODE_RE.fullmatch(a["code"]) and not set(a["code"][3:]) & set("0O1I")
    s, b = api(lf, "/api/account", {"email": "user@example.com"})
    assert b == {"code": a["code"], "credits": 20, "free": False}
    assert "user@example.com" not in lf.DDB.dump().lower()


def test_code_match_idempotent_and_no_pii(lf):
    code = api(lf, "/api/account", {"email": "player@example.com"})[1]["code"]
    p = donation(77, amount=4.99, email="someone-else@example.com", note=f"my code {code.lower()} thanks")
    assert hook(lf, p)[1]["applied"] is True
    assert hook(lf, p, b64=True)[1].get("duplicate") is True
    assert credits(lf, "player@example.com") == 20 + 99  # floor(4.99*20)
    assert credits(lf, "someone-else@example.com") == 20
    dump = lf.DDB.dump()
    for s in ("Kim", "someone-else@example.com", "thanks", "bought you"):
        assert s not in dump


def test_code_in_extra_question_answer(lf):
    code = api(lf, "/api/account", {"email": "x@example.com"})[1]["code"]
    p = donation(5, amount=3, email="", kind="extra_purchase.created")
    p["data"]["extras"] = [{"id": 1, "title": "credits", "amount": 3, "quantity": 1,
                            "extra_question": "Your code?", "question_answers": [code]}]
    hook(lf, p)
    assert credits(lf, "x@example.com") == 80


def test_email_match(lf):
    api(lf, "/api/account", {"email": "buyer@example.com"})
    hook(lf, donation(10, amount=1, email="BUYER@example.com"))
    assert credits(lf, "buyer@example.com") == 40


def test_unclaimed_claimed_on_account_open(lf):
    assert hook(lf, donation(11, amount=2, email="later@example.com", live=False))[1]["held"] is True
    s, a = api(lf, "/api/account", {"email": "later@example.com"})
    assert a["free"] is True and a["credits"] == 20 + 40
    assert api(lf, "/api/account", {"email": "later@example.com"})[1]["credits"] == 60
    items = api(lf, "/api/history", {"email": "later@example.com"})[1]["items"]
    assert {i["kind"] for i in items} == {"free", "buy"}
    assert any("(test)" in i["note"] for i in items if i["kind"] == "buy")


def test_charge_402_ref_idempotent_and_refund_once(lf):
    e = {"email": "c@example.com"}
    api(lf, "/api/account", e)
    assert api(lf, "/api/charge", {**e, "amount": 25, "ref": "r0"}) == (402, {"credits": 20})
    assert api(lf, "/api/charge", {**e, "amount": 8, "ref": "r1"}) == (200, {"credits": 12})
    assert api(lf, "/api/charge", {**e, "amount": 8, "ref": "r1"}) == (200, {"credits": 12})
    assert api(lf, "/api/refund", {**e, "amount": 8, "ref": "nope"}) == (200, {"credits": 12})
    assert api(lf, "/api/refund", {**e, "amount": 8, "ref": "r1"}) == (200, {"credits": 20})
    assert api(lf, "/api/refund", {**e, "amount": 8, "ref": "r1"}) == (200, {"credits": 20})
    items = api(lf, "/api/history", e)[1]["items"]
    assert [i["kind"] for i in items] == ["refund", "charge", "free"]
    assert [i["credits"] for i in items] == [20, 12, 20]


def test_refund_event_reverses_and_can_go_negative(lf):
    e = {"email": "r@example.com"}
    api(lf, "/api/account", e)
    hook(lf, donation(20, amount=1, email="r@example.com"))
    assert credits(lf, "r@example.com") == 40
    api(lf, "/api/charge", {**e, "amount": 35, "ref": "spend"})
    hook(lf, donation(20, kind="donation.refunded"))
    hook(lf, donation(20, kind="donation.refunded"))
    assert credits(lf, "r@example.com") == 5 - 20
    assert hook(lf, donation(20, amount=1, email="r@example.com"))[1].get("duplicate") is True
    kinds = [i["kind"] for i in api(lf, "/api/history", e)[1]["items"]]
    assert kinds.count("reversal") == 1


def test_refund_event_for_unclaimed_and_before_payment(lf):
    hook(lf, donation(30, amount=1, email="ghost@example.com"))
    hook(lf, donation(30, kind="donation.refunded"))
    assert api(lf, "/api/account", {"email": "ghost@example.com"})[1]["credits"] == 20
    hook(lf, donation(31, kind="donation.refunded"))
    assert hook(lf, donation(31, amount=1, email="ghost@example.com"))[1].get("duplicate") is True
    assert credits(lf, "ghost@example.com") == 20


def test_non_money_events_ignored(lf):
    api(lf, "/api/account", {"email": "n@example.com"})
    assert hook(lf, donation(40, amount=9, email="n@example.com", kind="extra_purchase.updated"))[1]["applied"] is False
    assert credits(lf, "n@example.com") == 20


def test_concurrent_charges_never_negative(lf):
    e = {"email": "race@example.com"}
    api(lf, "/api/account", e)
    results = []

    def go(i):
        results.append(api(lf, "/api/charge", {**e, "amount": 3, "ref": f"t{i}"})[0])

    ts = [threading.Thread(target=go, args=(i,)) for i in range(12)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert results.count(200) == 6 and results.count(402) == 6
    assert credits(lf, "race@example.com") == 2
