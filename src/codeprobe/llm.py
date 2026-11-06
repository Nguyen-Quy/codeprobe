from __future__ import annotations

import json
import logging
import os
from typing import Any

import requests

from .schemas import ModelTier

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


# Default Model Maps per Provider and Tier
PROVIDER_MODEL_MAPS = {
    "gemini": {
        ModelTier.FAST_INFER: "gemini-3.6-flash",
        ModelTier.STANDARD: "gemini-3.7-flash",
        ModelTier.REASONING_HEAVY: "gemini-3.8-pro-high",
    },
    "openai": {
        ModelTier.FAST_INFER: "gpt-4o-mini",
        ModelTier.STANDARD: "gpt-4o",
        ModelTier.REASONING_HEAVY: "o3-mini",
    },
    "anthropic": {
        ModelTier.FAST_INFER: "claude-3-5-haiku-20241022",
        ModelTier.STANDARD: "claude-3-5-sonnet-20241022",
        ModelTier.REASONING_HEAVY: "claude-3-7-sonnet-20250219",
    },
    "ollama": {
        ModelTier.FAST_INFER: "qwen2.5-coder:7b",
        ModelTier.STANDARD: "qwen2.5-coder:14b",
        ModelTier.REASONING_HEAVY: "deepseek-r1:14b",
    },
    "llama_server": {
        ModelTier.FAST_INFER: "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
        ModelTier.STANDARD: "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
        ModelTier.REASONING_HEAVY: "qwen2.5-coder-3b-instruct-q4_k_m.gguf",
    },
    "lmstudio": {
        ModelTier.FAST_INFER: "mistralai_devstral-small-2-24b-instruct-2512",
        ModelTier.STANDARD: "mistralai_devstral-small-2-24b-instruct-2512",
        ModelTier.REASONING_HEAVY: "mistralai_devstral-small-2-24b-instruct-2512",
    },
}


def detect_provider() -> str:
    """
    Detect the active LLM provider based on environment variables or local availability.
    Precedence:
    1. Explicit CODEPROBE_LLM_PROVIDER
    2. GEMINI_API_KEY / GOOGLE_API_KEY (Google Antigravity / Gemini)
    3. OPENAI_API_KEY (OpenAI / Codex / Cursor)
    4. ANTHROPIC_API_KEY (Claude Code)
    5. OLLAMA_HOST (Ollama local)
    6. LM_STUDIO_URL (LM Studio remote endpoint)
    7. Native local llama_server if binary & model or port 8033 are available
    """
    explicit = os.environ.get("CODEPROBE_LLM_PROVIDER", "").strip().lower()
    if explicit and explicit in PROVIDER_MODEL_MAPS:
        return explicit

    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"

    if os.environ.get("OPENAI_API_KEY"):
        return "openai"

    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic"

    if os.environ.get("OLLAMA_HOST"):
        return "ollama"

    if os.environ.get("LM_STUDIO_URL"):
        return "lmstudio"

    # Default local provider: native llama-server
    return "llama_server"


def resolve_model(
    provider: str,
    tier: ModelTier = ModelTier.STANDARD,
    model_override: str | None = None,
) -> str:
    """
    Resolve model name given provider, tier, and optional explicit model override.
    """
    if model_override:
        return model_override

    env_model = os.environ.get("CODEPROBE_LLM_MODEL")
    if env_model:
        return env_model

    return PROVIDER_MODEL_MAPS.get(provider, {}).get(tier, "default")


