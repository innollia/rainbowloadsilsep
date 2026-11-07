"""olmuse (구 strudel 딸깍이) 크레딧 장부 (Lambda Function URL + DynamoDB 한 테이블).

  POST /webhooks/bmc   BMC 웹훅. x-signature-sha256 = HMAC-SHA256(BMC_WEBHOOK_SECRET, 원문) 16진수. 틀리면 403.
  POST /api/account    {email}               → {code, credits, free}
  POST /api/charge     {email, amount, ref}  → 200 {credits} | 402 {credits}
  POST /api/refund     {email, amount, ref}  → 200 {credits}
  POST /api/history    {email}               → {items:[...]} 최근 50개
/api/* 는 Authorization: Bearer APP_TOKEN.

테이블 항목 (pk, sk):
  ACC#<key>, META         계정: credits, code, ver(낙관적 잠금)
  ACC#<key>, H#<ver>      기록: kind, amount(부호 있는 변화량), credits(그 뒤 잔액), at, note
  CODE#<SD-XXXXXX>, META  코드 → acct
  PAY#<종류:id>, META     결제: amount, currency, credits, at, test, st(applied|unclaimed|orphan|refunded), acct/owner
  UNCLAIMED#<key>, PAY#.. 주인 없는 결제 (key = 이메일 HMAC)
  CHG#<key>#<ref>, META   차감: amount, st(charged|refunded)
이메일은 HMAC(PEPPER, email.lower().strip()) 로만 남긴다. BMC 구매자 이름·이메일·메모 원문은 저장하지 않는다.
잔액 변경은 모두 계정 ver 조건 + 트랜잭션이라 동시 차감에도 음수가 되지 않는다(환불 이벤트의 회수만 음수 허용).
"""
import base64
import hashlib
import hmac
import json
import os
import re
import time
from decimal import Decimal, ROUND_FLOOR

DDB = None  # 시험에서는 가짜로 바꾼다
CODE_RE = re.compile(r"SD-[A-Z0-9]{6}")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 0/O/1/I 제외, 32자
PAYMENT_PREFIXES = ("donation.", "coffee.", "support.", "extra_purchase.", "commission_order.", "wishlist_payment.")
SUBSCRIPTION_STARTS = ("membership.started", "recurring_donation.started")


def ddb():
    global DDB
    if DDB is None:
        import boto3
        DDB = boto3.client("dynamodb")
    return DDB


def table():
    return os.environ["TABLE"]


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---------- DynamoDB 저수준 형식 ----------
def ser(v):
    if isinstance(v, bool):
        return {"BOOL": v}
    if isinstance(v, (int, Decimal)):
        return {"N": str(v)}
    return {"S": str(v)}


def des(a):
    (t, v), = a.items()
    if t == "N":
        d = Decimal(v)
        return int(d) if d == d.to_integral_value() else d
    if t == "BOOL":
        return v
    if t == "NULL":
        return None
    return v


def item_ser(d):
    return {k: ser(v) for k, v in d.items() if v is not None}


def item_des(d):
    return {k: des(v) for k, v in d.items()}


def get(pk, sk="META"):
    r = ddb().get_item(TableName=table(), Key={"pk": ser(pk), "sk": ser(sk)}, ConsistentRead=True)
    return item_des(r["Item"]) if r.get("Item") else None


def op_put(item, cond=None, vals=None):
    p = {"TableName": table(), "Item": item_ser(item)}
    if cond:
        p["ConditionExpression"] = cond
    if vals:
        p["ExpressionAttributeValues"] = {k: ser(v) for k, v in vals.items()}
    return {"Put": p}


def op_delete(pk, sk, cond=None):
    p = {"TableName": table(), "Key": {"pk": ser(pk), "sk": ser(sk)}}
    if cond:
        p["ConditionExpression"] = cond
    return {"Delete": p}


def transact(ops):
    """성공이면 None, 취소면 항목별 사유 코드 목록."""
    try:
        ddb().transact_write_items(TransactItems=ops)
        return None
    except Exception as e:  # botocore ClientError
        resp_ = getattr(e, "response", None) or {}
        if resp_.get("Error", {}).get("Code") != "TransactionCanceledException":
            raise
        return [(r or {}).get("Code", "None") for r in resp_.get("CancellationReasons", [])] or ["Unknown"]


# ---------- 계정 ----------
def acct_key(email):
    return hmac.new(os.environ["PEPPER"].encode(), email.lower().strip().encode(), hashlib.sha256).hexdigest()


