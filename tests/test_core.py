"""Test cho phan loi: humanizer, chunker, typo va toan bo vong doi state machine.

Chay:  python -m unittest discover -s tests -v
"""
from __future__ import annotations

import asyncio
import re
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from humanbot import humanizer as H                      # noqa: E402
from humanbot.chunker import chunk_reply                 # noqa: E402
from humanbot.clock import Clock                         # noqa: E402
from humanbot.config import load_persona                 # noqa: E402
from humanbot.llm.mock import MockLlm                    # noqa: E402
from humanbot.machine import ConversationMachine, Inbound  # noqa: E402
from humanbot.prompt import build_user_turn              # noqa: E402
from humanbot.rng import Rng                             # noqa: E402
from humanbot.states import S                            # noqa: E402
from humanbot.store import SessionStore                  # noqa: E402
from humanbot.typo import maybe_typo                     # noqa: E402

PERSONA = load_persona("config/persona.default.json")


def ts(y, mo, d, h, mi=0) -> float:
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc).timestamp() * 1000


class FakeAdapter:
    """Ghi lai moi hanh dong ra ngoai de kiem tra thu tu."""

    def __init__(self):
        self.events: list[tuple[str, object]] = []

    async def start(self, on_message):
        self.events.append(("start", None))

    async def run_forever(self):
        pass

    async def stop(self):
        pass

    async def mark_seen(self, conv_id, msg):
        self.events.append(("seen", msg.msg_id))

    async def set_typing(self, conv_id, on):
        self.events.append(("typing", on))

    async def send(self, conv_id, text):
        self.events.append(("send", text))

    @property
    def sent(self):
        return [t for k, t in self.events if k == "send"]


class HumanizerTest(unittest.TestCase):
    def test_delays_in_bounds(self):
        rng = Rng(1)
        now = ts(2026, 9, 18, 7, 30)
        ctx = {"lastActivityAt": now - 5000, "energy": 0.9, "engagement": 0.6}
        batch = [Inbound(text="cho minh hoi gia goi hosting nhe?")]
        for _ in range(200):
            seen = H.seen_delay_ms(persona=PERSONA, rng=rng, att=H.ATT.ACTIVE, ctx=ctx, batch=batch)
            think = H.think_delay_ms(persona=PERSONA, rng=rng, batch=batch, ctx=ctx)
            typ = H.typing_ms_for("x" * 120, persona=PERSONA, rng=rng, ctx=ctx, now_ms=now)
            self.assertGreaterEqual(seen, PERSONA["seen"]["minMs"])
            self.assertLessEqual(seen, PERSONA["seen"]["maxMs"])
            self.assertGreaterEqual(think, PERSONA["think"]["minMs"])
            self.assertLessEqual(think, PERSONA["think"]["maxMs"])
            self.assertLessEqual(typ, PERSONA["typing"]["maxChunkMs"])

    def test_attention_by_silence(self):
        now = ts(2026, 9, 18, 7, 30)
        self.assertEqual(H.attention_of({"lastActivityAt": now - 1000}, now, PERSONA), H.ATT.ACTIVE)
        self.assertEqual(H.attention_of({"lastActivityAt": now - 600_000}, now, PERSONA), H.ATT.IDLE)
        self.assertEqual(H.attention_of({"lastActivityAt": now - 7_200_000}, now, PERSONA), H.ATT.AWAY)

    def test_sleep_window_wraps_midnight(self):
        p = {**PERSONA, "sleep": {**PERSONA["sleep"], "startHour": 23, "endHour": 7}}
        self.assertTrue(H.is_sleep_hour(ts(2026, 9, 18, 17), p))     # 00:00 VN
        self.assertTrue(H.is_sleep_hour(ts(2026, 9, 18, 16, 30), p))  # 23:30 VN
        self.assertFalse(H.is_sleep_hour(ts(2026, 9, 18, 7), p))      # 14:00 VN

    def test_longer_message_takes_longer_to_type(self):
        rng = Rng(3)
        now = ts(2026, 9, 18, 7)
        ctx = {"energy": 1.0}
        short = sum(H.typing_ms_for("ok nha", persona=PERSONA, rng=rng, ctx=ctx, now_ms=now)
                    for _ in range(50))
        long = sum(H.typing_ms_for("ok nha " * 20, persona=PERSONA, rng=rng, ctx=ctx, now_ms=now)
                   for _ in range(50))
        self.assertGreater(long, short * 3)

    def test_energy_drains_and_recovers(self):
        now = ts(2026, 9, 18, 7)
        tired = H.update_rhythm({"energy": 1.0, "lastActivityAt": now}, now_ms=now,
                                persona=PERSONA, outbound_chars=800)
        self.assertLess(tired["energy"], 1.0)
        rested = H.update_rhythm({**tired, "lastActivityAt": now - 3_600_000}, now_ms=now,
                                 persona=PERSONA)
        self.assertGreater(rested["energy"], tired["energy"])


