# Paid Once: refunds over Nexus

A runnable test of one migration claim: moving an agent's refund-approval process onto Temporal, with
[Nexus](https://docs.temporal.io/nexus) to the payments team, keeps every approved refund **exactly once** and
**loses no ticket** under worker crashes, redelivery and a payments service that commits and then goes quiet. The agent
logic and the payments service do not change.

Two copies of the same refund agent run the same tickets under the same chaos:

- **Lane 1** ("Queue + LangGraph" on screen) is the stack a competent team ships today: a job queue with a visibility
  timeout, a LangGraph agent with the default in-memory checkpointer, and an HTTPS call to payments.
- **Lane 2** ("Temporal + Nexus" on screen) is the same agent logic on Temporal, with the refund exposed to the payments
  team as a Nexus operation across two namespaces.

A fault injector kills things. An independent audit then scores both lanes **from the payments ledger**, never from a
lane's own records.

An agent proposes a refund, a human approves it, and payments moves the money. That is the whole process. The
design is in [`docs/architecture.md`](docs/architecture.md), the measured results in
[`docs/scenario-results.md`](docs/scenario-results.md), and how to change the code in
[`docs/development.md`](docs/development.md).

## Quick start

You need [uv](https://docs.astral.sh/uv/) and the [Temporal CLI](https://docs.temporal.io/cli). The demo UI also
needs Node 22 or newer.

```bash
brew install temporal uv     # macOS; on Linux install both from their docs
make install                 # Python 3.12 environment from uv.lock
make test                    # fast suite, no Temporal server needed
make scenario                # the headless run: no API key, about four minutes
```

`make scenario` starts every service (and a Temporal dev server, if none is listening), runs the walkthrough, the happy
path, three chaos scenes and the Nexus gauntlet against both lanes with a **stub model**, prints a ledger scoreboard for each, and
exits non-zero if Lane 2 breaks an invariant. The invariants are decided by the ledger, not by the model's wording, so
the stub does not change the result.

## Run the live demo

The demo uses a real Anthropic model (`claude-sonnet-5-5`; `PAIDONCE_MODEL` changes it).

```bash
echo 'ANTHROPIC_API_KEY=...' > .env     # gitignored; or export it in your shell
make ui                                 # builds the UI into ui/dist
make demo                               # http://127.0.0.1:8100
```

The page is a seven-step stepper for a laptop browser in full screen. Arrow keys or `1`-`7` move between steps, and the
step is kept in the URL (`#5`). The scoreboard resets whenever the show server starts.

| Step | What it shows |
|---|---|
| 1 Architectures | The two stacks side by side, and a one-ticket walkthrough of the flow |
| 2 Happy path | Seven tickets per lane, no faults. Both lanes refund the five approved once |
| 3 Crash | The agent workers are killed with refunds in flight and approvals waiting for a human |
| 4 Redelivery | The queue delivers the same message twice |
| 5 Payments quiet | Payments commits a refund, then the reply never arrives |
| 6 Scoreboard | Totals since the reset for steps 2-5, from the ledger |
| 7 Nexus | What Nexus is, then a gauntlet of four failures on the same in-flight refunds (Lane 2 only) |

Steps 2-5 run the same chaos against both lanes; the scoreboards diverge. The payments node in the diagram marks each
ticket in the ledger: `✓` paid once, `×2` paid twice, `∅` owed and never paid, `—` denied and nothing owed.

The Temporal wordmark and favicon are trademarks, so they are not in the repo. Put `temporal-wordmark.svg` and
`favicon.svg` in `ui/public/brand/` (gitignored) before `make ui` to show them; otherwise the header shows text.

## Make targets

| Target | What it does |
|---|---|
| `make install` | Create the Python environment from `uv.lock` |
| `make test` | The fast suite: payments, ledger, audit, agent policy, Lane 1, the show server (stub model) |
| `make test-temporal` | Lane 2 and Nexus integration tests on their own throwaway Temporal server (port 7299) |
| `make setup` | Create the two namespaces and the Nexus endpoint on the server at `TEMPORAL_ADDRESS` (safe to repeat) |
| `make scenario` | The headless run described above. Needs port 8100 free |
| `make ui` | Build the UI into `ui/dist`; the show server serves it |
| `make demo` | Start everything and serve the show on :8100 |
| `make lint` / `make fmt` | `ruff check` and `ruff format --check` / apply the formatter |

## Configuration

Everything has a default; set a variable in your shell or in a gitignored `.env`.

| Variable | Default | Meaning |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | The live demo needs it. `make scenario` and `make test` do not |
| `PAIDONCE_MODEL` | `claude-sonnet-5-5` | The model the agent calls |
| `PAIDONCE_STUB_LLM` | unset | `1` replaces the model with a deterministic stub |
| `TEMPORAL_ADDRESS` | `127.0.0.1:7233` | The Temporal frontend. If nothing listens there the show starts a dev server |
| `PAIDONCE_SUPPORT_NS`, `PAIDONCE_PAYMENTS_NS` | `support`, `payments` | The two namespaces |
| `PAIDONCE_SHOW_PORT`, `PAIDONCE_PAYMENTS_PORT`, `PAIDONCE_LANE1_PORT` | 8100, 8101, 8102 | Where the services listen |
| `PAIDONCE_DATA` | `./data` | SQLite files, TLS certificates and the dev server's database |
| `PAIDONCE_PAYMENTS_TLS`, `PAIDONCE_LANE1_TLS` | `1` | `0` serves that service over plain HTTP (the tests do) |
| `PAIDONCE_VISIBILITY_S` | `10` | Lane 1's queue visibility timeout |
| `PAIDONCE_PAYMENTS_TIMEOUT_S` | `3` | Lane 1's client timeout against payments |
| `PAIDONCE_L1_STABLE_KEY` | unset | `1` makes Lane 1 derive its idempotency key from the ticket. Off by default; see below |
| `PAIDONCE_TEST_TEMPORAL_PORT` | `7299` | The throwaway server `make test-temporal` starts |

`PAIDONCE_L1_STABLE_KEY=1 make scenario` measures the one-line fix to Lane 1: duplicates drop to zero and the lost
tickets remain (see [`docs/scenario-results.md`](docs/scenario-results.md)).

## Scope

In scope: one process (refund approval, from "a ticket asks for a refund" to "the money moved once"), the agent's two
policy rules (at most $200, order at most 30 days old), a human approve or deny, and three ledger invariants: every
approved ticket refunded exactly once, no refund without an approval, no ticket lost or stuck. Everything runs on one
machine: local processes, SQLite and one Temporal dev server.

Out of scope, so do not read the results as claims about them: scale, load and cost; Temporal Cloud features (the Nexus
caller allowlist, the account-wide registry); Nexus cancellation and retargeting an endpoint while operations are in
flight; workflow versioning; approval waits longer than seconds; and the quality of the agent's decisions.

## Troubleshooting

- **Port 8100 is busy.** Another `make demo` or `make scenario` is running. The show server refuses to start a second
  instance. Stop the first one.
- **A Temporal server is already running on `TEMPORAL_ADDRESS`.** The show reuses it and creates its two namespaces and
  the Nexus endpoint there. It cannot kill a server it did not start, so the Nexus scene skips that failure. To keep
  the demo separate, run `temporal server start-dev --port 7299` and `TEMPORAL_ADDRESS=127.0.0.1:7299 make demo`, or
  free the port and let the show start its own.
- **Odd database errors after pulling a newer version.** Delete the old databases once: `rm data/*.db`.
- **A browser left open on :8100 during `make scenario`** shows a "not the demo" banner; its Run and Reset buttons are
  locked to the test runner.
- **Lane 1's counts differ from `docs/scenario-results.md`.** They vary a little run to run because kills land at
  wall-clock times. Lane 2's result (zero violations) does not.

## Layout

| Path | What it is |
|---|---|
| `paidonce/payments/` | The payments service and its SQLite ledger, with fault injection (commit-then-stall, latency) |
| `paidonce/lane1/` | Lane 1: API, threaded worker, jobs table with a visibility timeout, LangGraph graph |
| `paidonce/lane2/` | Lane 2: the Nexus contract, the support and payments workflows, activities, workers, setup |
| `paidonce/agent.py` | The policy check and the model call, shared by both lanes |
| `paidonce/audit.py` | The three invariants, computed from the ledger |
| `paidonce/show/` | The process manager, the scenes and the fault injector, and the server that streams state to the UI |
| `paidonce/db.py`, `models.py`, `config.py`, `tls.py` | SQLite helpers, shared types, settings, self-signed certificates |
| `scripts/` | `smoke.py` (the headless runner behind `make scenario`) and `test-temporal.sh` |
| `tests/` | The pytest suites. `-m temporal` tests need `make test-temporal` |
| `ui/` | The Vite + React + TypeScript demo UI |
| `docs/` | `architecture.md`, `development.md`, `scenario-results.md` |

## License

MIT. See [`LICENSE`](LICENSE).
