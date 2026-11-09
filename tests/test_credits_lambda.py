"""deploy/credits/lambda_function.py 시험. DynamoDB 저수준 클라이언트를 메모리 가짜로 바꾼다."""
import base64
import hashlib
import hmac
import importlib.util
import json
import pathlib
import re
import threading

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SECRET = "whsec-test"
TOKEN = "app-token-test"
ADMIN = "admin-token-test"


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
    monkeypatch.setenv("ADMIN_TOKEN", ADMIN)
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
    assert lf.CODE_RE.fullmatch(a["legacy_code"]) and not set(a["legacy_code"][3:]) & set("0O1I")
    assert re.fullmatch(r"[a-z]+-[a-z]+-[a-z]+", a["code"])
    s, b = api(lf, "/api/account", {"email": "user@example.com"})
    assert b == {"code": a["code"], "legacy_code": a["legacy_code"], "credits": 20, "free": False}
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


def test_email_match_only_when_a_code_was_attempted(lf):
    api(lf, "/api/account", {"email": "buyer@example.com"})
    hook(lf, donation(10, amount=1, email="BUYER@example.com", note="SD-ZZZZZZ"))  # 틀린 코드 → 이메일로
    assert credits(lf, "buyer@example.com") == 40
    hook(lf, donation(12, amount=1, email="buyer@example.com"))  # 코드 없음 = 블로그 후원일 수 있다 → 자동 적립 없음
    assert credits(lf, "buyer@example.com") == 40


def test_unclaimed_claimed_on_account_open(lf):
    assert hook(lf, donation(11, amount=2, email="later@example.com", live=False, note="sd abcdef"))[1]["held"] is True
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
    code = api(lf, "/api/account", e)[1]["code"]
    hook(lf, donation(20, amount=1, email="r@example.com", note=code))
    assert credits(lf, "r@example.com") == 40
    api(lf, "/api/charge", {**e, "amount": 35, "ref": "spend"})
    hook(lf, donation(20, kind="donation.refunded"))
    hook(lf, donation(20, kind="donation.refunded"))
    assert credits(lf, "r@example.com") == 5 - 20
    assert hook(lf, donation(20, amount=1, email="r@example.com", note=code))[1].get("duplicate") is True
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


def _key(lf, email):
    return lf.acct_key(email)


def test_loose_code_forms(lf):
    code = api(lf, "/api/account", {"email": "loose@example.com"})[1]["legacy_code"]
    body = code[3:]
    for i, note in enumerate((f"SD {body}", f"sd{body.lower()}", f"code: SD - {body[:3]} {body[3:]}", f"sd_{body[:3]}-{body[3:]}")):
        assert hook(lf, donation(100 + i, amount=1, note=note))[1]["applied"] is True, note
    assert credits(lf, "loose@example.com") == 20 + 4 * 20
    assert lf.LOOSE_CODE_RE.search("ASDF1234".upper()) is None  # 다른 낱말 속 SD 는 코드가 아니다


def test_confusable_letters_match_one_account_only(lf):
    api(lf, "/api/account", {"email": "conf@example.com"})
    lf.transact([lf.op_put({"pk": "CODE#SD-AD2Z5B", "sk": "META", "acct": _key(lf, "conf@example.com")})])
    assert hook(lf, donation(110, amount=1, note="sd a02z5b"))[1]["applied"] is True  # 0→D
    assert credits(lf, "conf@example.com") == 40
    api(lf, "/api/account", {"email": "other@example.com"})
    lf.transact([lf.op_put({"pk": "CODE#SD-AQ2Z5B", "sk": "META", "acct": _key(lf, "other@example.com")})])
    r = hook(lf, donation(111, amount=1, email="", note="sd a02z5b"))[1]  # 이제 두 계정이 맞는다 → 고르지 않는다
    assert r.get("applied") is not True and r["held"] is True
    assert credits(lf, "conf@example.com") == 40 and credits(lf, "other@example.com") == 20


