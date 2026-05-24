# Convenience wrappers for the dashboard generator.
# `uv` is the source of truth; this Makefile just keeps muscle memory short.

.PHONY: help install build check format lint clean

help:
	@grep -E '^[a-zA-Z_-]+:' $(MAKEFILE_LIST) | awk -F':' '{printf "  %-12s %s\n", $$1, $$2}'

install:           ## install / sync deps (uv handles the lock)
	uv sync

build:             ## regenerate every dashboard JSON
	uv run dashboards build

check:             ## fail if any committed dashboard JSON drifts from the generator
	uv run dashboards check

format:            ## auto-format with ruff
	uv run ruff format .

lint:              ## ruff lint
	uv run ruff check .

clean:             ## drop the virtualenv
	rm -rf .venv
