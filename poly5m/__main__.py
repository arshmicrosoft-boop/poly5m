import argparse
from .config import BotConfig
from .data import generate_historical_windows
from .replay import BacktestReplayEngine
from .metrics import compute_metrics, run_walk_forward_analysis, run_stress_test_suite
from .dry_run import DryRunExecutionEngine


def print_full_report(days: int) -> None:
    config = BotConfig(dry_run=True)
    print("=" * 78)
    print(f" POLYMARKET 5-MIN BTC UP/DOWN QUANTITATIVE BACKTEST ({days} DAYS / {days*288:,} WINDOWS)")
    print("=" * 78)
    print(
        f" Risk Config: Bankroll=${config.risk.starting_bankroll:.2f} | "
        f"Min Shares={config.physics.min_order_size_shares:.0f} | "
        f"Price Band=[${config.risk.min_token_price:.2f}, ${config.risk.max_token_price:.2f}] | "
        f"Fee=C*0.07*p*(1-p)"
    )
    print("-" * 78)

    windows = generate_historical_windows(num_days=days, seed=42)
    replay = BacktestReplayEngine(config)
    result = replay.run(windows)
    wf_decay = run_walk_forward_analysis(windows, config, folds=4)
    m = compute_metrics(result, walk_forward_decay_pct=wf_decay)
    stress = run_stress_test_suite(windows, config)

    all_stress_passed = all(s["passed"] for s in stress.values())

    print(f" 1. ACTIVITY & FILL METRICS")
    print(f"    Total 5m Windows Replayed : {m.total_windows:,}")
    print(f"    Total Trades Executed     : {m.total_trades:,} (Fill Rate: {m.fill_rate_pct:.1f}%)")
    print(f"    Trades / Day              : {m.trades_per_day:.2f}")
    print(f"    Trades / Year (Annualized): {m.trades_per_year:,.0f}")
    print()
    print(f" 2. EDGE, WIN RATE & STATISTICAL SIGNIFICANCE")
    print(f"    Realized Win Rate         : {m.win_rate_pct:.2f}%")
    print(f"    Avg Predicted Probability : {m.avg_predicted_prob_pct:.2f}%")
    print(f"    Net Realized Edge %       : {m.realized_edge_pct:+.2f}% (after fees & slippage)")
    print(f"    Z-Score (Edge vs Random)  : {m.z_score:.2f} (p < 0.0001 if Z > 3.89)")
    print(f"    Annualized Sharpe Ratio   : {m.sharpe_annualized:.2f}")
    print(f"    Walk-Forward OOS Decay    : {m.walk_forward_decay_pct:.1f}%")
    print()
    print(f" 3. PNL, FEE DRAG & RISK / DRAWDOWN")
    print(f"    Gross PnL (Before Drag)   : ${m.gross_pnl_usdc:+.2f}")
    print(f"    Total Crypto Fees Paid    : -${m.total_fees_usdc:.2f}")
    print(f"    Total Book-Walk Slippage  : -${m.total_slippage_usdc:.2f}")
    print(f"    Net PnL (After All Costs) : ${m.net_pnl_usdc:+.2f}")
    print(f"    Max Losing Streak         : {m.max_losing_streak} trades in a row")
    print(f"    Max Drawdown ($ / %)      : ${m.max_drawdown_usdc:.2f} ({m.max_drawdown_pct:.1f}%)")
    print(f"    Quarters Profitable       : {m.quarters_profitable_str}")
    for q_label, q_val in sorted(m.quarterly_pnl.items()):
        print(f"      - {q_label}: ${q_val:+.2f}")
    print()
    print(f" 4. PROFITABILITY AT $0.58 THRESHOLD CHECK")
    print(f"    Profitable at $0.58+?     : {'YES (PASSED)' if m.profitable_at_058 else 'NO (FAILED)'}")
    print(f"    Trades at Ask >= $0.58    : {m.cohort_058_trades}")
    print(f"    Win Rate at $0.58+        : {m.cohort_058_win_rate_pct:.2f}% (Breakeven ~60.1%)")
    print(f"    Net PnL at $0.58+         : ${m.cohort_058_net_pnl_usdc:+.2f}")
    print()
    print(f" 5. STRESS TEST BATTERY ({sum(1 for s in stress.values() if s['passed'])}/{len(stress)} PASSED)")
    for s_name, s_data in stress.items():
        status = "PASS" if s_data["passed"] else "FAIL"
        extra = f" ({s_data['detail']})" if "detail" in s_data else ""
        print(
            f"    [{status}] {s_name:<30} | Net PnL: ${s_data['net_pnl']:+7.2f} | "
            f"WR: {s_data['win_rate']:.1f}% | Z: {s_data['z_score']:.2f}{extra}"
        )
    print("=" * 78)


