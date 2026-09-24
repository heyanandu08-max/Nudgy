import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../components/ui";
import { formatDay, useAccess } from "./access";
import { useSubscribe } from "./SubscribeButton";

/** Shown when this month's free lessons are used up. Explains, gives the reset date, and
 * can always be dismissed; everything except new lessons keeps working. */
export function UpgradePrompt({ onClose }: { onClose: () => void }) {
  const { t, i18n } = useTranslation();
  const { access, refresh } = useAccess();
  useEffect(() => void refresh(), [refresh]);
  const q = access.lessons;
  const subscribe = useSubscribe(access.offer);

  return (
    <div className="flex min-h-full items-center justify-center px-14 py-10">
      <div className="w-full max-w-[520px]">
        <p className="font-mono text-[11px] text-ink-3 uppercase">{t("billing.meta")}</p>
        <h1 className="mt-2 text-[30px] leading-[1.15] font-semibold tracking-[-.02em]">
          {t("billing.titleBefore")}
          <em className="font-serif font-medium">{t("billing.titleEm")}</em>
          {t("billing.titleAfter")}
        </h1>
        {q && <p className="mt-4 text-[15px] leading-relaxed text-ink-2">{t("billing.resets", { count: q.limit, date: formatDay(q.resets_at, i18n.language) })}</p>}
        <p className="mt-3 text-[15px] leading-relaxed text-ink-2">{t("billing.stillWorks")}</p>
        <p className="mt-3 text-[15px] leading-relaxed text-ink-2">{t("billing.subscribeRemoves")}</p>
        <div className="mt-8 flex flex-wrap items-center gap-2">
          {subscribe.buttons}
          <Button onClick={onClose}>{t("billing.notNow")}</Button>
        </div>
        {subscribe.status && <div className="mt-3">{subscribe.status}</div>}
      </div>
    </div>
  );
}
