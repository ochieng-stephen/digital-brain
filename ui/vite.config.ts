import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // the live Brain engine over the local HTTP bridge (uv run digital-brain-http); override with
    // VITE_API_TARGET to point at a deployed backend for a quick UI preview without a local server.
    proxy: { "/api": { target: process.env.VITE_API_TARGET || "http://127.0.0.1:8787", changeOrigin: true, rewrite: (p) => p.replace(/^\/api/, "") } },
  },
});
