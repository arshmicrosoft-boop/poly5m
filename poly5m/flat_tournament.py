"""Flat-start directional tournament (Path A)."""
import math, json, os
from typing import List, Dict
from .real_data import build_real_windows_from_binance


def _flat_ok(snap):
    vol = snap.get("realized_vol_1s", 0.0001)
    tau = max(1.0, snap["remaining"])
    z = math.log(snap["spot"] / snap["start_twap"]) / (vol * math.sqrt(tau) + 1e-9)
    return abs(z) <= 0.15 * vol * math.sqrt(tau) * 0  # placeholder replaced below


def flat_filter(snap):
    vol = snap.get("realized_vol_1s", 0.0001)
    tau = max(1.0, snap["remaining"])
    z = math.log(snap["spot"] / snap["start_twap"]) / (vol * math.sqrt(tau) + 1e-9)
    # flat: |log(spot/start)| <= 0.15 * vol * sqrt(remaining)  (abs z <= 0.15*sqrt? approx)
    return abs(math.log(snap["spot"] / snap["start_twap"])) <= 0.15 * vol * math.sqrt(tau)


def predictors(snap):
    ofi = snap.get("order_flow_imbalance", 0.0)
    # D01 CVD acceleration proxy: use ofi magnitude
    d01 = ofi > 0.2
    # D02 OBI pressure proxy: ofi extreme
    d02 = abs(ofi) >= 0.35
    # D04 1m momentum: spot vs start
    d04 = snap["spot"] > snap["start_twap"]
    # D05 trend alignment: spot and curr_twap same side
    d05 = (snap["spot"] - snap["start_twap"]) * (snap["curr_twap"] - snap["start_twap"]) > 0
    return {"D01_CVD_ACCELERATION": d01, "D02_BINANCE_OBI_PRESSURE": d02, "D04_1M_MOMENTUM": d04, "D05_TREND_ALIGNMENT": d05}


def run_flat(days=7):
    w = build_real_windows_from_binance(num_days=days)
    results = {}
    for name in ["D01_CVD_ACCELERATION", "D02_BINANCE_OBI_PRESSURE", "D04_1M_MOMENTUM", "D05_TREND_ALIGNMENT"]:
        trades = 0; wins = 0; pnl = 0.0
        for window in w:
            for snap in window["snapshots"]:
                if not flat_filter(snap):
                    continue
                if snap["elapsed"] not in (60, 120):
                    continue
                preds = predictors(snap)
                if not preds.get(name, False):
                    continue
                side_up = True  # default up for directional
                # determine direction by predictor
                if name == "D04_1M_MOMENTUM":
                    side_up = snap["spot"] > snap["start_twap"]
                if name == "D05_TREND_ALIGNMENT":
                    side_up = snap["spot"] > snap["start_twap"]
                if name in ("D01_CVD_ACCELERATION", "D02_BINANCE_OBI_PRESSURE"):
                    side_up = snap.get("order_flow_imbalance", 0) > 0
                # entry ask
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
                break
        wr = wins / trades if trades else 0.0
        results[name] = {"trades": trades, "wins": wins, "wr": round(wr, 4), "net_pnl": round(pnl, 2)}
    os.makedirs("output/flat", exist_ok=True)
    with open("output/flat/report.json", "w") as f:
        json.dump(results, f, indent=2)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    run_flat()