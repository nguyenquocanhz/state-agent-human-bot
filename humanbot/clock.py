"""Dong ho co the tang toc: time_scale=0.2 -> moi do tre chi con 1/5 (debug/demo)."""
from __future__ import annotations

import asyncio
import time


class Clock:
    def __init__(self, time_scale: float = 1.0):
        self.time_scale = time_scale

    def now(self) -> float:
        """Epoch tinh bang mili-giay (dong don vi voi humanizer)."""
        return time.time() * 1000.0

    def scaled(self, ms: float) -> float:
        """Doi ms 'thoi gian nguoi' -> giay thuc te de sleep."""
        return max(0.0, ms * self.time_scale) / 1000.0

    async def sleep(self, ms: float) -> None:
        await asyncio.sleep(self.scaled(ms))
