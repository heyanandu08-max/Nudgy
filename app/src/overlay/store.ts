import { create } from "zustand";

export type CompanionMode = "idle" | "listening" | "thinking" | "talking" | "pointing";

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface PointTarget {
  rect: Rect;
  actionHint: string | null;
  highlight: boolean;
  /** Increments on every request so repeated identical targets still animate. */
  seq: number;
}

export interface Caption {
  transcript: string;
  speech: string;
  /** i18n key of an error or notice, shown instead of / below the speech. */
  noticeKey: string | null;
  noticeFallback: string | null;
  done: boolean;
}

const EMPTY_CAPTION: Caption = { transcript: "", speech: "", noticeKey: null, noticeFallback: null, done: false };

interface OverlayState {
  active: boolean; // cursor is on this overlay's monitor
  paused: boolean;
  mode: CompanionMode;
  target: PointTarget | null;
  caption: Caption | null;
  setActive: (active: boolean) => void;
  setPaused: (paused: boolean) => void;
  setMode: (mode: CompanionMode) => void;
  pointAt: (t: Omit<PointTarget, "seq">) => void;
  clearTarget: () => void;
  startCaption: (transcript: string) => void;
  appendSpeech: (delta: string) => void;
  setNotice: (key: string, fallback?: string | null) => void;
  finishCaption: () => void;
  clearCaption: () => void;
}

let seq = 0;

export const useOverlay = create<OverlayState>((set) => ({
  active: false,
  paused: false,
  mode: "idle",
  target: null,
  caption: null,
  setActive: (active) => set({ active }),
  setPaused: (paused) => set(paused ? { paused, caption: null, target: null, mode: "idle" } : { paused }),
  setMode: (mode) => set({ mode }),
  pointAt: (t) => set({ target: { ...t, seq: ++seq }, active: true }),
  clearTarget: () => set({ target: null }),
  startCaption: (transcript) => set({ caption: { ...EMPTY_CAPTION, transcript } }),
  appendSpeech: (delta) =>
    set((s) => ({ caption: { ...(s.caption ?? EMPTY_CAPTION), speech: (s.caption?.speech ?? "") + delta } })),
  setNotice: (noticeKey, noticeFallback = null) =>
    set((s) => ({ caption: { ...(s.caption ?? EMPTY_CAPTION), noticeKey, noticeFallback, done: true } })),
  finishCaption: () => set((s) => (s.caption ? { caption: { ...s.caption, done: true } } : {})),
  clearCaption: () => set({ caption: null }),
}));
