# Scenario results

What `make scenario` printed on the runs behind the case study. Everything here is scored from the payments ledger
(`paidonce/audit.py`), never from a lane's own state.

- **Date:** 2026-10-30
- **Code:** the two default runs and the flagged run used commit `c57210e` (the flagged run adds the off-by-default
  `PAIDONCE_L1_STABLE_KEY` switch, then uncommitted). Two more default runs from fresh clones are below: `a5f62d6` (the commit that
  contains the switch) and `main` at `9d77b11`.
- **Command:** `make scenario` (stub model, no API key, local Temporal dev server, about 4 minutes)
- **Machine:** one laptop, all services as local processes

## Latest: crash and deploy merged into one scene (2026-11-01, `main` at `8d59f79` plus the merge)

`tip_over` and `deploy_wait` killed the same two agent workers and differed only in when. They are now one scene,
`worker_crash`: payments stalls the first 3 approved refunds after booking, the human approves those 3, the workers are
killed 1.6 s later (3 refunds in flight, 3 approvals plus the human "no" still waiting for a human), and the human
reviews the rest after the restart. The tables below name the two old scenes; read them as that scene's two halves.
Two full `make scenario` runs on side ports (default, then `PAIDONCE_L1_STABLE_KEY=1`), both `SCENARIO PASSED`.

Per scene, Lane 1 duplicates / missing. Lane 2 was `ok = approved`, 0 elsewhere, and both lanes closed the two "no"
tickets unpaid, in every scene.

| Scene | Tickets (approved) | Default | `PAIDONCE_L1_STABLE_KEY=1` |
|---|---|---|---|
| `intro` | 7 (5) | 0 / 0 | 0 / 0 |
| `worker_crash` | 8 (6) | 3 / 3 | 0 / 3 |
| `double_delivery` | 7 (5) | 2 / 0 | 0 / 0 |
| `payments_timeout` | 7 (5) | 4 / 0 | 0 / 0 |
| `nexus_kill` | 7 (5), Lane 2 only | n/a | n/a |

| | Submitted | Refunded once | Duplicates | Missing | Stuck | Unapproved | Denied, none paid (policy / human) |
|---|---|---|---|---|---|---|---|
| Lane 1, default | 30 | 10 | 9 | 3 | 0 | 0 | 4 / 4 |
| Lane 1, stable key | 30 | 19 | 0 | 3 | 0 | 0 | 4 / 4 |
| Lane 2, both runs | 37 | 27 | 0 | 0 | 0 | 0 | 5 / 5 |

In `worker_crash` Lane 1 paid the 3 in-flight refunds twice (a new key per attempt) and lost the 3 waiting approvals
(their in-memory graph died with the worker); the stable key removes the duplicates and leaves the 3 lost, as before.
Lane 2 replayed with the same key and refunded all 6 once. In `nexus_kill` the payments-side activity attempt peaked at
3 and the caller's operation at 1; every failure hit all 5 refunds.

## Note: the walkthrough and the Nexus scene no longer count toward the scoreboard

