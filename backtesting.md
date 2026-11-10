# Backtesting Qualification Guidelines — poly5m

## Purpose
Define the standard workflow, fee/slippage accounting, and qualification gates for any strategy before promotion to paper trading or live.

## Workflow
1. **Reproducibility gate**: freeze data range, params, seeds, fees, slippage model. Re-run and confirm metrics match. Save config hash + data checksum.
2. **Hypothesis tournament**: run `python -m poly5m hypotheses --days N`. All strategies must fire; report WR, Net PnL, fees, slippage, Z, MaxDD, $0.58 cohort.
3. **Audit (red-team)**: run `python -m poly5m audit --days N` and `python -m poly5m truth --days N`. Check lead rate, future continuation WR, inversion/placebo.
4. **Adversarial validation**: run `poly5m/adversarial.py` Stage 1 (overlap + delay) then Stage 2 (OOS, cost stress, null, fragility, capacity).
5. **Flat-start / tail-quantile**: run `python -m poly5m flat` and `python -m poly5m tail` to test genuine directional alpha.
6. **Qualification gate**: only promote if all gates pass (see below).

## Fee & Slippage Accounting
- Fee formula: `fee = C * 0.07 * p * (1 - p)`, min `0.00001` (per share, C=shares).
- Min order size: 5 shares. Tick size: 0.001.
- Entry price band: $0.44 – $0.62 for asks.
- Slippage: book-walk (avg fill - best ask) + latency (150ms * 0.0045) * multiplier, min 0.001 baseline before multiplier.
- All-in entry cost: `best_ask + fee_per_share + est_slippage`. Enter only if `model_prob - all_in >= min_ev_edge` (default 0.055; S10 0.058).
- Crypto fee in sim: `calculate_crypto_fee(price, shares)`.

## Metrics Required
- Trades, Wins, Win Rate, Net PnL (after fees + slippage)
- Total fees, total slippage
- Z-score (vs 50% random)
- Max losing streak, Max drawdown ($ and %)
- $0.58+ cohort: trades, WR, Net PnL (breakeven ~60.1%)
- Walk-forward OOS decay (<25% to pass)
- Stress tests: Fee x1.5, Slippage x2, Latency +500ms, Fill rate -20%, Regime shift

## Qualification Gates (must ALL pass)
1. Positive net PnL in ≥3 of 4 OOS windows.
2. Clustered (block-adjusted) Z significant; permutation p < 0.05.
3. Lead rate at entry < 50% OR future continuation WR > 54% with counter-lead WR ≥ 50%.
4. Inverted-signal WR significantly lower than base (placebo check).
5. Survives realistic cost stress (slippage 2x + 25bps fees + 2 ticks adverse selection) with positive net PnL.
6. Max account drawdown ≤ $6 kill-switch on $10 bankroll (no kill-switch trigger).
7. Parameter plateau (not isolated spike) across ±10/20/30% threshold sweeps.
8. Fill rate 50% + market impact still profitable.
9. Trades not >30% overlapping with another promoted strategy (or treated as one family).

## Red Flags (auto-fail)
- Lead rate @ entry = 100% with future continuation WR ≈ 50% → coasting on lead, not alpha.
- Inverted microstructure WR ≥ base WR → placebo features.
- Slippage x2 printing identical PnL → slippage not actually applied.
- Walk-forward decay > 25% → overfit.
- MaxDD > kill-switch → risk-incompatible.

## Commands
```bash
python -m pytest -q
python -m poly5m backtest --days 14 --real-data
python -m poly5m hypotheses --days 7 --real-data
python -m poly5m audit --days 7
python -m poly5m truth --days 7
python -m poly5m tail --days 30
python -m poly5m flat --days 7
python -m poly5m live --dry-run --duration 60 --record
```

## Safety
- Never set DRY_RUN=False without explicit confirmation.
- Never bypass AssertionError guard in execution.py.
- Never commit .env or private keys.