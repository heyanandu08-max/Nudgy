import { useRef } from "react";
import { emit } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import type { TutorCommand, TutorView } from "../features/tutor/types";
import { useInteractiveRegion } from "./interactive";

/**
 * Bottom-center lesson HUD. Registers itself as a clickable region of the overlay.
 */
export function LessonPanel({ view }: { view: TutorView }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);

  useInteractiveRegion("lesson-panel", ref);

  const send = (cmd: TutorCommand) => void emit("lesson-command", cmd);
  const busy = view.phase === "planning" || view.phase === "verifying";
  const status =
    view.phase === "planning"
      ? t("tutor.panel.planning")
      : view.phase === "verifying"
        ? t("tutor.panel.checking")
        : view.phase === "finished"
          ? t("tutor.panel.finished")
          : view.phase === "failed"
            ? t("tutor.panel.failed")
            : t("tutor.panel.step", { current: view.stepIndex + 1, total: view.stepCount });
  const running = view.phase === "instructing" || view.phase === "waiting" || view.phase === "verifying";

  return (
    <div ref={ref} className="lesson-panel" role="region" aria-label={view.title}>
      <div className="lesson-panel__head">
        <span className="lesson-panel__title">{view.title || "Nudgy"}</span>
        <span className="lesson-panel__status">{status}</span>
      </div>
      {view.stepCount > 0 && (
        <div className="lesson-panel__progress" aria-hidden>
          {Array.from({ length: view.stepCount }, (_, i) => (
            <i key={i} className={i < view.stepIndex ? "done" : i === view.stepIndex ? "current" : ""} />
          ))}
        </div>
      )}
      {running && <p className="lesson-panel__instruction">{view.instruction}</p>}
      {running && (
        <div className="lesson-panel__actions">
          <button type="button" className="primary" disabled={busy} onClick={() => send("done")}>
            {t("tutor.panel.done")}
          </button>
          <button type="button" disabled={busy} onClick={() => send("show_me")}>
            {t("tutor.panel.showMe")}
          </button>
          <button type="button" disabled={busy} onClick={() => send("skip")}>
            {t("tutor.panel.skip")}
          </button>
          <button type="button" onClick={() => send("stop")}>
            {t("tutor.panel.stop")}
          </button>
        </div>
      )}
    </div>
  );
}
