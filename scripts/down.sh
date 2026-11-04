#!/usr/bin/env bash
# Stop what `make demo` or `make scenario` started from this checkout, including services left behind by a show server
# that died without cleaning up (they run in their own sessions, so they outlive it and keep their ports).
#
# Processes are matched by full command line, so another checkout's demo keeps running. So does a Temporal server this
# demo did not start: one the show started is the only one using this checkout's database file. See ensure_temporal().
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
PY="$ROOT/.venv/bin/python"

if [ ! -x "$PY" ]; then
  echo "Nothing to stop: this checkout has no .venv, so it cannot be running."
  exit 0
fi

escape() { printf '%s' "$1" | sed 's/[][\.*^$()+?{}|]/\\&/g'; }

# Ask config for the path, so PAIDONCE_DATA means the same here as it does to the show, whether set in the shell or .env.
DB="$(cd "$ROOT" && "$PY" -c 'from paidonce import config; print(config.DATA_DIR / "temporal.db")')"

PY_RE="^$(escape "$PY")[0-9.]*"
SHOW="$PY_RE (-m paidonce\.show|scripts/smoke\.py)( |$)"
ALL="$PY_RE (-m paidonce\.[a-z0-9_.]+|scripts/smoke\.py)( |$)|^(/.*/)?temporal server start-dev .*--db-filename $(escape "$DB")( |$)"

# True once nothing matches $1, false if something still does after $2 seconds.
gone_within() {
  for _ in $(seq 1 $(($2 * 4))); do
    pgrep -f "$1" >/dev/null || return 0
    sleep 0.25
  done
  return 1
}

# SIGTERM, then SIGKILL whatever has not exited after $2 seconds.
stop() {
  pkill -TERM -f "$1" || return 0
  gone_within "$1" "$2" || pkill -KILL -f "$1" || true
}

if ! pgrep -f "$ALL" >/dev/null; then
  echo "Nothing from this checkout is running."
else
  # The show goes first: while it lives, its watcher restarts any service that exits.
  if pgrep -f "$SHOW" >/dev/null; then
    stop "$SHOW" 10
    gone_within "$ALL" 10 || true # it passed SIGTERM to its services: let them finish before signalling them again
  fi
  stop "$ALL" 10

  if ! gone_within "$ALL" 3; then
    echo "Could not stop:" >&2
    pgrep -fl "$ALL" >&2 || true
    exit 1
  fi
  echo "Stopped the demo."
fi

# Not ours to stop, but it can hold port 7233 and the next `make demo` would reuse it, so say that it is still up.
OTHERS="$(pgrep -fl '^(/.*/)?temporal server start-dev' || true)"
if [ -n "$OTHERS" ]; then
  echo "Left running, because this demo did not start it:"
  echo "$OTHERS"
fi