def chat(
    *,
    system_prompt: str,
    input_text: str,
    tier: ModelTier = ModelTier.STANDARD,
    model: str | None = None,
    provider: str | None = None,
    temperature: float = 0.0,
    timeout: int = 120,
    max_tokens: int | None = None,
) -> str:
    """
    Unified multi-provider chat entrypoint. Dispatches to Gemini, OpenAI, Anthropic, Ollama, or LM Studio.
    """
    active_provider = provider or detect_provider()
    active_model = resolve_model(active_provider, tier, model)

    if active_provider == "gemini":
        return _chat_gemini(
            system_prompt=system_prompt,
            input_text=input_text,
            model=active_model,
            temperature=temperature,
            timeout=timeout,
        )
    elif active_provider == "openai":
        return _chat_openai(
            system_prompt=system_prompt,
            input_text=input_text,
            model=active_model,
            temperature=temperature,
            timeout=timeout,
        )
    elif active_provider == "anthropic":
        return _chat_anthropic(
            system_prompt=system_prompt,
            input_text=input_text,
            model=active_model,
            temperature=temperature,
            timeout=timeout,
        )
    elif active_provider == "ollama":
        return _chat_ollama(
            system_prompt=system_prompt,
            input_text=input_text,
            model=active_model,
            temperature=temperature,
            timeout=timeout,
        )
    elif active_provider == "llama_server":
        return _chat_llama_server(
            system_prompt=system_prompt,
            input_text=input_text,
            model=active_model,
            temperature=temperature,
            timeout=timeout,
            max_tokens=max_tokens,
        )
    else:
        return _chat_lmstudio(
            system_prompt=system_prompt,
            input_text=input_text,
            model=active_model,
            temperature=temperature,
            timeout=timeout,
        )


# ---------------------------------------------------------------------------
# Provider Adapters (Zero heavy SDKs, pure standard HTTP requests)
# ---------------------------------------------------------------------------


def _chat_gemini(
    system_prompt: str, input_text: str, model: str, temperature: float, timeout: int
) -> str:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not api_key:
        raise LLMError(
            "GEMINI_API_KEY or GOOGLE_API_KEY is required for Gemini provider."
        )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": input_text}]}],
        "generationConfig": {
            "temperature": temperature,
        },
    }

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as exc:
        raise LLMError(f"Gemini API call failed ({model}): {exc}") from exc


def _chat_openai(
    system_prompt: str, input_text: str, model: str, temperature: float, timeout: int
) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise LLMError("OPENAI_API_KEY is required for OpenAI provider.")

    url = os.environ.get(
        "OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ],
        "temperature": temperature,
    }

    try:
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise LLMError(f"OpenAI API call failed ({model}): {exc}") from exc


def _chat_anthropic(
    system_prompt: str, input_text: str, model: str, temperature: float, timeout: int
) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY is required for Anthropic provider.")

    url = "https://api.anthropic.com/v1/messages"
    payload = {
        "model": model,
        "max_tokens": 4096,
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": input_text},
        ],
        "temperature": temperature,
    }

    try:
        resp = requests.post(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["content"][0]["text"]
    except Exception as exc:
        raise LLMError(f"Anthropic API call failed ({model}): {exc}") from exc


def _chat_ollama(
    system_prompt: str, input_text: str, model: str, temperature: float, timeout: int
) -> str:
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    url = f"{host.rstrip('/')}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        return data["message"]["content"]
    except Exception as exc:
        raise LLMError(f"Ollama API call failed ({model}) at {url}: {exc}") from exc


def _chat_lmstudio(
    system_prompt: str, input_text: str, model: str, temperature: float, timeout: int
) -> str:
    url = os.environ.get("LM_STUDIO_URL", "http://192.168.100.77:8033/api/v1/chat")
    payload = {
        "model": model,
        "system_prompt": system_prompt,
        "input": input_text,
        "temperature": temperature,
        "store": False,
    }

    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        return extract_text(data)
    except Exception as exc:
        raise LLMError(f"LM Studio API call failed ({model}) at {url}: {exc}") from exc


def _chat_llama_server(
    system_prompt: str,
    input_text: str,
    model: str,
    temperature: float,
    timeout: int,
    max_tokens: int | None = None,
) -> str:
    from .core.llm_server import (
        DEFAULT_HOST,
        DEFAULT_PORT,
        is_server_alive,
        start_server_daemon,
    )

    host = os.environ.get("LLAMA_SERVER_HOST", DEFAULT_HOST)
    port = int(os.environ.get("LLAMA_SERVER_PORT", str(DEFAULT_PORT)))

    # Ensure local server is running (auto-load daemon)
    if not is_server_alive(host=host, port=port):
        logger.info("Local llama-server is not running. Automatically starting daemon on %s:%s...", host, port)
        try:
            start_server_daemon(host=host, port=port)
        except Exception as exc:
            raise LLMError(f"Failed to auto-start local llama-server on {host}:{port}: {exc}") from exc

    url = f"http://{host}:{port}/v1/chat/completions"
    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": input_text},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens or 200,
    }

    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices", [])
        if choices and "message" in choices[0] and "content" in choices[0]["message"]:
            return choices[0]["message"]["content"]
        raise LLMError(f"Unexpected response schema from llama-server:\n{json.dumps(data, indent=2)}")
    except Exception as exc:
        raise LLMError(f"llama-server API call failed at {url}: {exc}") from exc


