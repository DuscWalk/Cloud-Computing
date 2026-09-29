.PHONY: install dev-api dev-web test check build up down
UV ?= uv

install:
	$(UV) sync --project backend --frozen
	cd frontend && npm ci

dev-api:
	cd backend && mkdir -p data && $(UV) run alembic upgrade head && $(UV) run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

dev-web:
	cd frontend && npm run dev

test:
	cd backend && $(UV) run pytest -q

check:
	$(UV) run --project backend ruff check backend
	$(UV) run --project backend ruff format --check backend
	cd frontend && npm run build

build:
	docker compose build

up:
	docker compose up -d --wait

down:
	docker compose down
