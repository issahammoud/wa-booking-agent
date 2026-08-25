from unittest.mock import patch

import redis
from django.apps import apps
from django.db.utils import OperationalError
from django.urls import reverse

from core.tasks import log_test_task


def test_core_app_is_registered():
    assert apps.is_installed("core")


def test_log_test_task_runs_and_returns_message(caplog):
    with caplog.at_level("INFO"):
        result = log_test_task.apply(args=["hello from test"])
    assert result.result == "hello from test"
    assert "hello from test" in caplog.text


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
