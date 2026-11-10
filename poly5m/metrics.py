import math
from dataclasses import dataclass, replace
from typing import List, Dict
import numpy as np
from .config import BotConfig
from .data import HistoricalWindow
from .replay import ReplayResult, TradeRecord, BacktestReplayEngine


@dataclass
class BacktestMetricsSummary:
    total_windows: int
    total_trades: int
    fill_rate_pct: float
    trades_per_day: float
    trades_per_year: float
    win_rate_pct: float
    avg_predicted_prob_pct: float
    realized_edge_pct: float
    gross_pnl_usdc: float
    total_fees_usdc: float
    total_slippage_usdc: float
    net_pnl_usdc: float
    z_score: float
    sharpe_annualized: float
    max_losing_streak: int
    max_drawdown_usdc: float
    max_drawdown_pct: float
    quarters_profitable_str: str
    quarterly_pnl: Dict[str, float]
    walk_forward_decay_pct: float
    profitable_at_058: bool
    cohort_058_trades: int
    cohort_058_win_rate_pct: float
    cohort_058_net_pnl_usdc: float


def compute_metrics(result: ReplayResult, walk_forward_decay_pct: float = 0.0) -> BacktestMetricsSummary:
    trades = result.trades
    n_trades = len(trades)
    days = max(1.0, result.total_windows / 288.0)

    if n_trades == 0:
        return BacktestMetricsSummary(
            result.total_windows, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, "0/0", {}, walk_forward_decay_pct, False, 0, 0.0, 0.0
        )

    wins = sum(t.won for t in trades)
    win_rate = wins / n_trades
    avg_pred_prob = float(np.mean([t.predicted_prob for t in trades]))
    avg_all_in_price = float(np.mean([t.total_cost_usdc / t.shares for t in trades]))
    realized_edge = win_rate - avg_all_in_price

    gross_pnl = sum(t.gross_pnl_usdc for t in trades)
    total_fees = sum(t.fee_usdc for t in trades)
    total_slip = sum(t.slippage_usdc for t in trades)
    net_pnl = sum(t.net_pnl_usdc for t in trades)

    pnl_array = np.array([t.net_pnl_usdc for t in trades])
    pnl_std = float(np.std(pnl_array, ddof=1)) if n_trades > 1 else 1.0
    z_score = float(np.mean(pnl_array) / (pnl_std / math.sqrt(n_trades))) if pnl_std > 1e-9 else 0.0

    trades_per_day = n_trades / days
    trades_per_year = trades_per_day * 365.0
    sharpe_annual = (float(np.mean(pnl_array)) / (pnl_std + 1e-9)) * math.sqrt(trades_per_year)

    max_streak = 0
    curr_streak = 0
    for t in trades:
        if t.won == 0:
            curr_streak += 1
            max_streak = max(max_streak, curr_streak)
        else:
            curr_streak = 0

    eq = np.array(result.equity_curve)
    peaks = np.maximum.accumulate(eq)
    drawdowns = peaks - eq
    max_dd_usdc = float(np.max(drawdowns))
    max_dd_pct = float(np.max(drawdowns / np.maximum(peaks, 1e-9))) * 100.0

    q_pnl: Dict[str, float] = {}
    for t in trades:
        q_pnl[t.quarter_label] = q_pnl.get(t.quarter_label, 0.0) + t.net_pnl_usdc
    q_prof = sum(1 for v in q_pnl.values() if v > 0)
    q_str = f"{q_prof}/{len(q_pnl)} ({(q_prof / max(1, len(q_pnl))) * 100:.0f}%)"

    cohort_058 = [t for t in trades if t.best_ask_price >= 0.575]
    c058_count = len(cohort_058)
    c058_wr = (sum(t.won for t in cohort_058) / c058_count * 100.0) if c058_count > 0 else 0.0
    c058_pnl = sum(t.net_pnl_usdc for t in cohort_058)
    prof_058 = (c058_count > 0) and (c058_pnl > 0.0)

    fill_rate = (result.total_fills / max(1, result.total_signals_attempted)) * 100.0

    return BacktestMetricsSummary(
        total_windows=result.total_windows,
        total_trades=n_trades,
        fill_rate_pct=fill_rate,
        trades_per_day=trades_per_day,
        trades_per_year=trades_per_year,
        win_rate_pct=win_rate * 100.0,
        avg_predicted_prob_pct=avg_pred_prob * 100.0,
        realized_edge_pct=realized_edge * 100.0,
        gross_pnl_usdc=gross_pnl,
        total_fees_usdc=total_fees,
        total_slippage_usdc=total_slip,
        net_pnl_usdc=net_pnl,
        z_score=z_score,
        sharpe_annualized=sharpe_annual,
        max_losing_streak=max_streak,
        max_drawdown_usdc=max_dd_usdc,
        max_drawdown_pct=max_dd_pct,
        quarters_profitable_str=q_str,
        quarterly_pnl=q_pnl,
        walk_forward_decay_pct=walk_forward_decay_pct,
        profitable_at_058=prof_058,
        cohort_058_trades=c058_count,
        cohort_058_win_rate_pct=c058_wr,
        cohort_058_net_pnl_usdc=c058_pnl,
    )


