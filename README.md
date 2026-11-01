# Paid Once: refunds over Nexus

A small, runnable test of one migration assumption: **moving an agent's refund-approval process onto Temporal,
with Nexus to the payments team, keeps every approved refund exactly-once and loses no ticket under worker
crashes and deploys (including during an approval wait), redelivery, and a payments commit-then-timeout, without changing the
agent logic or the payments service.**

Two copies of the same refund agent run the same tickets under the same chaos:

- **Lane 1** ("Queue + LangGraph" on screen) is the stack a competent team ships today: a job queue with a visibility timeout, a LangGraph agent
  with the default in-memory checkpointer, and an HTTPS call to payments.
- **Lane 2** ("Temporal + Nexus" on screen) is the same agent logic on Temporal, with the refund exposed to the payments team as a Nexus operation
  across two namespaces.

A fault injector kills things. An independent audit then scores both lanes **from the payments ledger**, never
from a lane's own records.

Architecture and diagrams: [`docs/architecture.md`](docs/architecture.md).
Measured results and how to read them: [`docs/scenario-results.md`](docs/scenario-results.md).

## Scope

In scope:
- One process: refund approval, from "a helpdesk ticket asks for a refund" to "the money moved once". The agent
  checks two policy rules in code (at most $200, order at most 30 days old) before it asks the model, and a human
  approves or denies what it proposes.
- Five chaos scenes: happy path, agent workers killed (a crash or a deploy, with refunds in flight and tickets waiting for a
  human), message delivered twice, payments commits then goes quiet, and a Nexus gauntlet (Lane 2 only): payments goes quiet, then the support worker,
  the payments worker and the Temporal server are killed, all while the refunds are in flight.
- Three ledger invariants: every approved ticket refunded exactly once; no refund without an approval; no ticket
  lost or stuck. Each scene includes one ticket outside the policy and one a human denies, so the second invariant is
  tested under the same chaos as the first.
- Everything on one machine: processes only, SQLite, one local Temporal dev server.

Out of scope, so do not read results as claims about them:
- Scale, load, latency and cost. Local processes model crash and retry semantics, not distributed-system scale.
- Temporal Cloud features (the Nexus caller allowlist, the account-wide registry) and self-hosted authorizers. The
  dev server shows none of them.
- Nexus cancellation, and retargeting an endpoint while operations are in flight. They are documented capabilities
  that this repository does not build. Setup only points an existing `payments-endpoint` at the current namespace.
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
`127.0.0.1:7233`), runs the walkthrough and the five scenes with a **stub model**, prints a ledger scoreboard for each, and exits
non-zero if Lane 2 shows any violation. It takes about four minutes. The invariants are decided by the ledger, not by
the model's wording, so the stub does not change the result.

Two things to know:
- If a Temporal server is already running on that address, the show **reuses it** and creates two namespaces
  (`support`, `payments`) and one Nexus endpoint (`payments-endpoint`) on it. To keep it separate, start
  your own on another port and point at it: `temporal server start-dev --port 7299` and
  `TEMPORAL_ADDRESS=127.0.0.1:7299 make scenario`. A reused server is not killed, so the Nexus scene then runs three
  failures instead of four; point `TEMPORAL_ADDRESS` at a free port and the show starts (and kills) its own.
- It needs port 8100, so stop `make demo` first; it refuses to start if anything is listening there. While it runs,
  a browser on :8100 shows a "not the demo" banner, and Run and Reset are locked to the test runner.
- The seed fixes ticket amounts and messages, not the exact timing of the kills. The reproducible claim is the Lane 2
  outcome (zero violations). Lane 1's failure counts vary a little from run to run, most in `double_delivery`.

To measure the one-line fix to Lane 1 (derive its idempotency key from the ticket instead of from each attempt):

```bash
PAIDONCE_L1_STABLE_KEY=1 make scenario
```

Lane 1 is unchanged unless that variable is set.

Integration tests for Lane 2 and Nexus: `make test-temporal`. It starts a throwaway in-memory Temporal dev server on
port 7299 (`PAIDONCE_TEST_TEMPORAL_PORT` changes it), creates the namespaces and endpoint there, and stops it after,
so it is safe to run while `make demo` is up.

