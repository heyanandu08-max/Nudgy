// Renders the shared UI as "Windows" and as "macOS" (only the user agent differs, which is
// all the app branches on) with the Tauri IPC mocked, so both builds' screens can be compared
// pixel by pixel. Chromium stands in for WebView2; for WKWebView compare against screenshots
// of the Linux build (WebKitGTK).
//
//   cd app && npx vite --port 1420 &      # serve the frontend
//   node scripts/ui_parity.mjs out/        # → out/<screen>-win.png, out/<screen>-mac.png
//   scripts/ui_parity.sh out/              # renders + diffs (ImageMagick)
//
// Needs Playwright with Chromium (PLAYWRIGHT_MODULE=/path/to/playwright/index.mjs if global).

import { mkdirSync } from "node:fs";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE ?? "playwright");
const out = process.argv[2] ?? "parity";
const base = process.env.NUDGY_UI_URL ?? "http://localhost:1420";
mkdirSync(out, { recursive: true });

const UA = {
  win: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36 Edg/140.0.0.0",
  mac: "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko)",
};

const quota = (left) => ({ used: 2 - left, limit: 2, left, resets_at: "2026-10-01T00:00:00+00:00" });
const capped = (left) => ({ notice: null, capped: true, lessons: quota(left) });
const STATES = {
  notice: { notice: { free_until: "2026-10-10", lessons_per_month: 2 }, capped: false, lessons: null },
  left1: capped(1),
  left0: capped(0),
};

/** Minimal stand-in for window.__TAURI_INTERNALS__ (what @tauri-apps/api calls into). */
function mockTauri(access) {
  const settings = {
    backendUrl: "http://127.0.0.1:8787",
    voiceEnabled: true,
    voiceId: null,
    hotkey: "Ctrl+Alt+Space",
    responseLength: "brief",
    language: "en",
    paused: false,
    blocklist: ["1Password", "Bitwarden"],
    cursorColor: "black",
    cursorSize: "m",
    hideCursorIdle: false,
    onboarded: true,
  };
  const me = { id: 1, email: "tester@example.com", plan: "free", plan_name: "Free", paid: false, subscription_status: null, access, team: null };
  const handlers = {
    get_settings: () => settings,
    access_get: () => access,
    auth_state: () => ({ email: me.email, plan: "free" }),
    account_me: () => me,
    dashboard: () => ({ skills: [], recent: [], weak_spots: [], recent_asks: [] }),
    last_timings: () => null,
    "plugin:event|listen": () => 1,
  };
  window.isTauri = true;
  let cb = 0;
  window.__TAURI_INTERNALS__ = {
    invoke: async (cmd) => (cmd in handlers ? handlers[cmd]() : null),
    transformCallback: () => ++cb,
    convertFileSrc: (p) => p,
    metadata: { currentWindow: { label: "main" }, currentWebview: { windowLabel: "main", label: "main" } },
  };
  // The app's backend health check: always "connected".
  const realFetch = window.fetch;
  window.fetch = (url, init) =>
    String(url).includes("127.0.0.1:8787")
      ? Promise.resolve(new Response(JSON.stringify({ status: "ok", version: "0.1.0", languages: [], voices: [] }), { headers: { "content-type": "application/json" } }))
      : realFetch(url, init);
}

// Screens: [name, access state, steps to reach it]
const SCREENS = [
  ["home-left1", "left1", async () => {}],
  ["upgrade", "left0", async (p) => {
    await p.getByRole("textbox").first().fill("cut a clip");
    await p.getByRole("button", { name: /Teach me/ }).click();
  }],
  ["account-capped", "left0", async (p) => {
    await p.getByText("Settings", { exact: true }).first().click();
    await p.locator("nav button", { hasText: "Account" }).click();
  }],
  ["settings-notice", "notice", async (p) => {
    await p.getByText("Settings", { exact: true }).first().click();
  }],
];

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
for (const [os, ua] of Object.entries(UA)) {
  for (const [name, state, go] of SCREENS) {
    const ctx = await browser.newContext({ viewport: { width: 980, height: 780 }, userAgent: ua, deviceScaleFactor: 1 });
    await ctx.addInitScript(mockTauri, STATES[state]);
    const page = await ctx.newPage();
    await page.goto(base);
    await page.waitForLoadState("networkidle");
    await page.evaluate(() => document.fonts.ready);
    await go(page);
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${out}/${name}-${os}.png` });
    await ctx.close();
  }
}
await browser.close();
console.log(`wrote ${SCREENS.length * 2} screenshots to ${out}/`);
