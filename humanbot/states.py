"""Cac trang thai cua 'bo nao' bot. Moi cuoc hoi thoai co dung 1 state machine."""
from __future__ import annotations

from enum import Enum


class S(str, Enum):
    IDLE = "IDLE"              # khong lam gi, dang doi tin nhan
    SEEN_DELAY = "SEEN_DELAY"  # tin da toi, nguoi chua kip mo may -> roi moi mark read
    THINKING = "THINKING"      # doc lai ngu canh + goi LLM
    TYPING = "TYPING"          # phat action typing, do dai ti le voi cau tra loi
    SENDING = "SENDING"        # bam gui (tach doan neu dai)
    COOLDOWN = "COOLDOWN"      # nghi mot nhip roi ve IDLE


#: Do thi chuyen trang thai hop le - vi pham se nem loi de bat bug som.
#:
#: Hai canh dac biet co mat o gan nhu moi trang thai:
#:   -> SEEN_DELAY : co tin nhan moi giua chung, bo chu ky cu va doc lai tu dau
#:   -> IDLE       : dung han (loi, bi huy, hoac xong luot)
#: Canh tu-quay-ve-chinh-no la cac buoc lap: SEEN_DELAY (doc lai), TYPING (doan ke
#: tiep) va SENDING (tin sua chinh ta ngay sau tin vua gui).
TRANSITIONS: dict[S, tuple[S, ...]] = {
    S.IDLE: (S.SEEN_DELAY,),
    S.SEEN_DELAY: (S.THINKING, S.SEEN_DELAY, S.IDLE),
    S.THINKING: (S.TYPING, S.SENDING, S.COOLDOWN, S.SEEN_DELAY, S.IDLE),
    S.TYPING: (S.SENDING, S.TYPING, S.THINKING, S.COOLDOWN, S.SEEN_DELAY, S.IDLE),
    S.SENDING: (S.TYPING, S.SENDING, S.THINKING, S.COOLDOWN, S.SEEN_DELAY, S.IDLE),
    S.COOLDOWN: (S.IDLE, S.SEEN_DELAY),
}


class IllegalTransition(RuntimeError):
    pass


def assert_transition(frm: S, to: S) -> None:
    if to not in TRANSITIONS.get(frm, ()):
        raise IllegalTransition(f"Chuyen trang thai khong hop le: {frm.value} -> {to.value}")
