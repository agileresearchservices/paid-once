.DEFAULT_GOAL := help
.PHONY: help install test test-temporal setup scenario ui demo lint fmt

help:            ## list the targets
	@awk -F':.*## ' '/^[a-z-]+:.*## /{printf "  %-14s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install:         ## create the Python environment from uv.lock
	uv sync

test:            ## fast suite: payments, ledger, audit, agent policy, Lane 1, show server (stub model, no Temporal server)
	PAIDONCE_STUB_LLM=1 uv run pytest -q

test-temporal:   ## Lane 2 + Nexus integration tests on their own throwaway Temporal server (needs the temporal CLI)
	scripts/test-temporal.sh

setup:           ## create the two namespaces and the Nexus endpoint (safe to repeat)
	uv run python -m paidonce.lane2.client

scenario:        ## headless run: the walkthrough, happy path, three chaos scenes and Nexus; exit 1 on a Lane 2 violation (stub model)
	PAIDONCE_STUB_LLM=1 uv run python scripts/smoke.py --check

ui:              ## build the Vite UI into ui/dist (needs Node 22+); the show server serves it
	cd ui && npm ci && npm run build

demo:            ## start everything and serve the show on http://127.0.0.1:8100 (needs ANTHROPIC_API_KEY)
	uv run python -m paidonce.show

lint:            ## ruff check and format check
	uv run ruff check . && uv run ruff format --check .

fmt:             ## apply ruff's fixes and formatting
	uv run ruff check . --fix && uv run ruff format .
