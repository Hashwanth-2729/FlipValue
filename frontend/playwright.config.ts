import { randomBytes } from "node:crypto";
import { resolve } from "node:path";

import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run the REAL backend (fresh database + synthetic development data) serving the built website.
// Keys are random per run and never written anywhere.
const PORT = 8092;
const adminKey = process.env.E2E_ADMIN_KEY ?? randomBytes(32).toString("base64url");
process.env.E2E_ADMIN_KEY = adminKey;
const root = resolve(import.meta.dirname, "..");
const python = process.platform === "win32" ? resolve(root, ".venv/Scripts/python.exe") : resolve(root, ".venv/bin/python");

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    // Uses the installed Microsoft Edge so no browser download is needed; set E2E_CHANNEL to change it.
    channel: process.env.E2E_CHANNEL ?? "msedge",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Edge"], channel: process.env.E2E_CHANNEL ?? "msedge" },
      grepInvert: /@mobile/,
    },
    { name: "mobile", use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true }, grep: /@mobile/ },
  ],
  webServer: {
    command: `"${python}" scripts/e2e_server.py ${PORT}`,
    cwd: root,
    url: `http://127.0.0.1:${PORT}/ready`,
    timeout: 120_000,
    reuseExistingServer: false,
    env: { FLIPVALUE_ADMIN_KEYS: adminKey, FLIPVALUE_API_KEYS: randomBytes(32).toString("base64url") },
  },
});
