import { useCallback, useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { Button } from "../../components/ui";
import { SettingsHeading } from "../settings/parts";
import { formatDay, type Access } from "./access";
import { useSubscribe } from "./SubscribeButton";

/** Mirrors GET /v1/plans. */
interface PlansInfo {
  signed_in: boolean;
  current: string | null;
  free_lessons_per_month: number;
  unlimited_until: string | null;
  pro_offer: Access["offer"];
  subscription: { status: string | null; paid_until: string | null } | null;
}

/** Settings → Plan: Free and Pro side by side, what each includes, and how to subscribe. */
export function PlansSection({ onSignIn }: { onSignIn: () => void }) {
  const { t, i18n } = useTranslation();
  const [info, setInfo] = useState<PlansInfo | null>(null);
  const [offline, setOffline] = useState(false);

  const load = useCallback(async () => {
    if (!isTauri()) return;
    try {
      setInfo(await invoke<PlansInfo>("plans_get"));
      setOffline(false);
    } catch {
      setOffline(true);
    }
  }, []);

  useEffect(() => {
    void load();
    if (!isTauri()) return;
    const offs = [listen("auth-changed", () => void load()), listen("tauri://focus", () => void load())];
    return () => offs.forEach((p) => void p.then((f) => f()));
  }, [load]);

  const subscribe = useSubscribe(info?.pro_offer ?? null);
  const isPro = info?.current === "pro" || info?.current === "team";
  const sub = info?.subscription;
  const day = (iso: string) => formatDay(iso, i18n.language, true);

  return (
    <>
      <SettingsHeading before={t("plans.title")} em={t("plans.titleEm")} sub={t("plans.sub")} />
      {offline && <p className="mt-4 font-mono text-xs text-ink-2">{t("errors.backend_unreachable")}</p>}
      {info?.unlimited_until && (
        <p className="mt-4 font-mono text-[11px] text-ink-3">{t("plans.unlimitedUntil", { date: day(info.unlimited_until) })}</p>
      )}

      <div className="mt-5.5 grid gap-4 min-[900px]:grid-cols-2">
        <section className="rounded-card border border-line-2 bg-white p-5">
          <div className="flex items-baseline justify-between">
            <h3 className="text-[15px] font-semibold">{t("plans.free")}</h3>
            {info?.signed_in && !isPro && <span className="font-mono text-[11px] text-ink-3">{t("plans.current")}</span>}
          </div>
          <p className="mt-2 text-[28px] leading-none font-semibold tracking-[-.02em]">{t("plans.freePrice")}</p>
          <ul className="mt-4 space-y-1.5 text-[13px] text-ink-2">
            <li>{t("plans.f.questions")}</li>
            <li>{t("plans.f.lessons", { count: info?.free_lessons_per_month ?? 5 })}</li>
            <li>{t("plans.f.reviews")}</li>
            <li>{t("plans.f.walkthroughs")}</li>
          </ul>
        </section>

        <section className="rounded-card border-[1.5px] border-ink bg-white p-5 shadow-[4px_4px_0_#0a0a0a]">
          <div className="flex items-baseline justify-between">
            <h3 className="text-[15px] font-semibold">{t("plans.pro")}</h3>
            {isPro && <span className="font-mono text-[11px] text-ink-3">{t("plans.current")}</span>}
          </div>
          <p className="mt-2 text-[28px] leading-none font-semibold tracking-[-.02em]">
            {info?.pro_offer?.month ?? "—"}
            <span className="ml-1 text-[13px] font-normal text-ink-2">{t("plans.perMonth")}</span>
          </p>
          {info?.pro_offer?.year && <p className="mt-1 font-mono text-[11px] text-ink-3">{t("plans.orYear", { price: info.pro_offer.year })}</p>}
          <p className="mt-1 font-mono text-[11px] text-ink-3">{t("plans.taxNote")}</p>
          <ul className="mt-4 space-y-1.5 text-[13px] text-ink-2">
            <li>{t("plans.p.everything")}</li>
            <li>{t("plans.p.lessons")}</li>
            <li>{t("plans.p.cancel")}</li>
          </ul>

          <div className="mt-5">
            {isPro ? (
              <div className="space-y-2">
                {sub?.status === "canceled" && sub.paid_until && (
                  <p className="font-mono text-[11px] text-ink-2">{t("plans.endsOn", { date: day(sub.paid_until) })}</p>
                )}
                {sub?.status === "past_due" && <p className="font-mono text-[11px] text-ink-2">{t("account.pastDue")}</p>}
                <Button onClick={() => void invoke("billing_portal").catch(() => {})}>{t("account.manage")}</Button>
              </div>
            ) : info && !info.signed_in ? (
              <Button variant="primary" onClick={onSignIn}>
                {t("plans.signInFirst")}
              </Button>
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">{subscribe.buttons}</div>
                {subscribe.status && <div className="mt-2">{subscribe.status}</div>}
              </>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
