"""Luu trang thai lau dai cho tung cuoc hoi thoai.

Gom: session-id cua claude-cli (de resume dung mach hoi thoai), energy/engagement,
va cac moc thoi gian. Ghi file JSON atomic, co debounce.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path


class SessionStore:
    def __init__(self, path: str = "data/sessions.json", flush_after: float = 1.5):
        self.path = Path(path)
        self.flush_after = flush_after
        self._lock = threading.Lock()
        self._timer = None
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self.data = {}

    def get(self, conv_id) -> dict:
        key = str(conv_id)
        if key not in self.data:
            self.data[key] = {
                "convId": key,
                "sessionId": None,
                "energy": 1.0,
                "engagement": 0.5,
                "lastActivityAt": 0,
                "lastRepliedAt": 0,
                "turns": 0,
            }
        return self.data[key]

    def set(self, conv_id, **patch) -> dict:
        rec = {**self.get(conv_id), **patch}
        self.data[str(conv_id)] = rec
        self._schedule()
        return rec

    def _schedule(self) -> None:
        with self._lock:
            if self._timer is not None:
                return
            self._timer = threading.Timer(self.flush_after, self._on_timer)
            self._timer.daemon = True
            self._timer.start()

    def _on_timer(self) -> None:
        with self._lock:
            self._timer = None
        self.flush()

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            Path(tmp).unlink(missing_ok=True)
            raise

    def close(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        self.flush()
