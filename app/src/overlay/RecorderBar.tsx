import { useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { useInteractiveRegion } from "./interactive";

/** Top-center pill while a walkthrough is being recorded. Its own clicks are not recorded. */
export function RecorderBar({ steps }: { steps: number }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  useInteractiveRegion("recorder-bar", ref);
  return (
    <div ref={ref} className="recbar" role="status">
      <span className="recbar__dot" aria-hidden />
      <b>{t("walkthroughs.recording.label")}</b>
      <span className="recbar__meta">{t("walkthroughs.recording.steps", { count: steps })}</span>
      <span className="recbar__hint">{t("walkthroughs.recording.hint")}</span>
      <button type="button" onClick={() => void invoke("open_note_box")}>
        {t("walkthroughs.recording.note")}
      </button>
      <button type="button" className="b1" onClick={() => void emit("recorder-stop")}>
        {t("walkthroughs.recording.stop")}
      </button>
      <button type="button" onClick={() => void invoke("recorder_cancel")}>
        {t("walkthroughs.recording.cancel")}
      </button>
    </div>
  );
}
