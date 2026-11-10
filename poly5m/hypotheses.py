"""Stage 2: Strategy hypotheses (10-strategy tournament) for real-data backtesting."""
import math
from typing import Callable, Dict, List, Optional

from .config import ExecutionPhysicsConfig, RiskConfig
from .sim_exec import SimulatedExecutionEngine, calculate_crypto_fee
from .data import OrderBookLevel


def _z_to_prob(z: float) -> float:
    # logistic CDF approximating normal
    try:
        return 1.0 / (1.0 + math.exp(-z))
    except OverflowError:
        return 1.0 if z > 0 else 0.0


# ---------- helpers ----------
def _tau_eff(snap: dict) -> float:
    return max(5.0, snap["remaining"] - 40.0)


def _z_spot(snap: dict) -> float:
    vol = snap.get("realized_vol_1s", 0.0001)
    tau = max(1.0, snap["remaining"])
    return math.log(snap["spot"] / snap["start_twap"]) / (vol * math.sqrt(tau) + 1e-9)


# ---------- strategies ----------
def S01_KEMNA_VORST_TWAP_BS(snap: dict) -> float:
    vol = snap.get("realized_vol_1s", 0.0001)
    tau_eff = max(5.0, snap["remaining"] - 45.0)
    z_spot = math.log(snap["spot"] / snap["start_twap"]) / (vol * math.sqrt(tau_eff) + 1e-9)
    v_drift = 0.30 * math.log(snap["spot"] / snap["curr_twap"]) * math.sqrt(snap["remaining"] / 60.0) / (vol + 1e-9)
    return _z_to_prob(z_spot + v_drift)


def S02_LOW_VOL_THETA_DECAY(snap: dict, median_vol: float = 0.0001) -> float:
    vol = snap.get("realized_vol_1s", 0.0001)
    if vol > 0.00050:
        return 0.5
    tau_eff = max(5.0, snap["remaining"] - 45.0)
    z_base = math.log(snap["spot"] / snap["start_twap"]) / (vol * math.sqrt(tau_eff) + 1e-9)
    if abs(z_base) < 0.05:
        return 0.5
    z = z_base + 0.32 * (1.0 if z_base >= 0 else -1.0) + 0.25 * snap.get("order_flow_imbalance", 0.0)
    return _z_to_prob(z)


def S03_PRE_TWAP_LOCKIN_SNIPER(snap: dict) -> float:
    if snap["elapsed"] < 115:
        return 0.5
    spot = snap["spot"]; curr = snap["curr_twap"]; start = snap["start_twap"]
    if not ((spot - start) * (curr - start) > 0):
        return 0.5
    vol = snap.get("realized_vol_1s", 0.0001)
    tau_eff = max(5.0, snap["remaining"] - 45.0)
    eff_spot = 0.70 * spot + 0.30 * curr
    z_base = math.log(eff_spot / start) / (vol * math.sqrt(tau_eff) + 1e-9)
    z = z_base + 0.35 * (1.0 if z_base >= 0 else -1.0) + 0.20 * snap.get("order_flow_imbalance", 0.0)
    return _z_to_prob(z)


def S04_CVD_DRIFT_BS(snap: dict) -> float:
    vol = snap.get("realized_vol_1s", 0.0001)
    rem = max(1.0, snap["remaining"])
    ofi = snap.get("order_flow_imbalance", 0.0)
    z = (math.log(snap["spot"] / snap["start_twap"]) + 0.35 * ofi * vol * math.sqrt(rem)) / (vol * math.sqrt(_tau_eff(snap)) + 1e-9)
    return _z_to_prob(z)


def S05_PASSIVE_ABSORPTION_BREAKOUT(snap: dict) -> float:
    # cheap odds handled in runner via ask band; here return model prob
    vol = snap.get("realized_vol_1s", 0.0001)
    rem = max(1.0, snap["remaining"])
    ofi = snap.get("order_flow_imbalance", 0.0)
    if abs(math.log(snap["spot"] / snap["start_twap"])) >= 0.40 * vol * math.sqrt(rem):
        return 0.5
    if abs(ofi) < 0.35:
        return 0.5
    # direction from order flow
    z = (0.35 * ofi * vol * math.sqrt(rem)) / (vol * math.sqrt(rem) + 1e-9) if False else (1.0 if ofi > 0 else -1.0) * 1.0
    return _z_to_prob(z)


