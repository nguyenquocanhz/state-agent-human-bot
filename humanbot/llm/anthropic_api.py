"""Backend LLM: goi thang Messages API bang SDK `anthropic` (khong qua claude-cli).

Khac biet duy nhat so voi claude_cli.py: o day MINH tu giu lich su hoi thoai.
claude-cli co --resume nen no nho ho, doi lai moi luot phai nap lai toan bo
system prompt + dinh nghia tool cua Claude Code (~25k token) du bot chi chat.

`session_id` trong giao dien complete() duoc dung lam KHOA hoi thoai: lan dau
tra ve mot id moi, machine luu lai, cac luot sau dua lai de lay dung lich su.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from ..util import log
from .claude_cli import LlmReply

#: Alias giong claude-cli -> id day du ma API doi hoi.
MODEL_ALIASES = {
    "opus": "claude-opus-5",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
    "fable": "claude-fable-5-1",
}

#: USD / 1 trieu token (input, output). Cache ghi ~1.25x input, cache doc ~0.1x input.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-haiku-4-5": (1.0, 5.0),
}

#: Nhung model khong nhan output_config.effort (gui vao la loi 400).
NO_EFFORT = {"claude-haiku-4-5"}
#: Nhung model khong nhan thinking={"type": "disabled"}; bo han tham so la khong nghi.
NO_DISABLE_THINKING = {"claude-haiku-4-5"}


def resolve_model(name: str) -> str:
    return MODEL_ALIASES.get((name or "").lower(), name)


def estimate_cost(model: str, usage: Any) -> float:
    """Quy doi usage ra USD. Bang gia la ban chup, khong phai hoa don that."""
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    get = lambda f: getattr(usage, f, 0) or 0          # noqa: E731
    return (
        get("input_tokens") * price_in
        + get("cache_creation_input_tokens") * price_in * 1.25
        + get("cache_read_input_tokens") * price_in * 0.1
        + get("output_tokens") * price_out
    ) / 1_000_000


class HistoryStore:
    """Lich su tung hoi thoai, moi hoi thoai mot file JSON, ghi atomic."""

    def __init__(self, directory: str = "data/history", max_messages: int = 40):
        self.dir = Path(directory)
        self.max_messages = max_messages
        self._cache: Dict[str, List[dict]] = {}

    def _path(self, key: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(key))
        return self.dir / f"{safe}.json"

    def load(self, key: str) -> List[dict]:
        if key in self._cache:
            return self._cache[key]
        try:
            data = json.loads(self._path(key).read_text(encoding="utf-8"))
            msgs = data.get("messages", [])
        except Exception:
            msgs = []
        self._cache[key] = msgs
        return msgs

    def save(self, key: str, messages: List[dict]) -> None:
        messages = self.trim(messages)
        self._cache[key] = messages
        self.dir.mkdir(parents=True, exist_ok=True)
        path = self._path(key)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"messages": messages}, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, path)

    def trim(self, messages: List[dict]) -> List[dict]:
        """Giu cua so truot; API bat buoc tin dau tien phai la cua user."""
        msgs = messages[-self.max_messages:]
        while msgs and msgs[0].get("role") != "user":
            msgs = msgs[1:]
        return msgs


class AnthropicApi:
    """Cung giao dien complete() voi ClaudeCli nen doi qua lai bang mot co --llm."""

    def __init__(self, *, model: str = "sonnet", max_tokens: int = 1000,
                 effort: Optional[str] = "low", thinking: bool = False,
                 history_dir: str = "data/history", max_history: int = 40,
                 max_concurrency: int = 4, timeout: float = 120.0,
                 client: Any = None, api_key: Optional[str] = None):
        self.model = resolve_model(model)
        self.max_tokens = max_tokens
        self.effort = effort
        self.thinking = thinking
        self.history = HistoryStore(history_dir, max_history)
        self._sem = asyncio.Semaphore(max_concurrency)
        self.total_cost = 0.0
        self.calls = 0

        if client is not None:
            self.client = client                      # dung cho test, khong cham mang
        else:
            from anthropic import AsyncAnthropic      # import tre: chi can khi dung --llm api
            self.client = AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=3)

    # ------------------------------------------------------------ tham so
    def _model_kwargs(self) -> dict:
        kwargs: dict = {}
        if self.thinking:
            kwargs["thinking"] = {"type": "adaptive"}
        elif self.model not in NO_DISABLE_THINKING:
            # Bot chat can tra loi nhanh va ngan -> khong can suy nghi sau.
            kwargs["thinking"] = {"type": "disabled"}
        if self.effort and self.model not in NO_EFFORT:
            kwargs["output_config"] = {"effort": self.effort}
        return kwargs

    def _system_for(self, system: Optional[str]) -> str:
        if not system:
            return ""
        if self.thinking:
            return system
        # Tat thinking co the lam model lot the XML noi bo vao cau tra loi.
        return system + "\nKhong bao gio chen the XML noi bo vao tin nhan."

    # ------------------------------------------------------------- public
    @staticmethod
    def _image_blocks(images: Sequence[str]) -> list:
        """Doc file anh thanh content block base64 cua Messages API."""
        import base64
        import mimetypes

        blocks = []
        for path in images:
            p = Path(path)
            if not p.exists():
                log.warning(f"Khong thay file anh: {path}")
                continue
            media = mimetypes.guess_type(str(p))[0] or "image/jpeg"
            if media not in ("image/jpeg", "image/png", "image/gif", "image/webp"):
                log.warning(f"Bo qua {path}: API khong nhan dinh dang {media}")
                continue
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": media,
                           "data": base64.standard_b64encode(p.read_bytes()).decode()},
            })
        return blocks

    async def complete(self, *, prompt: str, system: Optional[str] = None,
                       session_id: Optional[str] = None,
                       images: Sequence[str] = ()) -> LlmReply:
        key = session_id or str(uuid.uuid4())
        messages = list(self.history.load(key))

        blocks = self._image_blocks(images) if images else []
        if blocks:
            # Anh truoc, cau hoi sau - model doc anh roi moi doc yeu cau.
            messages.append({"role": "user", "content": blocks + [{"type": "text", "text": prompt}]})
        else:
            messages.append({"role": "user", "content": prompt})

        started = time.time()
        async with self._sem:
            resp = await self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self._system_for(system),
                messages=self.history.trim(messages),
                **self._model_kwargs(),
            )

        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
        if getattr(resp, "stop_reason", None) == "max_tokens":
            log.warning(f"Cau tra loi bi cat vi cham max_tokens={self.max_tokens}")
        if getattr(resp, "stop_reason", None) == "refusal":
            log.warning("Model tu choi tra loi luot nay")
            return LlmReply(text="", session_id=key, cost_usd=0.0)

        # Chi ghi vao lich su khi da co cau tra loi that (bi huy giua chung thi
        # khong luu gi ca -> luot sau nhac lai tin cu, khong bi lech mach).
        if text:
            messages.append({"role": "assistant", "content": text})
            # Khong luu base64 anh vao lich su: file se phinh to va moi luot sau
            # deu phai gui lai ca anh. Thay bang mot dong ghi chu.
            slim = []
            for m in messages:
                if isinstance(m.get("content"), list):
                    texts = [b["text"] for b in m["content"] if b.get("type") == "text"]
                    n = sum(1 for b in m["content"] if b.get("type") == "image")
                    slim.append({"role": m["role"],
                                 "content": f"[da gui {n} anh] " + " ".join(texts)})
                else:
                    slim.append(m)
            self.history.save(key, slim)

        cost = estimate_cost(self.model, resp.usage)
        self.total_cost += cost
        self.calls += 1
        u = resp.usage
        log.debug(
            "API %s: in=%s cache_r=%s out=%s -> $%.5f (tong $%.4f / %d luot)"
            % (self.model, u.input_tokens, getattr(u, "cache_read_input_tokens", 0),
               u.output_tokens, cost, self.total_cost, self.calls))

        return LlmReply(text=text, session_id=key, cost_usd=cost,
                        duration_ms=(time.time() - started) * 1000,
                        raw={"usage": u.model_dump() if hasattr(u, "model_dump") else {}})
