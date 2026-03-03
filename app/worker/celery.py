import os
from celery import Celery

# Get Redis URL from environment or default to local (for development)
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery = Celery(
    "copilot",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.worker.tasks"]
)

# Production-ready configuration
celery.conf.update(
    task_acks_late=True,             # Task acknowledged after execution completes
    worker_prefetch_multiplier=1,     # One task per worker at a time (prevents hoarding)
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

if __name__ == "__main__":
    celery.start()
