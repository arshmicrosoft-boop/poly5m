import os
import math
import time
import json
import random
from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime, timezone
import numpy as np
import requests


@dataclass
class OrderBookLevel:
    price: float
    size: float  # in shares


@dataclass
class MarketSnapshot:
    window_ts: int                 # Start timestamp of 5m window (divisible by 300)
    current_ts: float              # Current timestamp in seconds
    elapsed_sec: float             # Seconds since window start (0 to 300)
    remaining_sec: float           # Seconds until window close (300 to 0)
    up_token_id: str
    down_token_id: str
    accepting_orders: bool
    spot_price: float              # Current BTC spot price
    start_twap_60s: float          # Ground-truth 60s TWAP at T=0 (Price to Beat)
    current_twap_60s: float        # Rolling 60s TWAP at current_ts (no look-ahead!)
    realized_vol_1s: float         # Rolling per-second log return volatility
    order_flow_imbalance: float    # Normalized CVD / aggressive buy-sell imbalance [-1, +1]
    up_bids: List[OrderBookLevel]  # Sorted highest to lowest
    up_asks: List[OrderBookLevel]  # Sorted lowest to highest
    down_bids: List[OrderBookLevel]
    down_asks: List[OrderBookLevel]


@dataclass
class HistoricalWindow:
    window_ts: int
    slug: str
    up_token_id: str
    down_token_id: str
    start_twap_60s: float
    end_twap_60s: float
    outcome_up_won: int            # 1 if end_twap_60s >= start_twap_60s else 0
    volatility_regime: str         # "HIGH_VOL" or "LOW_VOL"
    quarter_label: str             # e.g., "2024-Q3"
    snapshots: List[MarketSnapshot]


