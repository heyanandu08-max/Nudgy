import { useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import type { TutorCommand, TutorView } from "../features/tutor/types";

/**
 * Bottom-center lesson HUD. It's the only clickable part of the overlay, so it registers
 * its rectangle with Rust, which turns click-through off while the cursor is over it.
 */
export function LessonPanel({ view }: { view: TutorView }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const report = () => {
      const r = el.getBoundingClientRect();
      void invoke("set_interactive_regions", { rects: [{ x: r.x, y: r.y, w: r.width, h: r.height }] });
    };
    report();
    const ro = new ResizeObserver(report);
    ro.observe(el);
    return () => {
      ro.disconnect();
      void invoke("set_interactive_regions", { rects: [] });
    };
  }, []);

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