def test_non_usd_is_converted_and_unknown_currency_is_held_for_review(lf, capsys):
    code = api(lf, "/api/account", {"email": "won@example.com"})[1]["code"]
    p = donation(120, amount=7000, note=code)
    p["data"]["currency"] = "krw"
    assert hook(lf, p)[1]["applied"] is True
    assert credits(lf, "won@example.com") == 20 + 100  # 7000 × 0.00072 = 5.04 USD → 100
    q = donation(121, amount=50, note=code)
    q["data"]["currency"] = "XYZ"
    assert hook(lf, q)[1]["review"] is True
    assert hook(lf, q)[1].get("duplicate") is True
    assert credits(lf, "won@example.com") == 120
    items = api(lf, "/api/history", {"email": "won@example.com"})[1]["items"]
    assert items[0]["kind"] == "pending" and "XYZ" in items[0]["note"]
    assert "≈ 5.04 USD" in items[1]["note"]
    assert "ALERT" in capsys.readouterr().out
    assert [x["currency"] for x in api(lf, "/api/reviews", {"email": "ops@x"}, ADMIN)[1]["items"]] == ["XYZ"]
    hook(lf, donation(121, kind="donation.refunded"))
    assert api(lf, "/api/reviews", {"email": "ops@x"}, ADMIN)[1]["items"] == []


def test_find_payment_by_payer_email_amount_and_date(lf):
    me = {"email": "me@example.com"}
    api(lf, "/api/account", me)
    hook(lf, donation(130, amount=3, email="Paypal-Me@example.com"))  # 코드 없음 → orphan, 2024-07-01 UTC
    find = lambda **kw: api(lf, "/api/find", {**me, "payer_email": "paypal-me@example.com", "amount": "3",
                                              "date": "2024-07-01", **kw})
    assert find(amount="4")[1]["found"] == 0
    assert find(date="2024-07-05")[1]["found"] == 0
    assert find(payer_email="nobody@example.com")[1]["found"] == 0
    assert find(date="2024-07-02") == (200, {"found": 1, "added": 60, "credits": 80})  # 시간대 차이로 하루는 봐준다
    assert find()[1]["found"] == 0  # 두 번 가져갈 수 없다
    assert find(date="nope")[0] == 400
    for _ in range(10):
        status = find()[0]
    assert status == 429
    assert any("결제 찾기" in i["note"] for i in api(lf, "/api/history", me)[1]["items"])


def test_find_also_reaches_payments_waiting_for_another_email(lf):
    hook(lf, donation(140, amount=2, email="bmc@example.com", note="SD-ZZZZZZ"))  # 코드 오타, 계정 없음 → unclaimed
    s, r = api(lf, "/api/find", {"email": "google@example.com", "payer_email": "bmc@example.com", "amount": 2,
                                 "date": "2024-07-01"})
    assert r["found"] == 1 and r["credits"] == 60
    assert api(lf, "/api/account", {"email": "bmc@example.com"})[1]["credits"] == 20  # 나중에 그 이메일로 가입해도 겹치지 않는다


def test_word_codes_are_found_however_they_are_typed(lf):
    code = api(lf, "/api/account", {"email": "word@example.com"})[1]["code"]
    a, b, c = code.split("-")
    notes = (code, f"{a} {b} {c}".upper(), f"thanks! {a.title()}{b}{c} :)", f"{a}-{b} {c}", f"code is {a}{b}-{c}.")
    for i, note in enumerate(notes):
        r = hook(lf, donation(200 + i, amount=1, note=note))[1]
        assert r["applied"] is True and r["credit"] is True, note
    assert credits(lf, "word@example.com") == 20 + 20 * len(notes)
    assert hook(lf, donation(299, amount=1, note="love the music"))[1]["credit"] is False


def test_old_accounts_get_a_word_code_and_keep_their_sd_code(lf):
    key = lf.acct_key("old@example.com")
    lf.transact([lf.op_put({"pk": f"ACC#{key}", "sk": "META", "credits": 5, "code": "SD-ABCDEF", "ver": 1}),
                 lf.op_put({"pk": "CODE#SD-ABCDEF", "sk": "META", "acct": key})])
    a = api(lf, "/api/account", {"email": "old@example.com"})[1]
    assert a["legacy_code"] == "SD-ABCDEF" and a["code"].count("-") == 2
    hook(lf, donation(300, amount=1, note="SD-ABCDEF"))
    hook(lf, donation(301, amount=1, note=a["code"]))
    assert credits(lf, "old@example.com") == 45


def test_word_code_collisions_are_redrawn(lf, monkeypatch):
    first = api(lf, "/api/account", {"email": "one@example.com"})[1]["code"]
    draws = iter([first, first, "brave-otter-lamp"])
    monkeypatch.setattr(lf, "word_code", lambda: next(draws))
    assert api(lf, "/api/account", {"email": "two@example.com"})[1]["code"] in ("brave-otter-lamp",)
    w = lf.words()
    assert len(w["adjectives"]) * len(w["nouns"]) ** 2 > 10_000_000


