"""Giao dien chung cho moi kenh chat (Telegram/Telethon, console, ...).

State machine chi biet 4 hanh dong nay, nen them kenh moi la viet them 1 adapter.
"""
from __future__ import annotations

from typing import Any, Callable, Protocol

from ..machine import Inbound

#: Callback adapter goi khi co tin nhan moi: on_message(conv_id, Inbound)
OnMessage = Callable[[Any, Inbound], None]


class Adapter(Protocol):
    async def start(self, on_message: OnMessage) -> None:
        """Ket noi + bat dau nhan tin nhan."""

    async def run_forever(self) -> None:
        """Chay den khi bi ngat (Ctrl+C)."""

    async def stop(self) -> None:
        ...

    async def mark_seen(self, conv_id: Any, msg: Inbound) -> None:
        """Danh dau da doc (hien 2 tick xanh / da xem)."""

    async def set_typing(self, conv_id: Any, on: bool) -> None:
        """Bat/tat trang thai dang soan tin."""

    async def send(self, conv_id: Any, text: str) -> None:
        """Gui 1 tin nhan."""
