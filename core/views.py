import redis
from django.conf import settings
from django.db import connection
from django.db.utils import OperationalError
from django.http import JsonResponse


def health_check(request):
    """Report DB/Redis connectivity. Returns 200 if both are reachable, 503 otherwise."""
    status = {"database": "ok", "redis": "ok"}
    healthy = True

    try:
        connection.ensure_connection()
    except OperationalError:
        status["database"] = "error"
        healthy = False

    try:
        redis.Redis.from_url(settings.REDIS_URL).ping()
    except redis.RedisError:
        status["redis"] = "error"
        healthy = False

    return JsonResponse(status, status=200 if healthy else 503)