class ChunkerTest(unittest.TestCase):
    def test_code_block_stays_intact(self):
        rng = Rng(5)
        reply = "thu cai nay nha\n\n```py\nprint(1)\nprint(2)\n```\n\nxong bao minh"
        chunks = chunk_reply(reply, persona=PERSONA, rng=rng)
        code = [c for c in chunks if c.startswith("```")]
        self.assertEqual(len(code), 1)
        self.assertIn("print(1)\nprint(2)", code[0])

    def test_blank_line_becomes_separate_message(self):
        rng = Rng(5)
        chunks = chunk_reply("cau mot day nhe\n\ncau hai day nhe", persona=PERSONA, rng=rng)
        self.assertEqual(len(chunks), 2)

    def test_respects_max_chunks(self):
        rng = Rng(9)
        reply = "\n\n".join(f"day la doan so {i} noi ve mot y rieng biet." for i in range(12))
        self.assertLessEqual(len(chunk_reply(reply, persona=PERSONA, rng=rng)),
                             PERSONA["send"]["maxChunks"])


class TypoTest(unittest.TestCase):
    def test_typo_and_correction(self):
        p = {**PERSONA, "typo": {"rate": 1.0, "correctionProb": 1.0}}
        rng = Rng(2)
        original = "minh gui ban duong link dang ky Business nhe"
        text, correction = maybe_typo(original, persona=p, rng=rng)
        self.assertNotEqual(text, original)
        self.assertTrue(correction.startswith("*"))
        self.assertIn(correction[1:], original)

    def test_code_block_never_corrupted(self):
        p = {**PERSONA, "typo": {"rate": 1.0, "correctionProb": 1.0}}
        src = "```py\nprint(12345)\n```"
        self.assertEqual(maybe_typo(src, persona=p, rng=Rng(2)), (src, None))


class PromptTest(unittest.TestCase):
    def test_undelivered_marked_in_prompt(self):
        now = ts(2026, 9, 18, 7)
        out = build_user_turn(batch=[Inbound(text="alo")], ctx={"lastRepliedAt": now - 60_000},
                              persona=PERSONA, now_ms=now, undelivered=["doan chua kip gui"])
        self.assertIn("chua_gui", out)
        self.assertIn("doan chua kip gui", out)
        self.assertIn("alo", out)

    def test_no_marker_when_everything_delivered(self):
        out = build_user_turn(batch=[Inbound(text="alo")], ctx={}, persona=PERSONA,
                              now_ms=ts(2026, 9, 18, 7))
        self.assertNotIn("chua_gui", out)
        self.assertIn("lan_dau_nhan_tin", out)


class MachineTest(unittest.IsolatedAsyncioTestCase):
    def _machine(self, llm=None, persona=None, seed=4):
        self.adapter = FakeAdapter()
        self.llm = llm or MockLlm(delay_ms=10, reply="cau tra loi ngan\n\nva doan thu hai")
        store = SessionStore(path="data/test-sessions.json", flush_after=60)
        store.data = {}
        return ConversationMachine(
            "test", adapter=self.adapter, llm=self.llm, persona=persona or PERSONA,
            store=store, rng=Rng(seed), clock=Clock(time_scale=0.002))

    async def _wait_idle(self, m, timeout=10.0):
        loop = asyncio.get_running_loop()
        end = loop.time() + timeout
        while loop.time() < end:
            await asyncio.sleep(0.01)
            if m.state is S.IDLE and (m._task is None or m._task.done()):
                return
        self.fail(f"State machine khong ve IDLE (dang o {m.state})")

    async def test_full_cycle_order(self):
        m = self._machine()
        seen_states = []
        m.on_state = lambda c, f, t, d: seen_states.append(t)

        m.push(Inbound(text="chao ban, con hang khong?", msg_id=1))
        await self._wait_idle(m)

        self.assertEqual(seen_states[:3], [S.SEEN_DELAY, S.THINKING, S.TYPING])
        self.assertIn(S.SENDING, seen_states)
        self.assertEqual(seen_states[-1], S.IDLE)
        self.assertEqual(seen_states[-2], S.COOLDOWN)

        kinds = [k for k, _ in self.adapter.events]
        self.assertLess(kinds.index("seen"), kinds.index("send"))   # seen truoc khi gui
        self.assertEqual(self.adapter.sent, ["cau tra loi ngan", "va doan thu hai"])
        self.assertEqual(self.adapter.events[-1], ("typing", False))  # khong bo quen typing

    async def test_new_message_interrupts_and_merges(self):
        m = self._machine(llm=MockLlm(delay_ms=30, reply="mot doan thoi"))
        m.push(Inbound(text="tin nhan dau tien", msg_id=1))
        await asyncio.sleep(0.05)
        m.push(Inbound(text="a quen, them y nua", msg_id=2))
        await self._wait_idle(m)

        prompt = self.llm.calls[-1]
        self.assertIn("tin nhan dau tien", prompt)
        self.assertIn("a quen, them y nua", prompt)     # gop chung mot luot
        self.assertEqual(self.adapter.sent, ["mot doan thoi"])  # chi tra loi mot lan

    async def test_llm_failure_does_not_send_anything(self):
        class BoomLlm:
            async def complete(self, **kw):
                raise RuntimeError("claude-cli chet")

        m = self._machine(llm=BoomLlm())
        m.push(Inbound(text="hello", msg_id=1))
        await self._wait_idle(m)
        self.assertEqual(self.adapter.sent, [])

    async def test_message_arriving_at_end_of_cycle_is_not_lost(self):
        """Tin den dung luc may dang ket thuc luot -> phai duoc tra loi, khong duoc rot."""
        m = self._machine(llm=MockLlm(delay_ms=5, reply="xong roi nha"))
        m.push(Inbound(text="tin 1", msg_id=1))
        await self._wait_idle(m)
        first_calls = len(self.llm.calls)

        m.push(Inbound(text="tin 2 den ngay sau do", msg_id=2))
        await self._wait_idle(m)
        self.assertEqual(len(self.llm.calls), first_calls + 1)
        self.assertIn("tin 2 den ngay sau do", self.llm.calls[-1])
        self.assertEqual(len(self.adapter.sent), 2)

    async def test_sleeping_persona_defers_reply(self):
        persona = {**PERSONA, "sleep": {**PERSONA["sleep"], "enabled": True,
                                        "startHour": 0, "endHour": 23,
                                        "replyProbWhileAsleep": 0.0,
                                        "wakeJitterMedianMs": 60_000}}
        m = self._machine(persona=persona)
        m.push(Inbound(text="ngu chua", msg_id=1))
        await asyncio.sleep(0.2)
        self.assertEqual(self.adapter.sent, [])         # dang ngu, chua tra loi
        self.assertIs(m.state, S.SEEN_DELAY)
        await m.stop()


