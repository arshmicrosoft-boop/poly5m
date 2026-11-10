# AGENTS.md — Guide for AI Agents Working on poly5m

## Project Overview

`poly5m` is a Python trading bot for Polymarket's 5-minute BTC Up/Down markets. All code lives in `poly5m/` package. Tests in `tests/`.

## Key Files & Responsibilities

| File | Purpose |
|------|---------|
| `config.py` | Frozen dataclasses: RiskConfig, ExecutionPhysicsConfig, BotConfig. All tunable params here. |
| `data.py` | Gamma API fetcher, synthetic market generator, MarketSnapshot, HistoricalWindow |
| `real_data.py` | Binance klines, 60s TWAP labels, Black-Scholes MM book, `load_recorded_windows` |
| `sim_exec.py` | SimulatedExecutionEngine + module-level `calculate_crypto_fee(price, shares)` |
| `strategy.py` | StrategyEngine.evaluate_snapshot() → TradeSignal or None |
| `replay.py` | BacktestReplayEngine.run(windows, compound_sizing, drift_weight) |
| `metrics.py` | compute_metrics, run_walk_forward_analysis, run_stress_test_suite |
| `hypotheses.py` | HYPOTHESES dict + run_hypothesis_backtest |
| `risk_engine.py` | CapitalBuckets, RiskEngine (can_open, open_position, try_auto_cashout, resolve_window) |
| `dry_run.py` | DryRunExecutionEngine (paper orders, hard assert dry_run=True) |
| `execution.py` | ExecutionEngine (unified dry/live, hard guard) |
| `ws_collector.py` | RollingTWAP, LiveFeedEngine |
| `live_feed.py` | Live discovery + paper session |
| `__main__.py` | CLI: backtest, hypotheses, dryrun |

## Critical Invariants

1. **Fee formula**: `fee = C × 0.07 × p × (1 - p)`, min `0.00001`. Always apply in sim + metrics.
2. **Min order size**: 5 shares. **Tick size**: 0.001.
3. **Price band**: $0.44 – $0.62 for entries.
4. **DRY_RUN guard**: `ExecutionEngine._send_live_clob_order` raises AssertionError unless `dry_run=False` AND `live_confirmed=True`. Never bypass.
5. **Risk engine**: 1 concurrent window max, $3.10 max per trade, $5.50 max exposure, $6.00 kill switch.
6. **TWAP resolution**: 60s TWAP at T=0 vs final 60s (T+240..T+300). Never use spot price as label.
7. **Off-by-one**: In `real_data.py`, snapshot index = `w_start + elapsed - 1` (not `+ elapsed`).

## Data Flow

```
Gamma API → discovery → token IDs
Binance WS → RollingTWAP (60s) → start_twap, current_twap, vol, CVD
CLOB WS/REST → order book (bids/asks)
StrategyEngine.evaluate_snapshot(snap) → TradeSignal
RiskEngine.can_open() → deploy capital
ExecutionEngine.submit_entry() → dry-run log or live CLOB order
RiskEngine.try_auto_cashout() at $0.93+ bid
RiskEngine.resolve_window() after 5-min expiry
```

## Testing

```bash
python -m pytest -q   # 10 tests, must all pass
```

## Common Tasks

- **Add a new hypothesis**: Add function to `hypotheses.py`, register in `HYPOTHESES` dict.
- **Change risk params**: Edit `RiskConfig` in `config.py`.
- **Add a new metric**: Add to `BacktestMetricsSummary` and `compute_metrics` in `metrics.py`.
- **Live burn-in**: `python -m poly5m live --dry-run --duration 7200 --record`

## Safety Rules for Agents

- Never set `DRY_RUN=False` in code or config without explicit user confirmation.
- Never bypass the `AssertionError` guard in `execution.py`.
- Never commit private keys or `.env` files.
- Always run `pytest` after changes.
- Prefer editing existing files over creating new ones.