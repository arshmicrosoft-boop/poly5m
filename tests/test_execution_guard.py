import pytest
from poly5m.config import BotConfig
from poly5m.risk_engine import RiskEngine
from poly5m.execution import ExecutionEngine


def test_live_order_blocked_dry_run():
    cfg = BotConfig(dry_run=True)
    re = RiskEngine()
    eng = ExecutionEngine(config=cfg, risk_engine=re, live_confirmed=False)
    with pytest.raises(AssertionError):
        eng._send_live_clob_order()


def test_live_order_blocked_no_confirm():
    cfg = BotConfig(dry_run=False)
    re = RiskEngine()
    eng = ExecutionEngine(config=cfg, risk_engine=re, live_confirmed=False)
    with pytest.raises(AssertionError):
        eng._send_live_clob_order()