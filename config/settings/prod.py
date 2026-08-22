"""Production settings, hardened per the Django deployment checklist.

See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/
"""

from .base import *  # noqa: F401,F403

DEBUG = False

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_SSL_REDIRECT = True

SECURE_HSTS_SECONDS = 60 * 60 * 24 * 7  # 1 week; raise once HTTPS is confirmed stable
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

X_FRAME_OPTIONS = "DENY"

# If deployed behind a reverse proxy/load balancer that terminates TLS and
# sets X-Forwarded-Proto, uncomment the line below - only do so once that
# proxy is confirmed to strip/overwrite any client-supplied header of the
# same name, otherwise it opens a spoofing hole.
# SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
