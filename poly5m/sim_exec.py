from dataclasses import dataclass
from typing import List, Optional
import numpy as np
from .config import ExecutionPhysicsConfig
from .data import OrderBookLevel


@dataclass
class SimulatedFill:
    filled: bool
    side: str
    requested_shares: float
    filled_shares: float
    best_ask_price: float
    avg_fill_price: float
    slippage_per_share: float
    gross_cost_usdc: float
    fee_usdc: float
    total_cost_usdc: float
    reject_reason: Optional[str] = None


def calculate_crypto_fee(price: float, shares: float = 1.0, fee_coeff: float = 0.07, min_fee_usdc: float = 0.00001) -> float:
    if shares <= 0:
        return 0.0
    p = max(0.001, min(0.999, price))
    raw = shares * fee_coeff * p * (1.0 - p)
    return max(min_fee_usdc, raw)


class SimulatedExecutionEngine:
    def __init__(self, physics: ExecutionPhysicsConfig, seed: int = 101):
        self.physics = physics
        self.rng = np.random.default_rng(seed)

    def calculate_crypto_fee(self, shares: float, price: float) -> float:
        if shares <= 0:
            return 0.0
        p = max(0.001, min(0.999, price))
        raw_fee = shares * self.physics.fee_coeff * p * (1.0 - p)
        return max(self.physics.min_fee_usdc, raw_fee)

    def execute_taker_buy(self, side: str, desired_shares: float, limit_max_price: float, asks: List[OrderBookLevel], accepting_orders: bool) -> SimulatedFill:
        if not accepting_orders:
            return SimulatedFill(False, side, desired_shares, 0, 0, 0, 0, 0, 0, 0, "NOT_ACCEPTING_ORDERS")

        if desired_shares < self.physics.min_order_size_shares:
            return SimulatedFill(False, side, desired_shares, 0, 0, 0, 0, 0, 0, 0, "BELOW_MIN_SIZE_5_SHARES")

        if not asks:
            return SimulatedFill(False, side, desired_shares, 0, 0, 0, 0, 0, 0, 0, "EMPTY_BOOK")

        if self.physics.fill_probability < 1.0:
            if self.rng.random() > self.physics.fill_probability:
                return SimulatedFill(False, side, desired_shares, 0, 0, 0, 0, 0, 0, 0, "FILL_PROB_REJECTED")

        best_ask = asks[0].price

        remaining = desired_shares
        cost_accum = 0.0
        filled_accum = 0.0

        for level in asks:
            if level.price > limit_max_price:
                break
            available_at_level = level.size * self.physics.depth_haircut
            take = min(remaining, available_at_level)
            if take > 0:
                cost_accum += take * level.price
                filled_accum += take
                remaining -= take
            if remaining <= 1e-9:
                break

        if filled_accum < self.physics.min_order_size_shares:
            return SimulatedFill(False, side, desired_shares, 0, best_ask, 0, 0, 0, 0, 0, "INSUFFICIENT_LIQUIDITY")

        raw_avg_price = cost_accum / filled_accum
        book_walk_slip = max(0.0, raw_avg_price - best_ask)

        latency_slip = max(0.001, (self.physics.simulated_latency_ms / 1000.0) * 0.0045)
        total_slippage = (book_walk_slip + latency_slip) * self.physics.slippage_multiplier

        effective_price = round((best_ask + total_slippage) / self.physics.tick_size) * self.physics.tick_size
        effective_price = min(0.999, effective_price)

        if effective_price > limit_max_price:
            return SimulatedFill(False, side, desired_shares, 0, best_ask, 0, 0, 0, 0, 0, "SLIPPAGE_EXCEEDED_LIMIT")

        gross_cost = filled_accum * effective_price
        fee_usdc = self.calculate_crypto_fee(filled_accum, effective_price)
        total_cost = gross_cost + fee_usdc

        return SimulatedFill(
            filled=True,
            side=side,
            requested_shares=desired_shares,
            filled_shares=filled_accum,
            best_ask_price=best_ask,
            avg_fill_price=effective_price,
            slippage_per_share=effective_price - best_ask,
            gross_cost_usdc=gross_cost,
            fee_usdc=fee_usdc,
            total_cost_usdc=total_cost,
        )