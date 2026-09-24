import { useRef } from "react";
import { emit } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import type { TutorCommand, TutorView } from "../features/tutor/types";
import { QuotaNote } from "../features/billing/QuotaNote";
import { useInteractiveRegion } from "./interactive";

/** The lesson card (top-right of the learner's screen), with a hard offset shadow. */
export function LessonCard({ view }: { view: TutorView }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  useInteractiveRegion("lesson-card", ref);
  const send = (cmd: TutorCommand) => void emit("lesson-command", cmd);

  const running = view.phase === "instructing" || view.phase === "waiting" || view.phase === "verifying";
  const busy = view.phase === "verifying" || view.phase === "planning";
  let heading = view.instruction;
  let body = view.hint || (view.app ? t("tutor.card.waiting", { app: view.app }) : t("tutor.card.waitingNoApp"));
  if (view.phase === "planning") [heading, body] = [view.title || t("tutor.card.planning"), t("tutor.card.planning")];
  if (view.phase === "waiting_app") [heading, body] = [view.title, t("tutor.card.openApp", { app: view.app })];
  if (view.phase === "verifying") body = t("tutor.card.checking");
  if (view.phase === "finished") [heading, body] = [view.title, t("tutor.card.finished")];
  if (view.phase === "failed") [heading, body] = [t("tutor.card.failed"), ""];

  return (
    <div ref={ref} className="lesson" role="region" aria-label={view.title}>
      <div className="lesson__top">
        <span>
          {t("tutor.card.lesson")}
          {view.app && ` · ${view.app}`}
        </span>
        {view.stepCount > 0 && <span>{t("tutor.card.of", { current: view.stepIndex + 1, total: view.stepCount })}</span>}
      </div>
      <h4>{heading}</h4>
      {body && <p>{body}</p>}
      {view.stepCount > 0 && (
        <div className="lesson__steps" aria-hidden>
          {Array.from({ length: view.stepCount }, (_, i) => (
            <i key={i} className={i < view.stepIndex || view.phase === "finished" ? "d" : i === view.stepIndex ? "c" : ""} />
          ))}
        </div>
      )}
      {view.stepIndex === 0 && view.phase !== "finished" && <QuotaNote quota={view.quota} during className="mt-3" />}
      {running && (
        <div className="lesson__acts">
          <button type="button" className="b1" disabled={busy} onClick={() => send("show_me")}>
            {t("tutor.card.showMe")}
          </button>
          <button type="button" className="b2" disabled={busy} onClick={() => send("skip")}>
            {t("tutor.card.skip")}
          </button>
          <span className="lesson__links">
            <button type="button" disabled={busy} onClick={() => send("done")}>
              {t("tutor.card.done")}
            </button>
            ·
            <button type="button" onClick={() => send("stop")}>
              {t("tutor.card.stop")}
            </button>
          </span>
        </div>
      )}
      {(view.phase === "waiting_app" || view.phase === "planning") && (
        <div className="lesson__acts">
          <span className="lesson__links">
            <button type="button" onClick={() => send("stop")}>
              {t("tutor.card.stop")}
            </button>
          </span>
        </div>
      )}
    </div>
  );
}
