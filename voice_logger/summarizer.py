from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .config import SummarizerConfig


def _post_json(url: str, payload: dict, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"LLM API error {e.code}: {detail}") from e


def summarize_text(text: str, cfg: SummarizerConfig) -> str:
    api_key = os.getenv(cfg.api_key_env, "").strip()
    if not api_key:
        raise RuntimeError(f"API key env var not set: {cfg.api_key_env}")

    provider = cfg.provider.lower()
    if provider in {"openai", "openrouter", "cloudflare"}:
        if not cfg.endpoint:
            raise RuntimeError(f"endpoint is required for provider={provider}")

        payload = {
            "model": cfg.model,
            "messages": [
                {"role": "system", "content": cfg.system_prompt},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        data = _post_json(cfg.endpoint, payload, headers)
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
