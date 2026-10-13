import { useCallback, useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import { SectionHeader, isMac } from "../../components/ui";
import { errorCode, errorKey } from "../../lib/errors";
import { fetchPacks, type Pack } from "../../lib/api";
import { useSettings } from "../../stores/settings";
import { outOfLessons, useAccess } from "../billing/access";
import { getTutor, hideMainWindow, playWalkthrough, subscribeTutor } from "../tutor/host";
import { CourseCard } from "./CourseCard";

const ACTIVE = ["planning", "waiting_app", "instructing", "waiting", "verifying"];

/** Mirrors GET /v1/team/courses. */
interface TeamCourse {
  id: number;
  title: string;
  summary: string;
  items: { slug: string; title: string; app: string; steps: number; done: boolean }[];
}

/** Courses: short, ordered lessons per app, plus the team's own onboarding courses. Each
 *  lesson is a normal verified lesson (or a team walkthrough played as one). */
export function CoursesPage({ onUpgrade }: { onUpgrade: () => void }) {
  const { t, i18n } = useTranslation();
  const { settings } = useSettings();
  const access = useAccess((s) => s.access);
  const [packs, setPacks] = useState<Pack[] | null>(null);
  const [team, setTeam] = useState<TeamCourse[]>([]);
  const [offline, setOffline] = useState(false);
  const [status, setStatus] = useState<string | null>(null);
  const [done, setDone] = useState<Set<string>>(new Set());
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
    if (!isTauri()) return;
    // Not on a team (or signed out): no team section.
    invoke<TeamCourse[]>("team_courses")
      .then(setTeam)
      .catch(() => setTeam([]));
    if (!packs?.length) return;
    const goals = packs.flatMap((p) => p.lessons.map((l) => l.goal));
    invoke<string[]>("completed_goals", { goals })
      .then((g) => setDone(new Set(g)))
      .catch(() => {});
  }, [packs]);

  useEffect(() => {
    refresh();
    if (!isTauri()) return;
    const offs = [listen("progress-changed", refresh), listen("data-wiped", refresh), listen("auth-changed", refresh), listen("tauri://focus", refresh)];
    return () => offs.forEach((p) => void p.then((f) => f()));
  }, [refresh]);

  const start = (goal: string) => {
    if (busy) return;
    if (outOfLessons(access)) return onUpgrade();
    hideMainWindow();
    void getTutor().start(goal);
  };

  // Team lessons are the team's walkthroughs: fetch the latest copy, then play it.
  const playTeam = async (slug: string) => {
    if (busy) return;
    setStatus(null);
    try {
      const w = await invoke<{ id: string }>("walkthrough_fetch", { link: slug });
      await playWalkthrough(w.id);
    } catch (e) {
      setStatus(t(errorKey(errorCode(e)), { defaultValue: String(e) }));
    }
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
      {status && <p className="font-mono text-xs text-ink-2">{status}</p>}

      {team.length > 0 && (
        <section>
          <SectionHeader title={t("courses.fromTeam")} />
          <ul className="grid gap-3.5 min-[900px]:grid-cols-2">
            {team.map((c) => (
              <CourseCard
                key={c.id}
                title={c.title}
                app={c.items[0]?.app || c.title}
                summary={c.summary}
                lessons={c.items.map((i) => ({ id: i.slug, title: i.title, done: i.done }))}
                busy={busy}
                onStart={(slug) => void playTeam(slug)}
              />
            ))}
          </ul>
        </section>
      )}

      <section>
        {team.length > 0 && <SectionHeader title={t("courses.fromNudgy")} />}
        <ul className="grid gap-3.5 min-[900px]:grid-cols-2">
          {packs?.map((p) => (
            <CourseCard
              key={p.id}
              title={p.title}
              app={p.app}
              summary={p.summary}
              lessons={p.lessons.map((l) => ({ id: l.goal, title: l.title, done: done.has(l.goal) }))}
              busy={busy}
              onStart={start}
            />
          ))}
        </ul>
      </section>
    </div>
  );
}
