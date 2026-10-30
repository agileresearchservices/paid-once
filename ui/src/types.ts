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
}

export interface ProcStatus {
  label: string;
  alive: boolean;
  starts: number;
  kills: number;
}

export interface RaccoonEvent {
  ts: number;
  kind: string; // boot | scene | human | raccoon | scene_done | reset | note | error
  msg: string;
  scene?: string;
}

export interface NexusHandler {
  workflow_id?: string;
  namespace?: string;
  status?: string;
  activity_attempt?: number;
  activity_failure?: string;
}

export interface NexusRow {
  ticket: string;
  handler: NexusHandler;
  endpoint: string;
  service: string;
  operation: string;
  state: string;
  attempt: number;
  last_failure: string;
}

export interface FaultState {
  mode: string;
  remaining: number;
  delay_s: number;
  latency_s: number;
}

export interface Snapshot {
  now: number;
  running: boolean;
  current: string | null;
  scenes: { id: string; title: string }[];
  audit: Record<LaneId, LaneAudit>;
  processes: Record<string, ProcStatus>;
  events: RaccoonEvent[];
  nexus: NexusRow[];
  lane1_view: Record<string, number>;
  lane2_view: Record<string, number>;
  faults: Partial<Record<LaneId, FaultState>>;
}
