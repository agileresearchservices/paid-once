import { useEffect, useState } from "react";
import type { Snapshot } from "./types";

// One EventSource feeds the whole UI. EventSource reconnects by itself, so a show-server restart
// shows up as a brief "reconnecting" state rather than a dead page.
export function useSnapshot(): { snap: Snapshot | null; connected: boolean } {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    const es = new EventSource("/api/stream");
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (e) => {
      setConnected(true);
      setSnap(JSON.parse(e.data) as Snapshot);
    };
    return () => es.close();
  }, []);

  return { snap, connected };
}

export async function post(path: string): Promise<void> {
  const r = await fetch(path, { method: "POST" });
  if (!r.ok && r.status !== 409) throw new Error(`${path}: ${r.status}`);
}
