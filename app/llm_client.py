"""
LLM client — thin abstraction over Groq (default) or Ollama.

Swap providers by editing llm_config.json in the project root:
  { "provider": "groq",   "model": "llama-3.3-70b-versatile" }
  { "provider": "ollama", "model": "llama3.1:8b" }

The public interface is a single function:
  call(prompt: str) -> dict

It always returns a dict with keys:
  score, points, explanation, student_feedback, flags (list of strings)

If the LLM call fails for any reason, it returns a safe fallback dict
so a network hiccup never kills a grading run.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------

def _load_llm_config() -> dict[str, Any]:
    config_path = _ROOT / "llm_config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.1,
        "max_tokens": 600,
    }


def _load_env_key(key_name: str = "GROQ_API_KEY") -> str:
    """Read an API key from .env file or environment.

    Supported keys: GROQ_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY.
    """
    env_path = _ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            k, _, v = line.partition("=")
            if k.strip() == key_name:
                return v.strip().strip('"').strip("'")
    return os.environ.get(key_name, "")


# ---------------------------------------------------------------------------
# Groq client
# ---------------------------------------------------------------------------

def _call_groq(prompt: str, config: dict) -> dict:
    try:
        from groq import Groq, RateLimitError, APIStatusError
    except ImportError:
        raise RuntimeError(
            "groq package not installed. Run: pip install groq"
        )

    api_key = _load_env_key("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY not found. Add it to your .env file."
        )

    client = Groq(api_key=api_key)
    max_retries = 4
    wait = 10  # seconds — start at 10s, double each retry

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=config.get("model", "llama-3.3-70b-versatile"),
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert CS teacher grading middle school "
                            "Python/Pygame assignments. You always respond with "
                            "valid JSON only — no markdown, no preamble, no "
                            "explanation outside the JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=config.get("temperature", 0.1),
                max_tokens=config.get("max_tokens", 600),
            )
            raw = response.choices[0].message.content.strip()
            # Strip markdown code fences if model adds them
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())

        except Exception as exc:
            error_str = str(exc)
            is_rate_limit = (
                "429" in error_str
                or "rate_limit" in error_str.lower()
                or "rate limit" in error_str.lower()
                or "too many" in error_str.lower()
            )
            if is_rate_limit and attempt < max_retries - 1:
                import time
                print(f"  ⏳ Rate limit hit — waiting {wait}s before retry {attempt + 2}/{max_retries}...")
                time.sleep(wait)
                wait = min(wait * 2, 60)  # double wait, cap at 60s
                continue
            raise  # re-raise on non-rate-limit errors or final attempt


# ---------------------------------------------------------------------------
# Ollama client
# ---------------------------------------------------------------------------

def _call_ollama(prompt: str, config: dict) -> dict:
    try:
        import requests
    except ImportError:
        raise RuntimeError("requests package not installed.")

    base_url = config.get("ollama_url", "http://localhost:11434")
    payload = {
        "model": config.get("model", "llama3.1:8b"),
        "prompt": prompt,
        "stream": False,
        "format": "json",
    }
    resp = requests.post(f"{base_url}/api/generate", json=payload, timeout=120)
    resp.raise_for_status()
    raw = resp.json().get("response", "").strip()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Fallback (returns a safe non-zero score so grading never silently fails)
# ---------------------------------------------------------------------------

def _fallback_result(error: str) -> dict:
    return {
        "score": 1,
        "points": 50,
        "explanation": f"AI grader unavailable — scored as attempt. Error: {error}",
        "student_feedback": "Your teacher will review this submission.",
        "flags": [f"AI grader error: {error}"],
    }


# ---------------------------------------------------------------------------
# OpenAI client
# ---------------------------------------------------------------------------

def _call_openai(prompt: str, config: dict) -> dict:
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError(
            "openai package not installed. Run: pip install openai"
        )

    api_key = _load_env_key("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY not found. Add it to your .env file."
        )

    client = OpenAI(api_key=api_key)
    max_retries = 4
    wait = 5  # OpenAI rarely rate-limits so start smaller

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=config.get("model", "gpt-4o-mini"),
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an expert CS teacher grading middle school "
                            "Python/Pygame assignments. You always respond with "
                            "valid JSON only — no markdown, no preamble, no "
                            "explanation outside the JSON."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=config.get("temperature", 0.1),
                max_tokens=config.get("max_tokens", 400),
                response_format={"type": "json_object"},  # guarantees JSON output
            )
            raw = response.choices[0].message.content.strip()
            return json.loads(raw)

        except Exception as exc:
            error_str = str(exc)
            is_rate_limit = (
                "429" in error_str
                or "rate_limit" in error_str.lower()
                or "rate limit" in error_str.lower()
            )
            if is_rate_limit and attempt < max_retries - 1:
                import time
                print(f"  ⏳ Rate limit hit — waiting {wait}s before retry {attempt + 2}/{max_retries}...")
                time.sleep(wait)
                wait = min(wait * 2, 30)
                continue
            raise


# ---------------------------------------------------------------------------
# Anthropic (Claude) client
# ---------------------------------------------------------------------------

def _call_anthropic(prompt: str, config: dict) -> dict:
    try:
        from anthropic import Anthropic
    except ImportError:
        raise RuntimeError(
            "anthropic package not installed. Run: pip install anthropic"
        )

    api_key = _load_env_key("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not found. Add it to your .env file."
        )

    client = Anthropic(api_key=api_key)
    max_retries = 4
    wait = 5

    for attempt in range(max_retries):
        try:
            response = client.messages.create(
                model=config.get("model", "claude-haiku-4-5"),
                max_tokens=config.get("max_tokens", 400),
                temperature=config.get("temperature", 0.1),
                system=(
                    "You are an expert CS teacher grading middle school "
                    "Python/Pygame assignments. You always respond with "
                    "valid JSON only — no markdown, no preamble, no "
                    "explanation outside the JSON object."
                ),
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )
            raw = response.content[0].text.strip()
            # Strip code fences if Claude adds them despite instructions
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())

        except Exception as exc:
            error_str = str(exc)
            is_rate_limit = (
                "429" in error_str
                or "rate_limit" in error_str.lower()
                or "rate limit" in error_str.lower()
                or "overloaded" in error_str.lower()
            )
            if is_rate_limit and attempt < max_retries - 1:
                import time
                print(f"  ⏳ Rate limit hit — waiting {wait}s before retry {attempt + 2}/{max_retries}...")
                time.sleep(wait)
                wait = min(wait * 2, 30)
                continue
            raise


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def call(prompt: str) -> dict:
    """Send a grading prompt to the configured LLM.

    Returns a dict with keys: score, points, explanation, student_feedback, flags.
    Never raises — falls back gracefully on any error.
    """
    config = _load_llm_config()
    provider = config.get("provider", "groq")

    try:
        if provider == "groq":
            result = _call_groq(prompt, config)
        elif provider == "openai":
            result = _call_openai(prompt, config)
        elif provider == "anthropic":
            result = _call_anthropic(prompt, config)
        elif provider == "ollama":
            result = _call_ollama(prompt, config)
        else:
            return _fallback_result(f"Unknown provider: {provider}")

        # Normalise keys — model might use slightly different names
        score = int(result.get("score", result.get("rubric_score", 1)))
        score = max(0, min(3, score))  # clamp to 0-3

        points_map = {0: 0, 1: 50, 2: 75, 3: 100}
        points = result.get("points", points_map[score])

        return {
            "score": score,
            "points": points,
            "explanation": result.get("explanation", result.get("teacher_explanation", "")),
            "student_feedback": result.get("student_feedback", result.get("feedback", "")),
            "flags": result.get("flags", result.get("flag_reasons", [])),
        }

    except Exception as exc:
        return _fallback_result(str(exc))
