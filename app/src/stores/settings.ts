import { create } from "zustand";
import { DEFAULT_SETTINGS, loadSettings, saveSettings, type Settings } from "../lib/settings";

interface SettingsState {
  settings: Settings;
  loaded: boolean;
  load: () => Promise<void>;
  save: (next: Settings) => Promise<void>;
  /** Apply a change made elsewhere (e.g. tray "Pause") without re-saving. */
  replace: (next: Settings) => void;
}

export const useSettings = create<SettingsState>((set) => ({
  settings: DEFAULT_SETTINGS,
  loaded: false,
  load: async () => set({ settings: await loadSettings(), loaded: true }),
  save: async (next) => set({ settings: await saveSettings(next) }),
  replace: (next) => set({ settings: next }),
}));
