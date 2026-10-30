import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
// Bundled, so the demo needs no network. Temporal's own face (Aeonik) is licensed, so Inter stands in.
import "@fontsource-variable/inter";
import "@fontsource/noto-sans-mono";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
