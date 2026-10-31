// Ticket IDs look like <run>-<scene>-r<n>-<i>-lane2; the scene is on screen already, so show the index.
export const shortTicket = (t: string) => {
  const m = t.match(/-(\d+)-lane2$/);
  return m ? `#${m[1]}` : t;
};

// Temporal Web UI links. With a run ID the link opens the history; without one, a list filtered to the workflow.
export function workflowLink(ui: string, ns: string, wid: string, run?: string) {
  const base = `${ui}/namespaces/${encodeURIComponent(ns)}/workflows`;
  return run
    ? `${base}/${encodeURIComponent(wid)}/${encodeURIComponent(run)}/history`
    : `${base}?query=${encodeURIComponent(`WorkflowId="${wid}"`)}`;
}
