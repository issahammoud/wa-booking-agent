# syntax=docker/dockerfile:1

FROM python:3.12-slim AS builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Which requirements file to install: requirements/prod.txt for the
# production image, requirements/dev.txt for local development
# (see docker-compose.override.yml).
ARG REQUIREMENTS_FILE=requirements/prod.txt

COPY requirements/ requirements/
RUN python -m venv /venv \
    && /venv/bin/pip install --no-cache-dir --upgrade pip \
    && /venv/bin/pip install --no-cache-dir -r ${REQUIREMENTS_FILE}

# Compiles the Tailwind CSS bundle via the standalone CLI binary - no
# Node/npm needed anywhere in this image.
FROM debian:bookworm-slim AS tailwind

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ARG TAILWIND_VERSION=v4.3.3
RUN curl -sL -o /usr/local/bin/tailwindcss \
        "https://github.com/tailwindlabs/tailwindcss/releases/download/${TAILWIND_VERSION}/tailwindcss-linux-x64" \
    && chmod +x /usr/local/bin/tailwindcss

WORKDIR /app
COPY assets/tailwind assets/tailwind
COPY core/templates core/templates
COPY bookings/templates bookings/templates
COPY conversations/templates conversations/templates
COPY integrations/templates integrations/templates
RUN mkdir -p static/css \
    && tailwindcss -i assets/tailwind/input.css -o static/css/output.css --minify

FROM python:3.12-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home appuser

WORKDIR /app

COPY --from=builder /venv /venv
ENV PATH="/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY . .
COPY --from=tailwind /app/static/css/output.css static/css/output.css

# collectstatic only reads settings and walks STATICFILES_DIRS - it never
# touches the database or uses a secret meaningfully - so these placeholder
# values exist purely to let Django's settings module load during the
# build. They're never used at runtime: docker-compose's env_file supplies
# the real .env once the container actually starts.
RUN DJANGO_SETTINGS_MODULE=config.settings.prod \
    DJANGO_SECRET_KEY=build-only \
    DATABASE_URL=postgres://build:build@localhost:5432/build \
    REDIS_URL=redis://localhost:6379/0 \
    WHATSAPP_WEBHOOK_VERIFY_TOKEN=build-only \
    WHATSAPP_APP_SECRET=build-only \
    OPENROUTER_API_KEY=build-only \
    python manage.py collectstatic --noinput

RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000"]