if __name__ == "__main__":
    unittest.main(verbosity=2)


class SystemPromptTest(unittest.TestCase):
    """Persona co the mang kien thuc chuyen mon va tu dat luat dinh dang rieng."""

    def test_expertise_block_appears(self):
        from humanbot.prompt import build_system_prompt
        p = {**PERSONA, "expertise": ["do dong tieu thu truoc khi doan benh"]}
        out = build_system_prompt(p)
        self.assertIn("Chuyen mon", out)
        self.assertIn("do dong tieu thu truoc khi doan benh", out)

    def test_no_expertise_block_when_absent(self):
        from humanbot.prompt import build_system_prompt
        self.assertNotIn("Chuyen mon", build_system_prompt(PERSONA))

    def test_persona_rules_replace_defaults(self):
        from humanbot.prompt import DEFAULT_RULES, build_system_prompt
        p = {**PERSONA, "rules": ["Duoc phep danh so buoc 1. 2. 3."]}
        out = build_system_prompt(p)
        self.assertIn("Duoc phep danh so buoc", out)
        self.assertNotIn(DEFAULT_RULES[2], out)   # luat "khong bullet" bi thay the

    def test_default_rules_used_when_persona_has_none(self):
        from humanbot.prompt import DEFAULT_RULES, build_system_prompt
        self.assertIn(DEFAULT_RULES[3], build_system_prompt(PERSONA))

    def test_every_shipped_persona_builds(self):
        from humanbot.prompt import build_system_prompt
        files = sorted(Path("config").glob("persona.*.json"))
        self.assertGreaterEqual(len(files), 4)
        for f in files:
            out = build_system_prompt(load_persona(str(f)))
            self.assertIn("Ban dang dong vai", out, f"{f.name} khong rap duoc prompt")


class NumberedStepsTest(unittest.TestCase):
    """Loi that gap khi chay: tin nhan bi ket thuc bang mot so lo loi kieu '2.'"""

    REPLY = ("May hoi vai thong tin da. 1. May co bi roi hay vao nuoc khong? "
             "2. Hien tuong la mat han khong len gi, hay co logo roi tat? "
             "3. Da do dong tieu thu chua, duoc bao nhieu mA?")

    def test_chunk_never_ends_with_a_bare_list_marker(self):
        for seed in range(30):
            chunks = chunk_reply(self.REPLY, persona=PERSONA, rng=Rng(seed))
            for c in chunks:
                self.assertIsNone(re.search(r"\b\d+\.$", c.strip()),
                                  f"seed {seed}: tin ket thuc bang so lo loi -> {c!r}")

    def test_steps_stay_with_their_content(self):
        chunks = chunk_reply(self.REPLY, persona=PERSONA, rng=Rng(7))
        joined = " ".join(chunks)
        for n in ("1.", "2.", "3."):
            i = joined.index(n)
            self.assertGreater(len(joined[i + 2:].strip()), 10,
                               f"buoc {n} khong con noi dung di kem")
