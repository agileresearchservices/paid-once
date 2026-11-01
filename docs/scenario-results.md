# Scenario results

What `make scenario` prints, and how to read it. Everything here is scored from the payments ledger
(`paidonce/audit.py`), never from a lane's own state.

- **Run:** 2026-11-01, `main` at `2dc1a02` (the docs change that follows it alters no behaviour)
- **Command:** `make scenario`, then `PAIDONCE_L1_STABLE_KEY=1 make scenario`. Stub model, no API key, a Temporal dev
  server the show started itself, about four minutes each, on one laptop. Both ended `SCENARIO PASSED`.

## Per scene

Lane 1 duplicates / missing, then the same with its idempotency key derived from the ticket. In every scene Lane 2
refunded each approved ticket exactly once (0 duplicates, 0 missing), and both lanes closed the two tickets owed nothing
(one outside the policy, one a human denied) with no refund.

| Scene | Tickets (approved) | Lane 1, default | Lane 1, `PAIDONCE_L1_STABLE_KEY=1` |
|---|---|---|---|
| `intro` (happy path) | 7 (5) | 0 / 0 | 0 / 0 |
| `worker_crash` | 8 (6) | 3 / 3 | 0 / 3 |
| `double_delivery` | 7 (5) | 3 / 0 | 0 / 0 |
| `payments_timeout` | 7 (5) | 4 / 0 | 0 / 0 |
| `walkthrough` | 1 (1) | 0 / 0 | 0 / 0 |
| `nexus_kill` (Lane 2 only) | 7 (5) | n/a | n/a |

## Cumulative audit

| | Submitted | Refunded once | Duplicates | Missing | Stuck | Unapproved | Denied, none paid (policy / human) |
|---|---|---|---|---|---|---|---|
| Lane 1, default | 30 | 9 | 10 | 3 | 0 | 0 | 4 / 4 |
| Lane 1, stable key | 30 | 19 | 0 | 3 | 0 | 0 | 4 / 4 |
| Lane 2 | 37 | 27 | 0 | 0 | 0 | 0 | 5 / 5 |

Lane 2 has more tickets because it also takes the Nexus scene's seven. "Duplicates" counts tickets paid more than once,
not extra payments. The show's scoreboard on screen leaves out the walkthrough and the Nexus scene, so a fresh run there
reads 29 submitted and 21 approved per lane, with Lane 2 refunding 21 of 21 once.

In `nexus_kill`, four failures hit the same five in-flight refunds (payments goes quiet after booking, then the support
worker, the payments worker and the Temporal server are killed). Every failure hit all five refunds and its window
closed. The payments-side activity peaked at attempt 3 while the caller's Nexus operation stayed at attempt 1,
`STARTED`: retries inside the handler's workflow are invisible to the caller.

## What is and is not reproducible

- **Reproducible:** Lane 2 finishes every scene with every approved ticket refunded exactly once, and nothing lost,
  stuck or unapproved. `make scenario` exits non-zero if that stops being true.
- **Not exactly reproducible:** Lane 1's counts. The seed fixes ticket amounts and messages, but kills land at
  wall-clock times, so duplicates vary by one or two between runs (9 or 10 refunded once, 9 to 11 duplicated, in earlier
  runs). The pattern repeats: duplicates in `worker_crash`, `double_delivery` and `payments_timeout`, and 3 lost
  tickets in `worker_crash`.
- **Not covered:** retargeting a Nexus endpoint with operations in flight, workflow versioning, approval waits longer
  than seconds, and the live model. These runs use the stub agent; the invariants do not depend on the wording of the
  model's reply, and `make demo` is the separate check of the live model.

## Why Lane 1 duplicates, and what the one-line fix does not fix

The default Lane 1 sends a fresh `Idempotency-Key` per attempt (`l1-{ticket_id}-{uuid8}`). When payments commits and the
response is lost, the retry arrives with a new key, and the ledger correctly treats it as a new refund. Lane 2 keys on
the business operation (`refund-{ticket_id}`), so a retry gets the stored row back. Temporal's documentation says Nexus
operations run at least once and handlers must be idempotent (https://docs.temporal.io/nexus/operations), so the key has
to come from the business operation.

With the key derived from the ticket, Lane 1's duplicates go to zero. Its 3 lost tickets remain: in `worker_crash` they
are approvals still waiting for a human, whose in-memory graph died with the worker. Fixing those needs a durable
checkpointer and a recovery sweeper, which is the case for moving the wait itself onto durable execution. These are
single runs, so read zero duplicates as "the mechanism works", not as a rate.
