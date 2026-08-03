import os

from dotenv import load_dotenv

# Loads .env when present. Absent .env is fine — every setting below has a
# default that matches the docker-compose stack.
load_dotenv()

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@db:5432/copilot"
DEFAULT_REDIS_URL = "redis://redis:6379/0"


class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL") or DEFAULT_DATABASE_URL
    REDIS_URL: str = os.getenv("REDIS_URL") or DEFAULT_REDIS_URL

    # Which review provider to use: auto | openai | stub. See app/services/providers.
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER") or "auto"
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY") or None
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL") or "gpt-4o"

    LOG_LEVEL: str = os.getenv("LOG_LEVEL") or "INFO"


settings = Settings()
