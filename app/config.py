"""Configuration management for GridWise Smart Campus Energy Optimization."""

import os
from typing import Optional
from pydantic import BaseModel, Field


class Settings(BaseModel):
    # Server settings
    host: str = Field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = Field(default_factory=lambda: int(os.getenv("PORT", "8000")))

    # LLM Settings
    # Supported providers: openai, anthropic, groq, custom, offline
    llm_provider: str = Field(default_factory=lambda: os.getenv("LLM_PROVIDER", "openai").lower())
    llm_api_key: Optional[str] = Field(default_factory=lambda: os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or os.getenv("ANTHROPIC_API_KEY") or os.getenv("GROQ_API_KEY"))
    llm_model: Optional[str] = Field(default_factory=lambda: os.getenv("LLM_MODEL"))
    llm_base_url: Optional[str] = Field(default_factory=lambda: os.getenv("LLM_BASE_URL"))
    llm_timeout_seconds: float = Field(default_factory=lambda: float(os.getenv("LLM_TIMEOUT_SECONDS", "8.0")))

    # Numeric tolerances
    tolerance: float = 0.01

    def get_effective_model(self) -> str:
        if self.llm_model:
            return self.llm_model
        if self.llm_provider == "anthropic":
            return "claude-3-5-haiku-20241022"
        elif self.llm_provider == "groq":
            return "llama-3.3-70b-versatile"
        elif self.llm_provider == "offline":
            return "offline-rule-based-calibrator"
        return "gpt-4o-mini"

    def masked_api_key(self) -> str:
        if not self.llm_api_key:
            return "<NOT_SET>"
        if len(self.llm_api_key) <= 8:
            return "***"
        return f"{self.llm_api_key[:4]}...{self.llm_api_key[-4:]}"


settings = Settings()
