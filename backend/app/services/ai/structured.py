"""Structured (JSON) generation on top of any provider.

Providers that can force JSON output (Gemini: responseMimeType) are asked to; others are asked in the prompt and the reply is parsed
leniently (fenced blocks, leading prose). Anything that does not parse into the expected shape raises AIUnavailable(code="bad_response"),
never a half-formed object."""
from __future__ import annotations

import inspect
import json
import re

from app.services.ai.base import AIUnavailable, LLMProvider


def parse_json(text: str):
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I).strip()
    start = min([i for i in (t.find("{"), t.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise AIUnavailable("AI did not return structured data", code="bad_response")
    for end in range(len(t), start, -1):  # tolerate trailing prose
        if t[end - 1] in "}]":
            try:
                return json.loads(t[start:end])
            except ValueError:
                continue
    raise AIUnavailable("AI returned malformed structured data", code="bad_response")


def generate_json(provider: LLMProvider, system: str, user: str, *, max_tokens: int = 1200, temperature: float = 0.7):
    kw = {"max_tokens": max_tokens, "temperature": temperature}
    try:
        if "json_mode" in inspect.signature(provider.generate).parameters:
            kw["json_mode"] = True
    except (TypeError, ValueError):
        pass
    return parse_json(provider.generate(system, user, **kw))
