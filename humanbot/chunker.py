"""Tach cau tra loi dai thanh nhieu tin nhan nhu nguoi that hay lam.

Nguyen tac: khong bao gio cat giua code block, uu tien cat o dong trong
(LLM duoc yeu cau dung dong trong lam diem ngat tin), sau do moi den ranh gioi cau.
"""
from __future__ import annotations

import re
from typing import List

from .rng import Rng

_FENCE = re.compile(r"```[\s\S]*?```")
#: Cat o cuoi cau. `(?<!\d\.)` soi NGUOC HAI KY TU de khong cat sau "1." "2."
#: cua danh sach danh so - cat o do thi tin nhan ket thuc bang mot so lo loi
#: con noi dung cua buoc lai roi sang tin sau.
_SENTENCE = re.compile(r"(?<=[.!?…])(?<!\d\.)\s+|\n+")


#: Ky tu ve khung / mui ten - dau hieu cua mot so do ASCII.
_BOX_CHARS = set("─│┌┐└┘├┤┬┴┼━┃╔╗╚╝╠╣╦╩╬→←↑↓▲▼")


def looks_like_diagram(block: str) -> bool:
    """Doan nay la so do ve bang ky tu?

    So do phai duoc giu NGUYEN VEN: khong gop khoang trang, khong cat giua chung.
    Nhan dien bang ky tu ve khung, hoac bang cac dong thut dau chua '|'.
    """
    lines = block.splitlines()
    if len(lines) < 2:
        return False
    if any(ch in _BOX_CHARS for ch in block):
        return True
    # Kieu ve bang ASCII thuan: it nhat 2 dong co '|' hoac khung '+--'.
    # Dieu kien chat de van xuoi co dau gach ngang khong bi nham la so do.
    drawn = sum(1 for ln in lines if "|" in ln or ln.strip().startswith("+-"))
    return drawn >= 2


def split_fences(text: str) -> List[dict]:
    """Tach thanh cac khoi {type: text|code}."""
    out, last = [], 0
    for m in _FENCE.finditer(text):
        if m.start() > last:
            out.append({"type": "text", "text": text[last:m.start()]})
        out.append({"type": "code", "text": m.group(0)})
        last = m.end()
    if last < len(text):
        out.append({"type": "text", "text": text[last:]})
    return [b for b in out if b["text"].strip()]


def _sentences(text: str) -> List[str]:
    parts = [s.strip() for s in _SENTENCE.split(text) if s and s.strip()]
    return parts or [text.strip()]


def _pack(items: List[str], target: int) -> List[str]:
    """Gom cac cau lai thanh doan <= target ky tu."""
    out: List[str] = []
    cur = ""
    for s in items:
        if not cur:
            cur = s
        elif len(cur) + 1 + len(s) <= target:
            cur += " " + s
        else:
            out.append(cur)
            cur = s
    if cur:
        out.append(cur)
    return out


def chunk_reply(reply: str, *, persona: dict, rng: Rng) -> List[str]:
    """Tra ve danh sach tin nhan se gui lan luot."""
    cfg = persona["send"]
    # (noi_dung, hard) - hard=True nghia la diem ngat do chinh LLM dat (dong trong,
    # code block) nen tuyet doi khong gop lai.
    chunks: List[tuple[str, bool]] = []

    for b in split_fences((reply or "").strip()):
        if b["type"] == "code":
            chunks.append((b["text"].strip(), True))
            continue

        for raw in re.split(r"\n{2,}", b["text"]):
            if not raw.strip():
                continue
            if looks_like_diagram(raw):
                # So do: giu nguyen xuong dong va thut dau, va khong bao gio cat.
                chunks.append((raw.strip("\n"), True))
                continue

            p = re.sub(r"\s+", " ", raw).strip()
            if len(p) <= cfg["splitThreshold"] or not rng.chance(cfg["splitProb"]):
                chunks.append((p, True))
                continue
            # Doan dai: cat theo cau, moi tin ~60-100% nguong.
            target = round(cfg["splitThreshold"] * rng.between(0.6, 1.0))
            pieces = _pack(_sentences(p), target)
            chunks.extend((piece, i == 0) for i, piece in enumerate(pieces))

    # Gop manh vun (<25 ky tu) do viec cat cau tao ra - khong dung vao diem ngat cung.
    merged: List[str] = []
    for text, hard in chunks:
        prev_atomic = bool(merged) and (merged[-1].startswith("```")
                                        or looks_like_diagram(merged[-1]))
        if merged and not hard and len(text) < 25 and not prev_atomic:
            merged[-1] = merged[-1] + " " + text
        else:
            merged.append(text)

    # Tran so tin: phan du don het vao tin cuoi.
    cap = cfg["maxChunks"]
    if len(merged) > cap:
        merged = merged[: cap - 1] + [" ".join(merged[cap - 1:])]
    return merged or [""]
