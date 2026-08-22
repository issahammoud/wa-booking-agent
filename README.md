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
   make up
   ```

   This starts three services in the background: `app` (Django dev
   server on `localhost:8000`), `db` (Postgres 18 on `localhost:5432`),
   and `redis` (Redis 7 on `localhost:6379`). `docker-compose.override.yml`
   is picked up automatically and gives the `app` container hot reload
   via a bind mount of the repo.

3. Apply migrations:

   ```sh
   make migrate
   ```

4. Confirm everything is wired up:

   ```sh
   make health
   ```

   should return `{"database": "ok", "redis": "ok"}` with a 200 status.

Run `make help` to see every available target, including `down` and
`shell`.

## Running tests and linters

```sh
make test
make lint
make format-check
```

## Pre-commit hooks

Install once per clone (needs a local Python virtualenv with
`requirements/dev.txt` installed, since pre-commit runs on the host,
not in the container):

```sh
make precommit-install
```

From then on, ruff and black run automatically on every commit. Run
`make precommit-run` to run all hooks against the whole repo on demand.

## Project layout

- `config/` - Django project package; settings are split into
  `config/settings/{base,dev,prod}.py`
- `tenants/`, `conversations/`, `bookings/`, `integrations/`, `core/` -
  Django apps
- `requirements/{base,dev,prod}.txt` - dependency sets for the base
  install, local development, and production
