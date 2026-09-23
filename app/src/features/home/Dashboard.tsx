import { useCallback, useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { startReview, subscribeTutor } from "../tutor/host";

interface SkillCard {
  id: string;
  app: string;
  name: string;
  progress: number;
  lessons: number;
  due_at: number | null;
  due: boolean;
}
interface RecentLesson {
  id: string;
  title: string;
  app: string;
  skill_id: string;
  status: "completed" | "abandoned" | "active";
  started_at: number;
  steps_passed: number;
  steps_total: number;
  hints: number;
}
interface WeakSpot {
  skill_id: string;
  skill_name: string;
  instruction: string;
  hints: number;
  skips: number;
}
interface DashboardData {
  skills: SkillCard[];
  recent: RecentLesson[];
  weak_spots: WeakSpot[];
}

const EMPTY: DashboardData = { skills: [], recent: [], weak_spots: [] };

export function Dashboard() {
  const { t, i18n } = useTranslation();
  const [data, setData] = useState<DashboardData>(EMPTY);
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(() => {
    if (!isTauri()) return;
    invoke<DashboardData>("dashboard").then(setData).catch(() => setData(EMPTY));
  }, []);

  useEffect(() => {
    refresh();
    if (!isTauri()) return;
    const off = listen("progress-changed", refresh);
    const unsub = subscribeTutor((v) => setBusy(["planning", "instructing", "waiting", "verifying"].includes(v.phase)));
    return () => {
      off.then((f) => f());
      unsub();
    };
  }, [refresh]);

  const date = (secs: number) =>
    new Intl.DateTimeFormat(i18n.language, { month: "short", day: "numeric" }).format(new Date(secs * 1000));

  return (
    <div className="space-y-6">
      <section>
        <h2 className="mb-3 text-lg font-semibold">{t("dashboard.skills")}</h2>
        {data.skills.length === 0 ? (
          <p className="text-sm text-slate-500">{t("dashboard.noSkills")}</p>
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {data.skills.map((s) => (
              <li key={s.id} className="rounded-xl border border-slate-200 p-4 dark:border-slate-700">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="text-xs uppercase tracking-wide text-slate-500">{s.app}</p>
                    <p className="font-medium">{s.name}</p>
                  </div>
                  {s.due && (
                    <span className="rounded-full bg-nudgy-50 px-2 py-0.5 text-xs font-medium text-nudgy-600">
                      {t("dashboard.due")}
                    </span>
                  )}
                </div>
                <div
                  className="mt-3 h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700"
                  role="progressbar"
                  aria-valuenow={s.progress}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <div className="h-full rounded-full bg-emerald-500" style={{ width: `${s.progress}%` }} />
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  {t("dashboard.progress", { value: s.progress })} · {t("dashboard.lessons", { count: s.lessons })}
                  {!s.due && s.due_at ? ` · ${t("dashboard.dueOn", { date: date(s.due_at) })}` : ""}
                </p>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void startReview(s.id)}
                  className="mt-3 rounded-md border border-slate-300 px-3 py-1 text-sm hover:border-nudgy-500 disabled:opacity-50 dark:border-slate-600"
                >
                  {s.due ? t("dashboard.review") : t("dashboard.practice")}
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <div className="grid gap-6 sm:grid-cols-2">
        <section>
          <h2 className="mb-2 text-lg font-semibold">{t("dashboard.recent")}</h2>
          {data.recent.length === 0 ? (
            <p className="text-sm text-slate-500">{t("dashboard.noRecent")}</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {data.recent.map((l) => (
                <li key={l.id}>
                  <p className="font-medium">{l.title}</p>
                  <p className="text-xs text-slate-500">
                    {l.app} · {t(`dashboard.status.${l.status}`)} ·{" "}
                    {t("dashboard.stepsHints", { passed: l.steps_passed, total: l.steps_total, hints: l.hints })} ·{" "}
                    {date(l.started_at)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h2 className="mb-2 text-lg font-semibold">{t("dashboard.weak")}</h2>
          {data.weak_spots.length === 0 ? (
            <p className="text-sm text-slate-500">{t("dashboard.noWeak")}</p>
          ) : (
            <ul className="space-y-2 text-sm">
              {data.weak_spots.map((w) => (
                <li key={`${w.skill_id}:${w.instruction}`}>
                  <p>{w.instruction}</p>
                  <p className="text-xs text-slate-500">
                    {w.skill_name} · {t("dashboard.weakDetail", { hints: w.hints, skips: w.skips })}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}
