import math
from dataclasses import dataclass
from typing import Optional
from .config import RiskConfig, ExecutionPhysicsConfig
from .data import MarketSnapshot


@dataclass
class TradeSignal:
    side: str
    token_id: str
    shares: float
    limit_price: float
    best_ask: float
    predicted_prob: float
    expected_fee_per_share: float
    net_ev_edge: float


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


class StrategyEngine:
    def __init__(self, risk: RiskConfig, physics: ExecutionPhysicsConfig, limit_price_buffer: float = 0.02, est_slippage: float = 0.003):
        self.risk = risk
        self.physics = physics
        self.limit_price_buffer = limit_price_buffer
        self.est_slippage = est_slippage

    def estimate_true_up_probability(self, snap: MarketSnapshot, drift_weight: float = 0.085) -> float:
        # Gate: restrict to late window or strong displacement
        z_base_check = math.log(snap.spot_price / snap.start_twap_60s) / (snap.realized_vol_1s * math.sqrt(max(5.0, snap.remaining_sec)) + 1e-9)
        if snap.elapsed_sec < 115:
            if not (abs(z_base_check) >= 0.30 and abs(snap.order_flow_imbalance) >= 0.30):
                return 0.5
        tau_eff = max(5.0, snap.remaining_sec - 42.0)
        sigma_tau = snap.realized_vol_1s * math.sqrt(tau_eff)
        eff_spot = 0.75 * snap.spot_price + 0.25 * snap.current_twap_60s
        z_base = math.log(eff_spot / snap.start_twap_60s) / (sigma_tau + 1e-9)
        if abs(z_base) < 0.15:
            return 0.5
        accel = math.log(snap.spot_price / snap.current_twap_60s) / (snap.realized_vol_1s * math.sqrt(60.0) + 1e-9)
        # obi from bids/asks
        obi = 0.0
        if snap.up_bids and snap.up_asks:
            pass
        # use order_flow as proxy if no book
        obi = snap.order_flow_imbalance
        z = 1.15 * z_base + 0.35 * accel + 0.25 * snap.order_flow_imbalance + 0.15 * obi
        # scale accel+order_flow by drift_weight
        z = z_base + (drift_weight / 0.085) * (0.35 * accel + 0.25 * snap.order_flow_imbalance + 0.15 * obi)
        # re-add base scaling
        z = 1.15 * z_base + (drift_weight / 0.085) * (0.35 * accel + 0.25 * snap.order_flow_imbalance + 0.15 * obi)
        prob_up = _norm_cdf(z)
        return float(max(0.01, min(0.99, prob_up)))

    def evaluate_snapshot(self, snap: MarketSnapshot, available_bankroll: float, drift_weight: float = 0.085) -> Optional[TradeSignal]:
        if not snap.accepting_orders:
            return None
        if snap.elapsed_sec < self.risk.min_entry_elapsed_sec:
            return None
        if snap.elapsed_sec > self.risk.max_entry_elapsed_sec:
            return None

        p_up = self.estimate_true_up_probability(snap, drift_weight=drift_weight)
        p_down = 1.0 - p_up

        candidates = [
            ("UP", snap.up_token_id, p_up, snap.up_bids, snap.up_asks),
            ("DOWN", snap.down_token_id, p_down, snap.down_bids, snap.down_asks),
        ]

        best_signal: Optional[TradeSignal] = None

        for side, token_id, model_prob, bids, asks in candidates:
            if not bids or not asks:
                continue

            best_bid = bids[0].price
            best_ask = asks[0].price
            spread = best_ask - best_bid

            if spread > self.risk.max_book_spread:
                continue
            if best_ask < self.risk.min_token_price or best_ask > self.risk.max_token_price:
                continue

            fee_per_share = self.physics.fee_coeff * best_ask * (1.0 - best_ask)
            all_in_entry_cost = best_ask + fee_per_share + self.est_slippage

            net_ev_edge = model_prob - all_in_entry_cost
            if net_ev_edge < self.risk.min_ev_edge:
                continue

            shares = self.risk.base_shares_per_trade
            est_total_usdc = shares * all_in_entry_cost
            if est_total_usdc > self.risk.max_usdc_per_trade or est_total_usdc > available_bankroll:
                continue

            max_limit_price = round(min(self.risk.max_token_price, model_prob - fee_per_share - self.limit_price_buffer), 3)
            if max_limit_price < best_ask:
                continue

            signal = TradeSignal(
                side=side,
                token_id=token_id,
                shares=shares,
                limit_price=max_limit_price,
                best_ask=best_ask,
                predicted_prob=model_prob,
                expected_fee_per_share=fee_per_share,
                net_ev_edge=net_ev_edge,
            )

            if best_signal is None or signal.net_ev_edge > best_signal.net_ev_edge:
                best_signal = signal

        return best_signal