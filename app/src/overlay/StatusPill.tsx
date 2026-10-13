import { useTranslation } from "react-i18next";

export type PillState = { kind: "speaking" } | { kind: "your_turn" } | { kind: "open_app"; app: string } | { kind: "planning" } | null;

/** Bottom-center pill: what's happening right now, in one line. */
export function StatusPill({ state }: { state: PillState }) {
  const { t } = useTranslation();
  if (!state) return null;
  return (
    <div className="pill" role="status">
      {state.kind === "speaking" && (
        <>
          <span className="wave" aria-hidden>
            {[6, 12, 16, 10, 14].map((h, i) => (
              <i key={i} style={{ height: h, animationDelay: `${i * 90}ms` }} />
            ))}
          </span>
          {t("pill.speaking")} · <kbd>Esc</kbd> {t("pill.toStop")}
        </>
      )}
      {state.kind === "your_turn" && (
        <>
          <span className="pill__dot" aria-hidden />
          {t("pill.yourTurn")}
        </>
      )}
      {state.kind === "open_app" && t("pill.openApp", { app: state.app })}
      {state.kind === "planning" && (
        <>
          {t("pill.planning")}
          <span className="state-label__dots" aria-hidden>
            <i>·</i>
            <i>·</i>
            <i>·</i>
          </span>
        </>
      )}
    </div>
  );
}
