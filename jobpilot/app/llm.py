"""Thin wrapper over the Anthropic API. Everything degrades gracefully when no key is set."""
import json
import re

from . import config

_client = None


def available():
    return bool(config.ANTHROPIC_API_KEY)


def complete(system, user, max_tokens=1500):
    global _client
    if not available():
        return None
    try:
        if _client is None:
            import anthropic

            _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        r = _client.messages.create(
            model=config.LLM_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    except Exception as e:  # network, quota, bad key...
        print("LLM error:", e)
        return None


def complete_json(system, user, max_tokens=1500):
    text = complete(system, user, max_tokens)
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
