"""Tam ly hoc cua bot: bien mot tin nhan den thanh cac khoang tre giong nguoi that.

Tat ca deu la ham thuan (pure) => de unit test, de tinh chinh.

Ba bien trang thai noi tai cua nhan vat:
    energy      0..1   do tinh tao   -> go nhanh/cham, nghi lau hay nhanh
    engagement  0..1   do hao hung   -> seen lien hay de tin nhan treo
    attention   ACTIVE | IDLE | AWAY | ASLEEP -> co dang cam may khong
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Sequence

from .rng import Rng, clamp


class ATT:
    ACTIVE = "ACTIVE"
    IDLE = "IDLE"
    AWAY = "AWAY"
    ASLEEP = "ASLEEP"


#: Nhip sinh hoc: he so tinh tao theo gio trong ngay (0h..23h).
CIRCADIAN = [
    0.45, 0.40, 0.38, 0.38, 0.42, 0.55, 0.70, 0.85,
    0.95, 1.00, 1.00, 0.98, 0.90, 0.80, 0.85, 0.95,
    0.98, 0.95, 0.90, 0.92, 0.95, 0.92, 0.80, 0.60,
]

_RE_QUESTION = re.compile(r"[?？]")
_RE_CODE = re.compile(r"(```|\bfunction\b|\bclass\b|\bdef\b|[{};]\s*$)", re.M)
_RE_NUM = re.compile(r"(\d{3,}|\d+[.,]\d+)")
_RE_HEAVY = re.compile(
    r"\b(tai sao|vi sao|so sanh|giai thich|phan tich|why|how|compare|explain)\b", re.I)
_RE_FINISHED = re.compile(r"[.!?)\]\"\x27…]$")


def local_parts(now_ms: float, persona: dict) -> datetime:
    """Gio dia phuong cua nhan vat (theo timezone khai bao trong persona)."""
    off = (persona.get("sleep") or {}).get("timezoneOffsetMin", 0)
    return datetime.fromtimestamp(now_ms / 1000.0, timezone.utc) + timedelta(minutes=off)


def circadian_factor(now_ms: float, persona: dict) -> float:
    return CIRCADIAN[local_parts(now_ms, persona).hour]


def is_sleep_hour(now_ms: float, persona: dict) -> bool:
    """Ho tro khung gio vat qua nua dem (vd 23h -> 7h)."""
    s = persona.get("sleep") or {}
    if not s.get("enabled"):
        return False
    hour = local_parts(now_ms, persona).hour
    start, end = s["startHour"], s["endHour"]
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def ms_until_wake(now_ms: float, persona: dict, rng: Rng) -> float:
    """Con bao lau nua thi tinh day (ms)."""
    s = persona["sleep"]
    t = local_parts(now_ms, persona)
    hours_left = (s["endHour"] - t.hour + 24) % 24 or 24
    base = hours_left * 3_600_000 - t.minute * 60_000
    jitter = rng.log_normal(s.get("wakeJitterMedianMs", 600_000), 0.6)
    return max(60_000.0, base + jitter)


def attention_of(ctx: dict, now_ms: float, persona: dict) -> str:
    """Trang thai chu y suy ra tu khoang lang cuoi cung cua cuoc hoi thoai."""
    if is_sleep_hour(now_ms, persona):
        return ATT.ASLEEP
    gap = now_ms - (ctx.get("lastActivityAt") or 0)
    r = persona["rhythm"]
    if gap <= r["activeWindowMs"]:
        return ATT.ACTIVE
    if gap <= r["idleWindowMs"]:
        return ATT.IDLE
    return ATT.AWAY


def complexity_of(text: str) -> float:
    """Do nang cua tin den: 0 (chao hoi) .. ~3 (cau hoi dai, nhieu y, co code)."""
    t = text or ""
    c = math.log1p(len(t)) / math.log(220)
    c += min(2, len(_RE_QUESTION.findall(t))) * 0.35
    if _RE_CODE.search(t):
        c += 0.8
    if _RE_NUM.search(t):
        c += 0.25
    if _RE_HEAVY.search(t):
        c += 0.45
    return clamp(c, 0.0, 3.2)


def seen_delay_ms(*, persona: dict, rng: Rng, att: str, ctx: dict, batch: Sequence[Any]) -> float:
    """Do tre truoc khi danh dau da xem (mark read)."""
    s = persona["seen"]
    median = {
        ATT.ACTIVE: s["activeMedianMs"],
        ATT.IDLE: s["idleMedianMs"],
        ATT.AWAY: s["awayMedianMs"],
        ATT.ASLEEP: s["awayMedianMs"],
    }[att]
    ms = rng.log_normal(median, s["sigma"])
    ms *= 1.6 - 0.7 * clamp(ctx.get("engagement", 0.5), 0, 1)   # hao hung -> liec may som
    if len(batch) > 1:
        ms *= 0.75                                              # nhieu tin lien tiep -> rung lien tuc
    if att == ATT.ACTIVE:
        ms *= 0.9 + 0.2 * (1 - clamp(ctx.get("energy", 1.0), 0, 1))
    return clamp(ms, s["minMs"], s["maxMs"])


def think_delay_ms(*, persona: dict, rng: Rng, batch: Sequence[Any], ctx: dict) -> float:
    """Thoi gian suy nghi = doc tin + hieu + quyet dinh tra loi."""
    th = persona["think"]
    text = " ".join(m.text for m in batch)
    read_ms = (len(text) / th["readCps"]) * 1000
    ms = read_ms + th["baseMs"] + complexity_of(text) * th["perComplexityMs"]
    ms *= rng.log_normal(1.0, th["sigma"])
    ms *= 1.35 - 0.35 * clamp(ctx.get("energy", 1.0), 0, 1)      # met -> nghi lau hon
    ms *= 1.25 - 0.25 * clamp(ctx.get("engagement", 0.5), 0, 1)  # hao hung -> phan xa nhanh
    return clamp(ms, th["minMs"], th["maxMs"])


def burst_grace_ms(*, persona: dict, rng: Rng, batch: Sequence[Any]) -> float:
    """Cua so cho them: nguoi that doi xem doi phuong con go tiep khong."""
    last = (batch[-1].text if batch else "").strip()
    unfinished = not _RE_FINISHED.search(last) or len(last) < 12
    if not unfinished:
        return 0.0
    return rng.log_normal(persona["think"]["burstGraceMs"], 0.35)


def cps_for(*, persona: dict, rng: Rng, ctx: dict, now_ms: float) -> float:
    """Toc do go thuc te (ky tu/giay), da tinh met moi + nhip sinh hoc."""
    t = persona["typing"]
    base = (t["wpm"] * 5) / 60.0                      # 1 tu ~ 5 ky tu
    personal = rng.log_normal(1.0, t["wpmSigma"])     # hom nay go nhanh hay cham
    energy_f = 0.75 + 0.35 * clamp(ctx.get("energy", 1.0), 0, 1)
    day_f = 0.85 + 0.2 * circadian_factor(now_ms, persona)
    return max(2.0, base * personal * energy_f * day_f)


def typing_ms_for(text: str, *, persona: dict, rng: Rng, ctx: dict, now_ms: float) -> float:
    """Thoi gian go xong 1 doan tin nhan."""
    t = persona["typing"]
    cps = cps_for(persona=persona, rng=rng, ctx=ctx, now_ms=now_ms)
    startup = rng.between(t["startupMinMs"], t["startupMaxMs"])
    pause_factor = 1 + min(0.3, (len(text) / 400) * 0.25)   # cang dai cang hay khung lai
    return clamp(startup + (len(text) / cps) * 1000 * pause_factor, 400, t["maxChunkMs"])


def inter_chunk_ms(*, persona: dict, rng: Rng) -> float:
    s = persona["send"]
    return clamp(rng.log_normal(s["interChunkMedianMs"], s["interChunkSigma"]), 200, 8000)


def cooldown_ms(*, persona: dict, rng: Rng) -> float:
    c = persona["cooldown"]
    return clamp(rng.log_normal(c["medianMs"], c["sigma"]), 300, 20_000)


def update_rhythm(ctx: dict, *, now_ms: float, persona: dict,
                  inbound_chars: int = 0, outbound_chars: int = 0) -> dict:
    """Cap nhat energy/engagement sau moi luot. Goi TRUOC khi tinh cac do tre."""
    r = persona["rhythm"]
    gap_min = max(0.0, (now_ms - (ctx.get("lastActivityAt") or now_ms)) / 60_000)

    # Nghi thi hoi suc, go nhieu thi mat suc; tran energy theo nhip sinh hoc.
    ceiling = clamp(0.55 + 0.45 * circadian_factor(now_ms, persona), 0.3, 1.0)
    energy = clamp(ctx.get("energy", 1.0) + gap_min * r["energyRecoverPerMin"], 0.2, ceiling)
    energy = clamp(energy - outbound_chars * r["energyDrainPerChar"], 0.2, ceiling)

    # Hao hung tang khi doi phuong nhan lien tuc, nguoi di theo thoi gian im lang.
    engagement = clamp(ctx.get("engagement", 0.5) - gap_min * r["engagementDecayPerMin"], 0, 1)
    if inbound_chars > 0:
        engagement = clamp(
            engagement + r["engagementGain"] * clamp(inbound_chars / 80, 0.3, 1.5), 0, 1)

    return {**ctx, "energy": energy, "engagement": engagement}
