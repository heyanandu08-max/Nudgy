import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../components/ui";
import type { Access, Interval } from "./access";
import { startSubscription } from "./subscribe";

/** Subscribe actions shared by the upgrade screen and Account: one button per price the
 * server offers (monthly first), plus a status line the caller places under its buttons. */
export function useSubscribe(offer: Access["offer"]) {
  const { t } = useTranslation();
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async (interval: Interval) => {
    setBusy(true);
    const r = await startSubscription(interval);
    setBusy(false);
    setNote(t(`billing.result.${r}`));
  };
  const intervals = (["month", "year"] as Interval[]).filter((i) => offer?.[i]);
  const buttons =
    intervals.length > 0 ? (
      intervals.map((i, n) => (
        <Button key={i} variant={n === 0 ? "primary" : "secondary"} disabled={busy} onClick={() => void go(i)}>
          {t(`billing.per.${i}`, { price: offer?.[i] })}
        </Button>
      ))
    ) : (
      <Button variant="primary" disabled>
        {t("billing.subscribe")}
      </Button>
    );
  const status = (note || intervals.length === 0) && (
    <p role="status" className="font-mono text-[11px] text-ink-2">
      {note ?? t("billing.result.not_connected")}
    </p>
  );
  return { buttons, status };
}