def fetch_gamma_window_metadata(window_ts: int) -> Optional[Dict]:
    """Fetches real Polymarket 5-min BTC market metadata by deterministic slug."""
    slug = f"btc-updown-5m-{window_ts}"
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    try:
        resp = requests.get(url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            return None
        market = data[0]["markets"][0]
        return {
            "slug": slug,
            "question": market.get("question"),
            "description": market.get("description"),
            "outcomes": json.loads(market.get("outcomes", '["Up", "Down"]')),
            "clobTokenIds": json.loads(market.get("clobTokenIds", '["0", "1"]')),
            "acceptingOrders": market.get("acceptingOrders", True),
            "orderPriceMinTickSize": float(market.get("orderPriceMinTickSize") or 0.001),
            "orderMinSize": float(market.get("orderMinSize") or 5.0),
        }
    except Exception:
        return None


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def build_realistic_order_book(
    mid_prob: float,
    tick_size: float = 0.001,
    base_spread: float = 0.012,
    vol_multiplier: float = 1.0,
) -> tuple[List[OrderBookLevel], List[OrderBookLevel]]:
    half_spread = max(tick_size, round((base_spread * vol_multiplier) / (2 * tick_size)) * tick_size)
    best_bid = max(0.01, min(0.98, round((mid_prob - half_spread) / tick_size) * tick_size))
    best_ask = max(0.02, min(0.99, round((mid_prob + half_spread) / tick_size) * tick_size))
    if best_ask <= best_bid:
        best_ask = round(best_bid + tick_size, 3)

    level_sizes = [12.0, 25.0, 45.0, 80.0, 150.0]
    bids = [
        OrderBookLevel(price=round(max(0.001, best_bid - i * tick_size), 3), size=level_sizes[i])
        for i in range(5)
    ]
    asks = [
        OrderBookLevel(price=round(min(0.999, best_ask + i * tick_size), 3), size=level_sizes[i])
        for i in range(5)
    ]
    return bids, asks


def generate_historical_windows(
    num_days: int = 90,
    seed: int = 42,
    step_sec: int = 15,
) -> List[HistoricalWindow]:
    rng = np.random.default_rng(seed)
    total_windows = num_days * 288
    base_ts = 1704067200  # 2024-01-01 00:00:00 UTC
    btc_price = 65000.0
    windows: List[HistoricalWindow] = []

    for w_idx in range(total_windows):
        w_ts = base_ts + w_idx * 300
        # Real calendar quarter label
        dt = datetime.fromtimestamp(w_ts, tz=timezone.utc)
        quarter_num = (dt.month - 1) // 3 + 1
        quarter_label = f"{dt.year}-Q{quarter_num}"

        is_high_vol = ((w_idx // 144) % 3 == 0)
        vol_1s = 0.00014 if is_high_vol else 0.000075
        regime = "HIGH_VOL" if is_high_vol else "LOW_VOL"

        window_flow_imbalance = float(np.clip(rng.normal(0.0, 0.55), -1.0, 1.0))
        true_drift_per_sec = window_flow_imbalance * (vol_1s * 0.085)

        dt_step = 5.0
        n_pre = 12
        n_steps = 60
        total_steps = n_pre + n_steps

        shocks = rng.normal(0.0, 1.0, size=total_steps)
        prices = np.zeros(total_steps + 1)
        prices[0] = btc_price

        for s in range(total_steps):
            step_drift = true_drift_per_sec * dt_step if s >= n_pre else 0.0
            prices[s + 1] = prices[s] * math.exp(step_drift + vol_1s * math.sqrt(dt_step) * shocks[s])

        btc_price = float(prices[-1])

        start_twap_60s = float(np.mean(prices[: n_pre + 1]))
        end_twap_60s = float(np.mean(prices[-13:]))
        outcome_up_won = 1 if end_twap_60s >= start_twap_60s else 0

        snapshots: List[MarketSnapshot] = []
        stride = max(1, step_sec // 5)
        for idx in range(0, n_steps, stride):
            p_idx = n_pre + idx
            elapsed = idx * 5.0
            remaining = 300.0 - elapsed
            spot = float(prices[p_idx])
            curr_twap = float(np.mean(prices[max(0, p_idx - 12) : p_idx + 1]))

            obs_flow = float(np.clip(window_flow_imbalance + rng.normal(0, 0.20), -1.0, 1.0))

            z_crowd = math.log(spot / start_twap_60s) / (vol_1s * math.sqrt(max(10.0, remaining)) + 1e-9)
            crowd_prob = _norm_cdf(z_crowd * 0.82) + rng.normal(0.0, 0.015)
            crowd_prob = float(np.clip(crowd_prob, 0.03, 0.97))

            up_bids, up_asks = build_realistic_order_book(
                mid_prob=crowd_prob,
                tick_size=0.001,
                base_spread=0.010,
                vol_multiplier=1.35 if is_high_vol else 1.0,
            )
            down_bids, down_asks = build_realistic_order_book(
                mid_prob=1.0 - crowd_prob,
                tick_size=0.001,
                base_spread=0.010,
                vol_multiplier=1.35 if is_high_vol else 1.0,
            )

            snapshots.append(
                MarketSnapshot(
                    window_ts=w_ts,
                    current_ts=w_ts + elapsed,
                    elapsed_sec=elapsed,
                    remaining_sec=remaining,
                    up_token_id=f"up_{w_ts}",
                    down_token_id=f"down_{w_ts}",
                    accepting_orders=(elapsed < 285.0),
                    spot_price=spot,
                    start_twap_60s=start_twap_60s,
                    current_twap_60s=curr_twap,
                    realized_vol_1s=vol_1s,
                    order_flow_imbalance=obs_flow,
                    up_bids=up_bids,
                    up_asks=up_asks,
                    down_bids=down_bids,
                    down_asks=down_asks,
                )
            )

        windows.append(
            HistoricalWindow(
                window_ts=w_ts,
                slug=f"btc-updown-5m-{w_ts}",
                up_token_id=f"up_{w_ts}",
                down_token_id=f"down_{w_ts}",
                start_twap_60s=start_twap_60s,
                end_twap_60s=end_twap_60s,
                outcome_up_won=outcome_up_won,
                volatility_regime=regime,
                quarter_label=quarter_label,
                snapshots=snapshots,
            )
        )

    return windows