"""Dung system prompt tu persona + dong goi luot noi cua user kem ngu canh thoi gian."""
from __future__ import annotations

from typing import Sequence

from .humanizer import local_parts
from .util import fmt_ms


#: Luat mac dinh, hop cho persona tam phao. Persona co the thay bang khoa "rules".
DEFAULT_RULES = [
    "Tra loi bang dung ngon ngu ma doi phuong dang dung.",
    "Khi can gui nhieu tin lien tiep, ngan cach chung bang MOT DONG TRONG."
    " Moi doan la mot tin nhan rieng.",
    "Khong mo ta hanh dong, khong tieu de, khong bullet, khong markdown trang trong.",
    "Neu khong biet thi noi khong biet, dung bia.",
]


def build_system_prompt(persona: dict) -> str:
    """Rap system prompt tu persona.

    Cac khoa dung o day (tat ca deu tuy chon tru `name`):
        bio        mot cau gioi thieu nhan vat
        expertise  kien thuc/quy trinh chuyen mon - phan nay lam nen chat luong
                   cau tra loi, persona tam phao thi bo trong
        style      giong dieu, cach nhan tin
        rules      thay the DEFAULT_RULES khi persona can dinh dang khac
                   (vi du tho sua chua can liet ke tung buoc do)
    """
    parts = [f"Ban dang dong vai {persona['name']}. {persona.get('bio', '')}".strip()]

    if persona.get("expertise"):
        parts += ["", "Chuyen mon va cach lam viec:"]
        parts += ["- " + e for e in persona["expertise"]]

    if persona.get("style"):
        parts += ["", "Cach nhan tin:"]
        parts += ["- " + s for s in persona["style"]]

    rules = persona.get("rules") or DEFAULT_RULES
    parts += ["", "Quy tac bat buoc:"] + ["- " + r for r in rules]
    parts += ["", "Chi xuat ra noi dung tin nhan, khong giai thich gi them."]
    return "\n".join(parts)


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