def run_walk_forward_analysis(windows: List[HistoricalWindow], config: BotConfig, folds: int = 4) -> float:
    fold_size = len(windows) // (folds + 1)
    if fold_size < 100:
        return 0.0

    is_edges = []
    oos_edges = []
    engine = BacktestReplayEngine(config)

    for k in range(folds):
        train_slice = windows[k * fold_size : (k + 1) * fold_size]
        test_slice = windows[(k + 1) * fold_size : (k + 2) * fold_size]

        best_w = 0.085
        best_train_pnl = -1e9
        for candidate_w in (0.065, 0.085, 0.105):
            res_tr = engine.run(train_slice, drift_weight=candidate_w)
            pnl_tr = sum(t.net_pnl_usdc for t in res_tr.trades)
            if pnl_tr > best_train_pnl:
                best_train_pnl = pnl_tr
                best_w = candidate_w

        res_is = engine.run(train_slice, drift_weight=best_w)
        res_oos = engine.run(test_slice, drift_weight=best_w)

        if res_is.trades and res_oos.trades:
            is_edges.append(np.mean([t.net_pnl_usdc for t in res_is.trades]))
            oos_edges.append(np.mean([t.net_pnl_usdc for t in res_oos.trades]))

    if not is_edges or np.mean(is_edges) <= 0:
        return 0.0

    decay_pct = (1.0 - (float(np.mean(oos_edges)) / float(np.mean(is_edges)))) * 100.0
    return max(0.0, decay_pct)


def run_stress_test_suite(windows: List[HistoricalWindow], base_config: BotConfig) -> Dict[str, Dict]:
    results = {}

    scenarios = {
        "1. Fee x1.5 (0.105 coeff)": replace(
            base_config, physics=replace(base_config.physics, fee_coeff=base_config.physics.fee_coeff * 1.5)
        ),
        "2. Slippage x2.0": replace(
            base_config, physics=replace(base_config.physics, slippage_multiplier=2.0)
        ),
        "3. Latency +500ms (650ms)": replace(
            base_config, physics=replace(base_config.physics, simulated_latency_ms=650)
        ),
        "4. Fill Rate -20% & Haircut": replace(
            base_config, physics=replace(base_config.physics, fill_probability=0.80, depth_haircut=0.35)
        ),
    }

    for name, cfg in scenarios.items():
        res = BacktestReplayEngine(cfg).run(windows)
        m = compute_metrics(res)
        passed = (m.net_pnl_usdc > 0.0) and (m.z_score >= 1.96)
        results[name] = {
            "passed": passed,
            "net_pnl": m.net_pnl_usdc,
            "win_rate": m.win_rate_pct,
            "z_score": m.z_score,
            "fees": m.total_fees_usdc,
        }

    high_vol_w = [w for w in windows if w.volatility_regime == "HIGH_VOL"]
    low_vol_w = [w for w in windows if w.volatility_regime == "LOW_VOL"]
    res_hv = BacktestReplayEngine(base_config).run(high_vol_w)
    res_lv = BacktestReplayEngine(base_config).run(low_vol_w)
    m_hv = compute_metrics(res_hv)
    m_lv = compute_metrics(res_lv)
    regime_passed = (m_hv.net_pnl_usdc > 0.0) and (m_lv.net_pnl_usdc > 0.0)
    results["5. Regime Shift (HV & LV)"] = {
        "passed": regime_passed,
        "net_pnl": m_hv.net_pnl_usdc + m_lv.net_pnl_usdc,
        "win_rate": (m_hv.win_rate_pct + m_lv.win_rate_pct) / 2.0,
        "z_score": min(m_hv.z_score, m_lv.z_score),
        "detail": f"HV PnL=${m_hv.net_pnl_usdc:+.2f} | LV PnL=${m_lv.net_pnl_usdc:+.2f}",
    }

    return results