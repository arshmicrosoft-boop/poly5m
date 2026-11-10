"""Adversarial validation harness - Stage 1 + Stage 2 (family-level)."""
import json, os, math, random
from typing import List, Dict
from .real_data import build_real_windows_from_binance
from .hypotheses import STRATEGIES


def _run_with_details(windows, hyp_name, exec_delay_min=0):
    from .config import RiskConfig, ExecutionPhysicsConfig
    from .sim_exec import SimulatedExecutionEngine
    from .data import OrderBookLevel
    hyp = STRATEGIES[hyp_name]
    risk = RiskConfig()
    physics = ExecutionPhysicsConfig()
    engine = SimulatedExecutionEngine(physics, seed=101)
    trades = []
    for wi, w in enumerate(windows):
        for snap in w["snapshots"]:
            if snap["elapsed"] < (60 + exec_delay_min * 60):
                continue
            p = hyp(snap)
            if p == 0.5:
                continue
            side_up = p >= 0.55
            if side_up:
                best_ask = snap["up_ask"]
            else:
                if p > 0.45:
                    continue
                best_ask = snap["down_ask"]
            if best_ask < 0.44 or best_ask > risk.max_token_price:
                continue
            fee_ps = 0.07 * best_ask * (1 - best_ask)
            est_slip = 0.003
            edge = 0.055
            if hyp_name == "S10_LOGIT_BAYESIAN_ENSEMBLE":
                edge = 0.058
            if not (p - (best_ask + fee_ps + est_slip) >= edge):
                continue
            asks = [OrderBookLevel(price=best_ask, size=100.0)]
            fill = engine.execute_taker_buy("UP" if side_up else "DOWN", risk.base_shares_per_trade, best_ask + 0.05, asks, True)
            if not fill.filled:
                continue
            outcome_up = bool(w["outcome_up"])
            win = side_up == outcome_up
            pnl = (fill.filled_shares * 1.0 - fill.total_cost_usdc) if win else (-fill.total_cost_usdc)
            trades.append({"window_idx": wi, "side": "UP" if side_up else "DOWN", "pnl": pnl, "win": win, "ask": best_ask})
            break
    return trades


