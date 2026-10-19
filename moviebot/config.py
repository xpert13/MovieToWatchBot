from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    telegram_token: str
    tmdb_api_key: str
    omdb_api_key: str | None
    allowed_chat_ids: frozenset[int]
    language: str
    max_results: int
    include_tv: bool
    delete_original: bool
    log_level: str

    @classmethod
    def from_env(cls) -> Config:
        missing = [name for name in ("TELEGRAM_BOT_TOKEN", "TMDB_API_KEY") if not _get(name)]
        if missing:
            raise SystemExit(f"Missing required environment variables: {', '.join(missing)} (see .env.example)")
        return cls(
            telegram_token=_get("TELEGRAM_BOT_TOKEN"),
            tmdb_api_key=_get("TMDB_API_KEY"),
            omdb_api_key=_get("OMDB_API_KEY") or None,
            allowed_chat_ids=frozenset(int(i) for i in _get("ALLOWED_CHAT_IDS").replace(" ", "").split(",") if i),
            language=_get("LANGUAGE") or "en-US",
            max_results=max(1, int(_get("MAX_RESULTS") or 3)),
            include_tv=_bool(_get("INCLUDE_TV"), default=True),
            delete_original=_bool(_get("DELETE_ORIGINAL"), default=False),
            log_level=(_get("LOG_LEVEL") or "INFO").upper(),
        )


def _get(name: str) -> str:
    return os.environ.get(name, "").strip()


def _bool(value: str, default: bool) -> bool:
    return value.lower() in {"1", "true", "yes", "on"} if value else default
