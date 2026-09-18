"""Logging gon nhe, to mau theo state de nhin dong doi trang thai cho de."""
from __future__ import annotations

import logging
import os
import sys

RESET = "\033[0m"
DIM = "\033[2m"
BOLD = "\033[1m"
GRAY = "\033[90m"

STATE_COLOR = {
    "IDLE": GRAY,
    "SEEN_DELAY": "\033[34m",
    "THINKING": "\033[35m",
    "TYPING": "\033[36m",
    "SENDING": "\033[32m",
    "COOLDOWN": "\033[33m",
}

_color_ok = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
log = logging.getLogger("humanbot")


def paint(color: str, text: str) -> str:
    return f"{color}{text}{RESET}" if _color_ok else text


class _Formatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%H:%M:%S")
        tag = getattr(record, "tag", record.levelname.lower())
        color = STATE_COLOR.get(tag, GRAY)
        return f"{paint(GRAY, ts)} {paint(color, tag.ljust(11))} {record.getMessage()}"


def setup_logging(level: str = "info") -> None:
    # Windows console mac dinh khong phai UTF-8 -> tieng Viet se vo.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_Formatter())
    log.handlers[:] = [handler]
    log.setLevel(getattr(logging, level.upper(), logging.INFO))
    log.propagate = False


def log_state(conv_id: str, frm: str, to: str, detail: str = "") -> None:
    msg = f"{paint(GRAY, '[' + str(conv_id) + ']')} {paint(DIM, frm + ' ->')} {paint(BOLD, to)}"
    if detail:
        msg += " " + paint(DIM, detail)
    log.info(msg, extra={"tag": to})


def fmt_ms(ms: float) -> str:
    if ms < 1000:
        return f"{round(ms)}ms"
    if ms < 60_000:
        return f"{ms / 1000:.1f}s"
    if ms < 3_600_000:
        return f"{ms / 60_000:.1f}m"
    return f"{ms / 3_600_000:.1f}h"
