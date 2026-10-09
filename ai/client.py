"""Claude, called only on events, with strict guardrails.

- Responses are parsed into the Pydantic schema by the SDK; failures → None
  and the rule-based plan stands.
- Every price in a response must be one of the prices code passed in.
- 10 s timeout, no retries; on timeout the alert goes out without the AI note.
- Refusals fall back server-side to another model; a final refusal → None.
- Every call is logged verbatim (prompt, response, model, latency, cost, action).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from pydantic import BaseModel

import config
from ai.schemas import needs_reason, prices_in

FALLBACK_BETA = "server-side-fallback-2026-07-01"


def load_prompt(name: str, version: str = "v1") -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / config.AI_PROMPTS_DIR / f"{name}.{version}.md").read_text()


def call_cost(usage: Any) -> float:
    if usage is None:
        return 0.0
    tin = (getattr(usage, "input_tokens", 0) or 0) + (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    tin += 0.1 * (getattr(usage, "cache_read_input_tokens", 0) or 0)
    tout = getattr(usage, "output_tokens", 0) or 0
    return (tin * config.AI_PRICE_IN_PER_MTOK + tout * config.AI_PRICE_OUT_PER_MTOK) / 1e6


class AIClient:
    def __init__(self, client=None, log: Callable[[dict], None] | None = None,
                 model: str = config.CLAUDE_MODEL):
        if client is None:
            import anthropic
            client = anthropic.Anthropic(max_retries=0, timeout=config.CLAUDE_TIMEOUT_S)
        self.client = client
        self.model = model
        self.log = log or (lambda rec: None)

    def ask(self, role: str, prompt: str, payload: dict, schema: type[BaseModel],
            allowed_prices: list[float] | None = None, prompt_version: str = "v1") -> BaseModel | None:
        """One guarded call. Returns the validated object, or None (rule-based plan stands)."""
        import anthropic

        user = json.dumps(payload, sort_keys=True, default=str)
        rec = {"role": role, "prompt_version": prompt_version, "model": self.model, "system": prompt,
               "input": user, "output": None, "status": "", "latency_s": 0.0, "cost_usd": 0.0, "action": ""}
        t0 = time.monotonic()
        try:
            resp = self.client.beta.messages.parse(
                model=self.model,
                max_tokens=config.AI_MAX_TOKENS,
                system=prompt,
                messages=[{"role": "user", "content": user}],
                output_format=schema,
                output_config={"effort": config.AI_EFFORT},
                betas=[FALLBACK_BETA],
                fallbacks="default",
                timeout=config.CLAUDE_TIMEOUT_S,
            )
        except anthropic.APITimeoutError:
            rec["status"] = "timeout"
            return self._done(rec, t0, None)
        except anthropic.APIStatusError as e:
            rec["status"] = f"http_{e.status_code}"
            return self._done(rec, t0, None)
        except anthropic.APIConnectionError:
            rec["status"] = "connection_error"
            return self._done(rec, t0, None)
        except Exception as e:  # schema validation errors from parse
            rec["status"] = f"invalid: {type(e).__name__}"
            return self._done(rec, t0, None)

        rec["model"] = getattr(resp, "model", self.model)
        rec["cost_usd"] = call_cost(getattr(resp, "usage", None))
        if getattr(resp, "stop_reason", None) == "refusal":
            rec["status"] = "refusal"
            return self._done(rec, t0, None)
        out = getattr(resp, "parsed_output", None)
        if out is None:
            rec["status"] = "no_output"
            return self._done(rec, t0, None)
        rec["output"] = out.model_dump_json()
        rec["action"] = getattr(out, "action", "")
        if needs_reason(out) and not getattr(out, "reason", "").strip():
            rec["status"] = "rejected: missing reason"
            return self._done(rec, t0, None)
        if allowed_prices is not None:
            bad = [p for p in prices_in(out)
                   if not any(abs(p - a) <= config.AI_PRICE_TOLERANCE for a in allowed_prices)]
            if bad:
                rec["status"] = f"rejected: invented prices {bad}"
                return self._done(rec, t0, None)
        rec["status"] = "ok"
        return self._done(rec, t0, out)

    def _done(self, rec: dict, t0: float, out):
        rec["latency_s"] = round(time.monotonic() - t0, 3)
        self.log(rec)
        return out
