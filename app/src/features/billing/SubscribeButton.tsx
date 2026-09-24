import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "../../components/ui";
import { startSubscription } from "./subscribe";

/** Subscribe action shared by the upgrade screen and Account: the button, plus a status
 * line the caller places under its row of buttons. */
export function useSubscribe() {
  const { t } = useTranslation();
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const go = async () => {
    setBusy(true);
    const r = await startSubscription();
    setBusy(false);
    setNote(r.ok ? null : t("billing.notConnected"));
  };
  const button = (
    <Button variant="primary" disabled={busy} onClick={() => void go()}>
      {t("billing.subscribe")}
    </Button>
  );
  const status = note && (
    <p role="status" className="font-mono text-[11px] text-ink-2">
      {note}
    </p>
  );
  return { button, status };
}
