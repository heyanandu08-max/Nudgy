import { useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { useInteractiveRegion } from "./interactive";

/** Top-center bar while a walkthrough is being recorded. Its clicks are not recorded. */
export function RecorderBar({ steps }: { steps: number }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  useInteractiveRegion("recorder-bar", ref);
  return (
    <div ref={ref} className="recorder-bar" role="status">
      <span className="recorder-bar__dot" aria-hidden />
      <span className="recorder-bar__label">
        {t("walkthroughs.recording.label")} · {t("walkthroughs.recording.steps", { count: steps })}
      </span>
      <span className="recorder-bar__hint">{t("walkthroughs.recording.hint")}</span>
      <button type="button" onClick={() => void invoke("open_note_box")}>
        {t("walkthroughs.recording.note")}
      </button>
      <button type="button" className="primary" onClick={() => void emit("recorder-stop")}>
        {t("walkthroughs.recording.stop")}
      </button>
      <button type="button" onClick={() => void invoke("recorder_cancel")}>
        {t("walkthroughs.recording.cancel")}
      </button>
    </div>
  );
}
