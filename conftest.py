import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

# Configure Celery for synchronous execution during tests
# This ensures that process_review.delay() runs inline, making tests deterministic.
from app.worker.celery import celery
celery.conf.task_always_eager = True
celery.conf.task_eager_propagates = False
