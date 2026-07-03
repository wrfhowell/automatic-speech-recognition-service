.PHONY: up down logs test unit integration e2e deid lint psql

up:
	docker compose up --build -d

down:
	docker compose down -v

logs:
	docker compose logs -f

test:
	cd backend && uv run pytest

unit:
	cd backend && uv run pytest tests/unit tests/deid

integration:
	cd backend && uv run pytest tests/integration

e2e:
	cd backend && uv run pytest tests/e2e

deid:
	cd backend && uv run python -m app.deid.train

lint:
	cd backend && uv run ruff check .

psql:
	docker compose exec postgres psql -U asr -d asr
