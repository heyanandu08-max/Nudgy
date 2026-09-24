import { useCallback, useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { errorCode, errorKey } from "../../lib/errors";

type Kind = "asks" | "lessons" | "lesson_calls";

interface Me {
  id: number;
  email: string;
  plan: string;
  plan_name: string;
  subscription_status: string | null;
  usage: Record<Kind, number>;
  limits: Record<Kind, number | null>;
  resets_at: string;
  team: { id: number; name: string; seats: number; owner: boolean } | null;
}

interface Team {
  name: string;
  seats: number;
  owner: boolean;
  members: { id: number; email: string; owner: boolean }[];
  invites: string[];
}

const btn = "rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:border-nudgy-500 dark:border-slate-600";
const primary = "rounded-md bg-nudgy-500 px-4 py-2 text-sm font-medium text-white hover:bg-nudgy-600 disabled:opacity-50";
const input = "w-full rounded-md border border-slate-300 bg-transparent px-3 py-2 text-sm dark:border-slate-600";

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
    <div className="mx-auto max-w-2xl space-y-6 p-6">
      <h1 className="text-xl font-semibold">{t("account.title")}</h1>
      {status && (
        <p role="status" className="rounded-md bg-nudgy-50 px-3 py-2 text-sm text-nudgy-600">
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
    <section className="space-y-4 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
      <h2 className="text-lg font-semibold">{t("account.signInTitle")}</h2>
      <p className="text-sm text-slate-500">{t("account.signInHelp")}</p>
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

function Meter({ label, used, limit }: { label: string; used: number; limit: number | null }) {
  const { t } = useTranslation();
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  return (
    <div>
      <div className="flex justify-between text-sm">
        <span>{label}</span>
        <span className="text-slate-500">{limit === null ? t("account.unlimited", { used }) : t("account.usedOf", { used, limit })}</span>
      </div>
      {limit !== null && (
        <div className="mt-1 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
          <div className={`h-full rounded-full ${pct >= 100 ? "bg-red-500" : "bg-nudgy-500"}`} style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}

function Signed({ me, onStatus, onError }: { me: Me; onStatus: (s: string) => void; onError: (e: unknown) => void }) {
  const { t, i18n } = useTranslation();
  const [seats, setSeats] = useState(3);
  const [student, setStudent] = useState(false);
  const checkout = (plan: "pro" | "team") =>
    invoke("billing_checkout", { plan, seats: plan === "team" ? seats : 1, student })
      .then(() => onStatus(t("account.checkoutOpened")))
      .catch(onError);
  const resets = new Intl.DateTimeFormat(i18n.language, { dateStyle: "medium" }).format(new Date(me.resets_at));

  return (
    <>
      <section className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm">{t("account.signedInAs", { email: me.email })}</p>
          <button type="button" className={btn} onClick={() => invoke("auth_sign_out").catch(onError)}>
            {t("account.signOut")}
          </button>
        </div>
        <p className="text-sm">
          {t("account.plan")}: <strong>{me.plan_name}</strong>
        </p>
        {me.subscription_status === "past_due" && <p className="text-sm text-red-600">{t("account.pastDue")}</p>}
        <h3 className="pt-2 text-sm font-semibold">{t("account.usageTitle")}</h3>
        {(["asks", "lessons", "lesson_calls"] as Kind[]).map((k) => (
          <Meter key={k} label={t(`account.usage.${k}`)} used={me.usage[k]} limit={me.limits[k]} />
        ))}
        <p className="text-xs text-slate-500">{t("account.resets", { date: resets })}</p>
        {me.plan !== "free" && (
          <button type="button" className={btn} onClick={() => invoke("billing_portal").catch(onError)}>
            {t("account.manage")}
          </button>
        )}
      </section>

      {me.plan === "free" && (
        <section className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
          <h2 className="text-lg font-semibold">{t("account.upgradeTitle")}</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
              <p className="font-medium">{t("account.pro")}</p>
              <p className="text-sm text-slate-500">{t("account.proBlurb")}</p>
              <button type="button" className={primary} onClick={() => void checkout("pro")}>
                {t("account.choose", { plan: t("account.pro") })}
              </button>
            </div>
            <div className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
              <p className="font-medium">{t("account.team")}</p>
              <p className="text-sm text-slate-500">{t("account.teamBlurb")}</p>
              <label className="flex items-center gap-2 text-sm">
                {t("account.seats")}
                <input className="w-20 rounded-md border border-slate-300 bg-transparent px-2 py-1 dark:border-slate-600" type="number" min={1} max={500} value={seats} onChange={(e) => setSeats(Math.max(1, Number(e.target.value) || 1))} />
              </label>
              <button type="button" className={primary} onClick={() => void checkout("team")}>
                {t("account.choose", { plan: t("account.team") })}
              </button>
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={student} onChange={(e) => setStudent(e.target.checked)} />
            {t("account.student")}
          </label>
        </section>
      )}

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
    <section className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
      <h2 className="text-lg font-semibold">
        {t("account.teamTitle")}: {team.name}
      </h2>
      <p className="text-xs text-slate-500">{t("account.seatsUsed", { used: team.members.length + team.invites.length, seats: team.seats })}</p>
      <ul className="space-y-1 text-sm">
        {team.members.map((m) => (
          <li key={m.id} className="flex items-center justify-between">
            <span>{m.email}</span>
            {team.owner && !m.owner && (
              <button type="button" className="text-xs text-red-600 underline" onClick={() => invoke("team_remove", { memberId: m.id }).then(load).catch(onError)}>
                {t("account.remove")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {team.invites.length > 0 && <p className="text-xs text-slate-500">{t("account.pending", { emails: team.invites.join(", ") })}</p>}
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
        <p className="text-sm text-slate-500">{t("account.noLibrary")}</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {library.map((w) => (
            <li key={w.slug} className="flex items-center justify-between gap-2">
              <span>
                {w.title} <span className="text-xs text-slate-500">{w.app}</span>
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