def test_replayed_forward_from_blog_credits_once_and_still_says_credit(lf):
    """블로그 입구가 장부 장애 뒤 같은 결제를 다시 넘겨도(BMC attempt 값이 달라도) 한 번만 들어가고 credit 판정은 같다."""
    code = api(lf, "/api/account", {"email": "retry@example.com"})[1]["code"]
    p = donation(901, amount=2, note=code)
    first = hook(lf, p)[1]
    assert first["applied"] is True and first["credit"] is True
    for attempt in (2, 3):
        again = hook(lf, {**p, "attempt": attempt})[1]
        assert again.get("duplicate") is True and again["credit"] is True
    assert credits(lf, "retry@example.com") == 20 + 40


def test_coupon_once_per_account_and_runs_out(lf):
    assert api(lf, "/api/coupon_make", {"email": "op@x.io", "code": "olmuse-start-1", "credits": 10000, "uses": 2}, ADMIN)[0] == 200
    assert api(lf, "/api/coupon_make", {"email": "op@x.io", "code": "OLMUSESTART1", "credits": 5, "uses": 1}, ADMIN)[0] == 409
    before = credits(lf, "a@x.io")
    st, body = api(lf, "/api/redeem", {"email": "a@x.io", "code": "olmuse start 1"})
    assert st == 200 and body == {"added": 10000, "credits": before + 10000}
    assert api(lf, "/api/redeem", {"email": "a@x.io", "code": "OLMUSESTART1"})[0] == 409
    assert api(lf, "/api/redeem", {"email": "b@x.io", "code": "OLMUSESTART1"})[0] == 200
    assert api(lf, "/api/redeem", {"email": "c@x.io", "code": "OLMUSESTART1"})[0] == 410
    assert api(lf, "/api/redeem", {"email": "c@x.io", "code": "NOPE00"})[0] == 404
    assert api(lf, "/api/history", {"email": "a@x.io"})[1]["items"][0]["kind"] == "coupon"


def test_coupon_tries_are_limited(lf):
    for _ in range(10):
        assert api(lf, "/api/redeem", {"email": "d@x.io", "code": "WRONG0"})[0] == 404
    assert api(lf, "/api/redeem", {"email": "d@x.io", "code": "WRONG0"})[0] == 429


def test_app_token_cannot_mint_coupons_or_read_reviews(lf, capsys):
    body = {"email": "op@x.io", "code": "FREEMONEY1", "credits": 1000000, "uses": 100000}
    assert api(lf, "/api/coupon_make", body)[0] == 401
    assert api(lf, "/api/reviews", {"email": "ops@x"})[0] == 401
    assert api(lf, "/api/charge", {"email": "a@x.io", "amount": 1, "ref": "r"}, ADMIN)[0] == 401  # admin is not the app
    assert api(lf, "/api/coupon_make", body, ADMIN)[0] == 200
    out = capsys.readouterr().out
    assert "ALERT" in out and "coupon_made" in out and "FREEMONEY1" not in out
    assert api(lf, "/api/redeem", {"email": "a@x.io", "code": "FREEMONEY1"})[0] == 200  # the app token still redeems


def test_admin_routes_are_shut_without_admin_token(lf, monkeypatch):
    monkeypatch.delenv("ADMIN_TOKEN")
    assert api(lf, "/api/coupon_make", {"email": "op@x.io", "code": "ABCDEF1", "credits": 1}, "")[0] == 401
    assert api(lf, "/api/coupon_make", {"email": "op@x.io", "code": "ABCDEF1", "credits": 1})[0] == 401


def test_refund_by_account_key(lf):
    before = credits(lf, "k@x.io")
    assert api(lf, "/api/charge", {"email": "k@x.io", "amount": 3, "ref": "job:0"})[0] == 200
    st, body = api(lf, "/api/refund", {"acct": lf.acct_key("k@x.io"), "amount": 3, "ref": "job:0"})
    assert st == 200 and body["credits"] == before
    assert api(lf, "/api/refund", {"acct": "not-a-key", "amount": 3, "ref": "job:0"})[0] == 400
    assert api(lf, "/api/charge", {"acct": lf.acct_key("k@x.io"), "amount": 3, "ref": "job:1"})[0] == 400  # charge needs the email
