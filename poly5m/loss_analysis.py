"""Loss attribution for the signal family."""
import math, json, os
from .real_data import build_real_windows_from_binance
from .adversarial import _family_trades


def run(days=7):
    w = build_real_windows_from_binance(num_days=days)
    trades = _family_trades(w)
    # by side
    by_side = {}
    for n, t in trades:
        by_side.setdefault(t["side"], []).append(t)
    side_stats = {}
    for side, ts in by_side.items():
        wins = sum(1 for t in ts if t["win"])
        side_stats[side] = {"trades": len(ts), "wins": wins, "wr": round(wins / len(ts), 4) if ts else 0, "pnl": round(sum(t["pnl"] for t in ts), 2)}
    # by lead
    lead_trades = [t for _, t in trades if (t["side"] == "UP" and t["ask"] >= 0.5) or True]
    # losing trades detail
    losers = [t for _, t in trades if not t["win"]]
    # by window block (day)
    by_day = {}
    for _, t in trades:
        d = t["window_idx"] // 288
        by_day.setdefault(d, []).append(t)
    day_stats = {}
    for d, ts in by_day.items():
        wins = sum(1 for t in ts if t["win"])
        day_stats[d] = {"trades": len(ts), "wr": round(wins / len(ts), 4) if ts else 0, "pnl": round(sum(t["pnl"] for t in ts), 2)}
    # consecutive loss clusters: find max loss streak windows
    # loss magnitude distribution
    loss_mag = sorted([abs(t["pnl"]) for _, t in trades if not t["win"]], reverse=True)[:10]
    report = {
        "side_stats": side_stats,
        "day_stats": day_stats,
        "num_losers": len(losers),
        "top_loss_magnitudes": [round(x, 2) for x in loss_mag],
        "total_pnl": round(sum(t["pnl"] for _, t in trades), 2),
    }
    os.makedirs("output/loss", exist_ok=True)
    with open("output/loss/report.json", "w") as f:
        json.dump(report, f, indent=2)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    run()