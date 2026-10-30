# Handoff: where this stands (2026-10-30)

Everything the demo needs is built and verified on Python 3.12 with a local Temporal dev server (CLI 1.9.1,
server 1.32.0). Start with `README.md` for setup and `docs/architecture.md` for the design. This file is for
whoever changes the code next.

## Verified
- `make test`: 12 passed (payments service, ledger, audit, Lane 1; stub model).
- `make test-temporal`: 4 passed (one refund through Nexus; duplicate approval signals ignored; commit-then-timeout
  gives one refund; an approval sent while no worker is running survives).
- `make scenario`: runs six scenes headless against both lanes and exits non-zero if Lane 2 breaks an invariant.
  Results, SHAs and caveats: `docs/scenario-results.md`. It also passed from a fresh clone with no `.env`.
- The Vite UI (`make ui`, then `make demo`) was clicked through in Chrome. The Nexus step was checked full screen at
  1512x945 (14-inch MacBook Pro): it fits without scrolling, including mid-kill with the worker-down banner, and a
  second run of the scene shows only the new run's rows.

## Not verified
- Production anything: volume, a real payments service, approval waits longer than seconds, cost of running Temporal.
- Endpoint retargeting under in-flight Nexus operations (the docs cover a namespace change; a task-queue change is
  undocumented and untested here).
- Workflow versioning with executions in flight.
- The model path in `make scenario`: scored runs use the stub model. The live model is checked by `make demo`.

## Decisions worth knowing
- **Scoring reads only the payments ledger** (`raccoon/audit.py`). It iterates tickets the harness recorded, so
  ledger rows for unrecorded tickets are ignored; "no refund without an approval" covers recorded tickets only.
- **The key comes from the business operation.** Lane 2 uses `refund-<ticket_id>` for both the idempotency key and the
  refund workflow ID. The ledger is UNIQUE on the key only, not on the ticket. Do not weaken this.
- **Model:** the demo agent defaults to `claude-sonnet-5-5` (`RACCOON_MODEL` overrides). Forced `tool_choice` is
  rejected by that model, so `raccoon/agent.py` uses `auto` with a strict tool schema. Sampling parameters such as
  `temperature` are rejected on current models, so the agent does not set any. Strict schemas reject `minimum` on
  integers; the amount floor is applied in code.
- **For a workflow-run Nexus operation the caller's operation stays `STARTED, attempt 1`** while the payments-side
  activity retries. The UI reads retry state from pending-activity data, because retry attempts are not in workflow
  history. `raccoon/show/engine.py` keeps each row (and the peak activity attempt) after the operation completes, so
  the evidence stays on screen when the scene ends.
- **Ticket IDs carry a scene-run number** (`<boot>-<scene>-r<n>-<i>-<lane>`), so re-running a scene starts new
  workflows instead of colliding with the last run's IDs. The idempotency key is still `refund-<ticket_id>`.
- **The show links into the Temporal Web UI** (`TEMPORAL_UI_URL`, default `http://127.0.0.1:8233`; the links are hidden
  when it doesn't answer at boot). Each Nexus row links the caller's workflow history in `raccoon-support` and the
  handler's in `raccoon-payments`.
- **The UI is a stepper** for a laptop browser, full screen (`#1`..`#7` in the URL, arrow keys, 1-7, R runs the
  scene). Nothing is built for tablet or phone.
- **Temporal look, local only.** Palette and fonts (Inter, Noto Sans Mono, bundled) follow temporal.io. The wordmark and
  favicon go in `ui/public/brand/`, which is gitignored because they are trademarks; without them the header shows
  text.
- `raccoon/show/server.py` resets the scoreboard at boot and sets uvicorn `timeout_graceful_shutdown=2`, because an
  open SSE tab otherwise blocks shutdown and orphans the child services on 8101 and 8102.
- The show reuses any Temporal server already listening on `TEMPORAL_ADDRESS` and will create its two namespaces
  and the Nexus endpoint there. Point `TEMPORAL_ADDRESS` somewhere else if that server belongs to something else.

## Lane 1 realism (keep it fair; these are the deliberate choices)
- Per-attempt idempotency key in the client (fresh uuid each try). Very common bug; fixing it (derive the key from the ticket) is a one-line change that fixes the double-delivery and timeout scenes. The write-up measures this.
- LangGraph `MemorySaver` (the tutorial default). Approval interrupt state is lost when the worker restarts.
- At-least-once queue with a visibility timeout. A recovery path re-drives "executing" tickets from the DB after a crash, which is what turns a crash-after-commit into a second refund.
- A careful dedupe check exists for finished tickets, so redelivery after completion is a no-op. Duplicates only arise for in-flight work.
- `RACCOON_L1_STABLE_KEY=1` (off by default) makes Lane 1 derive its idempotency key from the ticket instead of the attempt. It exists only so the write-up can measure the one-line fix (duplicates drop to 0, the 7 lost tickets remain). Default runs, the UI and the demo are unchanged, so Lane 1 is still the competent-team-today system described above.
- "Improve the current implementation" (outbox, sweeper, durable checkpointer) is argued in the write-up, not built as a third lane.

## Constraints that bite
- Workflow modules (`lane2/support_side.py`, `lane2/payments_side.py`) must not import `raccoon.config`,
  `raccoon.agent`, httpx or anything that touches the filesystem at import time: the Temporal workflow sandbox rejects
  it. Activities live in `*_activities.py` and are called by name.
- Workflow code must stay deterministic and replay-safe.
- Lane 1's counts vary run to run because kills land at wall-clock times. Assert on Lane 2 only.
- Stop `make demo` before `make test-temporal`: the show's workers poll the same task queues on the same Temporal
  server, pick up the tests' workflows and write to the show's ledger, so the tests see no refund.
