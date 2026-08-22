# wa-booking-agent

A multi-tenant WhatsApp booking agent, built on Django.

## Local setup

Requires Docker and Docker Compose.

1. Copy the example environment file and fill in real values (the
   defaults work fine for local dev as-is):

   ```sh
   cp .env.example .env
   ```

2. Bring up the stack:

   ```sh
   docker compose up --build
   ```

   This starts three services: `app` (Django dev server on
   `localhost:8000`), `db` (Postgres 16 on `localhost:5432`), and
   `redis` (Redis 7 on `localhost:6379`). `docker-compose.override.yml`
   is picked up automatically and gives the `app` container hot reload
   via a bind mount of the repo.

3. In another terminal, apply migrations:

   ```sh
   docker compose exec app python manage.py migrate
   ```

4. Confirm everything is wired up:

   ```sh
   curl localhost:8000/health/
   ```

   should return `{"database": "ok", "redis": "ok"}` with a 200 status.

## Running tests and linters

```sh
docker compose exec app pytest
docker compose exec app ruff check .
docker compose exec app black --check .
```

## Pre-commit hooks

Install once per clone (needs a local Python virtualenv with
`requirements/dev.txt` installed, since pre-commit runs on the host,
not in the container):

```sh
python3.12 -m venv .venv
.venv/bin/pip install -r requirements/dev.txt
.venv/bin/pre-commit install
```

From then on, ruff and black run automatically on every commit.

## Project layout

- `config/` - Django project package; settings are split into
  `config/settings/{base,dev,prod}.py`
- `tenants/`, `conversations/`, `bookings/`, `integrations/`, `core/` -
  Django apps
- `requirements/{base,dev,prod}.txt` - dependency sets for the base
  install, local development, and production
