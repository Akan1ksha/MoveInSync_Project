"""
Central configuration loaded from environment variables.
Never hardcode secrets here — use a .env file (not committed).
"""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # --- JWT ---
    JWT_SECRET: str = "dev-secret-change-in-prod"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60

    # --- LLM ---
    LLM_PROVIDER: str = "gemini"          # "gemini" | "groq" | "fake"
    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    LLM_MODEL: str = "gemini-2.0-flash"
    LLM_TIMEOUT_SECONDS: float = 10.0
    MAX_LLM_CALLS_PER_TURN: int = 4      # hard ceiling enforced in graph

    # --- Storage ---
    DATABASE_URL: str = "sqlite:///./moveinsync.db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # --- Business ---
    DEFAULT_CUTOFF_HOURS: float = 2.0    # fallback if company policy missing

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
