"""Tach cau tra loi dai thanh nhieu tin nhan nhu nguoi that hay lam.

Nguyen tac: khong bao gio cat giua code block, uu tien cat o dong trong
(LLM duoc yeu cau dung dong trong lam diem ngat tin), sau do moi den ranh gioi cau.
"""
from __future__ import annotations

import re
from typing import List

from .rng import Rng

_FENCE = re.compile(r"```[\s\S]*?```")
_SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n+")


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

        paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n{2,}", b["text"])]
        for p in [p for p in paras if p]:
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
        if merged and not hard and len(text) < 25 and not merged[-1].startswith("```"):
            merged[-1] = merged[-1] + " " + text
        else:
            merged.append(text)

    # Tran so tin: phan du don het vao tin cuoi.
    cap = cfg["maxChunks"]
    if len(merged) > cap:
        merged = merged[: cap - 1] + [" ".join(merged[cap - 1:])]
    return merged or [""]
