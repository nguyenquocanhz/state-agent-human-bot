"""Backend LLM: goi claude CLI o che do -p/--print roi doc JSON tra ve.

Moi cuoc hoi thoai giu mot session-id rieng, cac luot sau dung --resume nen
claude-cli tu nho lich su -> khong can tu quan ly context window.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import uuid
from dataclasses import dataclass, field
from typing import Sequence

from ..util import log


@dataclass
class LlmReply:
    text: str
    session_id: str | None = None
    cost_usd: float = 0.0
    duration_ms: float = 0.0
    raw: dict = field(default_factory=dict)


class ClaudeCliError(RuntimeError):
    pass


class ClaudeCli:
    """Bao mong quanh claude-cli: an toan voi asyncio, huy giua chung duoc."""

    def __init__(self, *, bin: str = "claude", model: str | None = "sonnet",
                 timeout: float = 180.0, cwd: str | None = None,
                 restricted: bool = True, system_prompt_mode: str = "replace",
                 extra_args: Sequence[str] = (), max_concurrency: int = 2):
        self.bin = bin
        self.model = model
        self.timeout = timeout
        self.cwd = cwd
        self.restricted = restricted
        self.system_prompt_mode = system_prompt_mode
        self.extra_args = list(extra_args)
        self._sem = asyncio.Semaphore(max_concurrency)

    def _argv(self, *, system: str | None, session_id: str | None) -> list[str]:
        args = ["--print", "--output-format", "json", "--permission-prompts", "none"]
        if session_id:
            args += ["--resume", session_id]
        else:
            args += ["--session-id", str(uuid.uuid4())]
        if self.model:
            args += ["--model", self.model]
        if system:
            flag = ("--system-prompt" if self.system_prompt_mode == "replace"
                    else "--append-system-prompt")
            args += [flag, system]
        if self.restricted:
            # Bot chat khong can Bash/Edit/WebFetch -> bo tool cho nhe va bot rui ro.
            args.append("--restricted")
        args += self.extra_args

        exe = shutil.which(self.bin) or self.bin
        if os.name == "nt" and exe.lower().endswith((".cmd", ".bat")):
            return [os.environ.get("COMSPEC", "cmd.exe"), "/c", exe, *args]
        return [exe, *args]

    async def _run(self, argv: list[str], prompt: str) -> dict:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.cwd,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(prompt.encode("utf-8")), timeout=self.timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            # Bi huy (co tin nhan moi den) hoac qua han -> dung han tien trinh con.
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            raise

        stdout = out.decode("utf-8", "replace").strip()
        stderr = err.decode("utf-8", "replace").strip()
        if proc.returncode != 0 and not stdout:
            raise ClaudeCliError(f"claude-cli thoat ma {proc.returncode}: {stderr[:500]}")

        data = _parse_json(stdout)
        if data is None:
            raise ClaudeCliError(f"Khong doc duoc JSON tu claude-cli: {stdout[:300]}")
        if data.get("is_error"):
            raise ClaudeCliError(str(data.get("result") or stderr)[:500])
        return data

    async def complete(self, *, prompt: str, system: str | None = None,
                       session_id: str | None = None, images: Sequence[str] = ()) -> LlmReply:
        if images:
            # claude-cli doc anh bang Read tool, chi can dua duong dan vao prompt.
            # Da kiem chung: che do --restricted van giu Read nen anh van xem duoc.
            listed = "\n".join(f"- {p}" for p in images)
            prompt = (f"{prompt}\n\n<anh_dinh_kem>Doi phuong gui kem anh. Doc tung file sau "
                      f"bang Read tool roi moi tra loi:\n{listed}\n</anh_dinh_kem>")

        async with self._sem:
            try:
                data = await self._run(self._argv(system=system, session_id=session_id), prompt)
            except ClaudeCliError as e:
                # Session cu bi mat (doi may / xoa ~/.claude) -> mo mach moi.
                if session_id and _looks_like_missing_session(str(e)):
                    log.warning(f"Session {session_id[:8]} khong resume duoc, mo session moi")
                    data = await self._run(self._argv(system=system, session_id=None), prompt)
                else:
                    raise

        return LlmReply(
            text=(data.get("result") or "").strip(),
            session_id=data.get("session_id") or session_id,
            cost_usd=float(data.get("total_cost_usd") or 0.0),
            duration_ms=float(data.get("duration_ms") or 0.0),
            raw=data,
        )


def _parse_json(stdout: str) -> dict | None:
    """claude-cli doi khi in them dong phu -> lay doan JSON doc duoc."""
    try:
        return json.loads(stdout)
    except Exception:
        pass
    start = stdout.find("{")
    while start != -1:
        try:
            return json.loads(stdout[start:])
        except Exception:
            start = stdout.find("{", start + 1)
    return None


def _looks_like_missing_session(msg: str) -> bool:
    """Session cu khong dung duoc nua (mat file, id sai dinh dang, ...)."""
    m = msg.lower()
    return any(k in m for k in (
        "not found", "no conversation", "not a uuid",
        "does not match any session", "--resume",
    ))