## Run the live demo

The demo uses a real Anthropic model (`claude-sonnet-5-5` by default; set `PAIDONCE_MODEL` to change it).

```bash
echo 'ANTHROPIC_API_KEY=...' > .env     # gitignored; or export it in your shell
make ui                                 # builds the Vite UI (needs Node 22+)
make demo                               # http://127.0.0.1:8100
```

The page opens with the two architectures. "Walk through one ticket" runs a single approved ticket
through both stacks and stops at five steps. Under the diagram, a support chat grows one line per step (the customer's request, the agent's proposal, the hand-off to a human, the approval, the refund) next to one plain sentence. This page outlines the flow; it does not compare the stacks yet. The scene does not move until you dismiss each step (button, Space or →). Then it steps through five scenes. An architecture diagram shows
where each fault lands and where each stack thinks each ticket is, above both lanes' ledger-based scoreboards; the
Nexus step shows the operations live. Arrow keys or 1-7 move between steps, R runs the current scene, and the step is kept in the URL (`#5`), so a refresh stays put. It
is built for a laptop browser in full screen. The scoreboard resets whenever the show server starts.

Run of show, about ten minutes:
- **Step 1, Two architectures**: the same refund flow built twice, and a one-ticket walkthrough of how each stack handles it.
- **Step 2, Happy path**: seven tickets per lane. The agent's policy check denies one, the human approves five and
  denies one; both lanes refund the five once and pay nothing on the two denied tickets, which go back to the
  helpdesk as grey dash badges.
- **Steps 3-5** (workers die, double delivery, payments goes quiet): the same chaos hits both
  lanes; watch the ledger-based scoreboards diverge. The payments node's slots mark each ticket in the ledger
  (`✓` paid once, `×2` paid twice, `∅` owed, never paid, `—` denied, nothing owed), and each lane shows what payments saw in the scene: calls, refunds booked, and
  calls answered from an existing key. On step 5 that line is the evidence: Temporal's retry is answered from the
  ledger, the queue's is booked again.
- **Step 6, Nexus**: four failures while the refunds are in flight. Payments books each refund and goes quiet, then
  the support worker, the payments worker and the Temporal server itself are killed, each for 5-6 seconds. A red row
  per failure shows when it was down and how many refunds it hit. Under them, each approved refund has two tracks:
  what support's code sees (one `STARTED` bar, no error) and what payments does (failed attempts, then one that
  succeeds). A `$` marks when the ledger booked the money; the attempt that finally succeeds is answered from the
  ledger, not paid again. Four beats light up as the story happens, and the tiles at the bottom read the result from
  the ledger. The `support sees ↗` and `payments does ↗` labels open each side's history in the Temporal Web UI
  (http://127.0.0.1:8233), including the caller's Nexus Links tab. The Temporal kill needs a server the show started
  itself (`make demo` does, if nothing is listening on 7233); with a server you started, the scene skips that kill.
- **Step 7, Scoreboard**: the totals, and the queue's own job table next to what the ledger says.

The Temporal wordmark and favicon are not in the repo. To show them, put `temporal-wordmark.svg` and `favicon.svg` in
`ui/public/brand/` (gitignored) before `make ui`; otherwise the header shows text.

## Layout

| Path | What it is |
|---|---|
| `paidonce/payments/` | The payments service and its SQLite ledger, with fault injection (commit-then-stall, latency) |
| `paidonce/lane1/` | Lane 1: API, threaded worker, jobs table with a visibility timeout, LangGraph graph |
| `paidonce/lane2/` | Lane 2: the Nexus contract, the support and payments workflows, activities, workers, setup |
| `paidonce/audit.py` | The three invariants, computed from the ledger |
| `paidonce/show/` | The process manager, the scenes and the fault injector, the server that streams state to the UI |
| `scripts/smoke.py` | The headless scene runner behind `make scenario` |
| `ui/` | The Vite + React + TypeScript demo UI |

## License

MIT. See [`LICENSE`](LICENSE).
