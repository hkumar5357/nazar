"""Provider-agnostic LLM client (PROTOCOL R5's ONLY LLM call site).

label_text(text) sends prompts.build_prompt(text) to whichever provider is
configured via the LLM_PROVIDER env var (gemini | openai | anthropic;
gemini is the default) and returns a single classification label plus
bookkeeping. Everything is plain `requests` REST -- no provider SDKs -- at
temperature 0, with model ids pinned via env vars with sane defaults:

    GEMINI_MODEL    default "gemini-2.5-flash"
    OPENAI_MODEL    default "gpt-5-mini"
    ANTHROPIC_MODEL default "claude-haiku-4-5-20251001"

No network call happens at import time -- every `requests.post` call lives
inside a function, never at module level. Credentials and provider/model
selection are read from the environment at call time (python-dotenv loaded
inside _resolve_provider(), not on import), matching the convention used
by pipeline.ingest.reddit / pipeline.ingest.youtube.

Missing key -> MissingLLMKey (not a silent fixture fallback): the caller
(pipeline.label.intent_labeler) catches this and falls back to the keyword
heuristic in prompts.py, and stamps the resulting labels with
fixture_heuristic provenance rather than pretending they came from an LLM.

Response parsing is strict JSON with exactly one retry: a response that
doesn't parse into {"label": <valid label>} triggers a second call to the
same provider; if that also fails to parse, label_text raises.
"""

from __future__ import annotations

import json
import os

import requests
from dotenv import load_dotenv

from pipeline.label import prompts

_VALID_LABELS = {"cafe_experience", "home_or_CPG", "other"}

_PROVIDER_KEY_ENV = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
_PROVIDER_MODEL_ENV = {
    "gemini": "GEMINI_MODEL",
    "openai": "OPENAI_MODEL",
    "anthropic": "ANTHROPIC_MODEL",
}
_PROVIDER_DEFAULT_MODEL = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-5-mini",
    "anthropic": "claude-haiku-4-5-20251001",
}

_TIMEOUT_S = 30
_ANTHROPIC_MAX_TOKENS = 64  # plenty for a one-line {"label": "..."} reply


class MissingLLMKey(RuntimeError):
    """Raised by label_text() when the configured provider's API key env
    var is absent or empty. There is no silent fixture fallback here --
    callers (pipeline.label.intent_labeler) catch this and switch to the
    keyword heuristic, stamping the result as fixture_heuristic provenance.
    """


def _resolve_provider() -> str:
    """LLM_PROVIDER from the environment, defaulting to 'gemini' (BRIEF §2).
    Loads .env at call time so importing this module touches no files."""
    load_dotenv()
    provider = (os.environ.get("LLM_PROVIDER") or "gemini").strip().lower()
    if provider not in _PROVIDER_KEY_ENV:
        raise ValueError(
            f"unknown LLM_PROVIDER {provider!r}; must be one of "
            f"{sorted(_PROVIDER_KEY_ENV)}"
        )
    return provider


def has_api_key() -> bool:
    """True if the configured provider's API key is present and non-empty.

    Lets intent_labeler decide llm-vs-heuristic up front without making a
    network call (an unknown LLM_PROVIDER value is treated as "not
    configured" here, rather than raising -- label_text() is the strict
    validator; this is just a cheap readiness check).
    """
    load_dotenv()
    provider = (os.environ.get("LLM_PROVIDER") or "gemini").strip().lower()
    key_env = _PROVIDER_KEY_ENV.get(provider)
    if key_env is None:
        return False
    return bool(os.environ.get(key_env, "").strip())


def _parse_label(raw_text: str) -> str:
    """Strict JSON parse of a provider's raw text reply into a label.

    Tolerates a markdown code fence some models add despite instructions
    ("```json\\n{...}\\n```") but otherwise demands an exact
    {"label": "<one of the three values>"} object.
    """
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[len("json"):].strip()
    try:
        data = json.loads(cleaned)
    except ValueError as exc:
        raise ValueError(f"response was not valid JSON: {raw_text!r}") from exc
    if not isinstance(data, dict) or "label" not in data:
        raise ValueError(f"response JSON missing 'label' key: {raw_text!r}")
    label = data["label"]
    if label not in _VALID_LABELS:
        raise ValueError(
            f"response label {label!r} is not one of {sorted(_VALID_LABELS)}: {raw_text!r}"
        )
    return label


def _call_gemini(prompt: str, model: str, api_key: str) -> tuple[str, int, int]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    resp = requests.post(
        url,
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        },
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    usage = data.get("usageMetadata", {})
    return (
        text,
        int(usage.get("promptTokenCount", 0)),
        int(usage.get("candidatesTokenCount", 0)),
    )


def _call_openai(prompt: str, model: str, api_key: str) -> tuple[str, int, int]:
    resp = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return (
        text,
        int(usage.get("prompt_tokens", 0)),
        int(usage.get("completion_tokens", 0)),
    )


def _call_anthropic(prompt: str, model: str, api_key: str) -> tuple[str, int, int]:
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": _ANTHROPIC_MAX_TOKENS,
            "temperature": 0,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    data = resp.json()
    text = "".join(
        block.get("text", "")
        for block in data.get("content", [])
        if block.get("type") == "text"
    )
    usage = data.get("usage", {})
    return (
        text,
        int(usage.get("input_tokens", 0)),
        int(usage.get("output_tokens", 0)),
    )


_PROVIDER_CALL = {
    "gemini": _call_gemini,
    "openai": _call_openai,
    "anthropic": _call_anthropic,
}


def label_text(text: str) -> dict:
    """Classify one text item via the configured LLM provider.

    Temperature 0. Raises MissingLLMKey if the provider's API key env var
    is absent or empty. On a JSON-parse failure, retries the call once
    against the same provider/model before raising ValueError.

    Returns {label, provider, model, tokens_in, tokens_out} -- token
    counts come from the response's usage fields, 0 if a provider omits
    them.
    """
    provider = _resolve_provider()
    key_env = _PROVIDER_KEY_ENV[provider]
    api_key = os.environ.get(key_env, "").strip()
    if not api_key:
        raise MissingLLMKey(
            f"{key_env} is not set; cannot call the {provider!r} LLM provider "
            "(PROTOCOL R5 labeling stack falls back to the keyword heuristic)."
        )
    model_env = _PROVIDER_MODEL_ENV[provider]
    model = (os.environ.get(model_env) or _PROVIDER_DEFAULT_MODEL[provider]).strip()
    call = _PROVIDER_CALL[provider]
    prompt = prompts.build_prompt(text)

    last_error: Exception | None = None
    for _attempt in range(2):
        raw_text, tokens_in, tokens_out = call(prompt, model, api_key)
        try:
            label = _parse_label(raw_text)
        except ValueError as exc:
            last_error = exc
            continue
        return {
            "label": label,
            "provider": provider,
            "model": model,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        }
    raise ValueError(
        "LLM response was not a valid {\"label\": ...} JSON object after 2 "
        f"attempts ({provider}/{model}): {last_error}"
    )
