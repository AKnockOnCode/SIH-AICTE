# AgniDrishti developer commands (Linux / macOS; on Windows use scripts\dev.ps1 and the commands in README).
PYTHON ?= python3
VPY    := $(CURDIR)/.venv/bin/python
PORT   ?= 8000

.PHONY: help start dev setup build seed reset-db test e2e check-views lint typecheck types samples models check clean-models

help:            ## list the available commands
	@grep -E '^[a-z0-9-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/' | expand -t 18

start:           ## one command: set up if needed, build the UI, start http://localhost:$(PORT)
	PORT=$(PORT) PYTHON=$(PYTHON) ./scripts/dev.sh

dev:             ## development mode: UI rebuild on change + API auto-reload
	PORT=$(PORT) PYTHON=$(PYTHON) ./scripts/dev.sh --watch

setup:           ## create .venv and install backend (incl. test tools) and UI packages
	test -x $(VPY) || $(PYTHON) -m venv .venv
	$(VPY) -m pip install -r backend/requirements-dev.txt
	test -f .env || cp .env.example .env
	if command -v npm >/dev/null 2>&1; then cd frontend && npm install --no-audit --no-fund; fi

build:           ## build the UI into frontend/dist
	cd frontend && npm run build

seed:            ## seed the demo database if it is empty (safe; never deletes data)
	cd backend && $(VPY) -m app.seed

reset-db:        ## DELETE all data and regenerate the synthetic dataset (asks for confirmation)
	cd backend && $(VPY) -m app.seed --reset

test:            ## backend unit + API integration tests
	cd backend && $(VPY) -m pytest

e2e:             ## end-to-end browser tests (needs the built UI and: python -m playwright install chromium)
	$(VPY) -m pytest e2e -q -p no:cacheprovider --rootdir=e2e

check-views:     ## every view: phone-width overflow, page errors, external requests (server must be running)
	$(VPY) e2e/check_views.py http://127.0.0.1:$(PORT)

lint:            ## Python lint (ruff) + strict TypeScript checks
	$(VPY) -m ruff check backend/app backend/tests scripts e2e
	cd frontend && npm run lint

typecheck:       ## TypeScript type check of the UI
	cd frontend && npm run typecheck

types:           ## regenerate frontend/src/api/types.gen.ts from the OpenAPI document
	cd backend && $(VPY) -m app.tools.gen_ts

samples:         ## regenerate the sample import files in backend/data/samples
	cd backend && $(VPY) -m app.tools.make_samples

models:          ## retrain the local models (classifier, matcher, SLA breach model)
	cd backend && $(VPY) -m app.tools.train_models

check: lint test build e2e   ## everything that CI would run

clean-models:    ## delete trained models (they are retrained on next start)
	rm -rf backend/var/models
