// Shape of Engine.snapshot() in paidonce/show/engine.py, streamed from /api/stream.

export type LaneId = "lane1" | "lane2";

export interface LaneAudit {
  lane: LaneId;
  submitted: number;
  approved: number;
  refunded_once: number;
  duplicates: number; // tickets refunded more than once
  duplicate_refunds: number;
  duplicate_cents: number;
  missing: number;
  in_flight: number;
  unapproved: number;
  rejected: number; // a human said no, and no money moved
  declined: number; // broke the refund policy, and no money moved
  waiting: number; // no decision yet, no money moved
  violations: number;
  // ledger state per ticket: ok | duplicate | in_flight | missing | waiting | unapproved | rejected | declined
  tickets?: Record<string, string>;
}

export interface ProcStatus {
  label: string;
  alive: boolean;
  starts: number;
}

export interface ShowEvent {
  ts: number;
  kind: string; // boot | scene | human | fault | scene_done | reset | note | error
  msg: string;
  scene?: string;
  ok?: boolean; // scene_done only
  target?: string[]; // fault only: diagram node ids it lands on (process names, or "temporal")
  effect?: "kill" | "duplicate" | "stall"; // fault only
  proc?: string; // kill and restart only: the process name
}

// Where one stack thinks one ticket is: a diagram node id, a wire ("lane1_worker>payments") or "done".
export interface FlowDot {
  ticket: string;
  at: string;
  state: string;
}

// The payments side, read by the dashboard straight from the payments namespace. Support never sees it.
export interface NexusHandler {
  workflow_id?: string;
  run_id?: string;
  namespace?: string;
  status?: string;
  activity_attempt?: number;
  peak_activity_attempt?: number;
  activity_failure?: string;
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
  caller_workflow_id: string;
  caller_run_id: string;
  caller_namespace: string;
  handler: NexusHandler;
  endpoint: string;
  service: string;
  operation: string;
  state: string;
  attempt: number; // start attempts on the caller side, not activity retries
  peak_attempt: number;
  last_failure: string;
  caller_saw_failure: boolean;
  // The timeline: what support saw over time, what payments did, and what the ledger says.
  op_scheduled_at: number;
  op_closed_at: number | null;
  phases: { state: string; at: number }[]; // the caller's operation state, each time it changed
  attempts: RefundAttempt[];
  ledger: { calls: number; replays: number; booked_at: number | null };
}

export interface Topology {
  support: { namespace: string; task_queue: string; workflow: string };
  endpoint: string;
  service: string;
  operation: string;
  payments: { namespace: string; task_queue: string; workflow: string; activity: string };
}

export interface FaultState {
  mode: string;
  remaining: number;
  delay_s: number;
  latency_s: number;
}

export interface SceneRun {
  started_at: number;
  finished_at: number | null;
  ok: boolean | null;
  error?: string | null; // why the scene failed, when ok is false
  kills: Record<string, number>; // kill -9s during this run, by process
  faults?: FaultWindow[]; // the failures this run injected, each with its window (the Nexus gauntlet records these)
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

export interface Snapshot {
  now: number;
  running: boolean;
  current: string | null;
  scene_runs: Record<string, SceneRun>; // last run of each scene since the last reset
  scenes: { id: string; title: string }[];
  audit: Record<LaneId, LaneAudit>;
  processes: Record<string, ProcStatus>;
  events: ShowEvent[];
  nexus: NexusRow[];
  lane1_view: Record<string, number>; // this scene's tickets, by the queue's own job table
  lane1_view_all: Record<string, number>; // every ticket since reset, by the queue's own job table
  lane2_view: Record<string, number>;
  faults: Partial<Record<LaneId, FaultState>>;
  // This scene's calls to payments, counted by payments: booked = new ledger rows, replays = answered from the key.
  payments_calls: Partial<Record<LaneId, { calls: number; booked: number; replays: number }>>;
  flow: Record<LaneId, FlowDot[]>; // this scene's tickets only
  beat: { scene: string; id: string; at: number } | null; // the walkthrough's step waiting for its box to be dismissed
  temporal_ui: string | null; // Temporal Web UI base URL, or null when it is not answering
  topology: Topology;
  locked: string | null; // what owns the server's controls (`make scenario`), or null for a normal show
}
