"""Mo phong go sai chinh ta + tin nhan sua lai (dang *tu_dung) - dac san cua chat that.

Chi ap dung cho text thuong: bo qua code block, URL va so.
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

from .rng import Rng

NEIGHBORS = {
    "a": "sqwz", "b": "vghn", "c": "xdfv", "d": "serfcx", "e": "wsdr", "f": "drtgvc",
    "g": "ftyhbv", "h": "gyujnb", "i": "ujko", "j": "huikmn", "k": "jiolm", "l": "kop",
    "m": "njk", "n": "bhjm", "o": "iklp", "p": "ol", "q": "wa", "r": "edft",
    "s": "awedxz", "t": "rfgy", "u": "yhji", "v": "cfgb", "w": "qase", "x": "zsdc",
    "y": "tghu", "z": "asx",
}

_RE_WORD = re.compile(r"^[^\W\d_]+$", re.UNICODE)
_RE_URL = re.compile(r"https?://")


def _corrupt(word: str, rng: Rng) -> str:
    i = rng.int(1, len(word) - 2)   # khong dong vao ky tu dau/cuoi
    ch = word[i]
    op = rng.pick(("swap", "drop", "double", "neighbor"))
    if op == "swap":
        return word[:i] + word[i + 1] + ch + word[i + 2:]
    if op == "drop":
        return word[:i] + word[i + 1:]
    if op == "double":
        return word[: i + 1] + ch + word[i + 1:]
    near = NEIGHBORS.get(ch.lower())
    if not near:
        return word[:i] + word[i + 1:]
    return word[:i] + rng.pick(near) + word[i + 1:]


def maybe_typo(text: str, *, persona: dict, rng: Rng) -> Tuple[str, Optional[str]]:
    """Tra ve (tin_co_the_bi_sai, tin_sua_lai_hoac_None)."""
    cfg = persona.get("typo") or {}
    if not cfg.get("rate") or text.startswith("```") or _RE_URL.search(text):
        return text, None
    if not rng.chance(cfg["rate"]):
        return text, None

    words = text.split()
    candidates = [(i, w) for i, w in enumerate(words) if len(w) >= 5 and _RE_WORD.match(w)]
    if not candidates:
        return text, None

    idx, good = rng.pick(candidates)
    bad = _corrupt(good, rng)
    if bad == good:
        return text, None

    words[idx] = bad
    correction = "*" + good if rng.chance(cfg.get("correctionProb", 0.8)) else None
    return " ".join(words), correction
