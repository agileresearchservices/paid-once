# refund-raccoon

A small, runnable test of one migration assumption: **moving an agent's refund-approval process onto Temporal,
with Nexus to the payments team, keeps every approved refund exactly-once and loses no ticket under worker
crashes, redelivery, deploys during an approval wait, and a payments commit-then-timeout, without changing the
agent logic or the payments service.**

Two copies of the same refund agent run the same tickets under the same chaos:

- **Lane 1** is the stack a competent team ships today: a job queue with a visibility timeout, a LangGraph agent
  with the default in-memory checkpointer, and a plain HTTP call to payments.
- **Lane 2** is the same agent logic on Temporal, with the refund exposed to the payments team as a Nexus operation
  across two namespaces.

A "refund raccoon" kills things. An independent audit then scores both lanes **from the payments ledger**, never
from a lane's own records.

Architecture and diagrams: [`docs/architecture.md`](docs/architecture.md).
Measured results and how to read them: [`docs/scenario-results.md`](docs/scenario-results.md).

## Scope

In scope:
- One process: refund approval, from "the agent proposes a refund" to "the money moved once".
- Six chaos scenes: happy path, agent process killed, message delivered twice, deploy during the approval wait,
  payments commits then goes quiet, payments worker killed mid-Nexus-operation (Lane 2 only).
- Three ledger invariants: every approved ticket refunded exactly once; no refund without an approval; no ticket
  lost or stuck.
- Everything on one machine: processes only, SQLite, one local Temporal dev server.

Out of scope, so do not read results as claims about them:
- Scale, load, latency and cost. Local processes model crash and retry semantics, not distributed-system scale.
- Temporal Cloud features (the Nexus caller allowlist, the account-wide registry) and self-hosted authorizers. The
  dev server shows none of them.
- Nexus cancellation and endpoint retargeting. They are documented capabilities that this repository does not build.
- The quality of the agent's decisions, and live routing of a real ticket stream between the lanes.
- A third, hardened Lane 1. What hardening would fix is argued in the write-up and measured for one change only
  (see "Reproduce" below).

## Setup (macOS or Linux)

You need the [Temporal CLI](https://docs.temporal.io/cli) and [uv](https://docs.astral.sh/uv/):

```bash
brew install temporal uv        # macOS; on Linux install both from their docs
make install                    # Python 3.12 environment from uv.lock
make test                       # fast suite, no Temporal server needed
```

## Reproduce the scenario (no API key needed)

```bash
make scenario
```

This starts everything (including a Temporal dev server if none is listening on `TEMPORAL_ADDRESS`, default
`127.0.0.1:7233`), runs the six scenes with a **stub model**, prints a ledger scoreboard for each, and exits
non-zero if Lane 2 shows any violation. It takes about four minutes. The invariants are decided by the ledger, not by
the model's wording, so the stub does not change the result.

Two things to know:
- If a Temporal server is already running on that address, the show **reuses it** and creates two namespaces
  (`raccoon-support`, `raccoon-payments`) and one Nexus endpoint (`payments-endpoint`) on it. To keep it separate, start
  your own on another port and point at it: `temporal server start-dev --port 7299` and
  `TEMPORAL_ADDRESS=127.0.0.1:7299 make scenario`.
- The seed fixes ticket amounts and messages, not the exact timing of the kills. The reproducible claim is the Lane 2
  outcome (zero violations). Lane 1's failure counts vary a little from run to run, most in `double_delivery`.

To measure the one-line fix to Lane 1 (derive its idempotency key from the ticket instead of from each attempt):

```bash
RACCOON_L1_STABLE_KEY=1 make scenario
```

Lane 1 is unchanged unless that variable is set.

Integration tests for Lane 2 and Nexus: `make test-temporal`. It starts a throwaway in-memory Temporal dev server on
port 7299 (`RACCOON_TEST_TEMPORAL_PORT` changes it), creates the namespaces and endpoint there, and stops it after,
so it is safe to run while `make demo` is up.

## Run the live demo

The demo uses a real Anthropic model (`claude-sonnet-5-5` by default; set `RACCOON_MODEL` to change it).

```bash
echo 'ANTHROPIC_API_KEY=...' > .env     # gitignored; or export it in your shell
make ui                                 # builds the Vite UI (needs Node 22+)
make demo                               # http://127.0.0.1:8100
```

The page steps through seven scenes and shows both lanes' scoreboards plus the Nexus operations live. Arrow keys or
1-7 move between steps, R runs the current scene, and the step is kept in the URL (`#6`), so a refresh stays put. It
is built for a laptop browser in full screen. The scoreboard resets whenever the show server starts.

Run of show, about ten minutes:
- **Step 1, Meet the system**: both lanes refund five tickets cleanly.
- **Steps 2-5** (agent tipped over, double delivery, deploy mid-wait, payments goes quiet): the same chaos hits both
  lanes; watch the ledger-based scoreboards diverge.
- **Step 6, Nexus**: the raccoon kills the payments team's worker mid-refund. Support's side stays `STARTED` with no
  failure while payments retries. Click a row's `history ↗` links to show both sides in the Temporal Web UI
  (http://127.0.0.1:8233), including the caller's Nexus Links tab.
- **Step 7, Scoreboard**: the totals.

The Temporal wordmark and favicon are not in the repo. To show them, put `temporal-wordmark.svg` and `favicon.svg` in
`ui/public/brand/` (gitignored) before `make ui`; otherwise the header shows text.

## Layout

| Path | What it is |
|---|---|
| `raccoon/payments/` | The payments service and its SQLite ledger, with fault injection (commit-then-stall, latency) |
| `raccoon/lane1/` | Lane 1: API, threaded worker, jobs table with a visibility timeout, LangGraph graph |
| `raccoon/lane2/` | Lane 2: the Nexus contract, the support and payments workflows, activities, workers, setup |
| `raccoon/audit.py` | The three invariants, computed from the ledger |
| `raccoon/show/` | The process manager, the scenes and the raccoon, the server that streams state to the UI |
| `scripts/smoke.py` | The headless scene runner behind `make scenario` |
| `ui/` | The Vite + React + TypeScript demo UI |

## License

MIT. See [`LICENSE`](LICENSE).
