// Ticket IDs look like <run>-<scene>-r<n>-<i>-lane2; the scene is on screen already, so show the index.
export const shortTicket = (t: string) => {
  const m = t.match(/-(\d+)-lane2$/);
  return m ? `#${m[1]}` : t;
};
