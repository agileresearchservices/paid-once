import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: the show server (make demo) runs on 8100; proxy /api to it so SSE and POSTs work.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8100" },
  },
});
