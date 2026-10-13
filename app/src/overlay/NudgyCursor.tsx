import type { CursorColor, CursorSize } from "../lib/settings";

/** The tilted Nudgy arrow (from the logo's knocked-over "y"). */
export const CURSOR_PATH = "M2 2 L2 21 L7 16.5 L10.5 24.5 L13.8 23 L10.3 15.2 L17 15.2 Z";

const FILL: Record<CursorColor, { fill: string; stroke: string }> = {
  black: { fill: "#0A0A0A", stroke: "#FFFFFF" },
  white: { fill: "#FFFFFF", stroke: "#0A0A0A" },
  red: { fill: "#FF4A1C", stroke: "#FFFFFF" },
  blue: { fill: "#2563EB", stroke: "#FFFFFF" },
};

export const CURSOR_WIDTH: Record<CursorSize, number> = { s: 20, m: 26, l: 34 };

export function NudgyCursor({ color, size, className = "" }: { color: CursorColor; size: CursorSize; className?: string }) {
  const w = CURSOR_WIDTH[size];
  const c = FILL[color];
  return (
    <svg className={`nudgy-cursor ${className}`} width={w} height={(w * 28) / 20} viewBox="0 0 20 28" aria-hidden>
      <path d={CURSOR_PATH} fill={c.fill} stroke={c.stroke} strokeWidth={1.8} strokeLinejoin="round" />
    </svg>
  );
}

export type CursorLabel = "listening" | "thinking" | "talking" | "watching" | "checking" | "nice" | null;

/** Tiny mono pill next to the cursor saying what Nudgy is doing. */
export function StateLabel({ label, text }: { label: CursorLabel; text: string }) {
  if (!label) return null;
  return (
    <span className={`state-label ${label === "nice" ? "state-label--ok" : ""}`}>
      {label === "listening" && <i className="state-label__rec" aria-hidden />}
      {text}
      {(label === "thinking" || label === "checking") && (
        <span className="state-label__dots" aria-hidden>
          <i>·</i>
          <i>·</i>
          <i>·</i>
        </span>
      )}
    </span>
  );
}
