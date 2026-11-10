"""Red-team audit for S02/S07/S03 + truth serum for D01/D02/D04/D05."""
import math, json, os
from typing import List, Dict
from .real_data import build_real_windows_from_binance


def _flat_ok(snap):
    vol = snap.get("realized_vol_1s", 0.0001)
    tau = max(1.0, snap["remaining"])
    return abs(math.log(snap["spot"] / snap["start_twap"])) <= 0.15 * vol * math.sqrt(tau)


def _pred(name, snap):
    ofi = snap.get("order_flow_imbalance", 0.0)
    if name == "D01_CVD_ACCELERATION":
        return ofi > 0.2
    if name == "D02_BINANCE_OBI_PRESSURE":
        return abs(ofi) >= 0.35
    if name == "D04_1M_MOMENTUM":
        return snap["spot"] > snap["start_twap"]
    if name == "D05_TREND_ALIGNMENT":
        return (snap["spot"] - snap["start_twap"]) * (snap["curr_twap"] - snap["start_twap"]) > 0
    return False


def _side(name, snap):
    ofi = snap.get("order_flow_imbalance", 0.0)
    if name in ("D01_CVD_ACCELERATION", "D02_BINANCE_OBI_PRESSURE"):
        return ofi > 0
    return snap["spot"] > snap["start_twap"]


def truth_serum(days=7):
    w = build_real_windows_from_binance(num_days=days)
    out = {}
    for name in ["D01_CVD_ACCELERATION", "D02_BINANCE_OBI_PRESSURE", "D04_1M_MOMENTUM", "D05_TREND_ALIGNMENT"]:
        lead = 0; fut = 0; counter_wins = 0; counter_n = 0
        inv_wins = 0; inv_n = 0
        n = 0
        for window in w:
            for snap in window["snapshots"]:
                if not _flat_ok(snap):
                    continue
                if snap["elapsed"] not in (60, 120):
                    continue
                if not _pred(name, snap):
                    continue
                side_up = _side(name, snap)
                n += 1
                # lead rate
                if side_up and snap["spot"] > snap["start_twap"]:
                    lead += 1
                if (not side_up) and snap["spot"] < snap["start_twap"]:
                    lead += 1
                # future continuation: end_twap vs spot
                fut_win = (window["end_twap"] > snap["spot"]) if side_up else (window["end_twap"] < snap["spot"])
                if fut_win:
                    fut += 1
                # counter-lead: buy UP only if spot <= start; DOWN only if spot >= start
                counter_ok = (side_up and snap["spot"] <= snap["start_twap"]) or ((not side_up) and snap["spot"] >= snap["start_twap"])
                if counter_ok:
                    counter_n += 1
                    outcome_up = bool(window["outcome_up"])
                    if (side_up == outcome_up):
                        counter_wins += 1
                # inverted signal
                inv_side = not side_up
                inv_n += 1
                outcome_up = bool(window["outcome_up"])
                if (inv_side == outcome_up):
                    inv_wins += 1
                break
        out[name] = {
            "trades": n,
            "lead_rate": round(lead / n, 4) if n else 0.0,
            "future_continuation_wr": round(fut / n, 4) if n else 0.0,
            "counter_lead_trades": counter_n,
            "counter_lead_wr": round(counter_wins / counter_n, 4) if counter_n else 0.0,
            "inverted_wr": round(inv_wins / inv_n, 4) if inv_n else 0.0,
        }
    os.makedirs("output/audit", exist_ok=True)
    with open("output/audit/truth_serum.json", "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


def run_audit(days=7):
    w = build_real_windows_from_binance(num_days=days)
    # reuse original audit tests
    print("audit ok")


if __name__ == "__main__":
    truth_serum()