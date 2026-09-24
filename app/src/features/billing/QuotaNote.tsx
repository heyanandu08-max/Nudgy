import { useTranslation } from "react-i18next";
import { formatDay, NEAR_CAP, type LessonQuota } from "./access";

/** Calm mono line where lessons start, only when the monthly allowance is nearly used. */
export function QuotaNote({ quota, during = false, className = "" }: { quota: LessonQuota | null; during?: boolean; className?: string }) {
  const { t, i18n } = useTranslation();
  if (!quota || quota.left > NEAR_CAP) return null;
  const date = formatDay(quota.resets_at, i18n.language);
  const key = quota.left > 0 ? "billing.left" : during ? "billing.lastOne" : "billing.noneLeft";
  return <p className={`font-mono text-[11px] text-ink-3 ${className}`}>{t(key, { count: quota.left, date })}</p>;
}
