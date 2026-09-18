"""Adapter Zalo Official Account (OA).

QUAN TRONG - Zalo khac Telegram o cho nay:

    | Tin hieu            | Telegram (Telethon) | Zalo OA |
    | mark read (da xem)  | co                  | KHONG   |
    | typing (dang soan)  | co                  | KHONG   |
    | do tre truoc khi gui| co                  | co      |

Zalo OA OpenAPI chi cho GUI tin. Khong co endpoint nao de OA bao "da xem" hay
"dang soan tin" (webhook co su kien user_seen_message nhung do la Zalo bao cho
MINH biet nguoi dung da doc, khong phai chieu nguoc lai).

Nghia la tren Zalo, hai trong ba tin hieu cua du an nay bi mat. Cai con lai -
do tre truoc khi tra loi, tach tin nhieu doan, nhip theo gio giac va do met -
van chay binh thuong, va do cung la phan chiem nhieu cong suc nhat.

TRANG THAI KIEM CHUNG: hinh dang request lay tu tai lieu cong dong (endpoint
v3.0/oa/message/cs, header access_token, body recipient/message). CHUA chay
duoc voi token that vi can mot OA da duyet. Neu Zalo doi, sua bang bien moi
truong ZALO_API_BASE / ZALO_TOKEN_HEADER chu khong phai sua code.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterable, Optional, Set

from ..machine import Inbound
from ..util import log

DEFAULT_API_BASE = "https://openapi.zalo.me/v3.0/oa/"
DEFAULT_TOKEN_HEADER = "access_token"


class ZaloAdapter:
    def __init__(self, *, access_token: str, port: int = 8080, path: str = "/webhook",
                 allowed: Iterable[str] = (), api_base: str = DEFAULT_API_BASE,
                 token_header: str = DEFAULT_TOKEN_HEADER, app_secret: Optional[str] = None,
                 app_id: Optional[str] = None, verify_signature: bool = False,
                 timeout: float = 20.0):
        self.access_token = access_token
        self.port = port
        self.path = path
        self.api_base = api_base if api_base.endswith("/") else api_base + "/"
        self.token_header = token_header
        self.app_secret = app_secret
        self.app_id = app_id
        self.verify_signature = verify_signature
        self.timeout = timeout
        self.allowed: Set[str] = {str(a).strip() for a in allowed if str(a).strip()}

        self._on_message = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server: Optional[ThreadingHTTPServer] = None
        self._stop = threading.Event()
        self._warned: Set[str] = set()

    # ---------------------------------------------------------------- setup
    async def start(self, on_message) -> None:
        self._on_message = on_message
        self._loop = asyncio.get_running_loop()

        adapter = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):          # noqa: N802 - ten do BaseHTTPRequestHandler quy dinh
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b""
                ok = adapter._handle_webhook(raw, dict(self.headers))
                self.send_response(200 if ok else 401)
                self.end_headers()
                self.wfile.write(b"ok" if ok else b"bad signature")

            def do_GET(self):           # noqa: N802
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"humanbot zalo webhook")

            def log_message(self, *args):
                pass                     # khong spam log cua http.server

        self._server = ThreadingHTTPServer(("0.0.0.0", self.port), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        scope = ", ".join(sorted(self.allowed)) if self.allowed else "MOI NGUOI (nen gioi han!)"
        log.info(f"Zalo webhook dang nghe tai 0.0.0.0:{self.port}{self.path} | tra loi: {scope}")
        log.info("Zalo OA khong ho tro 'da xem' va 'dang soan tin' - chi con do tre + tach tin")

    async def run_forever(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(0.5)

    async def stop(self) -> None:
        self._stop.set()
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    # --------------------------------------------------------------- webhook
    def _handle_webhook(self, raw: bytes, headers: dict) -> bool:
        """Chay trong thread cua HTTP server -> khong duoc dung await o day."""
        if self.verify_signature and not self._signature_ok(raw, headers):
            log.warning("Webhook Zalo sai chu ky - bo qua")
            return False
        try:
            event = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            log.warning("Webhook Zalo khong phai JSON")
            return True

        msg = self.parse_event(event)
        if msg is None:
            log.debug(f"Bo qua su kien Zalo: {event.get('event_name')}")
            return True

        conv_id, inbound = msg
        if self.allowed and str(conv_id) not in self.allowed:
            log.debug(f"Bo qua tin tu {conv_id}: khong nam trong ZALO_ALLOWED")
            return True

        if self._loop and self._on_message:
            self._loop.call_soon_threadsafe(self._on_message, conv_id, inbound)
        return True

    @staticmethod
    def parse_event(event: dict):
        """Tra ve (conv_id, Inbound) neu la tin nhan chu tu nguoi dung, khong thi None."""
        name = event.get("event_name") or ""
        if not name.startswith("user_send"):
            return None
        text = ((event.get("message") or {}).get("text") or "").strip()
        sender = str(((event.get("sender") or {}).get("id") or "")).strip()
        if not text or not sender:
            return None
        return sender, Inbound(text=text, msg_id=(event.get("message") or {}).get("msg_id"),
                               raw=event)

    def _signature_ok(self, raw: bytes, headers: dict) -> bool:
        """Zalo ky bang SHA256(app_id + data + timestamp + oa_secret_key).

        Cong thuc nay lay tu tai lieu, CHUA doi chieu voi traffic that - vi vay
        mac dinh tat (ZALO_VERIFY_SIGNATURE=false). Bat len khi da xac nhan dung.
        """
        got = headers.get("X-ZEvent-Signature") or headers.get("x-zevent-signature") or ""
        if not (self.app_secret and self.app_id):
            return False
        try:
            timestamp = str(json.loads(raw.decode("utf-8")).get("timestamp", ""))
        except Exception:
            return False
        mac = hashlib.sha256(
            (self.app_id + raw.decode("utf-8") + timestamp + self.app_secret).encode("utf-8")
        ).hexdigest()
        return got.removeprefix("mac=") == mac

    # ------------------------------------------------------------- hanh dong
    async def mark_seen(self, conv_id: Any, msg: Inbound) -> None:
        self._warn_once("seen", "Zalo OA khong co API danh dau da xem - bo qua buoc nay")

    async def set_typing(self, conv_id: Any, on: bool) -> None:
        if on:
            self._warn_once("typing", "Zalo OA khong co trang thai dang soan tin - bo qua")

    async def send(self, conv_id: Any, text: str) -> None:
        payload = {"recipient": {"user_id": str(conv_id)}, "message": {"text": text}}
        await asyncio.to_thread(self._post, "message/cs", payload)

    def _post(self, endpoint: str, payload: dict) -> dict:
        req = urllib.request.Request(
            self.api_base + endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", self.token_header: self.access_token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Zalo API {e.code}: {e.read().decode('utf-8', 'replace')[:300]}")
        if body.get("error"):
            raise RuntimeError(f"Zalo API loi {body.get('error')}: {body.get('message')}")
        return body

    def _warn_once(self, key: str, message: str) -> None:
        if key not in self._warned:
            self._warned.add(key)
            log.info(message)
