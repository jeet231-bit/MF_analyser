# mf-analyser task runner. On machines without GNU make, `npm run <target>` mirrors every target here.
.PHONY: install dev dev-backend dev-frontend test test-backend test-frontend lint lint-backend lint-frontend

install:
	cd backend && uv sync
	cd frontend && npm install
	npm install

dev:
	npx concurrently -k -n api,web -c blue,green "$(MAKE) dev-backend" "$(MAKE) dev-frontend"

dev-backend:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

dev-frontend:
	cd frontend && npm run dev

test: test-backend test-frontend

test-backend:
	cd backend && uv run pytest

test-frontend:
	cd frontend && npm test -- --run

lint: lint-backend lint-frontend

lint-backend:
	cd backend && uv run ruff check . && uv run ruff format --check .

lint-frontend:
	cd frontend && npm run lint && npm run typecheck
