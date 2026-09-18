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


if __name__ == "__main__":
    unittest.main(verbosity=2)
