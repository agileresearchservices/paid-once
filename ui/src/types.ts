// Shape of the snapshot streamed from /api/stream: Engine.snapshot() in paidonce/show/engine.py, plus `locked`
// from paidonce/show/server.py.

// The two stacks: `lane1` is Queue + LangGraph, `lane2` is Temporal + Nexus. Per-lane records are keyed by these.
export type LaneId = "lane1" | "lane2";

// One lane's verdict, scored by `audit.compute_all` (paidonce/audit.py) from the payments ledger and the harness's
// records. Never the lane's own state.
export interface LaneAudit {
  lane: LaneId;
  submitted: number;
  approved: number;
  refunded_once: number; // approved, and refunded exactly once
  duplicates: number; // tickets refunded more than once
  duplicate_refunds: number; // refunds beyond the first, summed over the duplicated tickets
  duplicate_cents: number; // the money in those extra refunds, in cents
  missing: number; // approved, never refunded, and past the settle window: counted lost
  in_flight: number; // approved, not refunded yet, and still inside the settle window
  unapproved: number; // refunded with no approval on record: an invariant violation
  rejected: number; // a human said no, and no money moved
  declined: number; // broke the refund policy, and no money moved
  waiting: number; // no decision yet, no money moved
  violations: number; // tickets breaking an invariant: duplicates, missing and unapproved
  // ledger state per ticket: ok | duplicate | in_flight | missing | waiting | unapproved | rejected | declined
  tickets?: Record<string, string>;
  // approved, no refund yet: when it was approved, and when the audit stops waiting and counts it lost
  pending?: Record<string, { since: number; verdict_at: number }>;
}

// One managed process as the page sees it (`ProcessManager.status` in paidonce/show/procs.py). `starts` counts every
// spawn, restarts included, so it reads 1 for a process that was never killed.
export interface ProcStatus {
  label: string;
  alive: boolean; // false once the process has exited, until the watcher restarts it
  starts: number;
}

// One line of the show's event log (`events` in the snapshot): a boot, reset, submit, scene, fault, kill and so on.
export interface ShowEvent {
  ts: number; // epoch seconds
  kind: "boot" | "reset" | "submit" | "scene" | "human" | "fault" | "kill" | "restart" | "scene_done" | "note" | "error";
  msg: string;
  scene?: string;
  ok?: boolean; // scene_done only
  target?: string[]; // fault only: diagram node ids it lands on (process names, or "temporal")
  effect?: "kill" | "duplicate" | "stall"; // fault only
  proc?: string; // kill and restart only: the process name
}

// Where one stack thinks one ticket is: a diagram node id, a wire ("lane1_worker>payments"), "closed" (denied) or
// "done".
export interface FlowDot {
  ticket: string;
  at: string;
  state: string;
}

// The payments side, read by the dashboard straight from the payments namespace. Support never sees it.
export interface NexusHandler {
  status?: string;
  activity_attempt?: number;
  peak_activity_attempt?: number;
}

// One attempt of the refund activity inside payments. Times are epoch seconds.
export interface RefundAttempt {
  n: number;
  started_at: number;
  ended_at: number | null; // null while running
  outcome: "running" | "failed" | "ok" | "unknown";
  failure: string;
}

// One Nexus operation in the current scene. Kept after it completes (live = false).
export interface NexusRow {
  ticket: string;
  live: boolean;
  handler: NexusHandler;
  state: string; // the caller's operation state (STARTED while payments retries), or COMPLETED / FAILED once closed
  last_failure: string;
  caller_saw_failure: boolean;
  attempt: number; // support's own start attempts of the operation (not payments' retries); read by `make scenario`
  peak_attempt: number;
  // What payments did (every attempt of the refund activity) and what the ledger says.
  attempts: RefundAttempt[];
  ledger: { calls: number; replays: number; booked_at: number | null };
}

// The Nexus wiring the Nexus panel draws, from TOPOLOGY in paidonce/show/catalog.py. Fixed for the life of the server.
export interface Topology {
  support: { namespace: string; task_queue: string; workflow: string }; // the caller side
  endpoint: string; // the Nexus endpoint name, `payments-endpoint`
  service: string; // the Nexus service: PaymentsService in paidonce/lane2/contract.py
  operation: string; // the one operation payments offers: issue_refund
  sends: string[]; // RefundRequest's fields, in order
  returns: string[]; // RefundResult's fields, in order
  payments: { namespace: string; task_queue: string; workflow: string; activity: string }; // the handler side
}

// The fault payments has set for one lane, as its `/admin/fault` endpoint reports it. Each lane has its own.
export interface FaultState {
  mode: string; // "none", or "commit_then_stall": the refund is booked, then the reply is held
  remaining: number; // refunds the stall still applies to, counting down as each one is held
  delay_s: number; // how long a stalled reply is held after the commit, in seconds
  latency_s: number; // extra delay before each commit, in seconds
}

// The last run of one scene: when it started and finished (epoch seconds) and what it did. Kept until the reset.
export interface SceneRun {
  started_at: number;
  finished_at: number | null; // null while the scene runs
  ok: boolean | null; // null while the scene runs
  error?: string | null; // why the scene failed, when ok is false
  kills: Record<string, number>; // kill -9s during this run, by process
  faults: FaultWindow[]; // the failures this run injected, each with its window (the Nexus gauntlet records these)
}

// One injected failure: when it started and ended (null while it lasts), and how many refunds were in flight.
export interface FaultWindow {
  key: string; // process name, or "payments" for the payments service's stall
  label: string;
  effect: "kill" | "stall";
  start: number | null; // a stall's start is known once the first stalled refund is booked
  end: number | null;
  hit: number;
}

// Everything the page draws. Adding a key means the engine, this interface and the component that reads it.
export interface Snapshot {
  now: number; // epoch seconds, read when the snapshot is built
  running: boolean; // a scene is in progress, and every Run button is off
  current: string | null; // the scene running or last run, null until one runs and after a reset
  scene_runs: Record<string, SceneRun>; // last run of each scene since the last reset
  audit: Record<LaneId, LaneAudit>; // the scoreboard, from the ledger since the reset, minus the demo scenes
  demo_audit: Record<LaneId, LaneAudit>; // the walkthrough's and the Nexus scene's tickets, scored apart from `audit`
  processes: Record<string, ProcStatus>; // every managed process, by name
  events: ShowEvent[]; // the newest 60 events, oldest first
  nexus: NexusRow[]; // the Nexus operations of the last scene run, none unless it was the Nexus scene
  lane1_view_all: Record<string, number>; // every ticket since reset, by the queue's own job table
  lane2_view_all: Record<string, number>; // every Lane 2 workflow since reset, by its Temporal status
  faults: Partial<Record<LaneId, FaultState>>; // payments' fault per lane, polled from /admin/fault
  // This scene's calls to payments, counted by payments: booked = new ledger rows, replays = answered from the key.
  payments_calls: Partial<Record<LaneId, { calls: number; booked: number; replays: number }>>;
  payments_calls_all: Partial<Record<LaneId, { calls: number; booked: number; replays: number }>>; // since reset
  flow: Record<LaneId, FlowDot[]>; // this scene's tickets only
  beat: { scene: string; id: string; at: number } | null; // the walkthrough step on screen
  topology: Topology; // the Nexus wiring, fixed for the life of the server
  locked: string | null; // what owns the server's controls (`make scenario`), or null for a normal show
}