def main() -> None:
    parser = argparse.ArgumentParser(description="Polymarket 5m BTC Backtest & Dry-Run CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    bt_parser = sub.add_parser("backtest", help="Run backtest and stress test suite")
    bt_parser.add_argument("--days", type=int, default=180, help="Number of days (288 windows/day)")
    bt_parser.add_argument("--real-data", action="store_true", help="Use real Binance data")

    hyp_parser = sub.add_parser("hypotheses", help="Run hypothesis comparison on real data")
    hyp_parser.add_argument("--days", type=int, default=7)
    hyp_parser.add_argument("--recorded", action="store_true", help="Use recorded live JSONL snapshots")

    dr_parser = sub.add_parser("dryrun", help="Run live discovery & paper execution check")
    audit_parser = sub.add_parser("audit", help="Run red-team audit")
    audit_parser.add_argument("--days", type=int, default=7)
    flat_parser = sub.add_parser("flat", help="Run flat-start directional tournament")
    flat_parser.add_argument("--days", type=int, default=7)
    truth_parser = sub.add_parser("truth", help="Run truth serum audit")
    truth_parser.add_argument("--days", type=int, default=7)
    tail_parser = sub.add_parser("tail", help="Run tail quantile sniper study")
    tail_parser.add_argument("--days", type=int, default=30)
    loss_parser = sub.add_parser("loss", help="Run loss attribution")
    loss_parser.add_argument("--days", type=int, default=7)
    dr_parser.add_argument("--duration", type=int, default=60, help="Duration in seconds")

    args = parser.parse_args()
    if args.cmd == "backtest":
        print_full_report(days=args.days)
    elif args.cmd == "hypotheses":
        if getattr(args, "recorded", False):
            from .real_data import load_recorded_windows
            w = load_recorded_windows()
        else:
            from .real_data import build_real_windows_from_binance
            w = build_real_windows_from_binance(num_days=args.days)
        from .hypotheses import run_hypothesis_backtest, STRATEGIES
        results = [run_hypothesis_backtest(w, h) for h in STRATEGIES]
        results.sort(key=lambda r: r.get("net_pnl", 0), reverse=True)
        print("| Rank | Strategy | Trades | Wins | WR | Net PnL | Fees | Slip | Z | MaxLoseStreak | MaxDD | $0.58 Trades/WR/PnL |")
        print("|---|---|---|---|---|---|---|---|---|---|---|---|")
        for i, r in enumerate(results, 1):
            print(f"| {i} | {r['hypothesis']} | {r['trades']} | {r['wins']} | {r['win_rate']:.2%} | ${r['net_pnl']:+.2f} | ${r['total_fees']:.2f} | ${r['total_slippage']:.2f} | {r['z_score']:.2f} | {r['max_losing_streak']} | ${r['max_drawdown']:.2f} | {r['cohort_058_trades']}/{r['cohort_058_win_rate']:.2%}/${r['cohort_058_net_pnl']:+.2f} |")
    elif args.cmd == "audit":
        from .audit import run_audit
        run_audit(days=args.days)
    elif args.cmd == "flat":
        from .flat_tournament import run_flat
        run_flat(days=args.days)
    elif args.cmd == "truth":
        from .audit import truth_serum
        truth_serum(days=args.days)
    elif args.cmd == "tail":
        from .tail_quantile import run
        run(days=args.days)
    elif args.cmd == "loss":
        from .loss_analysis import run
        run(days=args.days)
    elif args.cmd == "dryrun":
        import asyncio
        from .live_feed import LiveFeedEngine
        engine = LiveFeedEngine()
        asyncio.run(engine.run_paper_session(args.duration))


if __name__ == "__main__":
    main()