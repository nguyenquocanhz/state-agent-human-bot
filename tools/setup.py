"""Tro ly cai dat: hoi vai cau roi tu sinh file .env.

    python tools/setup.py

Khong ghi de mu quang: neu .env da co thi moi cau hoi lay gia tri cu lam mac dinh,
va ban cu duoc sao luu thanh .env.bak.
"""
from __future__ import annotations

import getpass
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENV = ROOT / ".env"
TEMPLATE = ROOT / ".env.example"


# ------------------------------------------------------------------ nhap lieu
def ask(prompt: str, default: str = "", secret: bool = False) -> str:
    hint = f" [{'(giu nguyen)' if secret and default else default}]" if default else ""
    while True:
        if secret and sys.stdin.isatty():
            val = getpass.getpass(f"{prompt}{hint}: ").strip()
        else:
            val = input(f"{prompt}{hint}: ").strip()
        if val:
            return val
        if default:
            return default
        print("  (bat buoc nhap)")


def choose(prompt: str, options: list[tuple[str, str]], default: str) -> str:
    print(f"\n{prompt}")
    for i, (key, desc) in enumerate(options, 1):
        mark = " *" if key == default else "  "
        print(f" {mark}{i}. {key:<10} {desc}")
    keys = [k for k, _ in options]
    while True:
        raw = input(f"Chon [1-{len(options)}, mac dinh {keys.index(default) + 1}]: ").strip()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return keys[int(raw) - 1]
        if raw in keys:
            return raw
        print("  (chon khong hop le)")


def yes_no(prompt: str, default: bool = True) -> bool:
    raw = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not raw else raw.startswith("y")


# -------------------------------------------------------------------- env I/O
def read_env(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.split("#", 1)[0].strip()
    return out


def write_env(values: dict) -> None:
    """Giu nguyen bo cuc + chu thich cua .env.example, chi thay phan gia tri."""
    lines = TEMPLATE.read_text(encoding="utf-8").splitlines()
    out, seen = [], set()
    for line in lines:
        m = re.match(r"^([A-Z_]+)=(.*)$", line)
        if not m:
            out.append(line)
            continue
        key = m.group(1)
        seen.add(key)
        comment = ""
        if "#" in m.group(2):
            comment = "  " + m.group(2)[m.group(2).index("#"):].strip()
        out.append(f"{key}={values.get(key, '')}{comment}")
    for key, val in values.items():          # khoa moi khong co trong template
        if key not in seen:
            out.append(f"{key}={val}")
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")


# ----------------------------------------------------------------------- main
def main() -> int:
    print("=" * 64)
    print("  Cai dat StateAgentHumanBot")
    print("=" * 64)

    old = read_env(ENV)
    if old:
        print(f"\nDa co {ENV.name} - cac cau hoi se lay gia tri cu lam mac dinh.")

    cfg = dict(old)

    # --- kenh chat ---
    adapter = choose("Chay tren kenh nao?", [
        ("console", "chat thu trong terminal, khong can dang nhap gi"),
        ("telegram", "tai khoan Telegram that qua Telethon"),
    ], old.get("ADAPTER", "console"))
    cfg["ADAPTER"] = adapter

    # --- persona ---
    personas = sorted((ROOT / "config").glob("persona.*.json"))
    opts = []
    for p in personas:
        d = json.loads(p.read_text(encoding="utf-8"))
        opts.append((str(Path("config") / p.name).replace("\\", "/"),
                     f"{d['name']} - {d.get('bio', '')[:46]}"))
    cfg["PERSONA"] = choose("Dung persona nao? (sua file JSON de tao persona cua ban)",
                            opts, old.get("PERSONA", opts[0][0]))

    # --- LLM ---
    has_claude = shutil.which("claude") is not None
    llm = choose("Sinh cau tra loi bang gi?", [
        ("claude", "claude-cli" + ("" if has_claude else "  (KHONG tim thay lenh `claude`)")),
        ("api", "goi thang Messages API, can ANTHROPIC_API_KEY, re hon"),
        ("mock", "tra loi gia, de thu may trang thai, khong ton tien"),
    ], old.get("LLM", "claude" if has_claude else "api"))
    cfg["LLM"] = llm

    if llm == "api":
        key = ask("ANTHROPIC_API_KEY (lay o console.anthropic.com)",
                  old.get("ANTHROPIC_API_KEY", ""), secret=True)
        cfg["ANTHROPIC_API_KEY"] = key
        cfg["ANTHROPIC_MODEL"] = choose("Model nao?", [
            ("sonnet", "can bang - mac dinh"),
            ("haiku", "re nhat, nhanh nhat"),
            ("opus", "thong minh nhat, dat nhat"),
        ], old.get("ANTHROPIC_MODEL", "sonnet"))
    elif llm == "claude":
        cfg["CLAUDE_MODEL"] = old.get("CLAUDE_MODEL", "sonnet")
        if not has_claude:
            print("\n  ! Chua co lenh `claude` trong PATH. Cai Claude Code truoc,")
            print("    hoac chay lai va chon backend `api`.")

    # --- telegram ---
    if adapter == "telegram":
        print("\nLay api_id / api_hash tai https://my.telegram.org/apps")
        cfg["TG_API_ID"] = ask("TG_API_ID", old.get("TG_API_ID", ""))
        cfg["TG_API_HASH"] = ask("TG_API_HASH", old.get("TG_API_HASH", ""), secret=True)
        cfg["TG_SESSION"] = old.get("TG_SESSION", "data/humanbot")

        print("\nAi duoc bot tra loi? (id hoac @username, cach nhau bang dau phay)")
        print("Chua biet id thi cu de trong, chay `python tools/tg_login.py` de lay sau.")
        cfg["TG_ALLOWED"] = input(f"TG_ALLOWED [{old.get('TG_ALLOWED', '')}]: ").strip() \
            or old.get("TG_ALLOWED", "")
        cfg["TG_ALLOW_GROUPS"] = str(yes_no("Tra loi trong group khi bi @mention?",
                                            old.get("TG_ALLOW_GROUPS", "false") == "true")).lower()
        cfg["TG_ALLOW_EVERYONE"] = old.get("TG_ALLOW_EVERYONE", "false")

    cfg.setdefault("TIME_SCALE", old.get("TIME_SCALE", "1.0"))
    cfg.setdefault("LOG_LEVEL", old.get("LOG_LEVEL", "info"))
    cfg.setdefault("DRY_RUN", old.get("DRY_RUN", "false"))

    # --- ghi file ---
    if ENV.exists():
        shutil.copy(ENV, ROOT / ".env.bak")
        print(f"\nDa sao luu ban cu -> .env.bak")
    write_env(cfg)
    print(f"Da ghi {ENV}")

    # --- buoc tiep theo ---
    print("\n" + "=" * 64)
    if adapter == "telegram":
        print("  Tiep theo:")
        print("    1. python tools/tg_login.py        # dang nhap + lay id")
        if not cfg.get("TG_ALLOWED"):
            print("    2. dien TG_ALLOWED vao .env       # bat buoc, khong la bot khong chay")
            print("    3. python -m humanbot --adapter telegram")
        else:
            print("    2. python -m humanbot --adapter telegram")
    else:
        print("  Chay thu ngay:")
        print("    python -m humanbot --time-scale 0.2")
    print("=" * 64)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print("\nDa huy, khong ghi gi.")
        sys.exit(130)
