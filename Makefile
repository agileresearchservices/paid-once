.PHONY: install test test-temporal setup scenario ui demo lint

install:
	uv sync

test:            ## fast suite: payments, audit, Lane 1 (stub model, no Temporal server needed)
	PAIDONCE_STUB_LLM=1 uv run pytest -q

test-temporal:   ## Lane 2 + Nexus integration tests on their own throwaway Temporal server (needs the temporal CLI)
	scripts/test-temporal.sh

setup:           ## create the two namespaces and the Nexus endpoint (safe to repeat)
	uv run python -m paidonce.lane2.client

scenario:        ## reproducible migration test: six chaos scenes, exit 1 on any Lane 2 ledger violation (stub model, no API key)
	PAIDONCE_STUB_LLM=1 uv run python scripts/smoke.py --check

ui:              ## build the Vite UI into ui/dist (needs Node 22+); the show server serves it
	cd ui && npm ci && npm run build

demo:            ## start everything and serve the show on http://127.0.0.1:8100 (needs ANTHROPIC_API_KEY)
	uv run python -m paidonce.show

lint:
	uv run ruff check . && uv run ruff format --check .
