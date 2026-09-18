"""Doc cau hinh: .env -> bien moi truong -> tham so dong lenh (uu tien tang dan)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

DEFAULT_PERSONA = "config/persona.default.json"


def load_dotenv(path: str = ".env") -> None:
    """Doc .env. Dung python-dotenv neu co, khong thi tu parse (tranh phu thuoc)."""
    try:
        from dotenv import load_dotenv as _load   # type: ignore
        _load(path)
        return
    except Exception:
        pass
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        val = val.split("#", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), val)


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def load_persona(path: str) -> dict:
    persona = json.loads(Path(path).read_text(encoding="utf-8"))
    for key in ("typing", "seen", "think", "send", "cooldown", "rhythm"):
        if key not in persona:
            raise ValueError(f"Persona thieu muc bat buoc: {key}")
    persona.setdefault("sleep", {"enabled": False})
    persona.setdefault("typo", {"rate": 0.0})
    persona.setdefault("style", [])
    return persona


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    load_dotenv()
    p = argparse.ArgumentParser(
        prog="humanbot",
        description="Chatbot mo phong nhip nhan tin cua nguoi that (Telethon + claude-cli)")
    p.add_argument("--adapter", choices=("telegram", "zalo", "zalo-oa", "console"),
                   default=os.environ.get("ADAPTER", "console"),
                   help="kenh chat: telegram (Telethon) | zalo (tai khoan ca nhan, qua "
                        "cau noi Node) | zalo-oa (Official Account) | console (thu)")
    p.add_argument("--llm", choices=("claude", "api", "mock"),
                   default=os.environ.get("LLM", "claude"),
                   help="claude = qua claude-cli (nho lich su ho, dat hon); "
                        "api = goi thang Messages API (tu giu lich su, re hon)")
    p.add_argument("--persona", default=os.environ.get("PERSONA", DEFAULT_PERSONA))
    p.add_argument("--model", default=os.environ.get("CLAUDE_MODEL", "sonnet"))
    p.add_argument("--time-scale", type=float,
                   default=float(os.environ.get("TIME_SCALE", "1.0")),
                   help="0.2 = moi do tre chi con 1/5 (demo/debug)")
    p.add_argument("--dry-run", action="store_true", default=env_bool("DRY_RUN"),
                   help="chi in ra man hinh, khong gui/seen/typing that")
    p.add_argument("--seed", type=int,
                   default=int(os.environ["SEED"]) if os.environ.get("SEED") else None)
    p.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "info"),
                   choices=("debug", "info", "warning", "error"))
    p.add_argument("--store", default=os.environ.get("STORE", "data/sessions.json"))
    return p.parse_args(argv)


def build_adapter(args: argparse.Namespace, persona: dict) -> Any:
    if args.adapter == "console":
        from .adapters.console import ConsoleAdapter
        return ConsoleAdapter(persona_name=persona.get("name", "Bot"))

    if args.adapter == "zalo":
        from .adapters.zalo_adapter import ZaloAdapter
        allowed = [s for s in os.environ.get("ZALO_ALLOWED", "").split(",") if s.strip()]
        if not allowed and not env_bool("ZALO_ALLOW_EVERYONE"):
            raise SystemExit(
                "ZALO_ALLOWED dang trong -> bot se tra loi MOI NGUOI nhan toi nick nay.\n"
                "Dien id nguoi duoc phep vao .env, hoac dat ZALO_ALLOW_EVERYONE=true.\n"
                "Chua biet id thi cu chay thu, log se in id cua nguoi nhan toi.")
        return ZaloAdapter(
            bridge_dir=os.environ.get("ZALO_BRIDGE_DIR", "zalo_bridge"),
            node_bin=os.environ.get("NODE_BIN", "node"),
            allowed=allowed,
            allow_groups=env_bool("ZALO_ALLOW_GROUPS"),
        )

    if args.adapter == "zalo-oa":
        from .adapters.zalo_oa_adapter import ZaloAdapter as ZaloOaAdapter
        token = os.environ.get("ZALO_OA_ACCESS_TOKEN")
        if not token:
            raise SystemExit(
                "Thieu ZALO_OA_ACCESS_TOKEN.\n"
                "Adapter nay danh cho Official Account (can doanh nghiep dang ky).\n"
                "Tai khoan ca nhan thi dung --adapter zalo.")
        return ZaloOaAdapter(
            access_token=token,
            port=int(os.environ.get("PORT", "8080")),
            path=os.environ.get("ZALO_WEBHOOK_PATH", "/webhook"),
            allowed=[s for s in os.environ.get("ZALO_ALLOWED", "").split(",") if s.strip()],
            app_secret=os.environ.get("ZALO_APP_SECRET") or None,
            app_id=os.environ.get("ZALO_APP_ID") or None,
            verify_signature=env_bool("ZALO_VERIFY_SIGNATURE"),
        )

    from .adapters.telethon_adapter import TelethonAdapter
    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")
    if not api_id or not api_hash:
        raise SystemExit(
            "Thieu TG_API_ID / TG_API_HASH.\n"
            "Lay tai https://my.telegram.org/apps roi dien vao file .env "
            "(copy tu .env.example).")
    allowed = [s for s in os.environ.get("TG_ALLOWED", "").split(",") if s.strip()]
    if not allowed and not env_bool("TG_ALLOW_EVERYONE"):
        # Day la tai khoan that: de trong nghia la bot tra loi BAT KY ai nhan toi,
        # ke ca ban be/khach hang that. Bat buoc khai bao ro rang moi cho chay.
        raise SystemExit(
            "TG_ALLOWED dang trong -> bot se tra loi MOI NGUOI nhan toi nick nay.\n"
            "Dien id hoac @username duoc phep vao .env, vi du:\n"
            "    TG_ALLOWED=123456789,@nick_phu\n"
            "Chay `python tools/tg_login.py` de lay danh sach id.\n"
            "Neu that su muon tra loi tat ca thi dat TG_ALLOW_EVERYONE=true.")
    return TelethonAdapter(
        api_id=int(api_id), api_hash=api_hash,
        session=os.environ.get("TG_SESSION", "data/humanbot"),
        phone=os.environ.get("TG_PHONE") or None,
        allowed=allowed,
        allow_groups=env_bool("TG_ALLOW_GROUPS"),
    )


def build_llm(args: argparse.Namespace) -> Any:
    if args.llm == "mock":
        from .llm.mock import MockLlm
        return MockLlm()
    if args.llm == "api":
        from .llm.anthropic_api import AnthropicApi
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise SystemExit(
                "Thieu ANTHROPIC_API_KEY (bat buoc voi --llm api).\n"
                "Lay tai https://console.anthropic.com/settings/keys roi dien vao .env")
        return AnthropicApi(
            model=os.environ.get("ANTHROPIC_MODEL") or args.model,
            max_tokens=int(os.environ.get("ANTHROPIC_MAX_TOKENS", "1000")),
            effort=os.environ.get("ANTHROPIC_EFFORT", "low") or None,
            thinking=env_bool("ANTHROPIC_THINKING"),
            max_history=int(os.environ.get("ANTHROPIC_MAX_HISTORY", "40")),
        )
    from .llm.claude_cli import ClaudeCli
    return ClaudeCli(
        bin=os.environ.get("CLAUDE_BIN", "claude"),
        model=args.model,
        timeout=float(os.environ.get("CLAUDE_TIMEOUT", "180")),
        cwd=os.environ.get("CLAUDE_CWD") or None,
    )
