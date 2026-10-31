# Handoff: where this stands (2026-10-31)

Everything the demo needs is built and verified on Python 3.12 with a local Temporal dev server (CLI 1.9.1,
server 1.32.0). Start with `README.md` for setup and `docs/architecture.md` for the design. This file is for
whoever changes the code next.

## Verified
- `make test`: 38 passed (payments service and its call counts, ledger, audit, the agent's policy rules, Lane 1, the
  show server's guards, the engine's scene views and scene settling; stub model).
- `make test-temporal`: 6 passed (one refund through Nexus; duplicate approval signals ignored; commit-then-timeout
  gives one refund; an approval sent while no worker is running survives; a human "no" ends `rejected` with no ledger
  row; a policy denial ends `denied` with no Nexus operation in its history). It runs on its own throwaway Temporal
  server (`scripts/test-temporal.sh`, port 7299), and passed with `make demo` running.
- `make scenario`: runs six scenes headless against both lanes and exits non-zero if Lane 2 breaks an invariant.
  Results, SHAs and caveats: `docs/scenario-results.md`. It also passed from a fresh clone with no `.env`.
- Two guards on the show server, after a browser left open on :8100 wrecked two scenario runs. `make scenario` locks
  the controls (`PAIDONCE_SCENARIO_TOKEN`: reset, run and kill answer 423 without it, and the UI shows a "not the demo"
  banner). A second show server, or `make scenario` with the demo up, refuses to start while :8100 is taken: a second
  instance used to run its whole startup, boot-time reset included, before the bind failed.
- The Vite UI (`make ui`, then `make demo`) was clicked through in Chrome. The Nexus step was checked full screen at
  1512x945 (14-inch MacBook Pro): after a gauntlet run it fits without scrolling (927 px), and a second run of the
  scene shows only the new run's rows.

## Not verified
- Production anything: volume, a real payments service, approval waits longer than seconds, cost of running Temporal.
- Endpoint retargeting under in-flight Nexus operations (the docs cover a namespace change; a task-queue change is
  undocumented and untested here).
- Workflow versioning with executions in flight.
- The model path in `make scenario`: scored runs use the stub model. The live model is checked by `make demo`.

## Decisions worth knowing
- **Scoring reads only the payments ledger** (`paidonce/audit.py`). It iterates tickets the harness recorded, so
  ledger rows for unrecorded tickets are ignored; "no refund without an approval" covers recorded tickets only.
- **The agent checks policy in code before it asks the model.** `agent.check_policy` denies refunds over $200
  (`POLICY_LIMIT_CENTS`) and orders older than 30 days (`RETURN_WINDOW_DAYS`, from `Ticket.order_age_days`). Both
  lanes reach it through `agent.decide`, so a policy ticket is denied identically in both, with the stub model too.
  A denied ticket never reaches the human: Lane 1 marks the row `denied`, Lane 2's workflow returns `denied`.
- **Every scene's cohort has two tickets owed nothing**: one outside the policy (alternating per scene run between an
  amount over the cap and a 45-day-old order) and one the human denies. They exercise invariant 2 under the same
  chaos. The harness records what it planned for each ticket (`tickets.expect` in `audit.db`: `refund` or `policy`)
  and every human decision (`decisions`, first decision wins). Those are the harness's own records, not a lane's
  state; the audit reads them with the ledger to score `rejected` (a human said no, no refund), `declined` (policy
  ticket, no refund) and `waiting` (no decision, no refund). Any of these with a refund is `unapproved`.
- **The key comes from the business operation.** Lane 2 uses `refund-<ticket_id>` for both the idempotency key and the
  refund workflow ID. The ledger is UNIQUE on the key only, not on the ticket. Do not weaken this.
- **Model:** the demo agent defaults to `claude-sonnet-5-5` (`PAIDONCE_MODEL` overrides). Forced `tool_choice` is
  rejected by that model, so `paidonce/agent.py` uses `auto` with a strict tool schema. Sampling parameters such as
  `temperature` are rejected on current models, so the agent does not set any. Strict schemas reject `minimum` on
  integers; the amount floor is applied in code.
