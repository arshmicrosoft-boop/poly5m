"""Dry-run execution engine wrapping simulated execution with paper orders."""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional

from .sim_exec import SimulatedExecutionEngine, SimulatedFill


@dataclass
class PaperOrder:
    window_ts: int
    side: str  # "UP" or "DOWN"
    price: float
    size: float
    fee: float = 0.0
    fills: List[SimulatedFill] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(f.price * f.size + f.fee for f in self.fills) if self.fills else self.price * self.size + self.fee


class DryRunExecutionEngine:
    """Paper-trading engine that records orders without hitting live markets."""

    def __init__(self, engine: Optional[SimulatedExecutionEngine] = None):
        self.engine = engine or SimulatedExecutionEngine()
        self.orders: List[PaperOrder] = []

    def submit(self, window_ts: int, side: str, book: List[Tuple[float, float]],
               size: float) -> PaperOrder:
        fills = self.engine.execute_taker_buy(book, size)
        order = PaperOrder(window_ts=window_ts, side=side,
                           price=fills[0].price if fills else 0.0,
                           size=sum(f.size for f in fills) if fills else size,
                           fee=sum(f.fee for f in fills),
                           fills=fills)
        self.orders.append(order)
        return order

    def inspect_live_window(self, current_window: int) -> int:
        """Return next window timestamp (prefetch current+300)."""
        return current_window + 300
