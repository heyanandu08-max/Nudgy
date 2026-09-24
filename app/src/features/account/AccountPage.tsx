import { useCallback, useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { errorCode, errorKey } from "../../lib/errors";
import { formatDay, type Access } from "../billing/access";
import { useSubscribe } from "../billing/SubscribeButton";

interface Me {
  id: number;
  email: string;
  plan: string;
  plan_name: string;
  paid: boolean;
  subscription_status: string | null;
  access: Access;
  team: { id: number; name: string; seats: number; owner: boolean } | null;
}

interface Team {
  name: string;
  seats: number;
  owner: boolean;
  members: { id: number; email: string; owner: boolean }[];
  invites: string[];
}

const btn = "rounded-btn border border-line-2 bg-white px-3 py-1.5 text-[13px] hover:border-ink-3";
const primary = "rounded-btn bg-ink px-4 py-2 text-[13px] font-medium text-white hover:bg-black disabled:opacity-40";
const input = "w-full rounded-btn border border-line-2 bg-transparent px-3 py-2 text-sm";

export function AccountPage() {
  const { t } = useTranslation();
  const [me, setMe] = useState<Me | null>(null);
  const [signedIn, setSignedIn] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!isTauri()) return;
    const state = await invoke<{ email: string } | null>("auth_state");
    setSignedIn(!!state);
    if (!state) return setMe(null);
    try {
      setMe(await invoke<Me>("account_me"));
    } catch (e) {
      if (errorCode(e) === "auth_expired" || errorCode(e) === "auth_required") setSignedIn(false);
    }
  }, []);

  useEffect(() => {
    void load();
    if (!isTauri()) return;
    const off = listen("auth-changed", () => void load());
    return () => void off.then((f) => f());
  }, [load]);

  const fail = (e: unknown) => setStatus(t(errorKey(errorCode(e)), { defaultValue: String(e) }));

  return (
    <div className="space-y-5">
      <h2 className="text-2xl font-semibold tracking-[-.01em]">{t("account.title")}</h2>
      {status && (
        <p role="status" className="rounded-btn border border-line bg-paper px-3 py-2 font-mono text-xs text-ink-2">
          {status}
        </p>
      )}
      {!signedIn ? <SignIn onStatus={setStatus} onError={fail} /> : me && <Signed me={me} onStatus={setStatus} onError={fail} />}
    </div>
  );
}

function SignIn({ onStatus, onError }: { onStatus: (s: string) => void; onError: (e: unknown) => void }) {
  const { t } = useTranslation();
  const [email, setEmail] = useState("");
  return (
    <section className="space-y-4 rounded-card border border-line-2 p-4">
      <h2 className="text-[15px] font-semibold">{t("account.signInTitle")}</h2>
      <p className="text-sm text-ink-3">{t("account.signInHelp")}</p>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          invoke("auth_send_magic", { email })
            .then(() => onStatus(t("account.linkSent")))
            .catch(onError);
        }}
      >
        <input className={input} type="email" required placeholder={t("account.email")} value={email} onChange={(e) => setEmail(e.target.value)} />
        <button type="submit" className={`${primary} shrink-0`}>
          {t("account.sendLink")}
        </button>
      </form>
      <div className="flex flex-wrap gap-2">
        <button type="button" className={btn} onClick={() => invoke("auth_open_provider", { provider: "google" }).catch(onError)}>
          {t("account.google")}
        </button>
        <button type="button" className={btn} onClick={() => invoke("auth_open_provider", { provider: "apple" }).catch(onError)}>
          {t("account.apple")}
        </button>
      </div>
    </section>
  );
}

