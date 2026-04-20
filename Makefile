.PHONY: install start migrate test lint format typecheck

install:
	poetry install

start:
	poetry run uvicorn main:app --reload --port 8001

migrate:
	poetry run alembic upgrade head

test:
	poetry run pytest tests/ -v

lint:
	poetry run ruff check .

format:
	poetry run ruff format .

typecheck:
	poetry run mypy .
