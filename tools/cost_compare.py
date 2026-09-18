"""So chi phi mot luot tra loi: claude-cli vs goi thang Messages API.

    python tools/cost_compare.py            # uoc tinh (khong can API key)
    python tools/cost_compare.py --exact    # dem token that qua API (can ANTHROPIC_API_KEY)

So cua claude-cli la DO THAT tu cac lan chay trong du an nay (xem MEASURED ben duoi),
khong phai uoc tinh.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from humanbot.config import load_persona                        # noqa: E402
from humanbot.llm.anthropic_api import (                        # noqa: E402
    PRICES, HistoryStore, resolve_model,
)
from humanbot.prompt import build_system_prompt                 # noqa: E402

# --------------------------------------------------------------------------
# Do that tu claude-cli (sonnet, --restricted, --system-prompt cua persona).
# Nguon: log chay that ngay 2026-09-18, truong total_cost_usd trong JSON tra ve.
MEASURED = {
    "cli_first_turn_usd": 0.0326,   # session moi: ghi ~25.7k token vao cache 1 gio
    "cli_warm_turn_usd": 0.0122,    # luot sau: doc lai 25.7k tu cache + ghi phan moi
    "cli_overhead_tokens": 25_700,  # system prompt + dinh nghia tool cua Claude Code
}

# Ty le ky tu / token, do tu chinh du an nay:
# "chào bạn, mình là Linh 👋 có gì cần giúp không?" = 46 ky tu -> 28 token.
CHARS_PER_TOKEN_VI = 1.65     # tieng Viet co dau
CHARS_PER_TOKEN_ASCII = 3.6   # tieng Viet khong dau / tieng Anh

# Hoi thoai mau: lay nguyen van tu lan chay that o console.
SAMPLE = [
    ("chao shop, minh can hosting cho web ban hang nho",
     "Chào bạn, Linh đây á. Web bán hàng nhỏ thì bên mình có gói hosting hợp lý lắm nè. "
     "Bạn cho Linh biết web đang dùng nền tảng gì không (WordPress, Shopify, hay code riêng), "
     "và ước lượng traffic/khách hàng tháng khoảng bao nhiêu không, để Linh tư vấn gói phù hợp nhé."),
    ("the goi do bao nhieu tien mot thang vay?",
     "Cái đó tùy gói và tùy nhu cầu xíu nên Linh chưa chốt số chính xác được á. "
     "Bạn cho Linh biết nền tảng web với traffic tháng khoảng bao nhiêu là Linh báo giá đúng gói cho nhé."),
]


def est_tokens(text: str) -> int:
    ratio = CHARS_PER_TOKEN_VI if any(ord(c) > 127 for c in text) else CHARS_PER_TOKEN_ASCII
    return max(1, round(len(text) / ratio))


def exact_tokens(model: str, system: str, messages: list[dict]) -> int:
    import anthropic
    client = anthropic.Anthropic()
    return client.messages.count_tokens(
        model=model, system=system, messages=messages).input_tokens


def api_cost_for_conversation(model: str, persona: dict, turns: int, exact: bool,
                              max_history: int = 40) -> dict:
    """Chi phi API cho `turns` luot, lich su cong don - va bi cat theo cua so truot
    giong het HistoryStore that, nen so nay khong bi phong len o hoi thoai dai."""
    price_in, price_out = PRICES[model]
    window = HistoryStore(max_messages=max_history)
    system = build_system_prompt(persona)
    messages: list[dict] = []
    rows = []
    total = 0.0

    for i in range(turns):
        user, assistant = SAMPLE[i % len(SAMPLE)]
        messages.append({"role": "user", "content": user})
        messages = window.trim(messages)

        if exact:
            tok_in = exact_tokens(model, system, messages)
        else:
            tok_in = est_tokens(system) + sum(est_tokens(m["content"]) for m in messages)
        tok_out = est_tokens(assistant)

        cost = (tok_in * price_in + tok_out * price_out) / 1_000_000
        total += cost
        rows.append({"turn": i + 1, "in": tok_in, "out": tok_out, "usd": cost})
        messages.append({"role": "assistant", "content": assistant})

    return {"rows": rows, "total": total, "system_tokens":
            exact_tokens(model, system, [{"role": "user", "content": "x"}]) if exact
            else est_tokens(system)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--persona", default="config/persona.default.json")
    ap.add_argument("--turns", type=int, default=10)
    ap.add_argument("--exact", action="store_true",
                    help="dem token that qua API (can ANTHROPIC_API_KEY)")
    ap.add_argument("--per-day", type=int, default=500, help="so luot tra loi moi ngay")
    ap.add_argument("--max-history", type=int, default=40,
                    help="cua so lich su cua backend api (ANTHROPIC_MAX_HISTORY)")
    args = ap.parse_args()

    if args.exact and not os.environ.get("ANTHROPIC_API_KEY"):
        print("Can ANTHROPIC_API_KEY cho --exact. Dang chay che do uoc tinh.\n")
        args.exact = False

    persona = load_persona(args.persona)
    mode = "DEM THAT qua API" if args.exact else f"UOC TINH ({CHARS_PER_TOKEN_VI} ky tu/token)"
    print(f"Persona: {persona['name']} | {args.turns} luot | che do: {mode}\n")

    print(f"{'backend / model':<28} {'luot dau':>10} {'luot sau':>10} {'TB/luot':>10} "
          f"{'x luot/ngay':>13}".replace("x", str(args.per_day)))
    print("-" * 76)

    cli_avg = (MEASURED["cli_first_turn_usd"]
               + MEASURED["cli_warm_turn_usd"] * (args.turns - 1)) / args.turns
    print(f"{'claude-cli (sonnet) [do that]':<28} "
          f"{MEASURED['cli_first_turn_usd']:>10.5f} {MEASURED['cli_warm_turn_usd']:>10.5f} "
          f"{cli_avg:>10.5f} {cli_avg * args.per_day:>12.2f}$")

    results = {}
    for alias in ("sonnet", "opus", "haiku"):
        model = resolve_model(alias)
        r = api_cost_for_conversation(model, persona, args.turns, args.exact,
                                      max_history=args.max_history)
        avg = r["total"] / args.turns
        results[alias] = r
        print(f"{'API ' + model:<28} {r['rows'][0]['usd']:>10.5f} "
              f"{r['rows'][-1]['usd']:>10.5f} {avg:>10.5f} {avg * args.per_day:>12.2f}$")

    sonnet_avg = results["sonnet"]["total"] / args.turns
    print("-" * 76)
    print(f"System prompt cua persona: ~{results['sonnet']['system_tokens']} token"
          f"   |   Overhead moi luot cua claude-cli: {MEASURED['cli_overhead_tokens']:,} token")
    print(f"=> Cung model sonnet, API re hon {cli_avg / sonnet_avg:.1f} lan "
          f"(tiet kiem {(cli_avg - sonnet_avg) * args.per_day * 30:.0f}$/thang "
          f"o muc {args.per_day} luot/ngay)")
    print(f"=> Doi sang haiku thi re hon {cli_avg / (results['haiku']['total'] / args.turns):.0f} lan")
    print("\nLuu y: so 'luot sau' cua claude-cli do o luot 2; hoi thoai cang dai thi no cang"
          "\nnhich len, nen khoang cach that con rong hon bang nay mot chut.")

    if os.environ.get("HUMANBOT_COST_JSON"):
        print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