- **For a workflow-run Nexus operation the caller's operation stays `STARTED, attempt 1`** while the payments-side
  activity retries. The step 7 timeline (`ui/src/NexusTimeline.tsx`) needs each attempt's times, and history only
  records the last attempt, so `paidonce/show/engine.py` builds `attempts` by polling the refund workflow's pending
  activity (`_merge_attempts`) and closes them from its history (`_finish_attempts`). A StartToClose timeout ends an
  attempt at start + `REFUND_START_TO_CLOSE`. The server's `current_retry_interval` came back unusable (an
  epoch-sized number, on one poll only), so backoff comes from `REFUND_RETRY`. The caller's times come from its
  history (Nexus operation scheduled, started, completed), and each row's `ledger` (calls, replays, `booked_at`) from
  payments' counter and `GET /refunds`. Rows are kept after the operation completes, so the evidence stays on screen.
- **Step 7 is a gauntlet: four failures on the same refunds.** `scene_nexus_kill` sets `commit_then_stall` on payments
  (count 5, 9 s, and 2 s of latency before each commit), then kills the support worker,
  the payments worker (after attempt 2 starts) and the Temporal server (`GAUNTLET_*` in `paidonce/show/engine.py`).
  Each failure is a window in `scene_runs[...]["faults"]`: `{key, label, effect, start, end, hit}`. A kill window opens
  in `kill_window` (with `hit` = live Nexus rows) and closes on that process's `restart` event; a restart of a process
  that wasn't killed (a worker crash-looping while Temporal is down) closes nothing. The stall window comes from the
  ledger (`_stall_window`: first booking to the last held reply). `scripts/smoke.py --check nexus_kill` fails if any
  window hit no refund or never closed. On a real run: 15 calls for 5 refunds, 5 booked and 10 answered from the
  ledger; support saw `STARTED`, 1 start attempt and no error throughout.
- **The show owns Temporal when it starts it.** If nothing listens on `TEMPORAL_ADDRESS`, `procs.ensure_temporal` runs
  `temporal server start-dev --db-filename data/temporal.db` as a managed process, so `/api/faults/kill/temporal`
  works and the server comes back from its database with every workflow where it left off (workers that lose it exit
  and are respawned). If a server is already listening, the show reuses it, doesn't kill it, and the gauntlet skips
  that failure (`procs.owns_temporal`). Don't pre-start Temporal for a side-port scenario run; let the show start it.
- **Ticket IDs carry a scene-run number** (`<reset id>-<scene>-r<n>-<i>-<lane>`), so re-running a scene starts new
  workflows instead of colliding with the last run's IDs. The idempotency key is still `refund-<ticket_id>`.
- **The show links into the Temporal Web UI** (`TEMPORAL_UI_URL`, default `http://127.0.0.1:8233`; the engine re-checks
  it every 10 seconds and hides the links while it doesn't answer). Each timeline row links the caller's workflow history in `support` and the
  handler's in `payments`.
- **The UI is a stepper** for a laptop browser, full screen (`#1`..`#8` in the URL, arrow keys, 1-8, R runs the
  scene). Nothing is built for tablet or phone. Step 1 is the side-by-side architecture page (`ui/src/Architecture.tsx`):
  every row of its table is what the code does, so keep it in step with `paidonce/lane1/` and `paidonce/lane2/`.
- **Faults are drawn where they land.** One architecture diagram (`ui/src/Diagram.tsx`) on step 1 and the scene steps
  replaces the old toast, payments strip and process tiles. Fault events carry `target` (diagram node ids: process
  names or `temporal`) and `effect` (`kill`, `duplicate`, `stall`), set in `Engine.fault()`, so the UI never parses
  message text. Latency is drawn as staging, not as a fault. Dots come from the snapshot's `flow`: where each stack
  thinks each of this scene's tickets is, read from Lane 1's own table and Lane 2's `describe()` (no query, so it works
  with the worker dead). The payments node's slots come from the ledger audit, never from a stack. The Nexus step keeps
  its own panel and has no diagram. There is no event log on screen; a failed scene shows its error on its status line.
- **On screen the demo is "Paid Once: refunds over Nexus"**, and faults are labelled plainly ("Fault: kill -9 on both
  agent workers", event kind `fault`). The lanes are "Job queue" and "Temporal + Nexus" on screen (`LANE_NAMES` in the
  engine, `LANES` in `ui/src/App.tsx`); code, docs, the ledger and ticket IDs still say lane1/lane2. The Temporal namespaces show
  on screen and in the Web UI links, so they are named for the teams, `support` and `payments` (`PAIDONCE_SUPPORT_NS`,
  `PAIDONCE_PAYMENTS_NS`). Setup retargets an existing `payments-endpoint` that still points at an old namespace. The
  repo (`paid-once`), the `paidonce` package and `PAIDONCE_*` settings carry the same name as the screen.
