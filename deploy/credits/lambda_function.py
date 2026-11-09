"""olmuse (구 strudel 딸깍이) 크레딧 장부 (Lambda Function URL + DynamoDB 한 테이블).

  POST /webhooks/bmc   BMC 웹훅. x-signature-sha256 = HMAC-SHA256(BMC_WEBHOOK_SECRET, 원문) 16진수. 틀리면 403.
  POST /api/account    {email}               → {code, credits, free}
  POST /api/charge     {email, amount, ref}  → 200 {credits} | 402 {credits}
  POST /api/refund     {email 또는 acct(계정 키 64자리 16진수), amount, ref}  → 200 {credits}
                       acct는 웹 서버가 이메일 없이 디스크에 남긴 차감을 재시작 때 환불하는 길이다
  POST /api/history    {email}               → {items:[...]} 최근 50개
  POST /api/find       {email, payer_email, amount, date(YYYY-MM-DD)} → {found, added, credits} | 429
                       주인 없는 결제를 결제 이메일·금액·날짜(±1일)로 찾아 이 계정에 넣는다. 하루 FIND_TRIES 번
  POST /api/reviews    {email(아무 값)}      → {items:[...]} 운영자가 볼 보류 결제(환율을 모르는 통화). ADMIN_TOKEN 전용
  POST /api/coupon_make {email(아무 값), code, credits, uses} → 200 {code} | 409 이미 있음. ADMIN_TOKEN 전용(tools/coupon.py)
  POST /api/redeem     {email, code}         → 200 {added, credits} | 404 없는 쿠폰 | 409 이미 씀 | 410 다 씀 | 429
                       쿠폰 하나는 계정당 한 번. 시도는 하루 FIND_TRIES 번(결제 찾기와 따로 셈)
/api/* 는 Authorization: Bearer APP_TOKEN (웹 서버). 쿠폰 발행과 보류 결제 조회는 Bearer ADMIN_TOKEN 만 받는다
(웹 서버는 이 토큰을 갖지 않는다). ADMIN_TOKEN 이 없으면 두 경로는 늘 401 이다.

테이블 항목 (pk, sk):
  ACC#<key>, META         계정: credits, code, ver(낙관적 잠금)
  ACC#<key>, H#<ver>      기록: kind, amount(부호 있는 변화량), credits(그 뒤 잔액), at, note
  CODE#<SD-XXXXXX>, META  코드 → acct
  PAY#<종류:id>, META     결제: amount, currency, usd, credits, at, test,
                          st(applied|unclaimed|orphan|review|refunded), acct/owner/payer
  UNCLAIMED#<key>, PAY#.. 코드를 적으려 했지만 계정이 없는 결제. 같은 이메일로 가입하면 들어간다 (key = 이메일 HMAC)
  ORPHAN#<payer>, PAY#..  코드가 없는 결제(블로그 후원 포함). "결제 찾기"로만 계정에 들어간다 (payer = 결제 이메일 HMAC)
  REVIEW#open, PAY#..     환율을 모르는 통화. 운영자 확인 대기(CloudWatch 로그에 ALERT 한 줄)
  FIND#<key>, <날짜>       결제 찾기 시도 횟수
  CHG#<key>#<ref>, META   차감: amount, st(charged|refunded)
  COUPON#<CODE>, META     쿠폰: credits, remain(남은 사용 횟수), uses, at. CODE는 영문 대문자·숫자만
  COUPON#<CODE>, USE#<key> 그 계정이 쓴 기록
  REDEEM#<key>, <날짜>     쿠폰 시도 횟수
이메일은 HMAC(PEPPER, email.lower().strip()) 로만 남긴다. BMC 구매자 이름·이메일·메모 원문은 저장하지 않는다.
잔액 변경은 모두 계정 ver 조건 + 트랜잭션이라 동시 차감에도 음수가 되지 않는다(환불 이벤트의 회수만 음수 허용).
"""
import base64
import hashlib
import hmac
import json
import os
import re
import itertools
import secrets
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_FLOOR

