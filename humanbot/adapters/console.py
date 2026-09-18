"""Adapter console: chat thang trong terminal de thu state machine.

Khong can Telegram, khong can dang nhap. Cac tin hieu "da xem" / "dang soan tin"
duoc in ra man hinh dung luc bot phat chung => nhin thay ro nhip cua may trang thai.
"""
from __future__ import annotations

import asyncio
import sys
import threading
from typing import Any

from ..machine import Inbound
from ..util import DIM, GRAY, paint

CONV_ID = "console"


class ConsoleAdapter:
    def __init__(self, persona_name: str = "Bot"):
        self.name = persona_name
        self._on_message = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = threading.Event()
        self._typing = False

    async def start(self, on_message) -> None:
        self._on_message = on_message
        self._loop = asyncio.get_running_loop()
        print(paint(GRAY, f"-- chat thu voi {self.name}. Ctrl+C de thoat --"))
        print(paint(GRAY, "   gui anh: /img duong/dan/anh.jpg cau hoi kem theo"))
        threading.Thread(target=self._read_stdin, daemon=True).start()

    def _read_stdin(self) -> None:
        for line in sys.stdin:
            if self._stop.is_set():
                return
            text = line.strip()
            if not text:
                continue
            images = []
            if text.startswith("/img "):
                # /img <duong_dan> [cau hoi]  - thu soi anh ngay trong terminal
                rest = text[5:].strip()
                path, _, after = rest.partition(" ")
                images = [path]
                text = after.strip() or "(gui anh, khong kem chu)"
            msg = Inbound(text=text, msg_id=None, images=images)
            self._loop.call_soon_threadsafe(self._on_message, CONV_ID, msg)
        # Het stdin (Ctrl+D hoac pipe dong) -> thoat, giong nhu dong cua so chat.
        print(paint(GRAY, "-- het input, thoat --"))
        self._stop.set()

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(0.5)

    async def stop(self) -> None:
        self._stop.set()

    async def mark_seen(self, conv_id: Any, msg: Inbound) -> None:
        print(paint(DIM, "   [da xem]"))

    async def set_typing(self, conv_id: Any, on: bool) -> None:
        if on and not self._typing:
            print(paint(DIM, f"   [{self.name} dang soan tin...]"))
        self._typing = on

    async def send(self, conv_id: Any, text: str) -> None:
        self._typing = False
        lines = text.splitlines() or [""]
        # Mot tin nhan nhieu dong van la MOT tin: in ten mot lan roi thut le
        # cac dong sau, giong cach Telegram hien thi.
        print(f"{self.name}: {lines[0]}")
        pad = " " * (len(self.name) + 2)
        for line in lines[1:]:
            print(pad + line)
