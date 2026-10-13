import { useEffect, useRef } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useTranslation } from "react-i18next";
import { hotkeyParts } from "../components/ui";
import { useInteractiveRegion } from "./interactive";

export interface Tip {
  id: string;
  /** Accelerator for this OS, e.g. "Ctrl+B" or "Super+B". */
  keys: string;
  app: string;
}

const IGNORE_MS = 15_000;

/** Shortcut coach: one quiet card, once per command. */
export function ShortcutTip({ tip, onClose }: { tip: Tip; onClose: () => void }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLDivElement>(null);
  useInteractiveRegion("shortcut-tip", ref);
  useEffect(() => {
    const id = setTimeout(onClose, IGNORE_MS);
    return () => clearTimeout(id);
  }, [tip.id, onClose]);

  const stop = () => {
    void invoke("coach_off");
    onClose();
  };

  return (
    <div ref={ref} className="nudge" role="status" aria-label={t("coach.title")}>
      <p className="nudge__title">
        <i aria-hidden />
        {t("coach.title")}
      </p>
      <p>
        {t("coach.body", { action: t(`coach.actions.${tip.id}`) })}{" "}
        {hotkeyParts(tip.keys).map((k) => (
          <kbd key={k} className="tip-key">
            {k}
          </kbd>
        ))}
      </p>
      <div className="lesson__acts">
        <button type="button" className="b1" onClick={onClose}>
          {t("coach.gotIt")}
        </button>
        <button type="button" className="b2" onClick={stop}>
          {t("coach.stop")}
        </button>
      </div>
    </div>
  );
}
