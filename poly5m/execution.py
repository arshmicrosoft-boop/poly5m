"""Production execution engine — unified dry-run + live CLOB via py-clob-client."""
import os
import time
import math
from dataclasses import dataclass, field
from typing import Optional, Any

from .config import BotConfig
from .risk_engine import RiskEngine
from .dry_run import DryRunExecutionEngine


@dataclass
class OrderResponse:
    ok: bool
    order_id: str = ""
    status: str = ""
    trade_ids: list = field(default_factory=list)
    transactions_hashes: list = field(default_factory=list)
    code: str = ""
    message: str = ""


class ExecutionEngine:
    """Unifies dry-run paper execution and live CLOB execution.

    Hard safety guard: live path raises AssertionError unless
    config.dry_run is False AND live_confirmed is True.
    """

    def __init__(self, config: BotConfig, risk_engine: RiskEngine,
                 live_confirmed: bool = False, client: Any = None):
        self.config = config
        self.risk_engine = risk_engine
        self.live_confirmed = live_confirmed
        self.dry_run_engine = DryRunExecutionEngine(config)
        self.client = client  # py_clob_client ClobClient instance (optional)
        self._init_client()

    def _init_client(self):
        if self.config.dry_run or not self.live_confirmed:
            return
        if self.client is not None:
            return
        try:
            from py_clob_client.client import ClobClient
            from py_clob_client.clob_types import ApiCreds
            pk = os.getenv("POLY_PRIVATE_KEY")
            funder = os.getenv("POLY_FUNDER_ADDRESS")
            if not pk:
                return
            self.client = ClobClient(
                host="https://clob.polymarket.com",
                key=pk,
                chain_id=137,
                signature_type=0 if not funder else 1,
                funder=funder,
            )
            # derive/create L2 creds
            try:
                creds = self.client.create_or_derive_api_creds()
                self.client.set_api_creds(creds)
            except Exception:
                pass
        except ImportError:
            self.client = None

    def _send_live_clob_order(self, asset_id: str = "", side: str = "BUY", price: float = 0.0,
                              size: float = 0.0, order_type: str = "FOK",
                              expiration: Optional[int] = None) -> OrderResponse:
        assert not self.config.dry_run, "LIVE ORDER BLOCKED: DRY_RUN active or --confirm-live not set"
        assert self.live_confirmed, "LIVE ORDER BLOCKED: DRY_RUN active or --confirm-live not set"
        if self.client is None:
            return OrderResponse(ok=False, message="no client configured")

        try:
            from py_clob_client.clob_types import OrderArgs, OrderType
            from py_clob_client.order_builder.constants import BUY, SELL
            order_side = BUY if side.upper() == "BUY" else SELL
            order_args = OrderArgs(
                price=price,
                size=size,
                side=order_side,
                token_id=asset_id,
            )
            if expiration is not None:
                order_args.expiration = expiration
            signed = self.client.create_order(order_args)
            if order_type == "FOK":
                resp = self.client.post_order(signed, OrderType.FOK)
            elif order_type == "GTD":
                resp = self.client.post_order(signed, OrderType.GTD)
            else:
                resp = self.client.post_order(signed, OrderType.GTC)
            return OrderResponse(
                ok=bool(resp.get("success", True)),
                order_id=resp.get("orderID", resp.get("orderId", "")),
                status=resp.get("status", ""),
                trade_ids=resp.get("tradeIds", []),
                transactions_hashes=resp.get("transactionsHashes", []),
                code=resp.get("code", ""),
                message=resp.get("message", resp.get("errorMsg", "")),
            )
        except Exception as e:
            return OrderResponse(ok=False, message=str(e))

    def submit_entry(self, snap: dict, signal: Any, asset_id: str) -> bool:
        wts = snap.get("window_ts", 0)
        cost = signal.shares * signal.best_ask + signal.shares * signal.expected_fee_per_share
        if not self.risk_engine.can_open(wts, cost):
            return False

        if self.config.dry_run or not self.live_confirmed:
            self.dry_run_engine.submit_order(f"window_{wts}", signal)
            self.risk_engine.open_position(wts, signal.side, signal.shares, cost, asset_id)
            return True

        # live path
        resp = self._send_live_clob_order(
            asset_id=asset_id,
            side="BUY",
            price=signal.limit_price,
            size=signal.shares,
            order_type="FOK",
        )
        if resp.ok:
            self.risk_engine.open_position(wts, signal.side, signal.shares, cost, asset_id)
            return True
        return False

    def check_and_execute_early_exit(self, snap: dict, asset_id: str,
                                    side: str, best_bid: float) -> float:
        wts = snap.get("window_ts", 0)
        proceeds = self.risk_engine.try_auto_cashout(wts, best_bid)
        if proceeds <= 0:
            return 0.0
        if not (self.config.dry_run or not self.live_confirmed):
            # sell shares on CLOB
            pos = None
            # find shares from risk engine open_positions (already popped by auto_cashout)
            shares = proceeds / max(best_bid, 1e-9)
            self._send_live_clob_order(
                asset_id=asset_id,
                side="SELL",
                price=best_bid,
                size=shares,
                order_type="FOK",
            )
        return proceeds

    def cancel_all(self) -> bool:
        if self.config.dry_run or not self.live_confirmed or self.client is None:
            return True
        try:
            self.client.cancel_all()
            return True
        except Exception:
            return False