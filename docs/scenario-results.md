# Scenario results

What `make scenario` printed on the runs behind the case study. Everything here is scored from the payments ledger
(`raccoon/audit.py`), never from a lane's own state.

- **Date:** 2026-10-30
- **Code:** the two default runs and the flagged run used commit `c57210e` (the flagged run adds the off-by-default
  `RACCOON_L1_STABLE_KEY` switch, then uncommitted). A third default run from a fresh clone at `a5f62d6`, the commit that
  contains the switch, is below.
- **Command:** `make scenario` (stub model, no API key, local Temporal dev server, about 4 minutes)
- **Machine:** one laptop, all services as local processes

## What is and is not reproducible

- **Reproducible:** Lane 2 finishes every scene with every approved ticket refunded exactly once: 0 duplicate,
  0 missing, 0 stuck, 0 unapproved. `make scenario` exits non-zero if that stops being true.
- **Not exactly reproducible:** Lane 1's counts. The seed fixes ticket amounts and messages, but the raccoon's
  kills land at wall-clock times, so Lane 1 duplicates vary run to run (see `double_delivery` below). What repeats is
  the pattern: duplicates in `tip_over`, `double_delivery` and `payments_timeout`, lost tickets in `tip_over` and
  `deploy_wait`.
- **Not covered here:** endpoint retargeting with operations in flight (the effect of a task-queue change is not
  documented and was not tested), workflow versioning, and approval waits longer than seconds.
- **Also not covered:** the live model. These runs use the stub agent. The invariants do not depend on the wording
  of the model's reply, but the live demo (`make demo`) is a separate check and is not in these tables.

## Two default runs

Per scene, Lane 1 only. Lane 2 was `ok = submitted`, 0 elsewhere, in every scene of both runs.

| Scene | Tickets | Run 1: duplicates / missing | Run 2: duplicates / missing |
|---|---|---|---|
| `intro` | 5 | 0 / 0 | 0 / 0 |
| `tip_over` | 6 | 4 / 2 | 4 / 2 |
| `double_delivery` | 5 | 1 / 0 | 3 / 0 |
| `deploy_wait` | 5 | 0 / 5 | 0 / 5 |
| `payments_timeout` | 5 | 4 / 0 | 4 / 0 |
| `nexus_kill` | 5 (Lane 2 only) | n/a | n/a |

Cumulative audit at the end of each run:

| | Submitted | Refunded once | Duplicates | Missing | Stuck | Unapproved |
|---|---|---|---|---|---|---|
| Lane 1, run 1 | 26 | 10 | 9 | 7 | 0 | 0 |
| Lane 1, run 2 | 26 | 8 | 11 | 7 | 0 | 0 |
| Lane 2, both runs | 31 | 31 | 0 | 0 | 0 | 0 |

(Lane 2 has 31 submitted because it also takes the five `nexus_kill` tickets, which Lane 1 does not run.)
"Duplicates" counts tickets paid more than once, not extra payments.

In `nexus_kill`, the payments-side activity attempt peaked at 2 in both runs while the caller's Nexus operation
stayed at attempt 1, `STARTED`. Retries inside the handler's workflow are not visible as retries on the caller. All
five refund workflows finished with `replayed: true` (the ledger returned the stored row for the retry).

## Fresh clone at `a5f62d6`

Cloned into an empty directory with no `.env` and no `ANTHROPIC_API_KEY`, then
`TEMPORAL_ADDRESS=127.0.0.1:7299 make install && make scenario`. The show started its own Temporal dev server on that
port (it created its own `data/temporal.db`), the run ended `SCENARIO PASSED`, and no process was left listening.

| | Submitted | Refunded once | Duplicates | Missing | Stuck | Unapproved |
|---|---|---|---|---|---|---|
| Lane 1 | 26 | 10 | 9 | 7 | 0 | 0 |
| Lane 2 | 31 | 31 | 0 | 0 | 0 | 0 |

Per scene, Lane 1: `tip_over` 4 duplicates / 2 missing, `double_delivery` 1 / 0, `deploy_wait` 0 / 5,
`payments_timeout` 4 / 0. Same pattern as the earlier runs.

## One run with Lane 1's key fixed

`RACCOON_L1_STABLE_KEY=1 make scenario` makes Lane 1 derive its idempotency key from the ticket
(`l1-{ticket_id}`) instead of from the attempt. Nothing else changes.

| | Submitted | Refunded once | Duplicates | Missing | Stuck | Unapproved |
|---|---|---|---|---|---|---|
| Lane 1, default (runs 1 and 2) | 26 | 10 / 8 | 9 / 11 | 7 | 0 | 0 |
| Lane 1, stable key | 26 | 19 | **0** | **7** | 0 | 0 |
| Lane 2 | 31 | 31 | 0 | 0 | 0 | 0 |

The one-line fix removes every duplicate. It does not touch the seven lost tickets: two in `tip_over` (approved tickets that had not reached
payments when the worker was killed, so their in-memory graph was gone) and five in `deploy_wait` (the in-memory
approval wait died with the process).
Those need a durable checkpointer plus a recovery sweeper, which is the case for moving the wait itself onto durable
execution. This is one run, so treat 0 duplicates as "the mechanism works", not as a rate.

## Why Lane 1 duplicates

The default Lane 1 sends a fresh `Idempotency-Key` per attempt (`l1-{ticket_id}-{uuid8}`). When payments commits and
then the response is lost, the retry arrives with a new key and the ledger correctly treats it as a new refund.
Lane 2 keys on the business operation (`refund-{ticket_id}`), so a retry gets the stored row back. Temporal's own
documentation says Nexus operations run at least once and handlers must be idempotent
(https://docs.temporal.io/nexus/operations), so the key must come from the business operation. The stable-key run
shows that fix works in Lane 1 too; Lane 2 was not run with a per-attempt key.
