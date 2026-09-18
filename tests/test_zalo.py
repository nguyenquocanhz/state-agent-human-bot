"""Test hai adapter Zalo - chi phan logic, khong goi mang, khong chay Node."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from humanbot.adapters.zalo_adapter import THREAD_GROUP, THREAD_USER, ZaloAdapter  # noqa: E402
from humanbot.adapters.zalo_oa_adapter import ZaloAdapter as ZaloOa                # noqa: E402

MSG = {
    "ev": "message", "conv": "789", "type": THREAD_USER, "text": "alo shop",
    "msgId": "m1", "data": {"msgId": "m1", "cliMsgId": "c1", "uidFrom": "789"},
}


def adapter(**kw):
    a = ZaloAdapter(**kw)
    a.received = []
    a._on_message = lambda conv, msg: a.received.append((conv, msg))
    return a


class ZaloPersonalTest(unittest.TestCase):
    def test_message_passes_when_allowed(self):
        a = adapter(allowed=["789"])
        a._handle(MSG)
        self.assertEqual(len(a.received), 1)
        conv, inbound = a.received[0]
        self.assertEqual(conv, "789")
        self.assertEqual(inbound.text, "alo shop")
        self.assertEqual(inbound.raw["cliMsgId"], "c1")   # can cho sendSeenEvent

    def test_stranger_blocked(self):
        a = adapter(allowed=["111"])
        a._handle(MSG)
        self.assertEqual(a.received, [])

    def test_group_blocked_by_default(self):
        a = adapter(allowed=["789"])
        a._handle({**MSG, "type": THREAD_GROUP})
        self.assertEqual(a.received, [])

    def test_group_passes_when_enabled(self):
        a = adapter(allowed=["789"], allow_groups=True)
        a._handle({**MSG, "type": THREAD_GROUP})
        self.assertEqual(len(a.received), 1)
        self.assertEqual(a._threads["789"], THREAD_GROUP)   # nho de gui dung loai thread

    def test_empty_text_ignored(self):
        a = adapter(allowed=["789"])
        a._handle({**MSG, "text": "   "})
        self.assertEqual(a.received, [])

    def test_non_message_events_do_not_crash(self):
        a = adapter(allowed=["789"])
        for ev in ({"ev": "ready", "me": {"id": 1, "name": "x"}},
                   {"ev": "qr", "path": "data/zalo-qr.png"},
                   {"ev": "error", "op": "send", "message": "loi gi do"},
                   {"ev": "la gi the"}):
            a._handle(ev)
        self.assertEqual(a.received, [])


class ZaloOaTest(unittest.TestCase):
    def test_parse_user_text_event(self):
        out = ZaloOa.parse_event({
            "event_name": "user_send_text",
            "sender": {"id": "42"},
            "message": {"text": "chao shop", "msg_id": "m9"},
        })
        self.assertIsNotNone(out)
        conv, inbound = out
        self.assertEqual(conv, "42")
        self.assertEqual(inbound.text, "chao shop")

    def test_ignores_non_user_events(self):
        self.assertIsNone(ZaloOa.parse_event({"event_name": "oa_send_text"}))
        self.assertIsNone(ZaloOa.parse_event({"event_name": "user_seen_message"}))
        self.assertIsNone(ZaloOa.parse_event({}))

    def test_ignores_empty_text(self):
        self.assertIsNone(ZaloOa.parse_event({
            "event_name": "user_send_image", "sender": {"id": "42"}, "message": {}}))



class ImageInputTest(unittest.IsolatedAsyncioTestCase):
    """Anh dinh kem phai di het duong tu Inbound -> LLM."""

    async def test_images_reach_the_llm(self):
        import asyncio as aio
        from humanbot.clock import Clock
        from humanbot.config import load_persona
        from humanbot.llm.mock import MockLlm
        from humanbot.machine import ConversationMachine, Inbound
        from humanbot.rng import Rng
        from humanbot.states import S
        from humanbot.store import SessionStore
        from tests.test_core import FakeAdapter

        llm = MockLlm(delay_ms=5, reply="de minh soi")
        store = SessionStore(path="data/test-img.json", flush_after=60)
        store.data = {}
        m = ConversationMachine("c1", adapter=FakeAdapter(), llm=llm,
                                persona=load_persona("config/persona.mainboard.json"),
                                store=store, rng=Rng(1), clock=Clock(time_scale=0.002))
        m.push(Inbound(text="soi ho em", msg_id=1, images=["data/test-board.png"]))
        for _ in range(500):
            await aio.sleep(0.01)
            if m.state is S.IDLE and (m._task is None or m._task.done()):
                break
        self.assertEqual(llm.images[-1], ["data/test-board.png"])
        self.assertIn("so_anh_dinh_kem=1", llm.calls[-1])


class DiagramChunkTest(unittest.TestCase):
    """So do ASCII phai giu nguyen xuong dong va khong bi cat."""

    DIAGRAM = ("Chuoi nguon:\n\nBATT+ 3.9V\n   |\n  [F1]\n   |\n PP_VDD_MAIN\n\n"
               "Do 2 dau F1 xem con thong khong.")

    def test_diagram_survives_intact(self):
        from humanbot.chunker import chunk_reply, looks_like_diagram
        from humanbot.config import load_persona
        from humanbot.rng import Rng
        persona = load_persona("config/persona.mainboard.json")
        for seed in range(20):
            chunks = chunk_reply(self.DIAGRAM, persona=persona, rng=Rng(seed))
            drawn = [c for c in chunks if looks_like_diagram(c)]
            self.assertEqual(len(drawn), 1, f"seed {seed}: so do bi vo")
            self.assertIn("[F1]", drawn[0])
            self.assertEqual(drawn[0].count("\n"), 4)   # giu du 5 dong

    def test_plain_prose_is_not_mistaken_for_a_diagram(self):
        from humanbot.chunker import looks_like_diagram
        self.assertFalse(looks_like_diagram("Cau mot day.\nCau hai - co gach ngang."))
        self.assertFalse(looks_like_diagram("Mot dong duy nhat | co gach dung"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