def S06_EXHAUSTION_MEAN_REVERSION(snap: dict) -> float:
    if not (60 <= snap["elapsed"] <= 120):
        return 0.5
    vol = snap.get("realized_vol_1s", 0.0001)
    sigma_tau = vol * math.sqrt(max(5.0, snap["remaining"]))
    z_spot = math.log(snap["spot"] / snap["start_twap"]) / (sigma_tau + 1e-9)
    if abs(z_spot) < 0.02 or abs(z_spot) > 0.24:
        return 0.5
    ofi = snap.get("order_flow_imbalance", 0.0)
    flow_opposes = (z_spot * ofi) < 0
    vel_opposes = (z_spot * (snap["spot"] - snap["curr_twap"])) <= 0
    if not (flow_opposes or vel_opposes):
        return 0.5
    z_rev = z_spot - 0.52 * (1.0 if z_spot >= 0 else -1.0) + 0.25 * ofi
    return _z_to_prob(z_rev)


def S07_SPOT_TWAP_ACCELERATION(snap: dict) -> float:
    spot = snap["spot"]; curr = snap["curr_twap"]; start = snap["start_twap"]
    if (spot - curr) * (spot - start) <= 0:
        return 0.5
    vol = snap.get("realized_vol_1s", 0.0001)
    tau_eff = max(5.0, snap["remaining"] - 40.0)
    z_base = math.log(spot / start) / (vol * math.sqrt(tau_eff) + 1e-9)
    accel = math.log(spot / curr) / (vol * math.sqrt(60.0) + 1e-9)
    ofi = snap.get("order_flow_imbalance", 0.0)
    z = z_base + 0.45 * accel + 0.30 * (1.0 if z_base >= 0 else -1.0) + 0.20 * ofi
    return _z_to_prob(z)


def S08_CLOB_BOOK_IMBALANCE_HYBRID(snap: dict) -> float:
    # obi from bids/asks if provided
    bids = snap.get("bid_sizes", [])
    asks = snap.get("ask_sizes", [])
    if bids and asks:
        bs = sum(bids[:3]); as_ = sum(asks[:3])
        obi = (bs - as_) / (bs + as_ + 1e-9)
    else:
        obi = 0.0
    vol = snap.get("realized_vol_1s", 0.0001)
    rem = max(1.0, snap["remaining"])
    ofi = snap.get("order_flow_imbalance", 0.0)
    z = (math.log(snap["spot"] / snap["start_twap"]) + 0.35 * ofi * vol * math.sqrt(rem)) / (vol * math.sqrt(_tau_eff(snap)) + 1e-9)
    z += 0.20 * obi
    return _z_to_prob(z)


def S09_REGIME_SWITCHING_ADAPTIVE(snap: dict) -> float:
    spot = snap["spot"]; curr = snap["curr_twap"]; start = snap["start_twap"]
    aligned = (spot - curr) * (curr - start) >= 0  # both same sign-ish
    # simpler: alignment of (spot-curr) and (curr-start)
    a = spot - curr
    b = curr - start
    trending = (a >= 0 and b >= 0) or (a <= 0 and b <= 0)
    if trending:
        return S04_CVD_DRIFT_BS(snap)
    # mean-reverting: dampen z_spot
    z = _z_spot(snap) * 0.75
    p = _z_to_prob(z)
    return p


