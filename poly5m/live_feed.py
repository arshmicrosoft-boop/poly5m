"""Live feed discovery for Polymarket 5-min windows."""

import asyncio
import time
from typing import Any, Tuple

import requests


GAMMA_URL = "https://gamma-api.polymarket.com/markets"


class LiveFeedEngine:
    def __init__(self):
        self.session = requests.Session()

    async def _fetch_gamma(self, params: dict) -> Any:
        def _do():
            r = self.session.get(GAMMA_URL, params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        return await asyncio.to_thread(_do)

    async def discover_current_window(self) -> Tuple[int, dict]:
        now = int(time.time())
        window_ts = (now // 300) * 300
        metadata = {"window_ts": window_ts, "fetched_at": now}
        try:
            data = await self._fetch_gamma({"limit": 5})
            metadata["gamma"] = data
        except Exception as e:
            metadata["error"] = str(e)
        return window_ts, metadata

    async def discover_next_window(self) -> Tuple[int, dict]:
        current, _ = await self.discover_current_window()
        nxt = current + 300
        return nxt, {"window_ts": nxt, "prefetch": True}

    async def run_paper_session(self, duration_sec: int = 60):
        end = time.time() + duration_sec
        while time.time() < end:
            window_ts, metadata = await self.discover_current_window()
            print(f"window={window_ts} metadata={metadata.get('window_ts')}")
            await asyncio.sleep(5)
        print("session ended")
