# refund-raccoon

Two copies of the same refund agent, one chaos monkey. Lane 1 is a typical queue-and-LangGraph stack. Lane 2 is
the same agent on Temporal, with the refund exposed to the payments team over Nexus. A raccoon kills things;
an independent ledger audit scores both.

Status and next steps: `docs/HANDOFF.md`. Agent instructions: `CLAUDE.md`.

## Run it
```bash
brew install temporal uv         # once
make install
export ANTHROPIC_API_KEY=...     # the demo calls a real model
make demo                        # starts Temporal, the services and the show on http://127.0.0.1:8100
```
Tests: `make test` (no server needed), then `temporal server start-dev`, `make setup`, `make test-temporal`.
