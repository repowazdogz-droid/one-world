"""Model transport. NO WORLD ACCESS.

Imports nothing from `one_world` and holds no database handle. Its only job is
to turn a prompt string into a response string, and to report transport failure
honestly rather than as an empty answer.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

MAX_TOKENS = 1024
RETRIES = 2


class TransportError(RuntimeError):
    """The provider did not answer. NOT the same as the model abstaining."""


def _post(url, payload, headers, timeout=120):
    last = None
    for _ in range(RETRIES + 1):
        try:
            req = urllib.request.Request(
                url, data=json.dumps(payload).encode(), headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            body = ""
            if isinstance(e, urllib.error.HTTPError):
                try:
                    body = e.read().decode()[:300]
                except Exception:
                    pass
            last = f"{type(e).__name__}: {e} {body}"
    raise TransportError(last)


def _openai(model, prompt):
    d = _post("https://api.openai.com/v1/chat/completions",
              {"model": model, "messages": [{"role": "user", "content": prompt}]},
              {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
               "content-type": "application/json"})
    return d["choices"][0]["message"]["content"]


def _gemini(model, prompt):
    d = _post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key=" + os.environ["GEMINI_API_KEY"],
        {"contents": [{"parts": [{"text": prompt}]}],
         "generationConfig": {"temperature": 0, "maxOutputTokens": MAX_TOKENS}},
        {"content-type": "application/json"})
    cand = d["candidates"][0]
    parts = cand.get("content", {}).get("parts", [])
    if not parts:
        raise TransportError(f"no parts; finishReason={cand.get('finishReason')}")
    return parts[0]["text"]


def _anthropic(model, prompt):
    d = _post("https://api.anthropic.com/v1/messages",
              {"model": model, "max_tokens": MAX_TOKENS, "temperature": 0,
               "messages": [{"role": "user", "content": prompt}]},
              {"x-api-key": os.environ["ANTHROPIC_API_KEY"],
               "anthropic-version": "2023-06-01",
               "content-type": "application/json"})
    return d["content"][0]["text"]


ROUTES = {"gpt-5": _openai, "gpt-5-mini": _openai,
          "gemini-2.5-flash": _gemini,
          "claude-sonnet-5": _anthropic, "claude-opus-5": _anthropic}


def complete(model, prompt):
    if model not in ROUTES:
        raise KeyError(f"unpinned model {model!r}")
    return ROUTES[model](model, prompt)


def smoke(model):
    """Preflight. Returns True only on a real answer."""
    try:
        return bool(complete(model, "Reply with the single word: OK").strip())
    except Exception:
        return False