The tables above include the one-ticket walkthrough from step 1 (a Lane 1 and Lane 2 ticket in every scored run), and
Lane 2's include the Nexus scene. The show server's scoreboard now leaves both out (`DEMO_SCENES` in
`paidonce/show/engine.py`) and scores them on their own as `demo_audit`; `make scenario` adds them back and checks them.
A fresh run on screen therefore reads Lane 1 29 submitted and 21 approved, and Lane 2 29 submitted and 21 approved
(Lane 1 loses the walkthrough ticket, Lane 2 loses it and the Nexus scene's seven). The recorded runs were not repeated.

## Before the merge: every scene with two tickets owed nothing (2026-10-31, `c085fb9`)

Each scene's cohort now adds one ticket outside the agent's policy and one a human denies (7 tickets per scene, 8 in
`tip_over`). Both runs used side ports and their own data directory and Temporal server
(`PAIDONCE_SHOW_PORT=8200 PAIDONCE_PAYMENTS_PORT=8201 PAIDONCE_LANE1_PORT=8202 PAIDONCE_DATA=… TEMPORAL_ADDRESS=127.0.0.1:7399`),
so they ran beside the demo. Both ended `SCENARIO PASSED`.

Per scene, Lane 1 duplicates / missing (default run, then stable key). In every scene both lanes closed the two "no"
tickets with no refund, and Lane 2 was `ok = approved`, 0 elsewhere.

| Scene | Tickets (approved) | Default | `PAIDONCE_L1_STABLE_KEY=1` |
|---|---|---|---|
| `intro` | 7 (5) | 0 / 0 | 0 / 0 |
| `tip_over` | 8 (6) | 4 / 2 | 0 / 2 |
| `double_delivery` | 7 (5) | 2 / 0 | 0 / 0 |
| `deploy_wait` | 7 (5) | 0 / 5 | 0 / 5 |
| `payments_timeout` | 7 (5) | 4 / 0 | 0 / 0 |
| `nexus_kill` | 7 (5), Lane 2 only | n/a | n/a |

| | Submitted | Refunded once | Duplicates | Missing | Stuck | Unapproved | Denied, none paid (policy / human) |
|---|---|---|---|---|---|---|---|
| Lane 1, default | 36 | 9 | 10 | 7 | 0 | 0 | 5 / 5 |
| Lane 1, stable key | 36 | 19 | 0 | 7 | 0 | 0 | 5 / 5 |
| Lane 2, both runs | 43 | 31 | 0 | 0 | 0 | 0 | 6 / 6 |

Invariant 2 ("no refund without an approval") now has 10 to 12 tickets per lane per run that must not be paid,
under the same kills, redeliveries and stalls as the approved ones; neither lane paid one. In `nexus_kill` the
payments-side activity attempt again peaked at 2 while the caller's operation stayed at attempt 1. The earlier runs
below had approved tickets only.

## What is and is not reproducible

- **Reproducible:** Lane 2 finishes every scene with every approved ticket refunded exactly once: 0 duplicate,
  0 missing, 0 stuck, 0 unapproved. `make scenario` exits non-zero if that stops being true.
- **Not exactly reproducible:** Lane 1's counts. The seed fixes ticket amounts and messages, but the fault injector's
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
five refund workflows finished with `replayed: true` (the ledger returned the stored row for the retry). The
refund result no longer carries `replayed` (it was payments-internal); the show counts replays from the payments service.

`nexus_kill` is now a gauntlet (four failures on the same in-flight refunds: payments stalls after booking, then
the support worker, the payments worker and the Temporal server are killed). On a side-port run at `2603d71`, with
the show starting its own Temporal server: every failure hit all 5 refunds and its window closed; the payments-side
activity peaked at attempt 3, the caller's operation at attempt 1; 5 refunds each paid once, 0 violations. The
cumulative Lane 2 totals are unchanged (43 submitted, 31 refunded once, 0 duplicates, 6/6 denials).

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

## Fresh clone of `main` at `9d77b11`

After the work was merged, a clone of `main` from GitHub (no `.env`, no `ANTHROPIC_API_KEY`) ran
`TEMPORAL_ADDRESS=127.0.0.1:7299 make install && make scenario` on 2026-10-30. Same result: `SCENARIO PASSED`.

| | Submitted | Refunded once | Duplicates | Missing | Stuck | Unapproved |
|---|---|---|---|---|---|---|
| Lane 1 | 26 | 9 | 10 | 7 | 0 | 0 |
| Lane 2 | 31 | 31 | 0 | 0 | 0 | 0 |

## One run with Lane 1's key fixed

`PAIDONCE_L1_STABLE_KEY=1 make scenario` makes Lane 1 derive its idempotency key from the ticket
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