def code_candidates(key):
    for i in range(64):
        h = hashlib.sha256(f"{key}:{i}".encode()).digest()
        yield "SD-" + "".join(CODE_ALPHABET[b % 32] for b in h[:6])


def hist(key, ver, kind, amount, credits, note):
    # 계정 ver 와 같은 트랜잭션에서 쓰이므로 ver 가 계정 안에서 유일하고 단조 증가하는 순번이다
    return {"pk": f"ACC#{key}", "sk": f"H#{ver:012d}",
            "kind": kind, "amount": amount, "credits": credits, "at": now_iso(), "note": note[:80]}


def apply(key, delta, kind, note, extra=(), need_balance=False):
    """잔액을 delta 만큼 바꾸고 기록을 남긴다. extra 연산과 한 트랜잭션.
    반환: ("ok", 새 잔액) | ("short", 잔액) | ("dup", 잔액: extra 조건 실패) | ("noacct", 0)"""
    for _ in range(10):
        acc = get(f"ACC#{key}")
        if not acc:
            return "noacct", 0
        new = acc["credits"] + delta
        if need_balance and new < 0:
            return "short", acc["credits"]
        ops = list(extra) + [
            op_put({**acc, "credits": new, "ver": acc["ver"] + 1}, "ver = :v", {":v": acc["ver"]}),
            op_put(hist(key, acc["ver"] + 1, kind, delta, new, note)),
        ]
        r = transact(ops)
        if r is None:
            return "ok", new
        if any(c == "ConditionalCheckFailed" for c in r[:len(extra)]):
            return "dup", acc["credits"]
        time.sleep(0.02 * (_ + 1))  # 계정 ver 충돌 또는 트랜잭션 충돌 → 다시 읽고 재시도
    raise RuntimeError("busy")


def open_account(email):
    key = acct_key(email)
    acc, free = get(f"ACC#{key}"), False
    if not acc:
        fc = int(os.environ.get("FREE_CREDITS", "20"))
        cands = code_candidates(key)
        code = next(cands)
        for _ in range(80):
            item = {"pk": f"ACC#{key}", "sk": "META", "credits": fc, "code": code, "ver": 1, "created": now_iso()}
            r = transact([
                op_put({"pk": f"CODE#{code}", "sk": "META", "acct": key}, "attribute_not_exists(pk)"),
                op_put(item, "attribute_not_exists(pk)"),
                op_put(hist(key, 1, "free", fc, fc, "가입 무료 크레딧")),
            ])
            if r is None:
                acc, free = item, True
                break
            if len(r) > 1 and r[1] == "ConditionalCheckFailed":  # 동시에 누가 만들었다
                acc = get(f"ACC#{key}")
                break
            if r[0] == "ConditionalCheckFailed":  # 코드 충돌 → 다음 후보
                code = next(cands)
        if not acc:
            raise RuntimeError("could not open account")
    claim_unclaimed(key)
    acc = get(f"ACC#{key}")
    return {"code": acc["code"], "credits": acc["credits"], "free": free}


def claim_unclaimed(key):
    r = ddb().query(TableName=table(), KeyConditionExpression="pk = :p",
                    ExpressionAttributeValues={":p": ser(f"UNCLAIMED#{key}")}, ConsistentRead=True)
    for it in (item_des(x) for x in r.get("Items", [])):
        pid = it["sk"][4:]
        pay = get(f"PAY#{pid}")
        if not pay or pay.get("st") != "unclaimed":
            ddb().delete_item(TableName=table(), Key={"pk": ser(it["pk"]), "sk": ser(it["sk"])})
            continue
        claimed = {**pay, "st": "applied", "acct": key}
        claimed.pop("owner", None)
        apply(key, pay["credits"], "buy", pay_note(pay), extra=[
            op_delete(it["pk"], it["sk"], "attribute_exists(pk)"),
            op_put(claimed, "st = :s", {":s": "unclaimed"}),
        ])


def pay_note(pay):
    n = f"BMC {pay.get('amount')} {pay.get('currency')}"
    return n + (" (test)" if pay.get("test") else "")


# ---------- 웹훅 ----------
def raw_body(event):
    b = event.get("body") or ""
    return base64.b64decode(b) if event.get("isBase64Encoded") else b.encode()