DDB = None  # 시험에서는 가짜로 바꾼다
CODE_RE = re.compile(r"SD-[A-Z0-9]{6}")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # 0/O/1/I 제외, 32자
# 너그러운 인식: 대소문자, 하이픈·공백 없음, "SD ABC123", "sd_abc-123". 대문자로 바꾼 글에 쓴다.
LOOSE_CODE_RE = re.compile(r"(?<![A-Z0-9])S\s*D[\s\-_.:#]*([A-Z0-9]{3})[\s\-]?([A-Z0-9]{3})(?![A-Z0-9])")
# 헷갈리는 글자. 코드에 없는 0·O·1·I 는 생김새가 가까운 글자로, 나머지는 서로 바꿔 본다. 맞는 계정이 하나일 때만 쓴다.
CONFUSABLE = {"0": "DQ", "O": "DQ", "1": "LJT7", "I": "LJT7", "5": "S5", "S": "S5", "2": "Z2", "Z": "Z2",
              "8": "B8", "B": "B8", "6": "G6", "G": "G6"}
# 1 단위의 USD 값(고정 환율표, 대략값). 환경 변수 USD_RATES(JSON)로 덮어쓴다. 표에 없는 통화는 보류하고 운영자에게 알린다.
USD_RATES = {"USD": "1", "EUR": "1.08", "GBP": "1.27", "KRW": "0.00072", "JPY": "0.0066", "CNY": "0.14", "CAD": "0.73",
             "AUD": "0.66", "NZD": "0.6", "CHF": "1.12", "SGD": "0.74", "HKD": "0.128", "TWD": "0.031", "INR": "0.012",
             "BRL": "0.18", "MXN": "0.055", "SEK": "0.095", "NOK": "0.093", "DKK": "0.145", "PLN": "0.25",
             "PHP": "0.017", "THB": "0.028", "MYR": "0.22", "IDR": "0.000062", "ZAR": "0.054"}
FIND_TRIES = 10
WORDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "words_en.txt")
_WORDS = None
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
    except Exception as e:  # botocore ClientError, 시험의 가짜도 같은 모양
        err = getattr(e, "response", None) or {}
        if err.get("Error", {}).get("Code") != "TransactionCanceledException":
            raise
        return [(r or {}).get("Code", "None") for r in err.get("CancellationReasons", [])] or ["Unknown"]


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
    for attempt in range(10):
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
        time.sleep(0.02 * (attempt + 1))  # 계정 ver 충돌 또는 트랜잭션 충돌 → 다시 읽고 재시도
    raise RuntimeError("busy")


