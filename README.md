# poly5m

Python trading bot for Polymarket 5-minute BTC Up/Down markets.

## Structure

```
poly5m/          # package
  config.py      # RiskConfig, ExecutionPhysicsConfig, BotConfig
  data.py        # Gamma discovery, synthetic windows, MarketSnapshot
  real_data.py   # Binance klines, TWAP labels, BS MM book
  sim_exec.py    # SimulatedExecutionEngine + crypto fee
  strategy.py    # StrategyEngine (champion model)
  strategy_vault.py  # promoted strategies (>300% return)
  hypotheses.py  # 10-strategy tournament
  replay.py      # BacktestReplayEngine
  metrics.py     # metrics, walk-forward, stress tests
  risk_engine.py # CapitalBuckets, RiskEngine
  dry_run.py     # paper orders
  execution.py   # unified dry/live
  ws_collector.py, live_feed.py
  __main__.py    # CLI
tests/           # pytest suite (10 tests)
data/            # recorded JSONL snapshots
```

## Commands
```bash
python -m pytest -q
python -m poly5m backtest --days 14 --real-data
python -m poly5m hypotheses --days 7 --real-data
python -m poly5m live --dry-run --duration 60 --record
```

## Safety
- DRY_RUN guard: never bypass AssertionError in execution.py
- Never commit .env or private keys
- Fee formula: C * 0.07 * p * (1-p), min 0.00001