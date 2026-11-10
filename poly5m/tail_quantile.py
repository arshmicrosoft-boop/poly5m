"""Tail-quantile sniper study on D01_CVD_ACCELERATION."""
import math, json, os
from .real_data import build_real_windows_from_binance


def cvd_score(snap):
    return snap.get("order_flow_imbalance", 0.0)


def run(days=30):
    w = build_real_windows_from_binance(num_days=days)
    # collect candidate events
    cands = []
    for window in w:
        for snap in window["snapshots"]:
            if snap["elapsed"] not in (60, 120):
                continue
            vol = snap.get("realized_vol_1s", 0.0001)
            tau = max(1.0, snap["remaining"])
            if abs(math.log(snap["spot"] / snap["start_twap"])) > 0.15 * vol * math.sqrt(tau):
                continue
            ofi = snap.get("order_flow_imbalance", 0.0)
            if abs(ofi) < 0.1:
                continue
            # volume burst proxy: use |ofi| as score
            score = abs(ofi)
            side_up = ofi > 0
            cands.append((score, snap, window, side_up))
    cands.sort(key=lambda x: x[0], reverse=True)
    n = len(cands)
    tiers = [("Top30", 0.30), ("Top15", 0.15), ("Top7", 0.07), ("Top3", 0.03)]
    results = {}
    for name, frac in tiers:
        k = max(1, int(n * frac))
        subset = cands[:k]
        trades = 0; wins = 0; fut = 0; pnl = 0.0; lead = 0
        for score, snap, window, side_up in subset:
            ask = snap["up_ask"] if side_up else snap["down_ask"]
            if ask < 0.44 or ask > 0.62:
                continue
            outcome_up = bool(window["outcome_up"])
            win = side_up == outcome_up
            trades += 1
            if win:
                wins += 1
                pnl += 5.0 * 1.0 - 5.0 * ask
            else:
                pnl -= 5.0 * ask
            if (side_up and snap["spot"] > snap["start_twap"]) or ((not side_up) and snap["spot"] < snap["start_twap"]):
                lead += 1
            fut_win = (window["end_twap"] > snap["spot"]) if side_up else (window["end_twap"] < snap["spot"])
            if fut_win:
                fut += 1
        wr = wins / trades if trades else 0.0
        fut_wr = fut / trades if trades else 0.0
        lead_rate = lead / trades if trades else 0.0
        results[name] = {"trades": trades, "trades_per_day": round(trades / days, 1), "lead_rate": round(lead_rate, 4), "future_cont_wr": round(fut_wr, 4), "realized_wr": round(wr, 4), "net_pnl": round(pnl, 2)}
    os.makedirs("output/tail", exist_ok=True)
    with open("output/tail/report.json", "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    run()