def resp(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json"}, "body": json.dumps(body, ensure_ascii=False)}


def texts_of(data):
    out = [data.get("support_note"), data.get("message"), data.get("supporter_feedback")]
    for x in data.get("extras") or []:
        if isinstance(x, dict):
            out.append(x.get("extra_question"))
            out += list(x.get("question_answers") or [])
    c = data.get("commission")
    if isinstance(c, dict):
        out.append(c.get("additional_info"))
    return [str(t) for t in out if t]


def find_owner(data):
    """(key, 계정 있음 여부). 코드 → 이메일 순."""
    for t in texts_of(data):
        for code in CODE_RE.findall(t.upper()):
            c = get(f"CODE#{code}")
            if c:
                return c["acct"], True
    email = str(data.get("supporter_email") or "").strip()
    if "@" in email:
        key = acct_key(email)
        return key, get(f"ACC#{key}") is not None
    return None, False


def webhook(event):
    body = raw_body(event)
    sig = (event.get("headers") or {}).get("x-signature-sha256", "").strip().lower()
    want = hmac.new(os.environ["BMC_WEBHOOK_SECRET"].encode(), body, hashlib.sha256).hexdigest()
    if not sig or not hmac.compare_digest(sig, want):
        return resp(403, {"error": "bad signature"})
    try:
        ev = json.loads(body, parse_float=Decimal)
    except ValueError:
        return resp(422, {"error": "bad payload"})
    kind, data = str(ev.get("type", "")), ev.get("data") or {}
    rid = data.get("id") if data.get("id") not in (None, "") else data.get("support_id")
    if rid in (None, ""):
        return resp(200, {"ok": True, "applied": False})
    pid = f"{kind.split('.')[0]}:{rid}"
    if "refund" in kind:
        return refund_event(pid)
    is_money = (kind.startswith(PAYMENT_PREFIXES) and not kind.endswith(".updated")) or kind in SUBSCRIPTION_STARTS
    if not is_money:
        return resp(200, {"ok": True, "applied": False})
    if kind in SUBSCRIPTION_STARTS:
        pid += f":{data.get('current_period_start') or data.get('started_at') or ''}"
    test = str(ev.get("live_mode", True)).lower() == "false"
    try:
        amount = Decimal(str(data.get("amount") or 0))
    except ArithmeticError:
        amount = Decimal(0)
    currency = str(data.get("currency") or "USD").upper()
    cpu = Decimal(os.environ.get("CREDITS_PER_USD", "20"))
    credits = int((amount * cpu).to_integral_value(rounding=ROUND_FLOOR)) if currency == "USD" and amount > 0 else 0
    pay = {"pk": f"PAY#{pid}", "sk": "META", "amount": str(amount), "currency": currency, "credits": credits,
           "at": str(data.get("created_at") or ev.get("created") or ""), "received": now_iso(), "test": test}
    key, exists = find_owner(data)
    if key and exists:
        st, bal = apply(key, credits, "buy", pay_note(pay),
                        extra=[op_put({**pay, "st": "applied", "acct": key}, "attribute_not_exists(pk)")])
        if st == "ok":
            return resp(200, {"ok": True, "applied": True, "credits": credits})
        if st == "dup":
            return resp(200, {"ok": True, "duplicate": True})
        # 계정이 사라졌다 → 주인 없는 결제로
    if key:
        r = transact([op_put({**pay, "st": "unclaimed", "owner": key}, "attribute_not_exists(pk)"),
                      op_put({"pk": f"UNCLAIMED#{key}", "sk": f"PAY#{pid}"})])
    else:
        r = transact([op_put({**pay, "st": "orphan"}, "attribute_not_exists(pk)")])
    if r is not None:
        if r[0] == "ConditionalCheckFailed":
            return resp(200, {"ok": True, "duplicate": True})
        raise RuntimeError(f"store failed: {r}")
    return resp(200, {"ok": True, "applied": False, "held": True})


def refund_event(pid):
    for _ in range(10):
        pay = get(f"PAY#{pid}")
        if not pay:  # 결제보다 환불이 먼저 왔다 → 묘비를 남겨 나중 결제를 막는다
            r = transact([op_put({"pk": f"PAY#{pid}", "sk": "META", "st": "refunded", "credits": 0, "received": now_iso()},
                                 "attribute_not_exists(pk)")])
            if r is None:
                return resp(200, {"ok": True, "reversed": 0})
            continue
        st = pay.get("st")
        if st == "refunded":
            return resp(200, {"ok": True, "duplicate": True})
        done = {**pay, "st": "refunded", "refunded_at": now_iso()}
        cond = op_put(done, "st = :s", {":s": st})
        if st == "applied":
            res, _bal = apply(pay["acct"], -pay["credits"], "reversal", "BMC 환불 " + pay_note(pay), extra=[cond])
            if res == "ok":
                return resp(200, {"ok": True, "reversed": pay["credits"]})
            if res == "noacct":
                if transact([cond]) is None:
                    return resp(200, {"ok": True, "reversed": 0})
            continue
        ops = [cond]
        if st == "unclaimed":
            ops.append(op_delete(f"UNCLAIMED#{pay['owner']}", f"PAY#{pid}"))
        if transact(ops) is None:
            return resp(200, {"ok": True, "reversed": 0})
    raise RuntimeError("busy")


# ---------- 앱 API ----------
def authorized(event):
    got = (event.get("headers") or {}).get("authorization", "")
    return hmac.compare_digest(got.encode(), f"Bearer {os.environ['APP_TOKEN']}".encode())


def parse_api(event):
    try:
        b = json.loads(raw_body(event) or b"{}")
    except ValueError:
        return None, resp(400, {"error": "bad json"})
    if not isinstance(b, dict):
        return None, resp(400, {"error": "bad json"})
    email = str(b.get("email") or "").strip()
    if "@" not in email or len(email) > 254:
        return None, resp(400, {"error": "bad email"})
    return b, None


def parse_amount_ref(b):
    try:
        amount = int(b.get("amount"))
    except (TypeError, ValueError):
        return None, None, resp(400, {"error": "bad amount"})
    ref = str(b.get("ref") or "").strip()
    if amount <= 0 or amount > 10_000_000 or not ref or len(ref) > 200:
        return None, None, resp(400, {"error": "bad amount or ref"})
    return amount, ref, None


def balance(key):
    acc = get(f"ACC#{key}")
    return acc["credits"] if acc else 0


def api_charge(b):
    amount, ref, err = parse_amount_ref(b)
    if err:
        return err
    key = acct_key(b["email"])
    cpk = f"CHG#{key}#{ref}"
    if get(cpk):
        return resp(200, {"credits": balance(key)})
    st, bal = apply(key, -amount, "charge", ref, need_balance=True, extra=[
        op_put({"pk": cpk, "sk": "META", "amount": amount, "st": "charged", "at": now_iso()}, "attribute_not_exists(pk)")])
    if st in ("ok", "dup"):
        return resp(200, {"credits": bal if st == "ok" else balance(key)})
    return resp(402, {"credits": bal})


def api_refund(b):
    amount, ref, err = parse_amount_ref(b)
    if err:
        return err
    key = acct_key(b["email"])
    chg = get(f"CHG#{key}#{ref}")
    if not chg or chg.get("st") != "charged":
        return resp(200, {"credits": balance(key)})
    amt = min(amount, int(chg["amount"]))
    st, bal = apply(key, amt, "refund", ref, extra=[
        op_put({**chg, "st": "refunded", "refunded": amt}, "st = :s", {":s": "charged"})])
    return resp(200, {"credits": bal if st == "ok" else balance(key)})


def api_history(b):
    key = acct_key(b["email"])
    r = ddb().query(TableName=table(), KeyConditionExpression="pk = :p AND begins_with(sk, :h)",
                    ExpressionAttributeValues={":p": ser(f"ACC#{key}"), ":h": ser("H#")},
                    ScanIndexForward=False, Limit=50, ConsistentRead=True)
    items = [item_des(x) for x in r.get("Items", [])]
    return resp(200, {"items": [{"kind": x["kind"], "amount": x["amount"], "credits": x["credits"],
                                 "at": x["at"], "note": x.get("note", "")} for x in items]})


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "")
    if method == "POST" and path == "/webhooks/bmc":
        return webhook(event)
    if path.startswith("/api/"):
        if not authorized(event):
            return resp(401, {"error": "unauthorized"})
        if method != "POST":
            return resp(405, {"error": "method"})
        routes = {"/api/account": lambda b: resp(200, open_account(b["email"])),
                  "/api/charge": api_charge, "/api/refund": api_refund, "/api/history": api_history}
        fn = routes.get(path)
        if not fn:
            return resp(404, {"error": "not found"})
        b, err = parse_api(event)
        return err or fn(b)
    return resp(404, {"error": "not found"})
