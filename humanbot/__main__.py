"""Diem chay chinh:  python -m humanbot --adapter telegram

Vi du:
    python -m humanbot                                  # chat thu trong terminal
    python -m humanbot --llm mock --time-scale 0.2      # demo nhanh, khong ton tien
    python -m humanbot --adapter telegram               # chay that qua Telethon
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from .clock import Clock
from .config import build_adapter, build_llm, load_persona, parse_args
from .engine import HumanBotEngine
from .store import SessionStore
from .util import log, setup_logging


async def amain(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    setup_logging(args.log_level)

    if not Path(".env").exists():
        log.info("Chua co file .env - chay `python tools/setup.py` de tao (hoac copy .env.example)")

    persona = load_persona(args.persona)
    adapter = build_adapter(args, persona)
    llm = build_llm(args)
    store = SessionStore(args.store)

    engine = HumanBotEngine(
        adapter=adapter, llm=llm, persona=persona, store=store,
        clock=Clock(time_scale=args.time_scale), seed=args.seed, dry_run=args.dry_run,
    )

    log.info(f"Persona: {persona['name']} | kenh: {args.adapter} | LLM: {args.llm} "
             f"| time_scale: {args.time_scale}" + (" | DRY-RUN" if args.dry_run else ""))
    try:
        await engine.run()
    except (KeyboardInterrupt, asyncio.CancelledError):
        log.info("Nhan Ctrl+C, dang dung...")
        await engine.shutdown()
    return 0


def main() -> int:
    try:
        return asyncio.run(amain())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
