# Development guide

How the pieces fit, how to change them safely, and the gotchas that are not obvious from the code. Setup and the
commands are in the [README](../README.md); the design is in [`architecture.md`](architecture.md).

## How the pieces fit

`make demo` runs `python -m paidonce.show`, one server that owns everything else:

```
browser (ui/dist) <-- SSE snapshots + POST /api/... -- show server (:8100, paidonce/show/server.py)
                                                          |  Engine: scenes, approver bot, fault injector
                                                          |  ProcessManager: starts and kills the children
                                       +------------------+-------------------+----------------------+
                                  payments (:8101)   Lane 1 API (:8102)   Lane 1 worker      Lane 2 workers x2
                                       |                    |                                  (+ Temporal dev server,
                                  ledger.db            lane1.db                                if the show starts it)
```

- **`ProcessManager`** (`show/procs.py`) is the stand-in for Kubernetes: it spawns each service as a child process,
  `kill -9`s one on request, and restarts anything dead after a short delay. If nothing listens on `TEMPORAL_ADDRESS`
  it also starts `temporal server start-dev` with a database file, so the Temporal server can be killed and come back
  with every workflow where it was. A server someone else started is reused and never killed.
- **`Engine`** (`show/engine.py`) holds the state of the show and runs one scene at a time. It is assembled from mixins,
  one per concern: `catalog.py` (scenes, constants, the ticket-ID convention), `harness.py` (submitting tickets and the
  approver bot that plays the human), `scenes.py` (the scenes and the fault primitives), `views.py` (reading each
  stack's state in the background) and `timeline.py` (pure functions that turn that state into what the page draws).
- **The audit** (`audit.py`) is the scoreboard. It reads the payments ledger plus two records the harness writes (what
  it planned for each ticket, and each human decision), never a lane's own state.
- **Ports and data:** `paidonce/config.py` holds every port, path and name. Databases and certificates live in `data/`.

## The snapshot contract

The UI is a pure function of one JSON object. The server streams `Engine.snapshot()` over SSE about every 0.7 s
(`/api/stream`) and the UI reads it through `useSnapshot.ts`. `ui/src/types.ts` (`Snapshot`) is the contract, and a test
(`tests/test_show_views.py`) fails if the engine's keys and `types.ts` drift apart. Add a field in three places: the
engine, `types.ts`, and the component that reads it.

Two rules keep the numbers honest. The scoreboard comes from `audit.compute_all`, which reads the ledger.
`lane1_view_all`, `lane2_view_all` and `payments_calls_all` are each stack's own claim, shown next to the ledger and
never scored. The walkthrough and the Nexus scene (`DEMO_SCENES`) are left out of the scoreboard and scored alone as
`demo_audit`; `make scenario` adds them back and checks them.

## Adding a scene

1. Add `SceneInfo("my_scene", "Title")` to `SCENES` in `show/catalog.py`.
2. Write `async def scene_my_scene(self)` in `show/scenes.py`. Use `submit_cohort` to send the same tickets to both
   lanes, `approve_scene` to play the human, and the fault primitives (`kill_window`, `set_fault`, `fault`) so the
   page can draw where each fault landed. The scene ends when its tickets settle (`Engine.settle`).
3. Add a `Step` to `STEPS` in `ui/src/steps.ts` (copy is read from a projector: short, concrete sentences).
4. `scripts/smoke.py` runs every scene in `SCENES` and `make scenario` checks it, so there is nothing to register there.

An unknown scene id answers 404; a scene already running answers 409.

## Tests

| Command | What it covers | Needs |
|---|---|---|
| `make test` | Payments service and ledger, the audit, the agent's policy rules, Lane 1, the show server's guards, the engine's views and process manager | nothing (stub model) |
| `make test-temporal` | Lane 2 and Nexus end to end: a refund through Nexus, duplicate approval signals, commit-then-timeout, an approval sent while no worker runs, a human "no", a policy denial | the `temporal` CLI |
| `make scenario` | Every scene against both lanes, scored from the ledger | the `temporal` CLI, port 8100 free |

`make test-temporal` starts its own in-memory Temporal server on port 7299 and refuses to use any other. The tests run
workers on the same task queues as the show, so on a shared server the show's workers would take the tests' workflows.
Use `tests/helpers.wait_until` instead of fixed sleeps, and the shared `payments` fixture in `conftest.py` for a
payments service on a free port.

## Gotchas

- **The Temporal workflow sandbox.** `lane2/support_side.py` and `lane2/payments_side.py` must not import
  `paidonce.config`, `paidonce.agent`, httpx, or anything that touches the filesystem at import time. Activities live in
  `*_activities.py` and are called by name. Pass heavy imports through `workflow.unsafe.imports_passed_through()`.
  Workflow code must stay deterministic and replay-safe.
- **Durable execution is not exactly-once.** Lane 2's refund is safe because the idempotency key and the refund
  workflow ID both come from the business operation (`refund-<ticket_id>`). Do not derive either from an attempt.
- **Lane 1 must stay fair.** It is the system a competent team ships today, not a strawman. If you change it, say why
  in the "Lane 1 realism" section of `architecture.md`. `PAIDONCE_L1_STABLE_KEY` is a measurement switch, off by default.
- **Lane 1's counts vary.** Kills land at wall-clock times. Assert on Lane 2 only, never on Lane 1's exact numbers.
- **Ticket IDs** are `<reset id>-<scene>-r<run>-<index>-<lane>` (`catalog.ticket_id`), so re-running a scene never reuses
  a workflow ID. The idempotency key is still `refund-<ticket_id>`.
- **Payments latency in the walkthrough** (2.5 s) must stay under Lane 1's 3 s client timeout, or its retry would pay
  the happy path twice.
- **Model parameters.** `claude-sonnet-5-5` rejects forced `tool_choice` and sampling parameters such as `temperature`,
  so `agent.py` uses `auto` with a strict tool schema and sets no sampling parameters. Strict schemas reject `minimum` on
  integers, so the amount floor is applied in code.
- **A Nexus workflow-run operation stays `STARTED, attempt 1` on the caller** while the payments-side activity retries.
  The Nexus page needs every attempt, so the engine polls the refund workflow's pending activity and closes attempts
  from its history (`timeline.merge_attempts`, `finish_attempts`); backoff comes from `REFUND_RETRY`, not the server.
- **Brand assets** (`ui/public/brand/`) are gitignored trademarks. Without them the header shows text.
- **Do not claim live endpoint retargeting.** The repo only points `payments-endpoint` at the current namespace.

## Not verified

Production anything (volume, a real payments service, the cost of running Temporal); retargeting an endpoint under
in-flight Nexus operations; workflow versioning with executions in flight; approval waits longer than seconds; and the
live model inside `make scenario` (scored runs use the stub; `make demo` is the live check).
