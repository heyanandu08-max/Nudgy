import { invoke, isTauri } from "@tauri-apps/api/core";

/** Forwards uncaught errors and console errors/warnings to the Rust log. */
export function installUiLog(): void {
  if (!isTauri()) return;
  const send = (level: string, parts: unknown[]) => {
    const message = parts.map((p) => (p instanceof Error ? `${p.message}\n${p.stack}` : String(p))).join(" ");
    void invoke("ui_log", { level, message }).catch(() => {});
  };
  const origError = console.error.bind(console);
  const origWarn = console.warn.bind(console);
  console.error = (...a: unknown[]) => (send("error", a), origError(...a));
  console.warn = (...a: unknown[]) => (send("warn", a), origWarn(...a));
  window.addEventListener("error", (e) => send("error", [e.error ?? e.message]));
  window.addEventListener("unhandledrejection", (e) => send("error", ["unhandled rejection:", e.reason]));
}
