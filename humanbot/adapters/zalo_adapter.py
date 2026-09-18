"""Adapter Zalo cho TAI KHOAN CA NHAN (khong phai Official Account).

Zalo khong co API chinh thuc cho tai khoan ca nhan. Thu vien Python duy nhat
(zlapi) da bi archive tu 11/2024 nen coi nhu chet; thu vien con song la
`zca-js` (TypeScript, gia lap Zalo Web). Vi vay phan noi chuyen voi Zalo chay
bang Node, con may trang thai van la Python - hai ben noi qua stdio, moi dong
mot JSON. Xem zalo_bridge/bridge.mjs.

Doi lai su phuc tap do, Zalo ca nhan giu duoc CA BA tin hieu giong Telegram:

    | Tin hieu             | Telegram | Zalo ca nhan | Zalo OA |
    | mark read (da xem)   | co       | co           | KHONG   |
    | typing (dang soan)   | co       | co           | KHONG   |
    | do tre truoc khi gui | co       | co           | co      |

CANH BAO: zca-js gia lap trinh duyet, trai dieu khoan cua Zalo va co the lam
khoa tai khoan. Rui ro cao hon Telegram nhieu, vi Telegram cong khai API va
cho phep client thu ba, con Zalo thi khong.

TRANG THAI KIEM CHUNG: da xac nhan zca-js 2.2.0 cai duoc, import duoc tren
Node 24 va co du api.sendMessage / api.sendTypingEvent / api.sendSeenEvent /
api.listener. CHUA chay thong voi tai khoan Zalo that (can quet QR).
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

from ..machine import Inbound
from ..util import log

#: Zalo cung xoa trang thai "dang soan tin" sau vai giay -> phai nhac lai.
TYPING_REFRESH_S = 4.0

THREAD_USER = 0
THREAD_GROUP = 1


class ZaloAdapter:
    def __init__(self, *, bridge_dir: str = "zalo_bridge", node_bin: str = "node",
                 allowed: Iterable[str] = (), allow_groups: bool = False,
                 data_dir: str = "data"):
        self.bridge_dir = Path(bridge_dir)
        self.node_bin = node_bin
        self.allow_groups = allow_groups
        self.data_dir = data_dir
        self.allowed: Set[str] = {str(a).strip() for a in allowed if str(a).strip()}

        self._on_message = None
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader: Optional[asyncio.Task] = None
        self._typing_tasks: Dict[Any, asyncio.Task] = {}
        self._threads: Dict[str, int] = {}      # conv_id -> ThreadType
        self._stopped = asyncio.Event()

    # ---------------------------------------------------------------- setup
    async def start(self, on_message) -> None:
        self._on_message = on_message
        script = self.bridge_dir / "bridge.mjs"
        if not script.exists():
            raise SystemExit(f"Khong thay {script}. Chay: cd {self.bridge_dir} && npm install")
        if not (self.bridge_dir / "node_modules" / "zca-js").exists():
            raise SystemExit(f"Chua cai zca-js. Chay: cd {self.bridge_dir} && npm install")

        self._proc = await asyncio.create_subprocess_exec(
            self.node_bin, "bridge.mjs",
            cwd=str(self.bridge_dir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=None,                        # de bridge in huong dan thang ra man hinh
            env=self._env(),
        )
        self._reader = asyncio.create_task(self._read_loop())
        scope = ", ".join(sorted(self.allowed)) if self.allowed else "MOI NGUOI (nen gioi han!)"
        log.info(f"Zalo bridge dang khoi dong | tra loi: {scope}")

    def _env(self) -> dict:
        import os
        env = dict(os.environ)
        data = Path(self.data_dir).resolve()
        env["ZALO_DATA_DIR"] = str(data)
        env["ZALO_CREDENTIALS"] = str(data / "zalo-credentials.json")
        env["ZALO_QR_PATH"] = str(data / "zalo-qr.png")
        return env

    async def run_forever(self) -> None:
        await self._stopped.wait()

    async def stop(self) -> None:
        for task in list(self._typing_tasks.values()):
            task.cancel()
        self._typing_tasks.clear()
        if self._proc and self._proc.returncode is None:
            try:
                await self._write({"op": "quit"})
                await asyncio.wait_for(self._proc.wait(), timeout=5)
            except Exception:
                self._proc.kill()
        if self._reader:
            self._reader.cancel()
        self._stopped.set()

    # ------------------------------------------------------------- giao thuc
    async def _read_loop(self) -> None:
        assert self._proc and self._proc.stdout
        try:
            async for raw in self._proc.stdout:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    log.debug(f"[zalo] dong khong phai JSON: {line[:120]}")
                    continue
                self._handle(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[zalo] vong doc bridge loi")
        finally:
            log.warning("[zalo] bridge da dong")
            self._stopped.set()

    def _handle(self, event: dict) -> None:
        kind = event.get("ev")
        if kind == "ready":
            me = event.get("me") or {}
            log.info(f"Zalo da dang nhap: {me.get('name') or '?'} (id {me.get('id') or '?'})")
        elif kind == "qr":
            log.info(f"Mo file {event.get('path')} roi quet bang Zalo tren dien thoai")
        elif kind == "error":
            log.warning(f"[zalo] loi khi {event.get('op')}: {event.get('message')}")
        elif kind == "message":
            self._on_inbound(event)

    def _on_inbound(self, event: dict) -> None:
        conv = str(event.get("conv") or "")
        thread_type = int(event.get("type") or THREAD_USER)
        text = (event.get("text") or "").strip()
        if not conv or not text:
            return
        if thread_type == THREAD_GROUP and not self.allow_groups:
            log.debug(f"[zalo] bo qua tin group {conv}: ZALO_ALLOW_GROUPS=false")
            return
        if self.allowed and conv not in self.allowed:
            log.debug(f"[zalo] bo qua tin tu {conv}: khong nam trong ZALO_ALLOWED")
            return

        self._threads[conv] = thread_type
        if self._on_message:
            self._on_message(conv, Inbound(text=text, msg_id=event.get("msgId"),
                                           raw=event.get("data")))

    async def _write(self, op: dict) -> None:
        if not (self._proc and self._proc.stdin) or self._proc.returncode is not None:
            return
        self._proc.stdin.write((json.dumps(op, ensure_ascii=False) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    # ------------------------------------------------------------- hanh dong
    async def mark_seen(self, conv_id: Any, msg: Inbound) -> None:
        if not msg.raw:
            log.debug("[zalo] khong co du lieu tin goc -> bo qua mark seen")
            return
        await self._write({"op": "seen", "conv": str(conv_id),
                           "type": self._threads.get(str(conv_id), THREAD_USER),
                           "data": msg.raw})

    async def set_typing(self, conv_id: Any, on: bool) -> None:
        task = self._typing_tasks.pop(conv_id, None)
        if task:
            task.cancel()
        if on:
            self._typing_tasks[conv_id] = asyncio.create_task(self._typing_loop(conv_id))
        # Zalo khong co lenh tat typing - no tu het han sau vai giay.

    async def _typing_loop(self, conv_id: Any) -> None:
        try:
            while True:
                await self._write({"op": "typing", "conv": str(conv_id),
                                   "type": self._threads.get(str(conv_id), THREAD_USER)})
                await asyncio.sleep(TYPING_REFRESH_S)    # nhip that, khong nhan time_scale
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.debug(f"[zalo] vong typing dung: {e}")

    async def send(self, conv_id: Any, text: str) -> None:
        await self._write({"op": "send", "conv": str(conv_id),
                           "type": self._threads.get(str(conv_id), THREAD_USER),
                           "text": text})
