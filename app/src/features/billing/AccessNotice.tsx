import { useTranslation } from "react-i18next";
import { formatDay, useAccess } from "./access";

/** The one heads-up before free access ends: a meta line in Settings, last 30 days only. */
export function AccessNotice() {
  const { t, i18n } = useTranslation();
  const notice = useAccess((s) => s.access.notice);
  if (!notice) return null;
  return (
    <p className="font-mono text-[11px] leading-relaxed text-ink-3">
      {t("billing.notice", { date: formatDay(notice.free_until, i18n.language, true), count: notice.lessons_per_month })}
    </p>
  );
}
