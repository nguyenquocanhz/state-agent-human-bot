"""Adapter Telegram qua Telethon (MTProto - dang nhap bang tai khoan that).

Vi sao Telethon chu khong phai Bot API: chi tai khoan that moi
  - danh dau DA XEM duoc (send_read_acknowledge) -> dung tin hieu "seen",
  - phat "dang soan tin" lien tuc, va
  - khong bi gan nhan bot trong giao dien.

CANH BAO: day la userbot chay tren tai khoan that. Telegram cam spam/tu dong hoa
lam phien nguoi khac - chi dung cho tai khoan cua ban va nhung nguoi da dong y.
Luon dat TG_ALLOWED de gioi han doi tuong duoc tra loi.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from telethon import TelegramClient, events
from telethon.errors import FloodWaitError
from telethon.tl.functions.messages import SetTypingRequest
from telethon.tl.types import SendMessageCancelAction, SendMessageTypingAction

from ..machine import Inbound
from ..util import log

#: Telegram xoa trang thai "dang soan tin" sau ~6s -> phai nhac lai deu dan.
TYPING_REFRESH_S = 4.0


def phone_arg(phone: Optional[str]):
    """Tra ve thu hop le de dua vao TelegramClient.start(phone=...).

    Tham so `phone` cua Telethon mac dinh la MOT HAM di hoi nguoi dung. Truyen
    thang None vao se de len ham do -> Telethon gui None len server va no ra
    'TypeError: bytes or str expected, not NoneType'. Chua co so thi phai dua
    lai mot ham hoi, chu khong phai None.
    """
    if phone:
        return phone
    return lambda: input("So dien thoai (dang +84912345678): ").strip()


class TelethonAdapter:
    def __init__(self, *, api_id: int, api_hash: str, session: str,
                 phone: Optional[str] = None, allowed: Iterable[str] = (),
                 allow_groups: bool = False, media_dir: str = "data/media",
                 max_image_bytes: int = 8 * 1024 * 1024):
        self.client = TelegramClient(session, api_id, api_hash)
        self.phone = phone
        self.allow_groups = allow_groups
        self.media_dir = media_dir
        self.max_image_bytes = max_image_bytes
        self.allowed_ids: Set[int] = set()
        self.allowed_names: Set[str] = set()
        for item in allowed:
            item = str(item).strip().lstrip("@")
            if not item:
                continue
            if item.lstrip("-").isdigit():
                self.allowed_ids.add(int(item))
            else:
                self.allowed_names.add(item.lower())

        self._on_message = None
        self._me = None
        self._peers: Dict[Any, Any] = {}
        self._typing_tasks: Dict[Any, asyncio.Task] = {}
        self._hinted: Set[Any] = set()      # group da nhac 1 lan roi

    # ---------------------------------------------------------------- setup
    async def start(self, on_message) -> None:
        self._on_message = on_message
        await self.client.start(phone=phone_arg(self.phone))
        self._me = await self.client.get_me()
        who = "@" + self._me.username if self._me.username else str(self._me.id)
        scope = ("chi " + ", ".join(sorted(self.allowed_names | {str(i) for i in self.allowed_ids}))
                 if (self.allowed_ids or self.allowed_names) else "MOI NGUOI (nen gioi han lai!)")
        log.info(f"Telethon da dang nhap: {who} | tra loi: {scope}")

        self.client.add_event_handler(self._on_new_message, events.NewMessage(incoming=True))

    async def run_forever(self) -> None:
        await self.client.run_until_disconnected()

    async def stop(self) -> None:
        for task in list(self._typing_tasks.values()):
            task.cancel()
        self._typing_tasks.clear()
        await self.client.disconnect()

    # --------------------------------------------------------------- events
    async def _on_new_message(self, event) -> None:
        try:
            reason = await self._reject_reason(event)
            if reason:
                self._hint_if_called(event, reason)
                # In ra ca chat_id: day la cach de nhat de lay id cua group/nguoi
                # muon them vao TG_ALLOWED.
                log.debug("bo qua tin: chat_id=%s sender_id=%s (%s) - %s"
                          % (event.chat_id, event.sender_id,
                             "rieng" if event.is_private else "group", reason))
                return
            self._peers[event.chat_id] = await event.get_input_chat()
            text = (event.raw_text or "").strip()
            images = await self._download_images(event)

            if not text and not images:
                # Sticker/voice/file khac: chua ho tro doc noi dung -> bo qua.
                log.debug(f"[{event.chat_id}] bo qua tin khong co chu va khong co anh")
                return
            if not text:
                text = "(gui anh, khong kem chu)"

            self._on_message(event.chat_id,
                             Inbound(text=text, msg_id=event.id, raw=event, images=images))
        except Exception:
            log.exception("Loi khi nhan tin nhan")

    async def _download_images(self, event) -> List[str]:
        """Tai anh dinh kem ve dia de LLM doc duoc (vd: anh chup board).

        Chi lay ANH: sticker, voice, video, file khac deu bo qua.
        """
        msg = event.message
        doc = getattr(msg, "document", None)
        is_photo = bool(getattr(msg, "photo", None))
        is_image_doc = bool(
            doc and (getattr(doc, "mime_type", "") or "").startswith("image/")
            and not getattr(msg, "sticker", None))
        if not (is_photo or is_image_doc):
            return []

        size = getattr(doc, "size", 0) or 0
        if size > self.max_image_bytes:
            log.info(f"[{event.chat_id}] anh {size // 1024}KB vuot gioi han, bo qua")
            return []

        folder = Path(self.media_dir) / str(event.chat_id)
        folder.mkdir(parents=True, exist_ok=True)
        try:
            path = await msg.download_media(file=str(folder))
        except Exception as e:
            log.warning(f"[{event.chat_id}] tai anh that bai: {e}")
            return []
        if not path:
            return []
        log.info(f"[{event.chat_id}] da tai anh: {path}")
        return [str(path)]

    def _hint_if_called(self, event, reason: str) -> None:
        """Bi goi ma van im lang la trieu chung kho doan nhat -> noi thang phai sua gi.

        Chi nhac mot lan cho moi cuoc tro chuyen, va chi khi bot bi goi that su
        (@mention hoac reply), khong phai moi tin bi loc.
        """
        called = not event.is_private and (event.mentioned or event.is_reply)
        if not called or event.chat_id in self._hinted:
            return
        self._hinted.add(event.chat_id)
        log.info(f"Bi goi trong group {event.chat_id} nhung dang bo qua ({reason}).")
        log.info(f"    Muon tra loi ca group nay: them {event.chat_id} vao TG_ALLOWED"
                 + (" va dat TG_ALLOW_GROUPS=true" if not self.allow_groups else ""))

    async def _reject_reason(self, event) -> Optional[str]:
        """None = duoc tra loi. Nguoc lai tra ve ly do (de log ra cho de chinh)."""
        if event.out or (self._me and event.sender_id == self._me.id):
            return "tin cua chinh minh"
        if not event.is_private:
            if not self.allow_groups:
                return "dang o group ma TG_ALLOW_GROUPS=false"
            if not (event.mentioned or (event.is_reply and await self._is_reply_to_me(event))):
                return "trong group nhung khong @mention va khong reply vao bot"

        if not (self.allowed_ids or self.allowed_names):
            return None
        if event.sender_id in self.allowed_ids or event.chat_id in self.allowed_ids:
            return None
        sender = await event.get_sender()
        uname = (getattr(sender, "username", None) or "").lower()
        if uname and uname in self.allowed_names:
            return None
        return "khong nam trong TG_ALLOWED"

    async def _is_reply_to_me(self, event) -> bool:
        replied = await event.get_reply_message()
        return bool(replied and self._me and replied.sender_id == self._me.id)

    # ------------------------------------------------------------- hanh dong
    async def mark_seen(self, conv_id: Any, msg: Inbound) -> None:
        peer = await self._peer(conv_id)
        await self._call(lambda: self.client.send_read_acknowledge(peer, max_id=msg.msg_id))

    async def set_typing(self, conv_id: Any, on: bool) -> None:
        task = self._typing_tasks.pop(conv_id, None)
        if task:
            task.cancel()
        if on:
            self._typing_tasks[conv_id] = asyncio.create_task(self._typing_loop(conv_id))
        else:
            peer = await self._peer(conv_id)
            await self._call(lambda: self.client(SetTypingRequest(peer, SendMessageCancelAction())))

    async def _typing_loop(self, conv_id: Any) -> None:
        """Nhac lai trang thai dang soan tin cho den khi bi tat."""
        try:
            peer = await self._peer(conv_id)
            while True:
                await self._call(
                    lambda: self.client(SetTypingRequest(peer, SendMessageTypingAction())))
                await asyncio.sleep(TYPING_REFRESH_S)   # nhip that, khong nhan time_scale
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug(f"[{conv_id}] vong typing dung: {e}")

    async def send(self, conv_id: Any, text: str) -> None:
        peer = await self._peer(conv_id)
        await self._call(lambda: self.client.send_message(peer, text))

    # ------------------------------------------------------------- tien ich
    async def _peer(self, conv_id: Any):
        peer = self._peers.get(conv_id)
        if peer is None:
            peer = await self.client.get_input_entity(conv_id)
            self._peers[conv_id] = peer
        return peer

    async def _call(self, factory):
        """Boc moi loi goi API: gap FloodWait thi cho dung so giay Telegram yeu cau roi thu lai.

        Nhan vao mot ham tao coroutine (khong phai coroutine) de con retry duoc.
        """
        try:
            return await factory()
        except FloodWaitError as e:
            log.warning(f"FloodWait {e.seconds}s - cho roi thu lai")
            await asyncio.sleep(e.seconds + 1)
            try:
                return await factory()
            except FloodWaitError:
                log.error("Van bi FloodWait sau khi cho - bo qua loi goi nay")
                return None