function Signed({ me, onStatus, onError }: { me: Me; onStatus: (s: string) => void; onError: (e: unknown) => void }) {
  const { t, i18n } = useTranslation();
  const q = me.access.lessons;
  const subscribe = useSubscribe();

  return (
    <>
      <section className="space-y-3 rounded-card border border-line-2 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm">{t("account.signedInAs", { email: me.email })}</p>
          <button type="button" className={btn} onClick={() => invoke("auth_sign_out").catch(onError)}>
            {t("account.signOut")}
          </button>
        </div>
        {/* Nothing about plans or limits during the free window: paid or capped only. */}
        {me.paid && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm">
              {t("billing.plan")}: <strong>{me.plan_name}</strong>
            </p>
            <button type="button" className={btn} onClick={() => invoke("billing_portal").catch(onError)}>
              {t("account.manage")}
            </button>
          </div>
        )}
        {me.subscription_status === "past_due" && <p className="text-sm text-ink-2">{t("account.pastDue")}</p>}
        {!me.paid && me.access.capped && q && (
          <div className="space-y-3 border-t border-line pt-3">
            <p className="text-sm">
              {t("billing.plan")}: <strong>{t("billing.free")}</strong>
            </p>
            <p className="font-mono text-[11px] text-ink-3">{t("billing.capped", { left: q.left, count: q.limit, date: formatDay(q.resets_at, i18n.language) })}</p>
            <p className="text-[13px] text-ink-2">{t("billing.subscribeRemoves")}</p>
            <div className="flex flex-wrap items-center gap-2">{subscribe.button}</div>
            {subscribe.status}
          </div>
        )}
      </section>

      {me.team && <TeamSection onStatus={onStatus} onError={onError} />}
    </>
  );
}

function TeamSection({ onStatus, onError }: { onStatus: (s: string) => void; onError: (e: unknown) => void }) {
  const { t } = useTranslation();
  const [team, setTeam] = useState<Team | null>(null);
  const [library, setLibrary] = useState<{ slug: string; title: string; app: string }[]>([]);
  const [email, setEmail] = useState("");

  const load = useCallback(() => {
    invoke<Team>("team_get").then(setTeam).catch(onError);
    invoke<{ slug: string; title: string; app: string }[]>("team_walkthroughs").then(setLibrary).catch(() => setLibrary([]));
  }, [onError]);
  useEffect(load, [load]);

  if (!team) return null;
  return (
    <section className="space-y-3 rounded-card border border-line-2 p-4">
      <h2 className="text-[15px] font-semibold">
        {t("account.teamTitle")}: {team.name}
      </h2>
      <p className="text-xs text-ink-3">{t("account.seatsUsed", { used: team.members.length + team.invites.length, seats: team.seats })}</p>
      <ul className="space-y-1 text-sm">
        {team.members.map((m) => (
          <li key={m.id} className="flex items-center justify-between">
            <span>{m.email}</span>
            {team.owner && !m.owner && (
              <button type="button" className="text-xs text-accent underline" onClick={() => invoke("team_remove", { memberId: m.id }).then(load).catch(onError)}>
                {t("account.remove")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {team.invites.length > 0 && <p className="text-xs text-ink-3">{t("account.pending", { emails: team.invites.join(", ") })}</p>}
      {team.owner && (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            invoke("team_invite", { email })
              .then(() => {
                onStatus(t("account.invited", { email }));
                setEmail("");
                load();
              })
              .catch(onError);
          }}
        >
          <input className={input} type="email" required placeholder={t("account.invitePlaceholder")} value={email} onChange={(e) => setEmail(e.target.value)} />
          <button type="submit" className={`${btn} shrink-0`}>
            {t("account.invite")}
          </button>
        </form>
      )}
      <h3 className="pt-2 text-sm font-semibold">{t("account.library")}</h3>
      {library.length === 0 ? (
        <p className="text-sm text-ink-3">{t("account.noLibrary")}</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {library.map((w) => (
            <li key={w.slug} className="flex items-center justify-between gap-2">
              <span>
                {w.title} <span className="text-xs text-ink-3">{w.app}</span>
              </span>
              <button type="button" className={btn} onClick={() => invoke("walkthrough_fetch", { link: w.slug }).catch(onError)}>
                {t("account.import")}
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
