from __future__ import annotations

import json
import os
import re
from urllib.parse import urlparse
import urllib.error
import urllib.request

from .config import SummarizerConfig


def _normalize_cloudflare_compat_endpoint(url: str) -> str:
    trimmed = url.rstrip("/")
    if trimmed.endswith("/compat"):
        return f"{trimmed}/chat/completions"
    return trimmed


def _is_cloudflare_compat(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.netloc == "gateway.ai.cloudflare.com" and "/compat" in p.path
    except Exception:
        return False


def _post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "voice-logger/0.1",
            **headers,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        hint = ""
        if e.code == 403:
            hint = (
                " (403 Forbidden: check provider/endpoint/API key settings. "
                "For Cloudflare, verify AI Gateway endpoint and token permissions.)"
            )
        raise RuntimeError(f"LLM API error {e.code}: {detail}{hint}") from e


def summarize_text(text: str, cfg: SummarizerConfig) -> str:
    key_or_env = cfg.api_key_env.strip()
    api_key = os.getenv(key_or_env, "").strip()
    # Backward-compatible: allow direct API key value in config when env var is not used.
    if not api_key and key_or_env and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key_or_env):
        api_key = key_or_env
    if not api_key:
        raise RuntimeError(f"API key env var not set (or invalid direct key): {cfg.api_key_env}")

    provider = cfg.provider.lower()
    if provider in {"openai", "openrouter", "cloudflare"}:
        if not cfg.endpoint:
            raise RuntimeError(f"endpoint is required for provider={provider}")
        endpoint = cfg.endpoint
        model = cfg.model
        if _is_cloudflare_compat(endpoint):
            endpoint = _normalize_cloudflare_compat_endpoint(endpoint)
            if "/" not in model:
                model = f"openai/{model}"

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": cfg.system_prompt},
                {"role": "user", "content": text},
            ],
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        data = _post_json(endpoint, payload, headers)
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"Unexpected response: {data}")
        message = choices[0].get("message", {})
        content = message.get("content", "")
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
        return str(content).strip()

    if provider == "anthropic":
        endpoint = cfg.endpoint or "https://api.anthropic.com/v1/messages"
        payload = {
            "model": cfg.model,
            "max_tokens": 1200,
            "system": cfg.system_prompt,
            "messages": [{"role": "user", "content": text}],
        }
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
        data = _post_json(endpoint, payload, headers)
        content = data.get("content") or []
        result = "\n".join(item.get("text", "") for item in content if isinstance(item, dict))
        return result.strip()

    if provider == "gemini":
        model = cfg.model
        endpoint = (
            cfg.endpoint
            or f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        )
        payload = {
            "system_instruction": {"parts": [{"text": cfg.system_prompt}]},
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"temperature": 0.2},
        }
        data = _post_json(endpoint, payload, {})
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError(f"Unexpected response: {data}")
        parts = candidates[0].get("content", {}).get("parts", [])
        result = "\n".join(part.get("text", "") for part in parts if isinstance(part, dict))
        return result.strip()

    raise RuntimeError(f"Unsupported provider: {cfg.provider}")
