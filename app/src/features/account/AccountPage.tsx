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
  const subscribe = useSubscribe(me.access.offer);

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
            <div className="flex flex-wrap items-center gap-2">{subscribe.buttons}</div>
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
      <p className="text-xs text-ink-3">{team.owner ? t("report.ownerNote") : t("report.memberNote")}</p>
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
      {team.owner && library.length > 0 && <CourseBuilder library={library} onError={onError} />}
      {team.owner && library.length > 0 && <OnboardingReport />}
    </section>
  );
}

interface CourseRow {
  id: number;
  title: string;
  items: { slug: string }[];
}

/** Owner: put team walkthroughs in order as an onboarding course (shown under Courses). */
function CourseBuilder({ library, onError }: { library: { slug: string; title: string; app: string }[]; onError: (e: unknown) => void }) {
  const { t } = useTranslation();
  const [courses, setCourses] = useState<CourseRow[]>([]);
  const [title, setTitle] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const load = useCallback(() => {
    invoke<CourseRow[]>("team_courses")
      .then(setCourses)
      .catch(() => setCourses([]));
  }, []);
  useEffect(load, [load]);

  const toggle = (slug: string) => setPicked((p) => (p.includes(slug) ? p.filter((s) => s !== slug) : [...p, slug]));
  const save = () =>
    invoke("team_course_save", { id: null, title: title.trim(), summary: "", slugs: picked })
      .then(() => {
        setTitle("");
        setPicked([]);
        load();
      })
      .catch(onError);

  return (
    <div className="space-y-2 pt-2">
      <h3 className="text-sm font-semibold">{t("teamCourses.title")}</h3>
      <p className="text-xs text-ink-3">{t("teamCourses.help")}</p>
      {courses.length > 0 && (
        <ul className="space-y-1 text-sm">
          {courses.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-2">
              <span>
                {c.title} <span className="font-mono text-[11px] text-ink-3">{t("teamCourses.count", { count: c.items.length })}</span>
              </span>
              <button type="button" className="text-xs text-accent underline" onClick={() => invoke("team_course_delete", { id: c.id }).then(load).catch(onError)}>
                {t("account.remove")}
              </button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="space-y-2 rounded-card border border-line-2 bg-white p-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (title.trim() && picked.length) void save();
        }}
      >
        <input className={input} required placeholder={t("teamCourses.namePlaceholder")} aria-label={t("teamCourses.name")} value={title} onChange={(e) => setTitle(e.target.value)} />
        <ul className="space-y-1">
          {library.map((w) => {
            const n = picked.indexOf(w.slug);
            return (
              <li key={w.slug}>
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={n >= 0} onChange={() => toggle(w.slug)} />
                  <span className="w-5 font-mono text-[11px] text-ink-3">{n >= 0 ? n + 1 : ""}</span>
                  {w.title} <span className="text-xs text-ink-3">{w.app}</span>
                </label>
              </li>
            );
          })}
        </ul>
        <p className="font-mono text-[11px] text-ink-3">{t("teamCourses.order")}</p>
        <button type="submit" className={btn} disabled={!title.trim() || picked.length === 0}>
          {t("teamCourses.create")}
        </button>
      </form>
    </div>
  );
}

interface ReportRow {
  slug: string;
  title: string;
  app: string;
  members: { email: string; status: "completed" | "abandoned" | "not_started"; last_at: string | null }[];
  stuck: { step: number; instruction: string; count: number }[];
}

/** Owner view: per team walkthrough, who finished it and the steps people needed help with. */
function OnboardingReport() {
  const { t } = useTranslation();
  const [rows, setRows] = useState<ReportRow[] | null>(null);
  useEffect(() => {
    invoke<ReportRow[]>("team_report")
      .then(setRows)
      .catch(() => setRows([]));
  }, []);
  if (!rows) return null;
  return (
    <div className="space-y-3 pt-2">
      <h3 className="text-sm font-semibold">{t("report.title")}</h3>
      {rows.map((w) => {
        const done = w.members.filter((m) => m.status === "completed").length;
        return (
          <div key={w.slug} className="rounded-card border border-line-2 bg-white p-3.5">
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-[13px] font-medium">{w.title}</span>
              <span className="font-mono text-[11px] text-ink-3">{t("report.finished", { done, total: w.members.length })}</span>
            </div>
            <ul className="mt-2 space-y-1">
              {w.members.map((m) => (
                <li key={m.email} className="flex items-center justify-between gap-2 text-xs">
                  <span className="truncate">{m.email}</span>
                  <span className={`font-mono text-[11px] ${m.status === "completed" ? "text-ink" : m.status === "abandoned" ? "text-accent" : "text-ink-3"}`}>
                    {t(`report.status.${m.status}`)}
                  </span>
                </li>
              ))}
            </ul>
            {w.stuck.length > 0 && (
              <div className="mt-3 border-t border-line pt-2">
                <p className="font-mono text-[11px] text-ink-3">{t("report.stuckTitle")}</p>
                <ul className="mt-1 space-y-1">
                  {w.stuck.map((s) => (
                    <li key={s.step} className="text-xs">
                      <span className="font-mono text-ink-3">{t("report.step", { n: s.step + 1 })}</span> {s.instruction}{" "}
                      <span className="font-mono text-[11px] text-ink-3">{t("report.people", { count: s.count })}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
