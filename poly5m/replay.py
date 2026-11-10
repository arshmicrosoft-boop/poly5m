from dataclasses import dataclass
from typing import List
from .config import BotConfig
from .data import HistoricalWindow
from .sim_exec import SimulatedExecutionEngine
from .strategy import StrategyEngine


@dataclass
class TradeRecord:
    window_ts: int
    quarter_label: str
    volatility_regime: str
    side: str
    shares: float
    best_ask_price: float
    avg_fill_price: float
    slippage_usdc: float
    fee_usdc: float
    total_cost_usdc: float
    predicted_prob: float
    won: int
    payout_usdc: float
    gross_pnl_usdc: float
    net_pnl_usdc: float
    bankroll_after: float


@dataclass
class ReplayResult:
    trades: List[TradeRecord]
    total_windows: int
    total_signals_attempted: int
    total_fills: int
    starting_bankroll: float
    ending_bankroll: float
    equity_curve: List[float]


class BacktestReplayEngine:
    def __init__(self, config: BotConfig):
        self.config = config
        self.strategy = StrategyEngine(config.risk, config.physics)
        self.exec_engine = SimulatedExecutionEngine(config.physics)

    def run(self, windows: List[HistoricalWindow], compound_sizing: bool = False, drift_weight: float = 0.085) -> ReplayResult:
        bankroll = self.config.risk.starting_bankroll
        equity_curve = [bankroll]
        trades: List[TradeRecord] = []
        signals_attempted = 0
        consecutive_losses = 0
        cooldown_remaining = 0

        for window in windows:
            if cooldown_remaining > 0:
                cooldown_remaining -= 1
                continue

            if not compound_sizing:
                if bankroll < self.config.risk.max_usdc_per_trade:
                    continue

            effective_cash = bankroll if compound_sizing else max(self.config.risk.max_usdc_per_trade, bankroll)

            window_traded = False
            for snap in window.snapshots:
                if window_traded:
                    break

                signal = self.strategy.evaluate_snapshot(
                    snap, available_bankroll=effective_cash, drift_weight=drift_weight
                )
                if signal is None:
                    continue

                signals_attempted += 1
                asks = snap.up_asks if signal.side == "UP" else snap.down_asks
                fill = self.exec_engine.execute_taker_buy(
                    side=signal.side,
                    desired_shares=signal.shares,
                    limit_max_price=signal.limit_price,
                    asks=asks,
                    accepting_orders=snap.accepting_orders,
                )

                if not fill.filled:
                    continue

                window_traded = True
                won = (
                    1
                    if (
                        (fill.side == "UP" and window.outcome_up_won == 1)
                        or (fill.side == "DOWN" and window.outcome_up_won == 0)
                    )
                    else 0
                )
                payout = fill.filled_shares * 1.00 if won else 0.0
                gross_pnl = payout - (fill.filled_shares * fill.best_ask_price)
                net_pnl = payout - fill.total_cost_usdc
                bankroll += net_pnl
                equity_curve.append(bankroll)

                if won:
                    consecutive_losses = 0
                else:
                    consecutive_losses += 1
                    if consecutive_losses >= self.config.risk.max_consecutive_losses:
                        cooldown_remaining = self.config.risk.cooldown_windows_after_streak
                        consecutive_losses = 0

                trades.append(
                    TradeRecord(
                        window_ts=window.window_ts,
                        quarter_label=window.quarter_label,
                        volatility_regime=window.volatility_regime,
                        side=fill.side,
                        shares=fill.filled_shares,
                        best_ask_price=fill.best_ask_price,
                        avg_fill_price=fill.avg_fill_price,
                        slippage_usdc=fill.slippage_per_share * fill.filled_shares,
                        fee_usdc=fill.fee_usdc,
                        total_cost_usdc=fill.total_cost_usdc,
                        predicted_prob=signal.predicted_prob,
                        won=won,
                        payout_usdc=payout,
                        gross_pnl_usdc=gross_pnl,
                        net_pnl_usdc=net_pnl,
                        bankroll_after=bankroll,
                    )
                )

        return ReplayResult(
            trades=trades,
            total_windows=len(windows),
            total_signals_attempted=signals_attempted,
            total_fills=len(trades),
            starting_bankroll=self.config.risk.starting_bankroll,
            ending_bankroll=bankroll,
            equity_curve=equity_curve,
        )