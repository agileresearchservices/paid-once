# Handoff: where this stands (2026-10-30, Friday)

Due **Monday 2026-11-02**. Deliverables: written case study with diagrams, a repo (this), a slide deck, a live
UI demo run from Kevin's machine. The written case study is required; the deck is its presentation companion.
Strategy, customer profile, scene list and open questions live in the Claude project "Temporal"
(`claude/demo-scope.md`). This file covers the code.

## Done and tested
- Payments service + ledger, audit invariants, Lane 1 (12 tests pass, stub model).
- Lane 2 on a real Temporal dev server: ticket -> approval signal -> Nexus operation `PaymentsService.issue_refund`
  -> `RefundWorkflow` in `raccoon-payments` -> ledger. 4 integration tests pass (`make test-temporal`):
  one refund through Nexus; duplicate approval signals ignored; commit-then-timeout gives one refund; an approval
  sent while no worker is running survives.

## Written but NOT yet run end to end
- `raccoon/show/*` (process manager, scenes, server) and `scripts/smoke.py`. Run
  `RACCOON_STUB_LLM=1 uv run python scripts/smoke.py intro tip_over` (needs `temporal` on PATH) and check each scene
  moves the right counters: Lane 1 shows duplicates/missing, Lane 2 stays clean. Expect to tune sleeps and the
  `SETTLE_S` window in `raccoon/show/engine.py`.
- Live Anthropic calls (`raccoon/agent.py`) were never exercised: no API key where this was written. Check the
  forced tool call returns a `propose_action` block for `claude-haiku-5-5`.
- The Nexus panel reads `raw_description.pending_nexus_operations`; field names were checked against the proto, not against a live pending op.

## Not started
- Vite UI in `ui/` (step-wise NEXT/BACK, lanes side by side, scoreboard via SSE from `/api/stream`, Nexus panel).
- Slide deck, written case study, architecture diagrams, README polish.
- Scene 7 narrative: show the Nexus contract, the endpoint in the registry, the pending operation retrying, the endpoint retarget.

## Lane 1 realism (keep it fair; these are the deliberate choices)
- Per-attempt idempotency key in the client (fresh uuid each try). Very common bug; fixing it (derive the key from the ticket) is a one-line change that fixes the double-delivery and timeout scenes. Say so in the write-up.
- LangGraph `MemorySaver` (the tutorial default). Approval interrupt state is lost when the worker restarts.
- At-least-once queue with a visibility timeout. A recovery path re-drives "executing" tickets from the DB after a crash, which is what turns a crash-after-commit into a second refund.
- A careful dedupe check exists for finished tickets, so redelivery after completion is a no-op. Duplicates only arise for in-flight work.
- "Improve the current implementation" (idempotency keys, outbox, sweeper, durable checkpointer) is argued in the write-up, not built as a third lane.

## Environment notes
- Written in a cloud sandbox plus a Linux VM on Kevin's Mac; the Temporal CLI was downloaded in the VM. On the Mac: `brew install temporal uv`.
- Python 3.12 via uv; `requires-python >=3.11`. Node 22 for the UI.
- The tool that synced these files could not write a file named `Makefile`. Run `cp docs/Makefile.txt Makefile` once.
- Delete before committing: `raccoon/lane2/zz_test.py` (stray empty file) and any `refund-raccoon-sync*.tgz` in the parent folder.

## Suggested next steps in Claude Code
1. `make install && make test` then `temporal server start-dev` in another terminal, `make setup`, `make test-temporal`.
2. Run `scripts/smoke.py` for all six scenes and fix timing until Lane 1 fails and Lane 2 does not, every time.
3. Add `ANTHROPIC_API_KEY`, run one scene with the real model.
4. Build the UI against `/api/state` and `/api/stream`.
5. Then the deck and the written case study; diagrams can be generated from the Layout above.
