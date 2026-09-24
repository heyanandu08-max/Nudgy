import type { ButtonHTMLAttributes, ReactNode } from "react";

export const isMac = typeof navigator !== "undefined" && /Mac/i.test(navigator.userAgent);

/** "Ctrl+Alt+Space" → keycaps, shown with Mac symbols on macOS. */
export function hotkeyParts(accelerator: string): string[] {
  const mac: Record<string, string> = { ctrl: "⌃", control: "⌃", alt: "⌥", option: "⌥", shift: "⇧", cmd: "⌘", command: "⌘", super: "⌘", commandorcontrol: "⌘" };
  const win: Record<string, string> = { ctrl: "Ctrl", control: "Ctrl", alt: "Alt", option: "Alt", shift: "Shift", cmd: "Win", command: "Win", super: "Win", commandorcontrol: "Ctrl" };
  return accelerator
    .split("+")
    .map((k) => k.trim())
    .filter(Boolean)
    .map((k) => (isMac ? mac : win)[k.toLowerCase()] ?? k);
}

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded-[5px] border border-b-2 border-line-2 bg-white px-1.5 py-0.5 font-mono text-[11px] text-ink">
      {children}
    </kbd>
  );
}

export function Hotkey({ accelerator }: { accelerator: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      {hotkeyParts(accelerator).map((k) => (
        <Kbd key={k}>{k}</Kbd>
      ))}
    </span>
  );
}

type Variant = "primary" | "secondary" | "ghost";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-ink text-white hover:bg-black disabled:opacity-40",
  secondary: "border border-line-2 bg-white text-ink hover:border-ink-3 disabled:opacity-40",
  ghost: "text-ink-2 hover:text-ink disabled:opacity-40",
};

export function Button({ variant = "secondary", className = "", ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      type="button"
      className={`inline-flex items-center gap-2 rounded-btn px-3.5 py-2 text-[13px] font-medium ${VARIANTS[variant]} ${className}`}
      {...rest}
    />
  );
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-5 w-9 shrink-0 rounded-full ${checked ? "bg-ink" : "bg-line-2"}`}
    >
      <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition-[left] duration-150 ${checked ? "left-[18px]" : "left-0.5"}`} />
    </button>
  );
}

/** Small mono pills to pick one value (Short / Detailed, S / M / L). */
export function Segmented<T extends string>({ value, options, onChange, label }: { value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex gap-1.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          onClick={() => onChange(o.value)}
          className={`rounded-full px-3 py-0.5 font-mono text-[11px] ${
            o.value === value ? "border border-ink bg-white text-ink" : "border border-line-2 bg-paper text-ink-2 hover:border-ink-3"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** Title-bar style section header: 15px/600 heading with an optional link on the right. */
export function SectionHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <div className="mb-3.5 flex items-baseline justify-between">
      <h2 className="text-[15px] font-semibold">{title}</h2>
      {action}
    </div>
  );
}

/** Two-letter mono app code used on chips and badges (XL, DR, CH…). */
export function appCode(app: string): string {
  const known: Record<string, string> = {
    excel: "XL",
    "microsoft excel": "XL",
    sheets: "SH",
    "google sheets": "SH",
    "davinci resolve": "DR",
    chrome: "CH",
    "google chrome": "CH",
    figma: "FG",
    notepad: "NP",
    textedit: "TE",
    word: "WD",
    "microsoft word": "WD",
    powerpoint: "PP",
    safari: "SF",
    finder: "FN",
    explorer: "EX",
    outlook: "OL",
    slack: "SL",
  };
  const key = app.trim().toLowerCase();
  if (known[key]) return known[key];
  const words = key.split(/\s+/).filter(Boolean);
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase();
  return (key.slice(0, 2) || "··").toUpperCase();
}

export function AppBadge({ app }: { app: string }) {
  return (
    <span className="grid h-[34px] w-[34px] shrink-0 place-items-center rounded-[9px] border border-line-2 bg-paper font-mono text-xs font-bold">
      {appCode(app)}
    </span>
  );
}

export function StatusDot({ tone }: { tone: "good" | "bad" | "wait" }) {
  const c = tone === "good" ? "bg-good shadow-[0_0_0_3px_rgba(31,157,85,.15)]" : tone === "bad" ? "bg-accent" : "bg-ink-3";
  return <span aria-hidden className={`inline-block h-2 w-2 rounded-full ${c}`} />;
}
