"""Stage 3: Risk engine with 3-bucket capital accounting + early auto-cashout."""
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class CapitalBuckets:
    liquid_usdc: float = 10.0
    in_play_usdc: float = 0.0
    settling_usdc: float = 0.0

    @property
    def total(self) -> float:
        return self.liquid_usdc + self.in_play_usdc + self.settling_usdc

    def can_deploy(self, amount: float) -> bool:
        return self.liquid_usdc >= amount

    def deploy(self, amount: float) -> bool:
        if not self.can_deploy(amount):
            return False
        self.liquid_usdc -= amount
        self.in_play_usdc += amount
        return True

    def settle_win(self, payout: float, cost: float) -> None:
        self.in_play_usdc = max(0.0, self.in_play_usdc - cost)
        self.settling_usdc += payout

    def settle_loss(self, cost: float) -> None:
        self.in_play_usdc = max(0.0, self.in_play_usdc - cost)

    def redeem(self, amount: float) -> None:
        amt = min(amount, self.settling_usdc)
        self.settling_usdc -= amt
        self.liquid_usdc += amt

    def auto_cashout(self, bid_price: float, shares: float, threshold: float = 0.93) -> float:
        if bid_price < threshold:
            return 0.0
        proceeds = shares * bid_price
        self.in_play_usdc = max(0.0, self.in_play_usdc - shares * bid_price)
        self.liquid_usdc += proceeds
        return proceeds


@dataclass
class RiskEngine:
    buckets: CapitalBuckets = field(default_factory=CapitalBuckets)
    max_concurrent_windows: int = 1
    max_usdc_per_trade: float = 3.10
    max_total_exposure: float = 5.50
    auto_cashout_threshold: float = 0.93
    kill_switch_balance: float = 6.00
    open_positions: Dict[str, dict] = field(default_factory=dict)

    def can_open(self, window_ts: int, cost: float) -> bool:
        if len(self.open_positions) >= self.max_concurrent_windows:
            # allow a second window only if total exposure permits
            if len(self.open_positions) >= 2:
                return False
        if self.buckets.total < self.kill_switch_balance:
            return False
        if cost > self.max_usdc_per_trade:
            return False
        if self.buckets.in_play_usdc + cost > self.max_total_exposure:
            return False
        if not self.buckets.can_deploy(cost):
            return False
        return True

    def open_position(self, window_ts: int, side: str, shares: float, cost: float, token_id: str) -> bool:
        if not self.can_open(window_ts, cost):
            return False
        if not self.buckets.deploy(cost):
            return False
        self.open_positions[str(window_ts)] = {
            "side": side, "shares": shares, "cost": cost, "token_id": token_id
        }
        return True

    def try_auto_cashout(self, window_ts: int, best_bid: float) -> float:
        pos = self.open_positions.get(str(window_ts))
        if not pos:
            return 0.0
        if best_bid < self.auto_cashout_threshold:
            return 0.0
        proceeds = self.buckets.auto_cashout(best_bid, pos["shares"], self.auto_cashout_threshold)
        if proceeds > 0:
            del self.open_positions[str(window_ts)]
        return proceeds

    def resolve_window(self, window_ts: int, outcome_up_won: int) -> float:
        pos = self.open_positions.pop(str(window_ts), None)
        if not pos:
            return 0.0
        won = (pos["side"] == "UP" and outcome_up_won == 1) or (pos["side"] == "DOWN" and outcome_up_won == 0)
        if won:
            self.buckets.settle_win(pos["shares"] * 1.0, pos["cost"])
            self.buckets.redeem(pos["shares"] * 1.0)
            return pos["shares"] * 1.0 - pos["cost"]
        else:
            self.buckets.settle_loss(pos["cost"])
            return -pos["cost"]