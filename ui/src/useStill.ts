import { useEffect, useState } from "react";

// True when the viewer asked their system for reduced motion: the pages' animated bits then stand still.
export function useStill(): boolean {
  const [still, setStill] = useState(false);
  useEffect(() => {
    const q = window.matchMedia("(prefers-reduced-motion: reduce)");
    setStill(q.matches);
    const on = () => setStill(q.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);
  return still;
}
