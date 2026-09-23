import type { CompanionMode } from "./store";

/**
 * Nudgy's body: a little orange blob with eyes. All motion is CSS (see overlay.css) so the
 * companion stays cheap to render; `mode` only swaps classes.
 */
export function Companion({ mode }: { mode: CompanionMode }) {
  return (
    <div className={`companion companion--${mode}`} aria-hidden>
      {mode === "listening" && <span className="companion__listen-ring" />}
      <svg viewBox="0 0 48 48" width="36" height="36">
        <defs>
          <radialGradient id="nudgy-body" cx="40%" cy="35%" r="70%">
            <stop offset="0%" stopColor="#fdba74" />
            <stop offset="100%" stopColor="#ea580c" />
          </radialGradient>
        </defs>
        <path
          className="companion__body"
          d="M24 4c11 0 20 8 20 19 0 12-9 21-20 21S4 35 4 23C4 12 13 4 24 4z"
          fill="url(#nudgy-body)"
        />
        <g className="companion__eyes">
          <ellipse cx="17" cy="21" rx="4" ry="5" fill="#fff" />
          <ellipse cx="31" cy="21" rx="4" ry="5" fill="#fff" />
          <circle className="companion__pupil" cx="18" cy="22" r="2.2" fill="#1e293b" />
          <circle className="companion__pupil" cx="32" cy="22" r="2.2" fill="#1e293b" />
        </g>
        <path className="companion__mouth" d="M19 31q5 4 10 0" stroke="#7c2d12" strokeWidth="2" fill="none" strokeLinecap="round" />
      </svg>
      {mode === "thinking" && (
        <span className="companion__dots">
          <i />
          <i />
          <i />
        </span>
      )}
    </div>
  );
}
