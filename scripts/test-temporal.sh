#!/usr/bin/env bash
# Run the Lane 2 + Nexus integration tests against a throwaway, in-memory Temporal dev server.
# The tests start workers on the same task queues as the show; on a shared server the show's workers would pick up
# the tests' workflows and the tests would see no refund. Their own server keeps them isolated from `make demo`.
set -euo pipefail

PORT="${RACCOON_TEST_TEMPORAL_PORT:-7299}"
ADDRESS="127.0.0.1:${PORT}"

command -v temporal >/dev/null || { echo "temporal CLI not found: install it (see README Setup)" >&2; exit 1; }
if temporal operator cluster health --address "$ADDRESS" >/dev/null 2>&1; then
  echo "something is already serving Temporal on $ADDRESS; set RACCOON_TEST_TEMPORAL_PORT to a free port" >&2
  exit 1
fi

temporal server start-dev --headless --port "$PORT" --log-level error >/dev/null 2>&1 &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null; wait "$SERVER" 2>/dev/null || true' EXIT

for _ in $(seq 1 60); do
  temporal operator cluster health --address "$ADDRESS" >/dev/null 2>&1 && break
  kill -0 "$SERVER" 2>/dev/null || { echo "temporal dev server on $ADDRESS exited during startup" >&2; exit 1; }
  sleep 0.5
done
temporal operator cluster health --address "$ADDRESS" >/dev/null 2>&1 || { echo "temporal dev server on $ADDRESS never became healthy" >&2; exit 1; }

export TEMPORAL_ADDRESS="$ADDRESS"
uv run python -m raccoon.lane2.client
RACCOON_STUB_LLM=1 uv run pytest -q -m temporal "$@"
