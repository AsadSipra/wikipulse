"""Settings from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # "live" or "replay" (reads REPLAY_FILE)
    source: str = os.getenv("WIKIPULSE_SOURCE", "live")
    replay_file: str = os.getenv("REPLAY_FILE", "data/sample_events.jsonl")
    replay_speed: float = float(os.getenv("REPLAY_SPEED", "1.0"))
    window_seconds: int = int(os.getenv("WINDOW_SECONDS", "300"))
    include_bots: bool = _bool("INCLUDE_BOTS", False)
    wikipedia_only: bool = _bool("WIKIPEDIA_ONLY", True)
    # Any OpenAI-compatible endpoint; defaults to a local Ollama.
    ai_enabled: bool = _bool("AI_ENABLED", True)
    llm_base_url: str = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
    llm_api_key: str = os.getenv("LLM_API_KEY", "")
    llm_model: str = os.getenv("LLM_MODEL", "llama3.2")
    llm_timeout: float = float(os.getenv("LLM_TIMEOUT", "30"))
    llm_max_tokens: int = int(os.getenv("LLM_MAX_TOKENS", "300"))
    # Calls per minute, per feature.
    vandalism_calls_per_minute: int = int(os.getenv("VANDALISM_CALLS_PER_MINUTE", "16"))
    pulse_calls_per_minute: int = int(os.getenv("PULSE_CALLS_PER_MINUTE", "4"))
    pulse_interval_seconds: float = float(os.getenv("PULSE_INTERVAL_SECONDS", "60"))
    fetch_diffs: bool = _bool("FETCH_DIFFS", True)
    cors_origins: tuple[str, ...] = tuple(
        o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
    )


settings = Settings()
