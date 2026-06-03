.DEFAULT_GOAL := help
.PHONY: help dev down logs ps clean \
        test test-backend test-frontend \
        lint lint-backend lint-frontend \
        format format-backend \
        typecheck typecheck-backend typecheck-frontend \
        backend-shell frontend-shell

# ----- Help -------------------------------------------------------------------

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ----- Dev stack --------------------------------------------------------------

dev:  ## Boot api + postgres + redis + frontend via docker compose
	docker compose up --build

down:  ## Stop the stack (keeps volumes)
	docker compose down

logs:  ## Tail logs from all services
	docker compose logs -f --tail=100

ps:  ## Show running services
	docker compose ps

clean:  ## Stop the stack and remove volumes + local caches
	docker compose down -v
	rm -rf backend/.venv backend/.pytest_cache backend/.mypy_cache backend/.ruff_cache
	rm -rf frontend/node_modules frontend/dist frontend/coverage

# ----- Test -------------------------------------------------------------------

test: test-backend test-frontend  ## Run all tests

test-backend:
	cd backend && uv run pytest

test-frontend:
	cd frontend && npm run test:run

# ----- Lint -------------------------------------------------------------------

lint: lint-backend lint-frontend  ## Run all linters

lint-backend:
	cd backend && uv run ruff check . && uv run ruff format --check .

lint-frontend:
	cd frontend && npm run lint

# ----- Format -----------------------------------------------------------------

format: format-backend  ## Apply formatters

format-backend:
	cd backend && uv run ruff format . && uv run ruff check --fix .

# ----- Typecheck --------------------------------------------------------------

typecheck: typecheck-backend typecheck-frontend  ## Run all typecheckers

typecheck-backend:
	cd backend && uv run mypy app

typecheck-frontend:
	cd frontend && npm run typecheck

# ----- Shells -----------------------------------------------------------------

backend-shell:  ## Open a shell in the running api container
	docker compose exec api bash

frontend-shell:  ## Open a shell in the running frontend container
	docker compose exec frontend sh
