/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

// The production bundle is committed under the Python package so that
// `pip install` never needs Node. Relative base keeps asset URLs working
// wherever the backend mounts the static directory.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../src/gregraph/webui/static",
    emptyOutDir: true,
    sourcemap: false,
    modulePreload: { polyfill: false },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