def extract_text(data: dict[str, Any]) -> str:
    output = data.get("output")
    if not isinstance(output, list):
        raise LLMError(f"Unexpected LM Studio response:\n{json.dumps(data, indent=2)}")

    messages: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "message":
            continue
        content = item.get("content")
        if isinstance(content, str):
            messages.append(content)

    if not messages:
        raise LLMError(f"LM Studio returned no message:\n{json.dumps(data, indent=2)}")

    return "\n".join(messages).strip()


def extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            raise LLMError(f"Expected JSON from LLM, got:\n{text}")
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"Invalid JSON from LLM:\n{text}") from exc

    if not isinstance(value, dict):
        raise LLMError(f"Expected JSON object, got: {type(value).__name__}")

    return value


INVESTIGATOR_SYSTEM_PROMPT = """
You are the investigation planner of a local coding agent.

You do NOT directly modify files.

Your job is to decide what repository evidence should be collected
before answering the user's coding question.

Return ONLY valid JSON.

Schema:

{
  "goal": "short description of what needs to be discovered",
  "search_queries": [
    "small useful search query"
  ],
  "files_to_read": [
    "path/from/search/results.py"
  ],
  "git_query": "",
  "reason": "short explanation"
}

Rules:

- Start with 1-4 useful repository searches.
- Search terms should be suitable for ripgrep.
- Do not invent file paths.
- Only put a file in files_to_read if that path is explicitly present
  in the supplied investigation evidence.
- Prefer concrete symbols, class names, function names, error messages,
  model names, database fields, or configuration keys.
- Do not solve the problem yet.
"""


def plan_investigation(
    user_request: str,
    context: str,
    tier: ModelTier = ModelTier.FAST_INFER,
    timeout: int = 60,
) -> dict[str, Any]:
    prompt = f"""
ORIGINAL USER REQUEST:

{user_request}

CURRENT INVESTIGATION EVIDENCE:

{context or "(no evidence collected yet)"}

Determine the next useful repository searches.
"""

    raw = chat(
        system_prompt=INVESTIGATOR_SYSTEM_PROMPT,
        input_text=prompt,
        tier=tier,
        timeout=timeout,
    )
    return extract_json(raw)


SOLVER_SYSTEM_PROMPT = """
You are a senior software engineer investigating a real repository.

Answer the user's original question using the supplied repository
evidence.

Rules:

- Use evidence from the repository.
- Do not invent files, functions, relationships, or behavior.
- Distinguish confirmed facts from hypotheses.
- Explain the likely root cause.
- Identify relevant files and code when possible.
- If evidence is insufficient, explicitly say what is missing.
- Do not claim that you executed anything unless execution evidence
  is supplied.
- Keep answers concise, factual, and under 120 words.
"""


def solve(
    user_request: str,
    context: str,
    tier: ModelTier = ModelTier.REASONING_HEAVY,
    timeout: int = 60,
    max_tokens: int = 180,
) -> str:
    prompt = f"""
ORIGINAL USER REQUEST:

{user_request}

REPOSITORY INVESTIGATION EVIDENCE:

{context}
"""

    return chat(
        system_prompt=SOLVER_SYSTEM_PROMPT,
        input_text=prompt,
        tier=tier,
        timeout=timeout,
        max_tokens=max_tokens,
    )
