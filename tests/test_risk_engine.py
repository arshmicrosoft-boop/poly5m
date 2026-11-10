import pytest
from poly5m.risk_engine import RiskEngine, CapitalBuckets


def test_trade2_allowed_after_trade1_settling():
    re = RiskEngine()
    # Trade 1: 5 shares at ~0.54 -> cost ~2.70
    ok1 = re.open_position(1, "UP", 5.0, 2.70, "tok1")
    assert ok1 is True
    assert re.buckets.liquid_usdc < 10.0
    # Simulate window resolution -> moves to settling then redeem
    re.resolve_window(1, 1)
    # Now open trade 2 with ~2.70 cost while ~7.30 liquid
    ok2 = re.open_position(2, "UP", 5.0, 2.70, "tok2")
    assert ok2 is True, "Trade 2 should be allowed despite settling lag"


def test_auto_cashout_recycles_liquid():
    re = RiskEngine()
    re.open_position(3, "UP", 5.0, 2.70, "tok3")
    before = re.buckets.liquid_usdc
    proceeds = re.try_auto_cashout(3, 0.95)
    assert proceeds > 0
    assert re.buckets.liquid_usdc > before
    assert 3 not in re.open_positions or "3" not in re.open_positions