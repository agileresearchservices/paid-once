import type { NexusRow } from "./types";

const shortTicket = (t: string) => t.replace(/^[0-9a-f]{4}-/, "").replace(/-lane2$/, "");

// The contract the support team sees, then the two sides of each live operation. For a
// workflow-run operation the caller's side stays STARTED while the payments side retries.
export function NexusPanel({ rows }: { rows: NexusRow[] }) {
  return (
    <section className="nexus" aria-label="Nexus">
      <div className="contract">
        <h3>The contract</h3>
        <pre>{`service PaymentsService
  issue_refund(RefundRequest) -> RefundResult

endpoint  payments-endpoint`}</pre>
        <p>
          The support team sees one operation. It does not see the payments team's namespace, task queue,
          or workflow behind it.
        </p>
      </div>
      <div className="ops">
        <h3>Live operations</h3>
        {rows.length === 0 ? (
          <p className="muted">No operations in flight.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Ticket</th>
                <th>Support namespace: the call</th>
                <th>Payments namespace: the refund workflow</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const retrying = (r.handler.activity_attempt ?? 0) >= 2;
                return (
                  <tr key={r.ticket}>
                    <td>{shortTicket(r.ticket)}</td>
                    <td>
                      <span className="pill">{r.state}</span> attempt {r.attempt}
                      {r.last_failure && <div className="fail">{r.last_failure}</div>}
                    </td>
                    <td>
                      {r.handler.status ? (
                        <>
                          <span className="pill">{r.handler.status}</span>{" "}
                          {retrying ? (
                            <span className="pill warn">… activity attempt {r.handler.activity_attempt}</span>
                          ) : (
                            <span>activity attempt {r.handler.activity_attempt ?? 0}</span>
                          )}
                          {r.handler.activity_failure && <div className="fail">{r.handler.activity_failure}</div>}
                        </>
                      ) : (
                        <span className="muted">starting</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <p className="muted">
          When the payments worker dies, the caller's operation does not change. The retry happens on the payments side.
        </p>
      </div>
    </section>
  );
}
