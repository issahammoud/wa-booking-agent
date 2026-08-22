from unittest.mock import patch

import redis
from django.apps import apps
from django.db.utils import OperationalError
from django.urls import reverse


def test_core_app_is_registered():
    assert apps.is_installed("core")


def test_health_check_returns_200_when_healthy(client):
    with (
        patch("django.db.connection.ensure_connection"),
        patch("redis.Redis.ping", return_value=True),
    ):
        response = client.get(reverse("health-check"))
    assert response.status_code == 200
    assert response.json() == {"database": "ok", "redis": "ok"}


def test_health_check_returns_503_when_database_unreachable(client):
    with (
        patch("django.db.connection.ensure_connection", side_effect=OperationalError),
        patch("redis.Redis.ping", return_value=True),
    ):
        response = client.get(reverse("health-check"))
    assert response.status_code == 503
    assert response.json() == {"database": "error", "redis": "ok"}


def test_health_check_returns_503_when_redis_unreachable(client):
    with (
        patch("django.db.connection.ensure_connection"),
        patch("redis.Redis.ping", side_effect=redis.RedisError),
    ):
        response = client.get(reverse("health-check"))
    assert response.status_code == 503
    assert response.json() == {"database": "ok", "redis": "error"}
