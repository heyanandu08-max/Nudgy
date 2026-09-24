import { useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { emit } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { useInteractiveRegion } from "./interactive";

export interface Nudge {
  skill_id: string;
  skill_name: string;
  due_count: number;
}

/** Auto-dismiss (and snooze) if ignored. */
const IGNORE_MS = 25_000;

/** A small, polite card in the bottom-right corner offering a one-minute review. */
export function ReviewNudge({ nudge, onClose }: { nudge: Nudge; onClose: () => void }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  useInteractiveRegion("review-nudge", ref);
  const later = () => {
    void invoke("review_snooze");
    onClose();
  };
  const start = () => {
    void emit("review-start", nudge.skill_id);
    onClose();
  };
  useEffect(() => {
    const id = setTimeout(later, IGNORE_MS);
    return () => clearTimeout(id);
  }, [nudge.skill_id]);

  return (
    <div ref={ref} className="nudge" role="dialog" aria-label={t("review.nudgeTitle")}>
      <p className="nudge__title">
        <i aria-hidden />
        {t("review.nudgeTitle")}
      </p>
      <p>{t("review.nudgeBody", { skill: nudge.skill_name.toLowerCase() })}</p>
      {nudge.due_count > 1 && <p className="nudge__more">{t("review.nudgeMore", { count: nudge.due_count })}</p>}
      <div className="lesson__acts">
        <button type="button" className="b1" onClick={start}>
          {t("review.start")}
        </button>
        <button type="button" className="b2" onClick={later}>
          {t("review.later")}
        </button>
      </div>
    </div>
  );
}
