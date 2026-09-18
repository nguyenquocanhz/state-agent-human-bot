"""State machine cho MOT cuoc hoi thoai.

    [IDLE] --tin nhan moi--> [SEEN_DELAY] --> [THINKING] --> [TYPING] --> [SENDING]
        ^                                                        |            |
        +---------------------- [COOLDOWN] <---------------------+------------+

Tin nhan den giua chu ky se "ngat" chu ky do (giong nguoi that dang go thi thay
doi phuong nhan them -> doc lai roi tra loi mot the), tru khi dang go do dang
mot doan giua chung thi go not doan do roi moi doc lai.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, List, Optional

from . import humanizer as H
from .chunker import chunk_reply
from .prompt import build_system_prompt, build_user_turn
from .states import S, assert_transition
from .typo import maybe_typo
from .util import fmt_ms, log, log_state


@dataclass
class Inbound:
    """Mot tin nhan den, da chuan hoa tu adapter bat ky."""

    text: str
    msg_id: Any = None
    at_ms: float = field(default_factory=lambda: time.time() * 1000)
    raw: Any = None


class _Restart(Exception):
    """Co tin nhan moi -> bo chu ky hien tai, doc lai tu dau."""


class ConversationMachine:
    def __init__(self, conv_id, *, adapter, llm, persona, store, rng, clock,
                 dry_run: bool = False, on_state: Optional[Callable] = None,
                 max_batch: int = 20):
        self.conv_id = conv_id
        self.adapter = adapter
        self.llm = llm
        self.persona = persona
        self.store = store
        self.rng = rng
        self.clock = clock
        self.dry_run = dry_run
        self.on_state = on_state
        self.max_batch = max_batch

        self.state = S.IDLE
        self.inbox: List[Inbound] = []
        self._pending: List[Inbound] = []       # batch dang xu ly, giu lai neu bi ngat
        self._undelivered: List[str] = []       # doan da soan nhung bi ngat truoc khi gui
        self._interrupt = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self.ctx = dict(store.get(conv_id))

    # ------------------------------------------------------------------ API
    def push(self, msg: Inbound) -> None:
        """Adapter goi ham nay khi co tin nhan moi. Khong block."""
        self.inbox.append(msg)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())
        else:
            self._interrupt.set()               # dang ban -> bao hieu doc lai

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except BaseException:
                pass
        await self._typing_off()

    @property
    def busy(self) -> bool:
        return self.state is not S.IDLE

    # ------------------------------------------------------------- vong lap
    async def _loop(self) -> None:
        try:
            while self.inbox or self._pending:
                try:
                    await self._cycle()
                except _Restart:
                    # Dang go do thi doi phuong nhan them -> tat typing roi doc lai.
                    await self._typing_off()
                    continue
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception(f"[{self.conv_id}] chu ky loi")
        finally:
            await self._typing_off()
            if self.state is not S.IDLE:
                self._force(S.IDLE)
            # Tin den dung luc vong lap sap ket thuc thi khong ai danh thuc no nua
            # (push() thay _task chua done nen chi bao interrupt) -> tu mo lai.
            if self.inbox:
                self._interrupt.clear()
                self._task = asyncio.create_task(self._loop())

    async def _cycle(self) -> None:
        persona, rng = self.persona, self.rng
        self._interrupt.clear()
        batch = self._drain()
        if not batch:
            return

        t0 = time.time()
        now = self.clock.now()
        self.ctx = H.update_rhythm(self.ctx, now_ms=now, persona=persona,
                                   inbound_chars=sum(len(m.text) for m in batch))
        att = H.attention_of(self.ctx, now, persona)

        # ---------------------------------------------------- 1. SEEN_DELAY
        energy = self.ctx["energy"]
        engage = self.ctx["engagement"]
        self._set(S.SEEN_DELAY,
                  "att=%s energy=%.2f engage=%.2f tin=%d" % (att, energy, engage, len(batch)))
        if att == H.ATT.ASLEEP:
            await self._sleep_through_night(now)
            now = self.clock.now()

        seen_ms = H.seen_delay_ms(persona=persona, rng=rng, att=att, ctx=self.ctx, batch=batch)
        log.debug(f"[{self.conv_id}] doi {fmt_ms(seen_ms)} roi moi mo tin")
        await self._sleep(seen_ms)
        await self._mark_seen(batch)

        # ------------------------------------------------------ 2. THINKING
        think_ms = (H.think_delay_ms(persona=persona, rng=rng, batch=batch, ctx=self.ctx)
                    + H.burst_grace_ms(persona=persona, rng=rng, batch=batch))
        self._set(S.THINKING, f"~{fmt_ms(think_ms)} (LLM chay song song)")

        llm_task = asyncio.create_task(self._ask(batch, now))
        try:
            await self._sleep(think_ms)                 # nguoi nghi
            reply = await self._await_llm(llm_task)     # LLM cham hon thi doi not
        except BaseException:
            llm_task.cancel()
            raise

        if reply is None or not reply.text.strip():
            log.warning(f"[{self.conv_id}] khong co cau tra loi -> bo qua luot nay")
            self._pending = []
            await self._cooldown(t0)
            return

        # --------------------------------------------- 3. TYPING -> SENDING
        chunks = chunk_reply(reply.text, persona=persona, rng=rng)
        self._pending = []          # da quyet dinh tra loi: batch coi nhu xu ly xong
        self._undelivered = []      # cau tra loi moi da bao gom phan bi bo do truoc do
        out_chars = 0
        sent = 0

        try:
            for i, chunk in enumerate(chunks):
                text, correction = maybe_typo(chunk, persona=persona, rng=rng)
                type_ms = H.typing_ms_for(text, persona=persona, rng=rng,
                                          ctx=self.ctx, now_ms=self.clock.now())
                self._set(S.TYPING, "doan %d/%d ~%s (%d ky tu)"
                          % (i + 1, len(chunks), fmt_ms(type_ms), len(text)))
                await self._typing_on()

                # Doan dau tien co the bi ngat (chua gui gi); cac doan sau go cho xong.
                first = (i == 0)
                hes = persona["typing"]
                if rng.chance(hes.get("hesitationRate", 0)):
                    # Khung lai giua chung: tat typing vai giay roi go tiep.
                    cut = rng.between(0.35, 0.7)
                    await self._sleep(type_ms * cut, interruptible=first)
                    await self._typing_off()
                    await self._sleep(rng.between(hes["hesitationMinMs"], hes["hesitationMaxMs"]),
                                      interruptible=first)
                    await self._typing_on()
                    await self._sleep(type_ms * (1 - cut), interruptible=first)
                else:
                    await self._sleep(type_ms, interruptible=first)

                self._set(S.SENDING, "doan %d/%d" % (i + 1, len(chunks)))
                await self._send(text)
                out_chars += len(text)
                sent = i + 1

                if correction:
                    await self._sleep(
                        rng.log_normal(persona["typo"].get("correctionMedianMs", 1400), 0.4),
                        interruptible=False)
                    self._set(S.SENDING, "sua chinh ta")
                    await self._send(correction)
                    out_chars += len(correction)

                if i < len(chunks) - 1:
                    await self._typing_off()
                    gap = H.inter_chunk_ms(persona=persona, rng=rng)
                    self._set(S.TYPING, f"nghi {fmt_ms(gap)} truoc doan sau")
                    await self._sleep(gap)
        except _Restart:
            # Doi phuong nhan them -> bo cac doan con lai. Chung van nam trong lich su
            # cua claude session nen phai bao cho model biet la CHUA gui di.
            self._undelivered = chunks[sent:]
            log.debug(f"[{self.conv_id}] bi ngat, bo {len(self._undelivered)} doan chua gui")
            if sent:
                self._record_reply(out_chars)
            raise

        await self._typing_off()
        self._record_reply(out_chars)
        log.debug(f"[{self.conv_id}] chi phi luot nay ${reply.cost_usd:.4f}")
        await self._cooldown(t0)

    # ------------------------------------------------------------ cac buoc
    async def _sleep_through_night(self, now: float) -> None:
        s = self.persona["sleep"]
        if self.rng.chance(s.get("replyProbWhileAsleep", 0.0)):
            log.info(f"[{self.conv_id}] dang ngu nhung tinh giac -> van tra loi")
            return
        wait = H.ms_until_wake(now, self.persona, self.rng)
        log.info(f"[{self.conv_id}] dang ngu, de mai tra loi (sau {fmt_ms(wait)})")
        await self._sleep(wait)

    async def _ask(self, batch: List[Inbound], now: float):
        system = build_system_prompt(self.persona)
        # Khong xoa _undelivered o day: lan goi nay van co the bi huy giua chung.
        prompt = build_user_turn(batch=batch, ctx=self.ctx, persona=self.persona, now_ms=now,
                                 undelivered=self._undelivered)
        reply = await self.llm.complete(prompt=prompt, system=system,
                                        session_id=self.ctx.get("sessionId"))
        if reply.session_id and reply.session_id != self.ctx.get("sessionId"):
            self.ctx["sessionId"] = reply.session_id
            self.store.set(self.conv_id, sessionId=reply.session_id)
        return reply

    async def _await_llm(self, llm_task: asyncio.Task):
        """Doi LLM, nhung tin nhan moi den van ngat duoc."""
        waiter = asyncio.create_task(self._interrupt.wait())
        done, _ = await asyncio.wait({llm_task, waiter}, return_when=asyncio.FIRST_COMPLETED)
        waiter.cancel()
        if llm_task in done:
            try:
                return llm_task.result()
            except Exception as e:
                log.error(f"[{self.conv_id}] LLM loi: {e}")
                return None
        llm_task.cancel()
        raise _Restart()

    async def _cooldown(self, t0: float) -> None:
        ms = H.cooldown_ms(persona=self.persona, rng=self.rng)
        self._set(S.COOLDOWN, "tong luot %.1fs thuc te" % (time.time() - t0))
        await self._sleep(ms)
        self._set(S.IDLE)

    # ------------------------------------------------------------ tien ich
    def _drain(self) -> List[Inbound]:
        """Gop tin con ton (tu chu ky bi ngat) voi tin moi den."""
        self._pending = (self._pending + self.inbox)[-self.max_batch:]
        self.inbox = []
        return self._pending

    async def _sleep(self, ms: float, interruptible: bool = True) -> None:
        if ms <= 0:
            return
        if not interruptible:
            await self.clock.sleep(ms)
            return
        try:
            await asyncio.wait_for(self._interrupt.wait(), timeout=self.clock.scaled(ms))
        except asyncio.TimeoutError:
            return           # ngu du gio, khong ai lam phien
        raise _Restart()     # co tin nhan moi

    def _set(self, to: S, detail: str = "") -> None:
        assert_transition(self.state, to)
        frm, self.state = self.state, to
        log_state(self.conv_id, frm.value, to.value, detail)
        if self.on_state:
            self.on_state(self.conv_id, frm, to, detail)

    def _force(self, to: S) -> None:
        frm, self.state = self.state, to
        log_state(self.conv_id, frm.value, to.value, "(ep ve)")

    def _record_reply(self, out_chars: int) -> None:
        now = self.clock.now()
        self.ctx = H.update_rhythm(self.ctx, now_ms=now, persona=self.persona,
                                   outbound_chars=out_chars)
        self.ctx.update(lastActivityAt=now, lastRepliedAt=now,
                        turns=self.ctx.get("turns", 0) + 1)
        self.store.set(self.conv_id,
                       energy=self.ctx["energy"], engagement=self.ctx["engagement"],
                       lastActivityAt=now, lastRepliedAt=now, turns=self.ctx["turns"])

    async def _mark_seen(self, batch: List[Inbound]) -> None:
        self.ctx["lastActivityAt"] = self.clock.now()
        self.store.set(self.conv_id, lastActivityAt=self.ctx["lastActivityAt"])
        if self.dry_run:
            log.info(f"[{self.conv_id}] (dry-run) mark read")
            return
        try:
            await self.adapter.mark_seen(self.conv_id, batch[-1])
        except Exception as e:
            log.warning(f"[{self.conv_id}] mark read that bai: {e}")

    async def _typing_on(self) -> None:
        if self.dry_run:
            return
        try:
            await self.adapter.set_typing(self.conv_id, True)
        except Exception as e:
            log.warning(f"[{self.conv_id}] bat typing that bai: {e}")

    async def _typing_off(self) -> None:
        if self.dry_run:
            return
        try:
            await self.adapter.set_typing(self.conv_id, False)
        except Exception as e:
            log.debug(f"[{self.conv_id}] tat typing that bai: {e}")

    async def _send(self, text: str) -> None:
        if self.dry_run:
            log.info(f"[{self.conv_id}] (dry-run) gui: {text}")
            return
        await self.adapter.send(self.conv_id, text)
