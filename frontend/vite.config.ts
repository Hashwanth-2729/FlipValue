/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv, type Plugin } from "vite";

// The website calls the API at VITE_API_BASE_URL. Leave it empty when the API is served from the same origin
// (FastAPI serving dist/ locally, or Firebase Hosting rewrites to Cloud Run). Set it to the API origin only when the
// website and API are on different origins; the API must then list the website origin in FLIPVALUE_CORS_ORIGINS.

function contentSecurityPolicy(apiBase: string): Plugin {
  const apiOrigin = apiBase ? new URL(apiBase).origin : "";
  const policy = [
    "default-src 'self'",
    "img-src 'self' data:",
    "style-src 'self'",
    "script-src 'self'",
    `connect-src 'self'${apiOrigin ? ` ${apiOrigin}` : ""}`,
    "base-uri 'self'",
    "form-action 'self'",
  ].join("; ");
  return {
    name: "flipvalue-csp",
    apply: "build", // the dev server needs inline scripts for hot reload
    transformIndexHtml: (html) =>
      html.replace(
        '<meta charset="UTF-8" />',
        `<meta charset="UTF-8" />\n    <meta http-equiv="Content-Security-Policy" content="${policy}" />`,
      ),
  };
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const apiBase = (env.VITE_API_BASE_URL ?? "").trim().replace(/\/$/, "");
  if (apiBase && mode === "production" && !apiBase.startsWith("https://")) {
    throw new Error("VITE_API_BASE_URL must be an https:// URL for production builds.");
  }
  // Development only: Vite proxies API paths to a local backend so the browser stays on one origin.
  const backend = process.env.FLIPVALUE_BACKEND ?? "http://127.0.0.1:8091";
  return {
    plugins: [react(), contentSecurityPolicy(apiBase)],
    server: {
      port: 5173,
      proxy: { "/api": backend, "/admin/api": backend, "/v1": backend, "/docs": backend, "/openapi.json": backend },
    },
    build: { outDir: "dist", sourcemap: false },
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["src/test/setup.ts"],
      include: ["src/**/*.test.{ts,tsx}"],
    },
  };
});
