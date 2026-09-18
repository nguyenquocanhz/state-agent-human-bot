"""In ra system prompt ma mot persona sinh ra - de doc lai, sua, hoac copy di noi khac.

    python tools/show_prompt.py                                   # persona mac dinh
    python tools/show_prompt.py config/persona.mainboard.json
    python tools/show_prompt.py config/persona.mainboard.json --turn "may khong len nguon"
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from humanbot.config import DEFAULT_PERSONA, load_persona   # noqa: E402
from humanbot.machine import Inbound                        # noqa: E402
from humanbot.prompt import build_system_prompt, build_user_turn  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("persona", nargs="?", default=DEFAULT_PERSONA)
    ap.add_argument("--turn", help="kem theo mot luot noi mau de xem prompt day du")
    args = ap.parse_args()

    persona = load_persona(args.persona)
    system = build_system_prompt(persona)

    print("=" * 78)
    print(f"  SYSTEM PROMPT - {persona['name']} ({args.persona})")
    print(f"  {len(system)} ky tu, ~{round(len(system) / 3.2)} token")
    print("=" * 78)
    print(system)

    if args.turn:
        print()
        print("=" * 78)
        print("  LUOT CUA NGUOI DUNG (kem ngu canh may tu chen)")
        print("=" * 78)
        print(build_user_turn(batch=[Inbound(text=args.turn)], ctx={}, persona=persona,
                              now_ms=time.time() * 1000))
    return 0


if __name__ == "__main__":
    sys.exit(main())
