.PHONY: install test test-temporal setup demo lint

install:
	uv sync

test:            ## fast suite: payments, audit, Lane 1 (stub model, no Temporal server needed)
	RACCOON_STUB_LLM=1 uv run pytest -q

test-temporal:   ## Lane 2 + Nexus integration tests (needs: temporal server start-dev, then `make setup`)
	RACCOON_STUB_LLM=1 uv run pytest -q -m temporal

setup:           ## create the two namespaces and the Nexus endpoint (safe to repeat)
	uv run python -m raccoon.lane2.client

demo:            ## start everything and serve the show on http://127.0.0.1:8100 (needs ANTHROPIC_API_KEY)
	uv run python -m raccoon.show

lint:
	uv run ruff check . && uv run ruff format --check .
