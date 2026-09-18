"""Dung system prompt tu persona + dong goi luot noi cua user kem ngu canh thoi gian."""
from __future__ import annotations

from typing import Sequence

from .humanizer import local_parts
from .util import fmt_ms


def build_system_prompt(persona: dict) -> str:
    style = "\n".join("- " + s for s in persona.get("style", []))
    return "\n".join([
        f"Ban dang dong vai {persona['name']}. {persona.get('bio', '')}".strip(),
        "",
        "Cach nhan tin:",
        style,
        "- Tra loi bang dung ngon ngu ma doi phuong dang dung.",
        "- Khi can gui nhieu tin lien tiep, ngan cach chung bang MOT DONG TRONG."
        " Moi doan la mot tin nhan rieng.",
        "- Khong mo ta hanh dong, khong tieu de, khong bullet, khong markdown trang trong.",
        "- Neu khong biet thi noi khong biet, dung bia.",
        "",
        "Chi xuat ra noi dung tin nhan, khong giai thich gi them.",
    ])


def build_user_turn(*, batch: Sequence, ctx: dict, persona: dict, now_ms: float,
                    undelivered: Sequence[str] = ()) -> str:
    """Luot cua user + meta ngu canh (gio giac, khoang lang) de model chon giong dieu.

    `undelivered` la phan cau tra loi truoc da soan nhung BI NGAT nen chua gui di.
    Claude-cli van luu no trong lich su session, nen phai noi ro de model dung
    tuong la doi phuong da doc roi.
    """
    t = local_parts(now_ms, persona)
    last_replied = ctx.get("lastRepliedAt") or 0
    meta = [f"gio_hien_tai={t.hour:02d}:{t.minute:02d}"]
    meta.append(f"khoang_lang={fmt_ms(now_ms - last_replied)}" if last_replied
                else "lan_dau_nhan_tin=true")
    if len(batch) > 1:
        meta.append(f"so_tin_lien_tiep={len(batch)}")

    parts = [f"<ngu_canh>{' '.join(meta)}</ngu_canh>"]
    if undelivered:
        parts.append(
            "<chua_gui>Phan sau ban vua soan nhung CHUA GUI DI (doi phuong chua he doc): "
            + " | ".join(undelivered)
            + ". Neu van con can thiet thi noi lai trong luot nay.</chua_gui>")
    parts.append("\n".join(m.text for m in batch))
    return "\n".join(parts)
