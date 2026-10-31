// Shape of Engine.snapshot() in raccoon/show/engine.py, streamed from /api/stream.

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
  violations: number;
  tickets?: Record<string, string>; // ledger state per ticket: ok | duplicate | in_flight | missing | waiting | unapproved
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
  kills: Record<string, number>; // kill -9s during this run, by process
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
  lane1_view: Record<string, number>;
  lane2_view: Record<string, number>;
  faults: Partial<Record<LaneId, FaultState>>;
  flow: Record<LaneId, FlowDot[]>; // this scene's tickets only
  temporal_ui: string | null; // Temporal Web UI base URL, or null when it is not answering
  topology: Topology;
  locked: string | null; // what owns the server's controls (`make scenario`), or null for a normal show
}