- **Kill badges count the scene on screen.** The engine records kills per scene run (`scene_runs[...]["kills"]`), so a
  step never shows kills from an earlier scene and Reset clears them. Before a lane has a ticket its invariants read
  "Not tested yet", not "Holds".
- **Every scene panel is scoped to the scene on screen.** `lane1_view`, `lane2_view`, `flow` and `payments_calls` count
  only the current scene's tickets, and the UI shows Nexus rows and lane chips only when `snap.current` is the step's
  scene, so step 7 reads "Not run yet" instead of step 6's rows. `lane1_view_all` (every ticket since reset) feeds the
  scoreboard's "its own job table says N done" line; it is the queue's claim, shown next to the ledger, never scored.
- **Payments counts its calls** (`CALLS` in `paidonce/payments/service.py`, `GET /admin/calls`, cleared by
  `/admin/reset`): per lane and ticket, calls and how many the ledger answered from an existing key. The engine sums
  them per scene into the snapshot's `payments_calls` (`booked` = calls − replays). It observes only; the ledger and
  the audit don't read it.
- **A decided Lane 2 ticket with nothing pending reads "approved (or denied), queued in Temporal for a worker"**,
  drawn as a position dot, not the "waiting for a human" ring. The engine remembers the decisions it sent
  (`Engine.decisions`) because `describe()` can't tell a waiting workflow from one whose worker is down. The replay in
  `double_delivery` resends each ticket's actual decision, never an approval the human didn't give.
- **`describe()` shows a refunded and a denied workflow both as `COMPLETED`.** The engine reads each completed
  workflow's result once (from history, so no worker is needed) and caches it in `Engine.lane2_outcomes`; denied and
  rejected tickets are drawn as grey dots back at the helpdesk, refunded ones at payments.
- **Temporal look, local only.** Palette and fonts (Inter, Noto Sans Mono, bundled) follow temporal.io. The wordmark and
  favicon go in `ui/public/brand/`, which is gitignored because they are trademarks; without them the header shows
  text.
- `paidonce/show/server.py` resets the scoreboard at boot and sets uvicorn `timeout_graceful_shutdown=2`, because an
  open SSE tab otherwise blocks shutdown and orphans the child services on 8101 and 8102.
- The show reuses any Temporal server already listening on `TEMPORAL_ADDRESS` and will create its two namespaces
  and the Nexus endpoint there. Point `TEMPORAL_ADDRESS` somewhere else if that server belongs to something else.

## Lane 1 realism (keep it fair; these are the deliberate choices)
- Per-attempt idempotency key in the client (fresh uuid each try). Very common bug; fixing it (derive the key from the ticket) is a one-line change that fixes the double-delivery and timeout scenes. The write-up measures this.
- LangGraph `MemorySaver` (the tutorial default). Approval interrupt state is lost when the worker restarts.
- At-least-once queue with a visibility timeout. A recovery path re-drives "executing" tickets from the DB after a crash, which is what turns a crash-after-commit into a second refund.
- A human "no" is handled at the API: `POST /tickets/{id}/reject` marks the row `rejected` and queues no job, so
  redelivery and the recovery path (both of which touch only execute jobs) never see it. That is how a team would
  build it; it is not weakened to make Lane 1 refund denied tickets.
- A careful dedupe check exists for finished tickets, so redelivery after completion is a no-op. Duplicates only arise for in-flight work.
- `PAIDONCE_L1_STABLE_KEY=1` (off by default) makes Lane 1 derive its idempotency key from the ticket instead of the attempt. It exists only so the write-up can measure the one-line fix (duplicates drop to 0, the 7 lost tickets remain). Default runs, the UI and the demo are unchanged, so Lane 1 is still the competent-team-today system described above.
- "Improve the current implementation" (outbox, sweeper, durable checkpointer) is argued in the write-up, not built as a third lane.

## Constraints that bite
- Workflow modules (`lane2/support_side.py`, `lane2/payments_side.py`) must not import `paidonce.config`,
  `paidonce.agent`, httpx or anything that touches the filesystem at import time: the Temporal workflow sandbox rejects
  it. Activities live in `*_activities.py` and are called by name.
- Workflow code must stay deterministic and replay-safe.
- Lane 1's counts vary run to run because kills land at wall-clock times. Assert on Lane 2 only.
- The integration tests must not share a Temporal server with the show. The show's workers poll the same task queues
  and would take the tests' workflows, so the tests would see no refund. `make test-temporal` starts its own server
  and tells the tests its address (`PAIDONCE_TEST_TEMPORAL`); the tests refuse to run on any other server.
