import { useCallback, useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { AppBadge, isMac } from "../../components/ui";
import { fetchPacks, type Pack } from "../../lib/api";
import { useSettings } from "../../stores/settings";
import { outOfLessons, useAccess } from "../billing/access";
import { getTutor, hideMainWindow, subscribeTutor } from "../tutor/host";

const ACTIVE = ["planning", "waiting_app", "instructing", "waiting", "verifying"];

/** Courses: short, ordered lessons per app. Each lesson is a normal verified lesson; progress
 *  is what you've completed on this computer. */
export function CoursesPage({ onUpgrade }: { onUpgrade: () => void }) {
  const { t, i18n } = useTranslation();
  const { settings } = useSettings();
  const access = useAccess((s) => s.access);
  const [packs, setPacks] = useState<Pack[] | null>(null);
  const [offline, setOffline] = useState(false);
  const [done, setDone] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => subscribeTutor((v) => setBusy(ACTIVE.includes(v.phase))), []);

  useEffect(() => {
    fetchPacks(settings.backendUrl, isMac ? "mac" : "windows", i18n.language)
      .then((p) => {
        setPacks(p);
        setOffline(false);
      })
      .catch(() => {
        setPacks([]);
        setOffline(true);
      });
  }, [settings.backendUrl, i18n.language]);

  const refresh = useCallback(() => {
    if (!isTauri() || !packs?.length) return;
    const goals = packs.flatMap((p) => p.lessons.map((l) => l.goal));
    invoke<string[]>("completed_goals", { goals })
      .then((g) => setDone(new Set(g)))
      .catch(() => {});
  }, [packs]);

  useEffect(() => {
    refresh();
    if (!isTauri()) return;
    const offs = [listen("progress-changed", refresh), listen("data-wiped", refresh)];
    return () => offs.forEach((p) => void p.then((f) => f()));
  }, [refresh]);

  const start = (goal: string) => {
    if (busy) return;
    if (outOfLessons(access)) return onUpgrade();
    hideMainWindow();
    void getTutor().start(goal);
  };

  return (
    <div className="space-y-5 px-14 pt-11 pb-10">
      <header>
        <h1 className="text-[40px] leading-[1.1] font-semibold tracking-[-.02em]">
          {t("courses.titleBefore")}
          <em className="font-serif font-medium">{t("courses.titleEm")}</em>
        </h1>
        <p className="mt-2 text-[13px] text-ink-2">{t("courses.help")}</p>
      </header>
      {offline && <p className="font-mono text-xs text-ink-2">{t("errors.backend_unreachable")}</p>}

      <ul className="grid gap-3.5 min-[900px]:grid-cols-2">
        {packs?.map((p) => {
          const finished = p.lessons.filter((l) => done.has(l.goal)).length;
          const next = p.lessons.find((l) => !done.has(l.goal));
          const pct = Math.round((finished / p.lessons.length) * 100);
          const expanded = open === p.id;
          return (
            <li key={p.id} className={`flex flex-col rounded-card border bg-white p-[18px] ${expanded ? "border-ink min-[900px]:col-span-2" : "border-line-2"}`}>
              <div className="flex items-start gap-3">
                <AppBadge app={p.app} />
                <div className="min-w-0 flex-1">
                  <h2 className="text-[15px] font-semibold">{p.title}</h2>
                  <p className="mt-0.5 text-[12.5px] text-ink-2">{p.summary}</p>
                </div>
              </div>
              <div className="mt-auto h-4 shrink-0" />
              <div className="h-1 overflow-hidden rounded bg-line" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={p.title}>
                <i className="block h-full bg-ink" style={{ width: `${pct}%` }} />
              </div>
              <div className="mt-3 flex items-center gap-2">
                <span className="font-mono text-[11px] text-ink-3">{t("courses.progress", { done: finished, total: p.lessons.length })}</span>
                <button type="button" className="ml-auto text-xs text-ink-2 hover:text-ink" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : p.id)}>
                  {expanded ? t("courses.hideLessons") : t("courses.showLessons")}
                </button>
                {next ? (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => start(next.goal)}
                    className="rounded-btn bg-ink px-3.5 py-1.5 text-[13px] font-medium text-white hover:bg-black disabled:opacity-40"
                  >
                    {finished === 0 ? t("courses.start") : t("courses.continue")}
                  </button>
                ) : (
                  <span className="font-mono text-[11px] text-ink">{t("courses.complete")}</span>
                )}
              </div>
              {expanded && (
                <ol className="mt-4 divide-y divide-line border-t border-line">
                  {p.lessons.map((l, i) => {
                    const isDone = done.has(l.goal);
                    return (
                      <li key={l.id} className="flex items-center gap-3 py-2.5">
                        <span
                          className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border font-mono text-[11px] ${isDone ? "border-ink bg-ink text-white" : "border-line-2 text-ink-3"}`}
                          aria-hidden
                        >
                          {isDone ? "✓" : i + 1}
                        </span>
                        <span className="flex-1 text-[13px]">
                          {l.title}
                          <span className="sr-only">{isDone ? t("courses.done") : ""}</span>
                        </span>
                        <button type="button" disabled={busy} onClick={() => start(l.goal)} className="text-xs text-ink-2 hover:text-ink disabled:opacity-40">
                          {isDone ? t("courses.again") : t("courses.learn")}
                        </button>
                      </li>
                    );
                  })}
                </ol>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
