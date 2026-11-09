import pytest

from credits import LocalLedger


def test_local_coupon_matches_lambda_contract():
    led = LocalLedger()
    assert led.make_coupon("olmuse-start-1", 10000, uses=2) == "OLMUSESTART1"
    with pytest.raises(ValueError):
        led.make_coupon("OLMUSESTART1", 5)
    start = led.account("a@x.io")["credits"]
    assert led.redeem("a@x.io", "olmuse start 1") == {"status": "ok", "added": 10000, "credits": start + 10000}
    assert led.redeem("a@x.io", "OLMUSESTART1")["status"] == "used"
    assert led.redeem("b@x.io", "OLMUSESTART1")["status"] == "ok"
    assert led.redeem("c@x.io", "OLMUSESTART1")["status"] == "empty"
    assert led.redeem("c@x.io", "NOPE00")["status"] == "none"
    assert led.history("a@x.io")[0]["kind"] == "coupon"


def test_local_coupon_tries_are_limited():
    led = LocalLedger()
    for _ in range(10):
        assert led.redeem("d@x.io", "WRONG0")["status"] == "none"
    assert led.redeem("d@x.io", "WRONG0")["status"] == "too_many"
