"""Dang nhap Telegram mot lan roi in ra thong tin can dien vao .env.

    python tools/tg_login.py

Lam rieng buoc nay de: (1) nhap ma OTP trong terminal cho thoai mai, (2) sau do bot
khoi dong duoc ma khong can tuong tac, (3) lay san id/username cua nick con lai de
dien vao TG_ALLOWED.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from humanbot.adapters.telethon_adapter import phone_arg  # noqa: E402
from humanbot.config import load_dotenv                   # noqa: E402


async def main() -> int:
    load_dotenv()
    api_id, api_hash = os.environ.get("TG_API_ID"), os.environ.get("TG_API_HASH")
    if not api_id or not api_hash:
        print("Thieu TG_API_ID / TG_API_HASH trong .env")
        print("Lay tai https://my.telegram.org/apps (dang nhap bang so dien thoai)")
        return 1

    from telethon import TelegramClient

    session = os.environ.get("TG_SESSION", "data/humanbot")
    Path(session).parent.mkdir(parents=True, exist_ok=True)

    client = TelegramClient(session, int(api_id), api_hash)
    await client.start(phone=phone_arg(os.environ.get("TG_PHONE")))

    me = await client.get_me()
    uname = f"@{me.username}" if me.username else "(khong co username)"
    print()
    print("=" * 62)
    print(f"  Da dang nhap: {me.first_name or ''} {uname}")
    print(f"  user id     : {me.id}")
    print(f"  session file: {session}.session")
    print("=" * 62)
    print()
    print("Cac cuoc tro chuyen gan day - copy id vao TG_ALLOWED:")
    print()
    users, groups = [], []
    async for d in client.iter_dialogs(limit=50):
        ent = d.entity
        if d.is_user:
            if getattr(ent, "bot", False):
                continue
            tag = f"@{ent.username}" if getattr(ent, "username", None) else ""
            users.append(f"  {ent.id:<16} {tag:<22} {(d.name or '')[:28]}")
        elif d.is_group or d.is_channel:
            kind = "group" if d.is_group else "channel"
            groups.append(f"  {d.id:<16} {kind:<22} {(d.name or '')[:28]}")

    print("  -- nguoi --")
    for row in users or ["  (chua co)"]:
        print(row)
    print()
    print("  -- group / channel (id am, muon dung phai bat TG_ALLOW_GROUPS=true) --")
    for row in groups or ["  (chua co)"]:
        print(row)

    print()
    print("Vi du:  TG_ALLOWED=123456789,@nick_phu_cua_ban")
    print("Dien xong thi chay:  python -m humanbot --adapter telegram")
    await client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