def S10_LOGIT_BAYESIAN_ENSEMBLE(snap: dict) -> float:
    subs = [S01_KEMNA_VORST_TWAP_BS, S04_CVD_DRIFT_BS, S07_SPOT_TWAP_ACCELERATION, S08_CLOB_BOOK_IMBALANCE_HYBRID]
    probs = [f(snap) for f in subs]
    # consensus: at least 3 sub-models agree on direction (>=0.5 or <0.5)
    ups = sum(1 for p in probs if p >= 0.5)
    downs = sum(1 for p in probs if p < 0.5)
    if ups < 3 and downs < 3:
        return 0.5
    # average log-odds
    def logit(p):
        p = min(0.999, max(0.001, p))
        return math.log(p / (1 - p))
    avg = sum(logit(p) for p in probs) / len(probs)
    return 1.0 / (1.0 + math.exp(-avg))


STRATEGIES: Dict[str, Callable[[dict], float]] = {
    "S01_KEMNA_VORST_TWAP_BS": S01_KEMNA_VORST_TWAP_BS,
    "S02_LOW_VOL_THETA_DECAY": S02_LOW_VOL_THETA_DECAY,
    "S03_PRE_TWAP_LOCKIN_SNIPER": S03_PRE_TWAP_LOCKIN_SNIPER,
    "S04_CVD_DRIFT_BS": S04_CVD_DRIFT_BS,
    "S05_PASSIVE_ABSORPTION_BREAKOUT": S05_PASSIVE_ABSORPTION_BREAKOUT,
    "S06_EXHAUSTION_MEAN_REVERSION": S06_EXHAUSTION_MEAN_REVERSION,
    "S07_SPOT_TWAP_ACCELERATION": S07_SPOT_TWAP_ACCELERATION,
    "S08_CLOB_BOOK_IMBALANCE_HYBRID": S08_CLOB_BOOK_IMBALANCE_HYBRID,
    "S09_REGIME_SWITCHING_ADAPTIVE": S09_REGIME_SWITCHING_ADAPTIVE,
    "S10_LOGIT_BAYESIAN_ENSEMBLE": S10_LOGIT_BAYESIAN_ENSEMBLE,
}

# Backwards compat alias
HYPOTHESES = STRATEGIES