# ---------- 기억하기 쉬운 결제 코드 (예: brave-otter-lamp) ----------
def words():
    """{"adjectives": [...], "nouns": [...]} words_en.txt 에서. 중복은 뺀다."""
    global _WORDS
    if _WORDS is None:
        out, part = {}, None
        with open(WORDS_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("["):
                    part = out.setdefault(line.strip("[]"), [])
                elif line and not line.startswith("#") and part is not None:
                    part += [w for w in line.split() if w not in part]
        _WORDS = out
    return _WORDS


def word_code(rng=secrets.SystemRandom()):
    """첫 글자를 칸마다 무작위로 뽑고 그 글자로 시작하는 쉬운 단어를 끼운다: 형용사-명사-명사.
    경우의 수는 약 1000만, 이미 쓰인 코드면 open_account 가 다시 뽑는다."""
    w, parts = words(), []
    for kind in ("adjectives", "nouns", "nouns"):
        by_letter = {}
        for x in w[kind]:
            by_letter.setdefault(x[0], []).append(x)
        letter = rng.choice(sorted(by_letter))
        parts.append(rng.choice([x for x in by_letter[letter] if x not in parts] or by_letter[letter]))
    return "-".join(parts)


def code_key(code):
    """코드 색인. SD-XXXXXX 는 그대로, 단어 코드는 소문자 글자만 이어 붙인다(공백·하이픈·대소문자 무시)."""
    return code if code.startswith("SD-") else "EN:" + re.sub(r"[^a-z]", "", code.lower())


def ensure_word_code(key):
    """예전 계정(SD- 코드만 있음)에 단어 코드를 붙인다. 충돌하면 다시 뽑는다."""
    for _ in range(40):
        acc = get(f"ACC#{key}")
        if not acc or acc.get("word_code"):
            return acc
        code = word_code()
        r = transact([op_put({"pk": f"CODE#{code_key(code)}", "sk": "META", "acct": key}, "attribute_not_exists(pk)"),
                      op_put({**acc, "word_code": code}, "ver = :v", {":v": acc["ver"]})])
        if r is None:
            return get(f"ACC#{key}")
        if r[0] != "ConditionalCheckFailed":
            time.sleep(0.02)
    raise RuntimeError("could not assign a code")


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
    acc = ensure_word_code(key)
    # code: 화면에 보여 줄 결제 코드(단어 코드). 예전 SD- 코드도 계속 인정하므로 legacy_code 로 함께 준다.
    return {"code": acc["word_code"], "legacy_code": acc["code"], "credits": acc["credits"], "free": free}


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
    if pay.get("currency") not in (None, "USD") and pay.get("usd"):
        n += f" ≈ {pay['usd']} USD"
    return n + (" (test)" if pay.get("test") else "")


def alert(kind, **fields):
    """운영자 알림: CloudWatch 로그에 ALERT 로 시작하는 한 줄(메트릭 필터·알람 대상). 이메일·이름은 넣지 않는다."""
    print("ALERT " + json.dumps({"kind": kind, **fields}, ensure_ascii=False, default=str))


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


def code_options(raw):
    """적힌 6글자를 헷갈리는 글자만 바꿔 만든 코드 후보(그대로인 것은 뺀다). 64개까지."""
    opts = [CONFUSABLE.get(c, c) for c in raw]
    if len(list(itertools.islice(itertools.product(*opts), 65))) > 64:  # 너무 많으면 코드에 없는 글자만 고친다
        opts = [c if c in CODE_ALPHABET else CONFUSABLE.get(c, c) for c in raw]
    for combo in itertools.islice(itertools.product(*opts), 64):
        code = "".join(combo)
        if code != raw and all(c in CODE_ALPHABET for c in code):
            yield "SD-" + code


def word_code_owner(texts, budget=80):
    """글 속 단어 코드의 계정. 이어진 낱말 1~4개를 붙여(공백·하이픈·대소문자 무시) 색인에서 찾는다."""
    for t in texts:
        tokens = re.findall(r"[a-z]+", t.lower())
        for i in range(len(tokens)):
            for n in range(1, 5):
                joined = "".join(tokens[i:i + n])
                if i + n > len(tokens) or len(joined) > 30:
                    break
                if len(joined) < 9:
                    continue
                budget -= 1
                if budget < 0:
                    return None
                hit = get(f"CODE#EN:{joined}")
                if hit:
                    return hit["acct"]
    return None


def code_owner(texts):
    """(계정 key 또는 None, 코드 비슷한 글자가 있었는지). 단어 코드 → SD- 코드 순."""
    key = word_code_owner(texts)
    if key:
        return key, True
    seen = False
    for t in texts:
        for a, b in LOOSE_CODE_RE.findall(t.upper()):
            seen, raw = True, a + b
            exact = get(f"CODE#SD-{raw}")
            if exact:
                return exact["acct"], True
            hits = {c["acct"] for c in (get(f"CODE#{x}") for x in code_options(raw)) if c}
            if len(hits) == 1:
                return hits.pop(), True
    return None, seen


def find_owner(data):
    """(key, 계정 있음 여부, 코드 비슷한 글자가 있었는지). 코드 → (코드를 적으려 한 결제만) 구매자 이메일 순.
    코드가 전혀 없는 결제는 블로그 후원일 수 있어 이메일로 자동 적립하지 않는다. 본인이 "결제 찾기"로 가져간다."""
    key, seen = code_owner(texts_of(data))
    if key:
        return key, True, True
    email = str(data.get("supporter_email") or "").strip()
    if seen and "@" in email:
        key = acct_key(email)
        return key, get(f"ACC#{key}") is not None, True
    return None, False, seen


def is_payment(kind):
    return (kind.startswith(PAYMENT_PREFIXES) and not kind.endswith(".updated")) or kind in SUBSCRIPTION_STARTS


def usd_rate(currency):
    rates = dict(USD_RATES)
    try:
        rates.update({str(k).upper(): str(v) for k, v in json.loads(os.environ.get("USD_RATES") or "{}").items()})
    except (ValueError, AttributeError):
        pass
    try:
        return Decimal(rates[currency]) if currency in rates else None
    except InvalidOperation:
        return None


def payment_item(pid, ev, data):
    """PAY# 항목. USD 가 아니면 고정 환율표로 USD 로 바꿔 크레딧을 센다. 표에 없는 통화는 unknown_currency(보류)."""
    try:
        amount = Decimal(str(data.get("amount") or 0))
    except ArithmeticError:
        amount = Decimal(0)
    currency = str(data.get("currency") or "USD").upper().strip()[:8]
    cpu = Decimal(os.environ.get("CREDITS_PER_USD", "20"))
    rate = usd_rate(currency)
    usd = (amount * rate).quantize(Decimal("0.01"), rounding=ROUND_FLOOR) if rate is not None and amount > 0 else None
    credits = int((usd * cpu).to_integral_value(rounding=ROUND_FLOOR)) if usd is not None else 0
    return {"pk": f"PAY#{pid}", "sk": "META", "amount": str(amount), "currency": currency, "credits": credits,
            "usd": str(usd) if usd is not None else None, "unknown_currency": rate is None and amount > 0,
            "at": str(data.get("created_at") or ev.get("created") or ""), "received": now_iso(),
            "test": str(ev.get("live_mode", True)).lower() == "false"}


def hold_payment(pay, pid, key, payer=None):
    """계정에 바로 못 넣은 결제를 보관한다. key 가 있으면 가입할 때 찾아가고, 없으면 orphan.
    orphan 은 결제 이메일 HMAC(payer)으로 색인해 "결제 찾기"로 가져갈 수 있게 한다."""
    if key:
        r = transact([op_put({**pay, "st": "unclaimed", "owner": key}, "attribute_not_exists(pk)"),
                      op_put({"pk": f"UNCLAIMED#{key}", "sk": f"PAY#{pid}"})])
    elif payer:
        r = transact([op_put({**pay, "st": "orphan", "payer": payer}, "attribute_not_exists(pk)"),
                      op_put({"pk": f"ORPHAN#{payer}", "sk": f"PAY#{pid}"})])
    else:
        r = transact([op_put({**pay, "st": "orphan"}, "attribute_not_exists(pk)")])
    if r is None:
        return resp(200, {"ok": True, "applied": False, "held": True})
    if r[0] == "ConditionalCheckFailed":
        return resp(200, {"ok": True, "duplicate": True})
    raise RuntimeError(f"store failed: {r}")


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
    if not is_payment(kind):
        return resp(200, {"ok": True, "applied": False})
    if kind in SUBSCRIPTION_STARTS:  # 구독은 기간마다 새 결제
        pid += f":{data.get('current_period_start') or data.get('started_at') or ''}"
    pay = payment_item(pid, ev, data)
    key, exists, seen = find_owner(data)
    out = credit_purchase(store_payment(pay, pid, data, key, exists), seen)
    return out


def credit_purchase(r, seen):
    """응답에 credit(코드를 적은 크레딧 구매인지)을 붙인다. 블로그 입구는 이것을 보고 후원 명단·대기에서 뺀다."""
    body = json.loads(r["body"])
    body["credit"] = bool(seen)
    return {**r, "body": json.dumps(body, ensure_ascii=False)}


def store_payment(pay, pid, data, key, exists):
    if pay["unknown_currency"]:  # 환율을 모른다 → 0크레딧으로 넣지 않고 보류, 운영자에게 알림
        return review_payment(pay, pid, key if exists else None)
    if key and exists:
        st, _ = apply(key, pay["credits"], "buy", pay_note(pay),
                      extra=[op_put({**pay, "st": "applied", "acct": key}, "attribute_not_exists(pk)")])
        if st == "ok":
            return resp(200, {"ok": True, "applied": True, "credits": pay["credits"]})
        if st == "dup":
            return resp(200, {"ok": True, "duplicate": True})
        # 계정이 사라졌다 → 주인 없는 결제로
    email = str(data.get("supporter_email") or "").strip()
    return hold_payment(pay, pid, key, acct_key(email) if "@" in email else None)


def review_payment(pay, pid, key):
    r = transact([op_put({**pay, "st": "review", "acct": key}, "attribute_not_exists(pk)"),
                  op_put({"pk": "REVIEW#open", "sk": f"PAY#{pid}"})])
    if r and r[0] == "ConditionalCheckFailed":
        return resp(200, {"ok": True, "duplicate": True})
    if r:
        raise RuntimeError(f"store failed: {r}")
    alert("unknown_currency", pid=pid, amount=pay["amount"], currency=pay["currency"], has_account=bool(key))
    if key:  # 사용자 기록에 "확인 중"을 남겨 0크레딧이 조용히 묻히지 않게 한다
        apply(key, 0, "pending", pay_note(pay) + " 확인 중")
    return resp(200, {"ok": True, "applied": False, "review": True})


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
        elif st == "orphan" and pay.get("payer"):
            ops.append(op_delete(f"ORPHAN#{pay['payer']}", f"PAY#{pid}"))
        elif st == "review":
            ops.append(op_delete("REVIEW#open", f"PAY#{pid}"))
        if transact(ops) is None:
            return resp(200, {"ok": True, "reversed": 0})
    raise RuntimeError("busy")


# ---------- 앱 API ----------
ADMIN_ROUTES = ("/api/coupon_make", "/api/reviews")
ACCT_RE = re.compile(r"[0-9a-f]{64}")


def authorized(event, env_name="APP_TOKEN"):
    want = os.environ.get(env_name, "")
    if not want:
        return False
    got = (event.get("headers") or {}).get("authorization", "")
    return hmac.compare_digest(got.encode(), f"Bearer {want}".encode())


def parse_api(event, allow_acct=False):
    try:
        b = json.loads(raw_body(event) or b"{}")
    except ValueError:
        return None, resp(400, {"error": "bad json"})
    if not isinstance(b, dict):
        return None, resp(400, {"error": "bad json"})
    email = str(b.get("email") or "").strip()
    if allow_acct and not email and ACCT_RE.fullmatch(str(b.get("acct") or "")):
        return b, None
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
    key = b["acct"] if not str(b.get("email") or "").strip() else acct_key(b["email"])
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


def pay_day(at):
    """결제 시각(BMC 의 epoch 초 또는 ISO 문자열) → UTC 날짜. 모르면 None."""
    s = str(at or "").strip()
    try:
        if re.fullmatch(r"\d{9,11}(\.\d+)?", s):
            return datetime.fromtimestamp(float(s), timezone.utc).date()
        return datetime.fromisoformat(s.replace("Z", "+00:00").replace(" ", "T")).date()
    except (ValueError, OverflowError, OSError):
        return None


def count_find_try(key, kind="FIND"):
    """오늘 결제 찾기(또는 쿠폰) 시도를 하나 센다. 한도를 넘었으면 False."""
    day = date.today().isoformat()
    for _ in range(10):
        cur = get(f"{kind}#{key}", day)
        n = cur["n"] if cur else 0
        if n >= FIND_TRIES:
            return False
        item = {"pk": f"{kind}#{key}", "sk": day, "n": n + 1}
        if transact([op_put(item, "n = :n", {":n": n}) if cur else op_put(item, "attribute_not_exists(pk)")]) is None:
            return True
    raise RuntimeError("busy")


def api_find(b):
    """주인 없는 결제를 결제 이메일·금액·날짜(±1일)로 찾아 이 계정에 넣는다. 셋이 다 맞아야 한다."""
    payer_email = str(b.get("payer_email") or "").strip()
    try:
        amount = Decimal(str(b.get("amount")).replace(",", "").strip())
        day = date.fromisoformat(str(b.get("date") or "").strip()[:10])
    except (InvalidOperation, ValueError):
        return resp(400, {"error": "bad amount or date"})
    if "@" not in payer_email or len(payer_email) > 254 or not amount.is_finite() or amount <= 0:
        return resp(400, {"error": "bad payer email or amount"})
    key = acct_key(b["email"])
    open_account(b["email"])
    if not count_find_try(key):
        return resp(429, {"error": "too many tries", "credits": balance(key)})
    payer = acct_key(payer_email)
    found = added = 0
    for index in (f"ORPHAN#{payer}", f"UNCLAIMED#{payer}"):
        r = ddb().query(TableName=table(), KeyConditionExpression="pk = :p",
                        ExpressionAttributeValues={":p": ser(index)}, ConsistentRead=True)
        for it in (item_des(x) for x in r.get("Items", [])):
            pay = get(it["sk"])
            if not pay or pay.get("st") not in ("orphan", "unclaimed"):
                continue
            paid = pay_day(pay.get("at"))
            try:
                same = abs(Decimal(str(pay.get("amount"))) - amount) <= Decimal("0.01")
            except InvalidOperation:
                same = False
            if not same or not paid or abs((paid - day).days) > 1:
                continue
            claimed = {**pay, "st": "applied", "acct": key, "found": now_iso()}
            claimed.pop("owner", None)
            st, _ = apply(key, pay["credits"], "buy", pay_note(pay) + " (결제 찾기)", extra=[
                op_put(claimed, "st = :s", {":s": pay["st"]}),
                op_delete(index, it["sk"], "attribute_exists(pk)"),
            ])
            if st == "ok":
                found, added = found + 1, added + pay["credits"]
    return resp(200, {"found": found, "added": added, "credits": balance(key)})


def api_reviews(_b):
    r = ddb().query(TableName=table(), KeyConditionExpression="pk = :p",
                    ExpressionAttributeValues={":p": ser("REVIEW#open")}, ConsistentRead=True)
    out = []
    for it in (item_des(x) for x in r.get("Items", [])):
        pay = get(it["sk"])
        if pay and pay.get("st") == "review":
            out.append({"pid": it["sk"][4:], "amount": pay.get("amount"), "currency": pay.get("currency"),
                        "at": pay.get("at"), "has_account": bool(pay.get("acct"))})
    return resp(200, {"items": out})


# ---------- 쿠폰 ----------
def coupon_code(raw):
    return re.sub(r"[^A-Z0-9]", "", str(raw or "").upper())[:40]


def api_coupon_make(b):
    code = coupon_code(b.get("code"))
    try:
        amount, uses = int(b.get("credits")), int(b.get("uses", 1))
    except (TypeError, ValueError):
        return resp(400, {"error": "bad credits or uses"})
    if len(code) < 6 or not 0 < amount <= 1_000_000 or not 0 < uses <= 100_000:
        return resp(400, {"error": "code needs 6+ letters/digits; credits 1..1000000; uses 1..100000"})
    item = {"pk": f"COUPON#{code}", "sk": "META", "credits": amount, "remain": uses, "uses": uses, "at": now_iso()}
    if transact([op_put(item, "attribute_not_exists(pk)")]) is not None:
        return resp(409, {"error": "exists"})
    alert("coupon_made", code=code[:3] + "…", credits=amount, uses=uses, total=amount * uses)
    return resp(200, {"code": code})


def api_redeem(b):
    code = coupon_code(b.get("code"))
    key = acct_key(b["email"])
    open_account(b["email"])
    if not count_find_try(key, "REDEEM"):
        return resp(429, {"error": "too many tries", "credits": balance(key)})
    for _ in range(10):
        cpn = get(f"COUPON#{code}") if code else None
        if not cpn:
            return resp(404, {"error": "no coupon", "credits": balance(key)})
        if get(f"COUPON#{code}", f"USE#{key}"):
            return resp(409, {"error": "used", "credits": balance(key)})
        if cpn["remain"] <= 0:
            return resp(410, {"error": "empty", "credits": balance(key)})
        st, bal = apply(key, cpn["credits"], "coupon", code, extra=[
            op_put({**cpn, "remain": cpn["remain"] - 1}, "remain = :l", {":l": cpn["remain"]}),  # left는 예약어
            op_put({"pk": f"COUPON#{code}", "sk": f"USE#{key}", "at": now_iso()}, "attribute_not_exists(pk)")])
        if st == "ok":
            return resp(200, {"added": cpn["credits"], "credits": bal})
        time.sleep(0.02)  # 다른 사람이 같은 순간에 썼다 → 다시 읽는다
    raise RuntimeError("busy")


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    path = event.get("rawPath", "")
    if method == "POST" and path == "/webhooks/bmc":
        return webhook(event)
    if path.startswith("/api/"):
        if not authorized(event, "ADMIN_TOKEN" if path in ADMIN_ROUTES else "APP_TOKEN"):
            return resp(401, {"error": "unauthorized"})
        if method != "POST":
            return resp(405, {"error": "method"})
        routes = {"/api/account": lambda b: resp(200, open_account(b["email"])),
                  "/api/charge": api_charge, "/api/refund": api_refund, "/api/history": api_history,
                  "/api/find": api_find, "/api/reviews": api_reviews,
                  "/api/coupon_make": api_coupon_make, "/api/redeem": api_redeem}
        fn = routes.get(path)
        if not fn:
            return resp(404, {"error": "not found"})
        b, err = parse_api(event, allow_acct=path == "/api/refund")
        return err or fn(b)
    return resp(404, {"error": "not found"})
