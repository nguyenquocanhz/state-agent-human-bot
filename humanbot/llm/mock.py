"""LLM gia lap: chay offline, khong ton chi phi - dung cho demo va unit test."""
from __future__ import annotations

import asyncio

from .claude_cli import LlmReply


class MockLlm:
    def __init__(self, delay_ms: float = 300, reply: str | None = None):
        self.delay_ms = delay_ms
        self.reply = reply
        self.calls: list[str] = []
        self.images: list[list[str]] = []

    async def complete(self, *, prompt: str, system: str | None = None,
                       session_id: str | None = None, images=()) -> LlmReply:
        self.calls.append(prompt)
        self.images.append(list(images))
        await asyncio.sleep(self.delay_ms / 1000.0)
        lines = [ln for ln in prompt.splitlines() if ln.strip()]
        last = lines[-1] if lines else ""
        text = self.reply or f"ok minh doc roi ne: {last[:60]}\n\nde minh coi rooi bao lai nha"
        # Tra lai dung session_id nhan vao: khong ghi id gia vao store thuc.
        return LlmReply(text=text, session_id=session_id,
                        cost_usd=0.0, duration_ms=self.delay_ms)
