"""Stage 4A: Live WebSocket collector + Binance TWAP tracker."""
import asyncio
import json
import time
from collections import deque
from typing import Optional
import requests


def fetch_gamma_window_metadata(window_ts: int) -> Optional[dict]:
    slug = f"btc-updown-5m-{window_ts}"
    url = f"https://gamma-api.polymarket.com/events?slug={slug}"
    try:
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        data = r.json()
        if not data:
            return None
        market = data[0]["markets"][0]
        return {
            "slug": slug,
            "clobTokenIds": json.loads(market.get("clobTokenIds", '["0","1"]')),
            "acceptingOrders": market.get("acceptingOrders", True),
        }
    except Exception:
        return None


class RollingTWAP:
    def __init__(self, window_sec: int = 60):
        self.window_sec = window_sec
        self.buf = deque(maxlen=window_sec)
        self.start_twap_locked = None
        self.start_lock_ts = None

    def push(self, price: float, ts: float):
        self.buf.append((ts, price))
        # lock start TWAP at window boundary
        if self.start_lock_ts is None or (int(ts) // 300) != (int(self.start_lock_ts) // 300):
            # new 5-min window: lock the 60s TWAP just before boundary
            if len(self.buf) >= self.window_sec:
                self.start_twap_locked = sum(p for _, p in list(self.buf)[-self.window_sec:]) / self.window_sec
            self.start_lock_ts = ts

    @property
    def current_twap(self) -> float:
        if not self.buf:
            return 0.0
        w = list(self.buf)[-self.window_sec:]
        return sum(p for _, p in w) / len(w)

    @property
    def start_twap(self) -> float:
        return self.start_twap_locked if self.start_twap_locked else self.current_twap

    @property
    def realized_vol_1s(self) -> float:
        prices = [p for _, p in list(self.buf)]
        if len(prices) < 2:
            return 0.0001
        rets = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
        if not rets:
            return 0.0001
        var = sum(r * r for r in rets) / len(rets)
        return var ** 0.5


import math


class LiveFeedEngine:
    def __init__(self, record: bool = False):
        self.record = record
        self.twap = RollingTWAP(60)
        self.current_window_ts = None
        self.meta = None

    async def run_paper_session(self, duration_sec: int = 60):
        end = time.time() + duration_sec
        while time.time() < end:
            now = int(time.time())
            wts = (now // 300) * 300
            if wts != self.current_window_ts:
                self.current_window_ts = wts
                self.meta = fetch_gamma_window_metadata(wts)
                print(f"window={wts} metadata={wts if self.meta else None}")
            # simulate a price tick
            try:
                r = requests.get("https://api.binance.com/api/v3/ticker/price", params={"symbol": "BTCUSDT"}, timeout=3)
                price = float(r.json()["price"])
            except Exception:
                price = 0.0
            self.twap.push(price, time.time())
            if self.record and self.meta:
                rec = {"ts": time.time(), "window": wts, "price": price, "twap": self.twap.current_twap}
                with open(f"data/live_snapshots_{wts}.jsonl", "a") as f:
                    f.write(json.dumps(rec) + "\n")
            await asyncio.sleep(1.0)
        print("session ended")