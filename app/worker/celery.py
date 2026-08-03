from celery import Celery

from app.core.config import settings

REDIS_URL = settings.REDIS_URL

celery = Celery(
    "copilot",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["app.worker.tasks"],
)

celery.conf.update(
    task_acks_late=True,              # Acknowledge only after execution completes
    worker_prefetch_multiplier=1,     # No task hoarding; fair dispatch across workers
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Ceiling on in-flight provider calls per worker process. This — not the
    # in-process semaphore — is the real concurrency control for the pipeline.
    worker_concurrency=4,
    # A task that outlives this is killed rather than pinning a worker slot.
    # Comfortably above the provider's own 10s request timeout.
    task_time_limit=120,
    task_soft_time_limit=90,
)

if __name__ == "__main__":
    celery.start()
