"""Test backend Messages API - dung client gia, khong cham mang, khong ton tien.

Chay:  python -m unittest tests.test_api_backend -v
"""
from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from humanbot.llm.anthropic_api import (  # noqa: E402
    AnthropicApi, HistoryStore, estimate_cost, resolve_model,
)


def fake_usage(inp=100, out=50, cache_read=0, cache_create=0):
    return SimpleNamespace(
        input_tokens=inp, output_tokens=out,
        cache_read_input_tokens=cache_read, cache_creation_input_tokens=cache_create,
        model_dump=lambda: {"input_tokens": inp, "output_tokens": out},
    )


class FakeMessages:
    def __init__(self, parent):
        self.parent = parent

    async def create(self, **kwargs):
        self.parent.requests.append(kwargs)
        reply = self.parent.replies.pop(0) if self.parent.replies else "ok nha"
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=reply)],
            stop_reason=self.parent.stop_reason,
            usage=self.parent.usage,
        )


class FakeClient:
    def __init__(self, replies=None, stop_reason="end_turn", usage=None):
        self.requests: list[dict] = []
        self.replies = list(replies or [])
        self.stop_reason = stop_reason
        self.usage = usage or fake_usage()
        self.messages = FakeMessages(self)


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_roundtrip(self):
        h = HistoryStore(self.dir)
        h.save("conv-1", [{"role": "user", "content": "hi"},
                          {"role": "assistant", "content": "chao"}])
        self.assertEqual(len(HistoryStore(self.dir).load("conv-1")), 2)

    def test_trim_keeps_user_first(self):
        h = HistoryStore(self.dir, max_messages=3)
        msgs = [{"role": "user", "content": f"u{i}"} if i % 2 == 0
                else {"role": "assistant", "content": f"a{i}"} for i in range(10)]
        trimmed = h.trim(msgs)
        self.assertLessEqual(len(trimmed), 3)
        self.assertEqual(trimmed[0]["role"], "user")   # API bat buoc bat dau bang user

    def test_conv_id_with_slash_does_not_escape_dir(self):
        h = HistoryStore(self.dir)
        h.save("../evil/-100123", [{"role": "user", "content": "x"}])
        files = list(Path(self.dir).glob("*.json"))
        self.assertEqual(len(files), 1)
        self.assertNotIn("..", files[0].name)


class CostTest(unittest.TestCase):
    def test_sonnet_math(self):
        # 1M input + 1M output tren sonnet-5 = 2 + 10 USD
        cost = estimate_cost("claude-sonnet-5", fake_usage(inp=1_000_000, out=1_000_000))
        self.assertAlmostEqual(cost, 12.0, places=6)

    def test_cache_read_is_cheap(self):
        full = estimate_cost("claude-sonnet-5", fake_usage(inp=100_000, out=0))
        cached = estimate_cost("claude-sonnet-5", fake_usage(inp=0, out=0, cache_read=100_000))
        self.assertAlmostEqual(cached, full * 0.1, places=6)

    def test_unknown_model_does_not_crash(self):
        self.assertEqual(estimate_cost("model-la", fake_usage()), 0.0)


class ApiBackendTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def _api(self, client, **kw):
        return AnthropicApi(client=client, history_dir=self.dir, **kw)

    async def test_history_grows_across_turns(self):
        client = FakeClient(replies=["chao ban", "gia 200k nha"])
        api = self._api(client)

        first = await api.complete(prompt="chao shop", system="SYS")
        self.assertTrue(first.session_id)
        second = await api.complete(prompt="bao nhieu tien",
                                    system="SYS", session_id=first.session_id)

        # Luot 2 phai mang theo ca 3 tin truoc do.
        sent = client.requests[1]["messages"]
        self.assertEqual([m["role"] for m in sent], ["user", "assistant", "user"])
        self.assertEqual(sent[0]["content"], "chao shop")
        self.assertEqual(sent[1]["content"], "chao ban")
        self.assertEqual(second.session_id, first.session_id)

    async def test_history_survives_new_instance(self):
        client = FakeClient(replies=["nho roi"])
        api = self._api(client)
        r = await api.complete(prompt="ten minh la An", system="SYS")

        client2 = FakeClient(replies=["An chu gi"])
        api2 = self._api(client2)
        await api2.complete(prompt="ten minh la gi", system="SYS", session_id=r.session_id)
        self.assertEqual(len(client2.requests[0]["messages"]), 3)

    async def test_cancelled_call_leaves_no_trace(self):
        """Bi ngat giua chung thi lich su khong duoc ban - luot sau nhac lai binh thuong."""
        class Boom(FakeClient):
            pass
        client = Boom()

        async def blow_up(**kwargs):
            raise RuntimeError("mat mang")
        client.messages.create = blow_up

        api = self._api(client)
        with self.assertRaises(RuntimeError):
            await api.complete(prompt="tin bi mat", system="SYS", session_id="conv-x")
        self.assertEqual(api.history.load("conv-x"), [])

    async def test_sonnet_disables_thinking_and_sets_effort(self):
        client = FakeClient()
        await self._api(client, model="sonnet", effort="low").complete(prompt="hi")
        req = client.requests[0]
        self.assertEqual(req["model"], "claude-sonnet-5")
        self.assertEqual(req["thinking"], {"type": "disabled"})
        self.assertEqual(req["output_config"], {"effort": "low"})

    async def test_haiku_gets_neither_effort_nor_disabled_thinking(self):
        client = FakeClient()
        await self._api(client, model="haiku").complete(prompt="hi")
        req = client.requests[0]
        self.assertEqual(req["model"], "claude-haiku-4-5")
        self.assertNotIn("output_config", req)   # haiku khong nhan effort
        self.assertNotIn("thinking", req)        # bo han tham so = khong nghi

    async def test_thinking_on_uses_adaptive(self):
        client = FakeClient()
        await self._api(client, model="opus", thinking=True).complete(prompt="hi", system="S")
        self.assertEqual(client.requests[0]["thinking"], {"type": "adaptive"})
        self.assertEqual(client.requests[0]["system"], "S")   # khong them canh bao the XML

    async def test_refusal_returns_empty_without_saving(self):
        client = FakeClient(replies=["khong the"], stop_reason="refusal")
        api = self._api(client)
        reply = await api.complete(prompt="hi", session_id="conv-r")
        self.assertEqual(reply.text, "")
        self.assertEqual(api.history.load("conv-r"), [])

    async def test_cost_is_tracked(self):
        client = FakeClient(usage=fake_usage(inp=500, out=200))
        api = self._api(client, model="sonnet")
        reply = await api.complete(prompt="hi")
        expected = (500 * 2.0 + 200 * 10.0) / 1_000_000
        self.assertAlmostEqual(reply.cost_usd, expected, places=8)
        self.assertAlmostEqual(api.total_cost, expected, places=8)


class MachineIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """Backend api phai cam thang vao state machine duoc, khong sua gi ben trong."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_drop_in_replacement_for_claude_cli(self):
        from humanbot.clock import Clock
        from humanbot.config import load_persona
        from humanbot.machine import ConversationMachine, Inbound
        from humanbot.rng import Rng
        from humanbot.states import S
        from humanbot.store import SessionStore
        from tests.test_core import FakeAdapter

        client = FakeClient(replies=["chao ban nha\n\nco gi minh giup duoc khong"])
        api = AnthropicApi(client=client, history_dir=self.dir)
        adapter = FakeAdapter()
        store = SessionStore(path=str(Path(self.dir) / "s.json"), flush_after=60)
        store.data = {}

        m = ConversationMachine("tg-42", adapter=adapter, llm=api,
                                persona=load_persona("config/persona.default.json"),
                                store=store, rng=Rng(1), clock=Clock(time_scale=0.002))
        m.push(Inbound(text="alo shop oi", msg_id=1))
        for _ in range(500):
            await asyncio.sleep(0.01)
            if m.state is S.IDLE and (m._task is None or m._task.done()):
                break

        self.assertEqual(adapter.sent, ["chao ban nha", "co gi minh giup duoc khong"])
        # session_id do backend sinh ra phai duoc machine luu lai de luot sau resume
        saved = store.get("tg-42")["sessionId"]
        self.assertTrue(saved)
        self.assertEqual(len(api.history.load(saved)), 2)
        self.assertGreater(api.total_cost, 0)


class AliasTest(unittest.TestCase):
    def test_aliases(self):
        self.assertEqual(resolve_model("sonnet"), "claude-sonnet-5")
        self.assertEqual(resolve_model("opus"), "claude-opus-5")
        self.assertEqual(resolve_model("claude-haiku-4-5"), "claude-haiku-4-5")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class PhoneArgTest(unittest.TestCase):
    """Regression: truyen phone=None thang vao Telethon lam no gui None len server."""

    def test_none_returns_a_prompt_callable(self):
        from humanbot.adapters.telethon_adapter import phone_arg
        arg = phone_arg(None)
        self.assertTrue(callable(arg))
        self.assertIsNotNone(arg)

    def test_empty_string_also_prompts(self):
        from humanbot.adapters.telethon_adapter import phone_arg
        self.assertTrue(callable(phone_arg("")))

    def test_real_number_passes_through(self):
        from humanbot.adapters.telethon_adapter import phone_arg
        self.assertEqual(phone_arg("+84912345678"), "+84912345678")
