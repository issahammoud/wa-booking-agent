from django.apps import apps


def test_core_app_is_registered():
    assert apps.is_installed("core")
