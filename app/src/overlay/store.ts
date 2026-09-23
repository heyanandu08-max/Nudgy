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

interface OverlayState {
  active: boolean; // cursor is on this overlay's monitor
  mode: CompanionMode;
  target: PointTarget | null;
  setActive: (active: boolean) => void;
  setMode: (mode: CompanionMode) => void;
  pointAt: (t: Omit<PointTarget, "seq">) => void;
  clearTarget: () => void;
}

let seq = 0;

export const useOverlay = create<OverlayState>((set) => ({
  active: false,
  mode: "idle",
  target: null,
  setActive: (active) => set({ active }),
  setMode: (mode) => set({ mode }),
  pointAt: (t) => set({ target: { ...t, seq: ++seq }, active: true }),
  clearTarget: () => set({ target: null }),
}));