def _family_trades(windows):
    names = ["S02_LOW_VOL_THETA_DECAY", "S07_SPOT_TWAP_ACCELERATION", "S03_PRE_TWAP_LOCKIN_SNIPER"]
    raw = []
    for n in names:
        for t in _run_with_details(windows, n):
            raw.append((n, t))
    seen = set()
    deduped = []
    for n, t in raw:
        key = (t["window_idx"], t["side"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append((n, t))
    return deduped


def _family_summary(trades):
    pnls = [t["pnl"] for _, t in trades]
    wins = sum(1 for _, t in trades if t["win"])
    n = len(trades)
    net = sum(pnls)
    maxstreak = 0; cur = 0
    for _, t in trades:
        if t["win"]:
            cur = 0
        else:
            cur += 1
            if cur > maxstreak:
                maxstreak = cur
    peak = 0.0; maxdd = 0.0; cum = 0.0
    for _, t in trades:
        cum += t["pnl"]
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > maxdd:
            maxdd = dd
    cohort = [t for _, t in trades if t["ask"] >= 0.58]
    # clustered z by 288-window blocks
    blocks = {}
    for _, t in trades:
        b = t["window_idx"] // 288
        blocks.setdefault(b, []).append(t["pnl"])
    block_means = [sum(v) / len(v) for v in blocks.values() if v]
    if len(block_means) > 1:
        m = sum(block_means) / len(block_means)
        var = sum((x - m) ** 2 for x in block_means) / (len(block_means) - 1)
        se = math.sqrt(var / len(block_means))
        z = m / (se + 1e-9)
    else:
        z = 0.0
    return {
        "trades": n, "wins": wins, "wr": round(wins / n, 4) if n else 0.0,
        "net_pnl": round(net, 2), "max_losing_streak": maxstreak,
        "max_drawdown_pnl": round(maxdd, 2),
        "cohort_058_trades": len(cohort),
        "cohort_058_pnl": round(sum(t["pnl"] for t in cohort), 2),
        "clustered_z": round(z, 4),
    }


def real_null_test(windows, n_iter=1000):
    trades = _family_trades(windows)
    pnls = [t["pnl"] for _, t in trades]
    wins = [1 if t["win"] else 0 for _, t in trades]
    observed_pnl = sum(pnls)
    observed_wr = sum(wins) / len(wins) if wins else 0.0
    # shuffled labels: randomize win/loss preserving timing/sizing; pnl magnitude from ask
    random.seed(42)
    null_pnls = []
    for _ in range(n_iter):
        sim = 0.0
        for _, t in trades:
            # random outcome with unconditional prob ~0.5
            w = 1 if random.random() < 0.5 else 0
            if w:
                sim += t["ask"] * 0 + (5.0 * 1.0 - 5.0 * t["ask"])  # approx win payout
            else:
                sim -= 5.0 * t["ask"]
        null_pnls.append(sim)
    count = sum(1 for x in null_pnls if x >= observed_pnl)
    pval = (1 + count) / (1 + n_iter)
    # randomized entry: random valid windows
    rand_pnls = []
    all_idx = list(range(len(windows)))
    for _ in range(n_iter):
        chosen = random.sample(all_idx, min(len(trades), len(all_idx)))
        sim = 0.0
        for wi in chosen:
            w = windows[wi]
            # random side
            side_up = random.random() < 0.5
            snap = w["snapshots"][0] if w["snapshots"] else None
            if snap is None:
                continue
            ask = snap["up_ask"] if side_up else snap["down_ask"]
            outcome_up = bool(w["outcome_up"])
            win = side_up == outcome_up
            sim += (5.0 * 1.0 - 5.0 * ask) if win else (-5.0 * ask)
        rand_pnls.append(sim)
    count2 = sum(1 for x in rand_pnls if x >= observed_pnl)
    pval2 = (1 + count2) / (1 + n_iter)
    # 95% CI of null pnl
    sp = sorted(null_pnls)
    lo = sp[int(0.025 * n_iter)]
    hi = sp[int(0.975 * n_iter)]
    return {
        "observed_pnl": round(observed_pnl, 2),
        "observed_wr": round(observed_wr, 4),
        "shuffled_pval": round(pval, 4),
        "randomized_entry_pval": round(pval2, 4),
        "null_pnl_95ci": [round(lo, 2), round(hi, 2)],
        "n_iter": n_iter,
    }


def cost_stress_grid(windows):
    # approximate: base family trades, apply mult and fees
    trades = _family_trades(windows)
    grid = []
    for sm in (0.5, 1.0, 2.0, 3.0, 5.0):
        for adv in (0, 1, 2, 3):
            for fee_bps in (0, 10, 25, 50):
                pnl = 0.0
                for _, t in trades:
                    ask = t["ask"]
                    slip = 0.000675 * sm + adv * 0.001
                    fee = ask * (fee_bps / 10000.0)
                    allin = ask + slip + fee
                    # recompute pnl roughly
                    if t["win"]:
                        pnl += 5.0 * 1.0 - 5.0 * (allin)
                    else:
                        pnl -= 5.0 * (allin)
                grid.append({"slip_mult": sm, "adv_ticks": adv, "fee_bps": fee_bps, "net_pnl": round(pnl, 2)})
    # breakeven: find first unprofitable
    return grid


def drawdown_resolution(windows):
    trades = _family_trades(windows)
    # account equity curve with $10 bankroll, 5 shares, kill switch 6
    bankroll = 10.0
    equity = [bankroll]
    peak = bankroll
    maxdd = 0.0
    for _, t in trades:
        bankroll += t["pnl"]
        if bankroll < 6.0:
            break
        equity.append(bankroll)
        if bankroll > peak:
            peak = bankroll
        dd = (peak - bankroll) / peak * 100 if peak > 0 else 0
        if (peak - bankroll) > maxdd:
            maxdd = peak - bankroll
    return {"starting_bankroll": 10.0, "final_bankroll": round(bankroll, 2), "max_peak_to_trough_dd_usd": round(maxdd, 2), "max_dd_pct": round(maxdd / 10.0 * 100, 2), "kill_switch_hit": bankroll < 6.0}


def run_stage2():
    os.makedirs("output/adversarial/family", exist_ok=True)
    w = build_real_windows_from_binance(num_days=7)
    fam = _family_summary(_family_trades(w))
    nt = real_null_test(w)
    cs = cost_stress_grid(w)
    dd = drawdown_resolution(w)
    # write json
    with open("output/adversarial/family/null_tests.json", "w") as f:
        json.dump(nt, f, indent=2)
    with open("output/adversarial/family/cost_stress.json", "w") as f:
        json.dump(cs, f, indent=2)
    with open("output/adversarial/family/risk_report.md", "w") as f:
        f.write(f"# Risk Report\n\nMax DD (pnl): {fam['max_drawdown_pnl']}\nAccount DD: {dd}\n")
    with open("output/adversarial/family/report.md", "w") as f:
        f.write(f"# Family Report\n\n{json.dumps(fam, indent=2)}\n\nNull: {json.dumps(nt)}\n\nDrawdown: {json.dumps(dd)}\n")
    print("FAMILY:", json.dumps(fam))
    print("NULL:", json.dumps(nt))
    print("DD:", json.dumps(dd))
    print("Cost grid cells:", len(cs))
    # breakeven: first unprofitable at 1x slippage 0 adv 0 fee? check
    base = [c for c in cs if c["slip_mult"] == 1.0 and c["adv_ticks"] == 0 and c["fee_bps"] == 0][0]
    print("Base cost cell:", base)


if __name__ == "__main__":
    run_stage2()