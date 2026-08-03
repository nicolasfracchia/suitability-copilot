"""Global test configuration.

Import order matters here: app.core.config reads the environment at import
time, so the defaults below must be set before any app module is imported.
"""
import os

# Force the deterministic offline reviewer. Without this, a developer with a
# real OPENAI_API_KEY in .env would have LLMService build a live client during
# tests, making the suite depend on network and credentials.
os.environ.setdefault("LLM_PROVIDER", "stub")
os.environ.setdefault("OPENAI_API_KEY", "")

# Matches the docker-compose service names; CI overrides this to localhost.
os.environ.setdefault(
    "DATABASE_URL", "postgresql://postgres:postgres@db:5432/copilot"
)

from app.worker.celery import celery  # noqa: E402

# Run process_review.delay() inline so tests observe the completed pipeline
# without needing a live Celery worker.
celery.conf.task_always_eager = True
celery.conf.task_eager_propagates = False
