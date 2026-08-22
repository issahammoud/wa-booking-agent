.PHONY: help up down build migrate health test lint format-check shell precommit-install precommit-run

help:
	@echo "Available targets:"
	@echo "  up                - docker compose up --build"
	@echo "  down              - docker compose down"
	@echo "  build             - docker compose build"
	@echo "  migrate           - run Django migrations in the app container"
	@echo "  health            - curl the /health/ endpoint"
	@echo "  test              - run pytest in the app container"
	@echo "  lint              - run ruff check in the app container"
	@echo "  format-check      - run black --check in the app container"
	@echo "  shell             - open a shell in the app container"
	@echo "  precommit-install - create .venv, install dev deps, install the pre-commit hook"
	@echo "  precommit-run     - run pre-commit against all files"

up:
	docker compose up --build -d

down:
	docker compose down

build:
	docker compose build

migrate:
	docker compose exec app python manage.py migrate

health:
	curl -s -w "\nHTTP %{http_code}\n" localhost:8000/health/

test:
	docker compose exec app pytest

lint:
	docker compose exec app ruff check .

format-check:
	docker compose exec app black --check .

shell:
	docker compose exec app bash

precommit-install:
	python3.12 -m venv .venv
	.venv/bin/pip install -r requirements/dev.txt
	.venv/bin/pre-commit install

precommit-run:
	.venv/bin/pre-commit run --all-files
