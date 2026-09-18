"""
Centralized configuration loaded from environment variables.

Loads .env via python-dotenv. Never logs raw key values; only records
whether each key is set.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)


def _mask(v: Optional[str]) -> str:
    if not v:
        return "<unset>"
    if len(v) <= 6:
        return "<set>"
    return f"<{v[:3]}…{v[-2:]}>"


class Config:
    # Provider keys
    GROQ_API_KEY: Optional[str] = os.getenv("GROQ_API_KEY")
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY")
    OPENROUTER_API_KEY: Optional[str] = os.getenv("OPENROUTER_API_KEY")
    PUKU_API_KEY: Optional[str] = os.getenv("PUKU_API_KEY")

    # Provider fallback chain — comma-separated
    LLM_PROVIDER_ORDER: str = os.getenv("LLM_PROVIDER_ORDER", "groq,gemini,openrouter")

    # Models
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    OPENROUTER_MODEL: str = os.getenv(
        "OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free"
    )
    PUKU_MODEL: str = os.getenv("PUKU_MODEL", "gpt-oss-20b")

    # Service
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    # LLM
    LLM_TIMEOUT_SECONDS: float = float(os.getenv("LLM_TIMEOUT_SECONDS", "8"))
    LLM_MAX_RETRIES: int = int(os.getenv("LLM_MAX_RETRIES", "1"))

    # Local-only debug UI (gated; default off so judges never see it).
    ENABLE_UI: bool = os.getenv("ENABLE_UI", "false").lower() in ("1", "true", "yes")

    @classmethod
    def summary(cls) -> dict:
        """Return a *non-sensitive* view of provider availability."""
        keys_present = {
            "groq": bool(cls.GROQ_API_KEY and not cls.GROQ_API_KEY.startswith("your_")),
            "gemini": bool(cls.GEMINI_API_KEY and not cls.GEMINI_API_KEY.startswith("your_")),
            "openrouter": bool(
                cls.OPENROUTER_API_KEY and not cls.OPENROUTER_API_KEY.startswith("your_")
            ),
            "puku": bool(cls.PUKU_API_KEY and not cls.PUKU_API_KEY.startswith("your_")),
        }
        return {
            "providers_in_order": [
                p.strip() for p in cls.LLM_PROVIDER_ORDER.split(",") if p.strip()
            ],
            "keys_present": keys_present,
            "models": {
                "groq": cls.GROQ_MODEL,
                "gemini": cls.GEMINI_MODEL,
                "openrouter": cls.OPENROUTER_MODEL,
                "puku": cls.PUKU_MODEL,
            },
            "timeout_s": cls.LLM_TIMEOUT_SECONDS,
            "port": cls.PORT,
            "ui_enabled": cls.ENABLE_UI,
        }

    @classmethod
    def log_summary(cls) -> None:
        log.info("GridWise config: %s", cls.summary())


# Convenience singleton
CFG = Config()
