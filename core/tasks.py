import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def log_test_task(message="Celery is working"):
    logger.info(message)
    return message
