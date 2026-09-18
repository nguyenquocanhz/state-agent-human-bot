"""Bo dieu phoi: moi cuoc hoi thoai mot state machine, dung chung LLM + persona."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from .clock import Clock
from .machine import ConversationMachine, Inbound
from .rng import Rng
from .store import SessionStore
from .util import log


class HumanBotEngine:
    def __init__(self, *, adapter, llm, persona: dict, store: SessionStore,
                 clock: Optional[Clock] = None, seed: Optional[int] = None,
                 dry_run: bool = False):
        self.adapter = adapter
        self.llm = llm
        self.persona = persona
        self.store = store
        self.clock = clock or Clock()
        self.seed = seed
        self.dry_run = dry_run
        self.machines: Dict[Any, ConversationMachine] = {}

    def machine_for(self, conv_id: Any) -> ConversationMachine:
        m = self.machines.get(conv_id)
        if m is None:
            # Seed rieng theo conv_id: moi nguoi doi thoai co "nhip tay" rieng,
            # nhung chay lai voi cung seed thi tai lap duoc.
            rng = Rng(None if self.seed is None else f"{self.seed}:{conv_id}")
            m = ConversationMachine(
                conv_id, adapter=self.adapter, llm=self.llm, persona=self.persona,
                store=self.store, rng=rng, clock=self.clock, dry_run=self.dry_run)
            self.machines[conv_id] = m
        return m

    def on_message(self, conv_id: Any, msg: Inbound) -> None:
        """Adapter goi (dong bo) moi khi co tin nhan moi."""
        preview = msg.text if len(msg.text) <= 70 else msg.text[:70] + "..."
        log.info(f"[{conv_id}] << {preview}")
        self.machine_for(conv_id).push(msg)

    async def run(self, drain_timeout: float = 20.0) -> None:
        await self.adapter.start(self.on_message)
        try:
            await self.adapter.run_forever()
            # Ket thuc binh thuong (dong stdin / mat ket noi): cho not luot dang do,
            # dung bo roi nguoi ta giua cau. Ctrl+C thi dung ngay, khong cho.
            await self.drain(drain_timeout)
        finally:
            await self.shutdown()

    async def drain(self, timeout: float) -> None:
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            if not any(m.busy for m in self.machines.values()):
                return
            await asyncio.sleep(0.2)
        log.warning("Van con luot dang do sau khi cho - dung luon.")

    async def shutdown(self) -> None:
        await asyncio.gather(*(m.stop() for m in self.machines.values()),
                             return_exceptions=True)
        try:
            await self.adapter.stop()
        except Exception:
            pass
        self.store.close()
        log.info("Da dung.")
