"""Settings from environment variables (12-factor style), with safe defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # "live" reads Wikimedia; "replay" reads REPLAY_FILE (offline dev, tests, demo fallback)
    source: str = os.getenv("WIKIPULSE_SOURCE", "live")
    replay_file: str = os.getenv("REPLAY_FILE", "data/sample_events.jsonl")
    replay_speed: float = float(os.getenv("REPLAY_SPEED", "1.0"))
    window_seconds: int = int(os.getenv("WINDOW_SECONDS", "300"))
    include_bots: bool = _bool("INCLUDE_BOTS", False)
    cors_origins: tuple[str, ...] = tuple(
        o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()
    )


settings = Settings()
