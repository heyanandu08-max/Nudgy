import { invoke, isTauri } from "@tauri-apps/api/core";

export type ResponseLength = "brief" | "detailed";

/** Mirrors `Settings` in src-tauri/src/settings.rs (serde camelCase). */
export interface Settings {
  backendUrl: string;
  voiceEnabled: boolean;
  voiceId: string | null;
  hotkey: string;
  responseLength: ResponseLength;
  language: string;
  paused: boolean;
}

export const DEFAULT_SETTINGS: Settings = {
  backendUrl: "http://127.0.0.1:8787",
  voiceEnabled: true,
  voiceId: null,
  hotkey: "Ctrl+Alt+Space",
  responseLength: "brief",
  language: "en",
  paused: false,
};

const BROWSER_KEY = "nudgy.settings";

/** Outside Tauri (plain `npm run dev`) settings fall back to localStorage. */
export async function loadSettings(): Promise<Settings> {
  if (isTauri()) return invoke<Settings>("get_settings");
  try {
    const raw = localStorage.getItem(BROWSER_KEY);
    return raw ? { ...DEFAULT_SETTINGS, ...JSON.parse(raw) } : DEFAULT_SETTINGS;
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export async function saveSettings(settings: Settings): Promise<Settings> {
  if (isTauri()) return invoke<Settings>("save_settings", { settings });
  localStorage.setItem(BROWSER_KEY, JSON.stringify(settings));
  return settings;
}
