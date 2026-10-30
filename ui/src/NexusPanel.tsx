import type { ReactNode } from "react";
import type { NexusRow, ProcStatus, Topology } from "./types";

// Ticket IDs look like <run>-<scene>-r<n>-<i>-lane2; the scene is on screen already, so show the index.
const shortTicket = (t: string) => {
  const m = t.match(/-(\d+)-lane2$/);
  return m ? `#${m[1]}` : t;
};

// Temporal Web UI links. With a run ID the link opens the history; without one, a list filtered to the workflow.
function workflowLink(ui: string, ns: string, wid: string, run?: string) {
  const base = `${ui}/namespaces/${encodeURIComponent(ns)}/workflows`;
  return run
    ? `${base}/${encodeURIComponent(wid)}/${encodeURIComponent(run)}/history`
    : `${base}?query=${encodeURIComponent(`WorkflowId="${wid}"`)}`;
}

function Ext({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

// Who owns what: support's code names only the endpoint, and the endpoint maps to the payments namespace.
function Boundary({ t, ui }: { t: Topology; ui: string | null }) {
  return (
    <div className="boundary">
      <div className="team support">
        <span className="team-name">Support team</span>
        <code>{t.support.namespace}</code>
        <span>{t.support.workflow}</span>
        {ui && <Ext href={`${ui}/namespaces/${t.support.namespace}/workflows`}>Open namespace ↗</Ext>}
      </div>
      <div className="endpoint">
        <span className="boundary-label">team boundary</span>
        <div className="endpoint-card">
          <code>{t.endpoint}</code>
          <code>
            {t.service}.{t.operation}
          </code>
          <span className="muted">the only thing support's code names</span>
        </div>
      </div>
      <div className="team payments">
        <span className="team-name">Payments team</span>
        <code>{t.payments.namespace}</code>
        <span>
          {t.payments.workflow} → {t.payments.activity}
        </span>
        <span className="muted">task queue {t.payments.task_queue}</span>
        {ui && <Ext href={`${ui}/namespaces/${t.payments.namespace}/workflows`}>Open namespace ↗</Ext>}
      </div>
      <p className="caption">
        Simplified contract. The endpoint maps to the namespace and task queue; the caller's code never does.
      </p>
    </div>
  );
}

export function NexusPanel({
  rows,
  topology,
  temporalUi,
  paymentsWorker,
}: {
  rows: NexusRow[];
  topology: Topology;
  temporalUi: string | null;
  paymentsWorker?: ProcStatus;
}) {
  const surfaced = rows.filter((r) => r.caller_saw_failure || r.state === "FAILED").length;
  const retries = rows.reduce((n, r) => n + Math.max(0, (r.handler.peak_activity_attempt ?? 0) - 1), 0);
  const workerDown = paymentsWorker !== undefined && !paymentsWorker.alive;

  return (
    <section className="nexus" aria-label="Nexus">
      <Boundary t={topology} ui={temporalUi} />
      <div className="ops">
        <div className="headline">
          <div>
            <span className="headline-label">Support saw</span>
            <b>{rows.length}</b> operations · <b>{surfaced}</b> failures surfaced
          </div>
          <div>
            <span className="headline-label">Payments absorbed</span>
            <b>{retries}</b> activity retries
          </div>
        </div>
        {workerDown && (
          <p className="worker-down" role="status">
            🦝 Payments worker down. Accepted refunds wait and retry inside {topology.payments.namespace}.
          </p>
        )}
        {rows.length === 0 ? (
          <p className="muted">No operations yet in this scene.</p>
        ) : (
          <div className="ops-scroll">
            <table>
              <thead>
                <tr>
                  <th>Ticket</th>
                  <th>
                    Support sees <span className="th-sub">the caller's operation</span>
                  </th>
                  <th>
                    Payments sees <span className="th-sub">observed by this dashboard; support never reads it</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const h = r.handler;
                  const peak = h.peak_activity_attempt ?? 0;
                  const retrying = r.live && (h.activity_attempt ?? 0) >= 2;
                  return (
                    <tr key={r.ticket} className={r.live ? "" : "done"}>
                      <td title={r.ticket}>{shortTicket(r.ticket)}</td>
                      <td>
                        <span className="pill">{r.live ? r.state : `✓ ${r.state}`}</span>{" "}
                        <span className="muted">start attempts {r.peak_attempt}</span>
                        {temporalUi && (
                          <>
                            {" "}
                            <Ext href={workflowLink(temporalUi, r.caller_namespace, r.caller_workflow_id, r.caller_run_id)}>
                              history ↗
                            </Ext>
                          </>
                        )}
                        {r.last_failure && <div className="fail">{r.last_failure}</div>}
                      </td>
                      <td>
                        {h.workflow_id ? (
                          <>
                            <code title="The handler workflow ID comes from the ticket: a second dedup layer">
                              {h.workflow_id}
                            </code>{" "}
                            <span className="pill">{h.status}</span>{" "}
                            {retrying ? (
                              <span className="pill warn">activity attempt {h.activity_attempt}</span>
                            ) : peak >= 2 ? (
                              <span className="pill warn">retried ×{peak - 1}</span>
                            ) : (
                              <span className="muted">activity attempt {r.live ? (h.activity_attempt ?? 0) : peak}</span>
                            )}
                            {temporalUi && h.namespace && (
                              <>
                                {" "}
                                <Ext href={workflowLink(temporalUi, h.namespace, h.workflow_id, h.run_id)}>history ↗</Ext>
                              </>
                            )}
                            {r.live && h.activity_failure && <div className="fail">{h.activity_failure}</div>}
                          </>
                        ) : (
                          <span className="muted">not accepted yet</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <p className="muted footnote">
          Handler workflow ID <code>refund-&lt;ticket&gt;</code> is a second dedup layer: a re-sent start request finds the
          running workflow instead of starting another.
        </p>
      </div>
    </section>
  );
}
