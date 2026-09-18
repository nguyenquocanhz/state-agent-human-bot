"""Test bo loc "ai duoc bot tra loi" - phan quyet dinh bot co lam phien nguoi that hay khong.

Dung event gia, khong ket noi Telegram.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from humanbot.adapters.telethon_adapter import TelethonAdapter  # noqa: E402

BOT_ID = 5393099854
FRIEND_ID = 1364926983
GROUP_ID = -1001234567890


def event(*, sender_id=FRIEND_ID, chat_id=None, private=True, out=False,
          mentioned=False, is_reply=False, username=None):
    chat_id = sender_id if chat_id is None else chat_id

    async def get_sender():
        return SimpleNamespace(username=username)

    return SimpleNamespace(
        sender_id=sender_id, chat_id=chat_id, is_private=private, out=out,
        mentioned=mentioned, is_reply=is_reply, get_sender=get_sender,
    )


def adapter(**kw):
    a = TelethonAdapter(api_id=1, api_hash="0" * 32, session="data/test-filter", **kw)
    a._me = SimpleNamespace(id=BOT_ID, username="smn_esoftz")
    return a


class FilterTest(unittest.IsolatedAsyncioTestCase):
    async def test_allowed_user_passes(self):
        a = adapter(allowed=[str(FRIEND_ID)])
        self.assertIsNone(await a._reject_reason(event()))

    async def test_stranger_blocked(self):
        a = adapter(allowed=[str(FRIEND_ID)])
        reason = await a._reject_reason(event(sender_id=999))
        self.assertIn("TG_ALLOWED", reason)

    async def test_username_allowlist(self):
        a = adapter(allowed=["@WrenCyber"])   # hoa thuong khong quan trong
        self.assertIsNone(await a._reject_reason(event(sender_id=999, username="wrencyber")))

    async def test_own_message_ignored(self):
        a = adapter(allowed=[str(FRIEND_ID)])
        self.assertIsNotNone(await a._reject_reason(event(sender_id=BOT_ID)))

    async def test_group_blocked_by_default(self):
        a = adapter(allowed=[str(GROUP_ID)])
        reason = await a._reject_reason(
            event(chat_id=GROUP_ID, private=False, mentioned=True))
        self.assertIn("TG_ALLOW_GROUPS", reason)

    async def test_group_needs_mention_even_when_enabled(self):
        a = adapter(allowed=[str(GROUP_ID)], allow_groups=True)
        reason = await a._reject_reason(event(chat_id=GROUP_ID, private=False))
        self.assertIn("mention", reason)

    async def test_group_mention_passes_when_group_id_allowed(self):
        a = adapter(allowed=[str(GROUP_ID)], allow_groups=True)
        self.assertIsNone(await a._reject_reason(
            event(chat_id=GROUP_ID, private=False, mentioned=True)))

    async def test_negative_group_id_parsed(self):
        a = adapter(allowed=[str(GROUP_ID)], allow_groups=True)
        self.assertIn(GROUP_ID, a.allowed_ids)

    async def test_empty_allowlist_accepts_everyone(self):
        # Chot chan nam o config.build_adapter; adapter thi van cho qua.
        a = adapter()
        self.assertIsNone(await a._reject_reason(event(sender_id=999)))


class MentionInGroupFromAllowedUserTest(unittest.IsolatedAsyncioTestCase):
    """Nguoi da duoc whitelist @mention trong group thi khong can whitelist ca group."""

    async def test_allowed_sender_passes_in_group(self):
        a = adapter(allowed=[str(FRIEND_ID)], allow_groups=True)
        self.assertIsNone(await a._reject_reason(
            event(sender_id=FRIEND_ID, chat_id=GROUP_ID, private=False, mentioned=True)))

    async def test_other_member_still_blocked(self):
        a = adapter(allowed=[str(FRIEND_ID)], allow_groups=True)
        reason = await a._reject_reason(
            event(sender_id=777, chat_id=GROUP_ID, private=False, mentioned=True))
        self.assertIn("TG_ALLOWED", reason)

    async def test_hint_logged_once_per_chat(self):
        a = adapter(allowed=[str(FRIEND_ID)], allow_groups=True)
        ev = event(sender_id=777, chat_id=GROUP_ID, private=False, mentioned=True)
        a._hint_if_called(ev, "khong nam trong TG_ALLOWED")
        self.assertIn(GROUP_ID, a._hinted)
        a._hint_if_called(ev, "khong nam trong TG_ALLOWED")   # lan 2 khong nhac nua
        self.assertEqual(len(a._hinted), 1)

    async def test_no_hint_for_plain_group_chatter(self):
        a = adapter(allowed=[str(FRIEND_ID)], allow_groups=True)
        a._hint_if_called(event(sender_id=777, chat_id=GROUP_ID, private=False), "x")
        self.assertEqual(a._hinted, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