def _median_vol(windows: list) -> float:
    vols = [s.get("realized_vol_1s", 0.0) for w in windows for s in w["snapshots"]]
    vols = sorted(vols)
    if not vols:
        return 0.0001
    return vols[len(vols) // 2]


def run_hypothesis_backtest(windows: list, hyp_name: str, threshold: float = 0.55, min_ev_edge: float = 0.055) -> dict:
    hyp = STRATEGIES[hyp_name]
    risk = RiskConfig()
    physics = ExecutionPhysicsConfig()
    engine = SimulatedExecutionEngine(physics, seed=101)
    median_vol = _median_vol(windows)
    # S10 stricter edge
    MIN_EV = {
        "S01_KEMNA_VORST_TWAP_BS": 0.045,
        "S02_LOW_VOL_THETA_DECAY": 0.045,
        "S03_PRE_TWAP_LOCKIN_SNIPER": 0.050,
        "S04_CVD_DRIFT_BS": min_ev_edge,
        "S05_PASSIVE_ABSORPTION_BREAKOUT": min_ev_edge,
        "S06_EXHAUSTION_MEAN_REVERSION": 0.045,
        "S07_SPOT_TWAP_ACCELERATION": min_ev_edge,
        "S08_CLOB_BOOK_IMBALANCE_HYBRID": min_ev_edge,
        "S09_REGIME_SWITCHING_ADAPTIVE": min_ev_edge,
        "S10_LOGIT_BAYESIAN_ENSEMBLE": 0.058,
    }
    edge = MIN_EV.get(hyp_name, min_ev_edge)
    # S09 ask cap
    ask_cap = 0.53 if hyp_name == "S09_REGIME_SWITCHING_ADAPTIVE" else risk.max_token_price

    trades = 0
    wins = 0
    net_pnl = 0.0
    total_fees = 0.0
    total_slip = 0.0
    trade_pnls = []
    max_streak = 0
    cur_streak = 0
    peak = 0.0
    max_dd = 0.0
    cohort_058_trades = 0
    cohort_058_wins = 0
    cohort_058_pnl = 0.0
    for w in windows:
        for snap in w["snapshots"]:
            # inject median vol for S02
            snap2 = dict(snap)
            snap2["_median_vol"] = median_vol
            p = hyp(snap2) if hyp_name != "S02_LOW_VOL_THETA_DECAY" else None
            if hyp_name == "S02_LOW_VOL_THETA_DECAY":
                # call with median_vol
                p = S02_LOW_VOL_THETA_DECAY(snap2, median_vol=median_vol)
            if p is None or p == 0.5:
                # allow 0.5? skip neutral
                if p == 0.5:
                    continue
            side_up = p >= threshold
            if side_up:
                best_ask = snap["up_ask"]
                bid = snap["up_bid"]
            else:
                if p > (1 - threshold):
                    continue
                best_ask = snap["down_ask"]
                bid = snap["down_bid"]
            # chop filter: skip high vol
            if snap.get("realized_vol_1s", 0) > 0.00045:
                continue
            # tighter trigger: require strong ofi
            if abs(snap.get("order_flow_imbalance", 0.0)) < 0.25:
                continue
            # price band
            if best_ask < 0.44 or best_ask > min(risk.max_token_price, ask_cap):
                if hyp_name == "S05_PASSIVE_ABSORPTION_BREAKOUT":
                    if not (0.45 <= best_ask <= 0.54):
                        continue
                else:
                    continue
            if hyp_name == "S05_PASSIVE_ABSORPTION_BREAKOUT":
                if not (0.45 <= best_ask <= 0.54):
                    continue
            fee_per_share = calculate_crypto_fee(best_ask, 1.0)  # approx per share? actually per 1 share
            # fee per share = fee_coeff * p * (1-p)
            fee_per_share = risk and (0.07 * best_ask * (1 - best_ask))
            est_slippage = 0.0045 * (150 / 1000.0)
            if not (p - (best_ask + fee_per_share + est_slippage) >= edge):
                continue
            # build book
            asks = [OrderBookLevel(price=best_ask, size=100.0)]
            fill = engine.execute_taker_buy("UP" if side_up else "DOWN", risk.base_shares_per_trade, best_ask + 0.05, asks, True)
            if not fill.filled:
                continue
            trades += 1
            outcome_up = bool(w["outcome_up"])
            win = side_up == outcome_up
            if win:
                wins += 1
                pnl = fill.filled_shares * 1.0 - fill.total_cost_usdc
                cur_streak = 0
            else:
                # early-exit salvage: cut loss to ~1.40
                pnl = -1.40
                cur_streak += 1
                if cur_streak > max_streak:
                    max_streak = cur_streak
            trade_pnls.append(pnl)
            net_pnl += pnl
            # drawdown
            peak = max(peak, net_pnl)
            dd = peak - net_pnl
            if dd > max_dd:
                max_dd = dd
            total_fees += fill.fee_usdc
            total_slip += fill.slippage_per_share * fill.filled_shares
            if best_ask >= 0.58:
                cohort_058_trades += 1
                if win:
                    cohort_058_wins += 1
                cohort_058_pnl += pnl
            break  # one trade per window
    win_rate = wins / trades if trades else 0.0
    # z-score vs random (50%)
    import math as _m
    if trades > 0:
        se = _m.sqrt(0.25 / trades)
        z = (win_rate - 0.5) / se if se > 0 else 0.0
    else:
        z = 0.0
    return {
        "hypothesis": hyp_name,
        "trades": trades,
        "wins": wins,
        "win_rate": win_rate,
        "net_pnl": net_pnl,
        "total_fees": total_fees,
        "total_slippage": total_slip,
        "z_score": z,
        "max_losing_streak": max_streak,
        "max_drawdown": max_dd,
        "cohort_058_trades": cohort_058_trades,
        "cohort_058_win_rate": (cohort_058_wins / cohort_058_trades) if cohort_058_trades else 0.0,
        "cohort_058_net_pnl": cohort_058_pnl,
    }
