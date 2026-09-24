import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { useTranslation } from "react-i18next";
import { AppBadge, Hotkey, SectionHeader } from "../../components/ui";
import { useSettings } from "../../stores/settings";
import { getTutor, hideMainWindow, startReview, subscribeTutor } from "../tutor/host";
import type { TutorView } from "../tutor/types";
import { useDashboard, type RecentAsk, type RecentLesson, type SkillCard } from "./useDashboard";

interface Chip {
  app: string;
  code: string;
  label: string;
  goal: string;
}

const ACTIVE = ["planning", "waiting_app", "instructing", "waiting", "verifying"];

function useRelative() {
  const { t, i18n } = useTranslation();
  return (secs: number) => {
    const d = new Date(secs * 1000);
    const today = new Date();
    const days = Math.round((new Date(today.toDateString()).getTime() - new Date(d.toDateString()).getTime()) / 86_400_000);
    if (days <= 0) return t("home.today");
    if (days === 1) return t("home.yesterday");
    return new Intl.DateTimeFormat(i18n.language, { month: "short", day: "numeric" }).format(d);
  };
}

function Greeting() {
  const { t, i18n } = useTranslation();
  const now = new Date();
  const h = now.getHours();
  const part = h < 5 ? "night" : h < 12 ? "morning" : h < 18 ? "afternoon" : h < 22 ? "evening" : "night";
  const date = new Intl.DateTimeFormat(i18n.language, { weekday: "short", month: "short", day: "numeric" }).format(now);
  return (
    <p className="font-mono text-xs uppercase tracking-[.02em] text-ink-3">
      {date} · {t(`home.greeting.${part}`)}
    </p>
  );
}

export function HomePage({ onRecord }: { onRecord: () => void }) {
  const { t } = useTranslation();
  const { settings } = useSettings();
  const data = useDashboard();
  const [goal, setGoal] = useState("");
  const [busy, setBusy] = useState(false);
  const [allSkills, setAllSkills] = useState(false);
  const [allRecent, setAllRecent] = useState(false);
  useEffect(() => subscribeTutor((v: TutorView) => setBusy(ACTIVE.includes(v.phase))), []);

  const chips = t("home.chips", { returnObjects: true }) as unknown as Chip[];
  const askInput = useRef<HTMLInputElement>(null);
  const start = (g: string) => {
    const q = g.trim();
    if (busy) return;
    if (!q) {
      askInput.current?.focus();
      return;
    }
    setGoal("");
    hideMainWindow();
    void getTutor().start(q);
  };

  const skills = allSkills ? data.skills : data.skills.slice(0, 4);
  const recent = mergeRecent(data.recent, data.recent_asks);
  const shownRecent = allRecent ? recent : recent.slice(0, 3);

  return (
    <div className="px-14 pt-11 pb-10">
      <Greeting />
      <h1 className="mt-2.5 text-[40px] leading-[1.1] font-semibold tracking-[-.02em]">
        {t("home.headlineBefore")}
        <em className="font-serif font-medium">{t("home.headlineEm")}</em>
        {t("home.headlineAfter")}
      </h1>

      <form
        className="mt-6.5 flex items-center rounded-card border-[1.5px] border-ink bg-white py-1.5 pr-1.5 pl-[18px] shadow-[4px_4px_0_#0a0a0a]"
        onSubmit={(e) => {
          e.preventDefault();
          start(goal);
        }}
      >
        <input
          ref={askInput}
          aria-label={t("home.askLabel")}
          className="min-w-0 flex-1 border-0 bg-transparent text-base text-ink outline-none placeholder:text-ink-3"
          placeholder={t("home.askPlaceholder")}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          disabled={busy}
        />
        <button type="submit" disabled={busy} className="flex items-center gap-2 rounded-btn bg-ink px-[18px] py-3 text-sm font-medium text-white hover:bg-black disabled:opacity-40">
          {t("home.teachMe")} <span aria-hidden>→</span>
        </button>
      </form>

      <p className="mt-3.5 flex flex-wrap items-center gap-1.5 text-[12.5px] text-ink-2">
        {t("home.hintBefore")} <Hotkey accelerator={settings.hotkey} /> {t("home.hintAfter")}
      </p>

      <div className="mt-5.5 flex flex-wrap gap-2">
        {chips.map((c) => (
          <button
            key={c.goal}
            type="button"
            disabled={busy}
            onClick={() => start(c.goal)}
            className="rounded-full border border-dashed border-line-2 bg-paper px-3.5 py-[7px] text-[13px] hover:border-solid hover:border-ink-3 disabled:opacity-40"
          >
            <b className="mr-1.5 font-mono text-[11px] font-medium text-ink-3">{c.code}</b>
            {c.label}
          </button>
        ))}
      </div>

      <div className="mt-12 grid gap-7 min-[900px]:grid-cols-[1.35fr_1fr]">
        <section>
          <SectionHeader
            title={t("home.skills")}
            action={
              data.skills.length > 4 && (
                <button type="button" className="text-xs text-ink-2 hover:text-ink" onClick={() => setAllSkills(!allSkills)}>
                  {allSkills ? t("home.seeLess") : t("home.seeAll")}
                </button>
              )
            }
          />
          <div className="grid grid-cols-2 gap-3.5">
            {skills.map((s) => (
              <Skill key={s.id} skill={s} disabled={busy} />
            ))}
            {data.skills.length < 2 && (
              <div className="flex flex-col items-start justify-center rounded-card border border-dashed border-line-2 bg-paper p-[18px] text-ink-2">
                <span className="text-[26px] leading-none text-ink" aria-hidden>
                  +
                </span>
                <p className="mt-2.5 text-[13px] leading-[1.45]">{t("home.emptySkill")}</p>
              </div>
            )}
          </div>
          {data.weak_spots.length > 0 && (
            <div className="mt-6">
              <SectionHeader title={t("home.weak")} />
              <ul className="space-y-2">
                {data.weak_spots.slice(0, 3).map((w) => (
                  <li key={`${w.skill_id}:${w.instruction}`} className="text-[13px]">
                    {w.instruction}
                    <span className="block font-mono text-[11px] text-ink-3">{t("home.weakMeta", { skill: w.skill_name, hints: w.hints, skips: w.skips })}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>

        <section>
          <SectionHeader
            title={t("home.recent")}
            action={
              recent.length > 3 && (
                <button type="button" className="text-xs text-ink-2 hover:text-ink" onClick={() => setAllRecent(!allRecent)}>
                  {allRecent ? t("home.historyLess") : t("home.history")}
                </button>
              )
            }
          />
          {recent.length === 0 ? (
            <p className="rounded-card border border-dashed border-line-2 bg-paper p-4 text-[13px] text-ink-2">{t("home.noRecent")}</p>
          ) : (
            <ul className="overflow-hidden rounded-card border border-line-2 bg-white">
              {shownRecent.map((r) => (
                <RecentRow key={r.key} item={r} />
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="mt-7 flex items-center gap-5 rounded-card bg-ink px-6 py-5.5 text-white">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full border-2 border-white" aria-hidden>
          <i className="block h-3.5 w-3.5 rounded-full bg-accent" />
        </span>
        <div>
          <h3 className="text-[15px] font-semibold">{t("home.recordTitle")}</h3>
          <p className="mt-0.5 text-[12.5px] text-[#bdbbb4]">{t("home.recordBody")}</p>
        </div>
        <button type="button" onClick={onRecord} className="ml-auto rounded-btn bg-white px-4 py-2.5 text-[13px] font-medium whitespace-nowrap text-ink hover:bg-paper">
          {t("home.recordButton")}
        </button>
      </section>
    </div>
  );
}

function Skill({ skill, disabled }: { skill: SkillCard; disabled: boolean }) {
  const { t } = useTranslation();
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => void startReview(skill.id)}
      className="relative rounded-card border border-line-2 bg-white p-[18px] text-left hover:border-ink-3 disabled:opacity-60"
    >
      <p className="font-mono text-[11px] tracking-[.06em] text-ink-3 uppercase">{skill.app}</p>
      {skill.due && (
        <span className="absolute top-4 right-4 flex items-center gap-1.5 text-[11px] text-accent">
          <i className="block h-1.5 w-1.5 rounded-full bg-accent" aria-hidden />
          {t("home.reviewDue")}
        </span>
      )}
      <p className="mt-1.5 text-sm leading-[1.35] font-medium">{skill.name}</p>
      <p className="mt-3.5 font-serif text-[44px] leading-none font-medium tracking-[-.02em] italic">
        {skill.progress}
        <small className="text-lg text-ink-3">%</small>
      </p>
      <div className="mt-3 h-1 overflow-hidden rounded bg-line" role="progressbar" aria-valuenow={skill.progress} aria-valuemin={0} aria-valuemax={100}>
        <i className="block h-full bg-ink" style={{ width: `${skill.progress}%` }} />
      </div>
    </button>
  );
}

type RecentItem =
  | { key: string; kind: "lesson"; at: number; lesson: RecentLesson }
  | { key: string; kind: "ask"; at: number; ask: RecentAsk };

function mergeRecent(lessons: RecentLesson[], asks: RecentAsk[]): RecentItem[] {
  const items: RecentItem[] = [
    ...lessons.map((l) => ({ key: `l:${l.id}`, kind: "lesson" as const, at: l.started_at, lesson: l })),
    ...asks.map((a, i) => ({ key: `a:${a.at}:${i}`, kind: "ask" as const, at: a.at, ask: a })),
  ];
  return items.sort((a, b) => b.at - a.at).slice(0, 10);
}

function RecentRow({ item }: { item: RecentItem }) {
  const { t } = useTranslation();
  const when = useRelative();
  const base = "flex items-center gap-3.5 border-b border-line px-4 py-3.5 last:border-b-0";
  if (item.kind === "lesson") {
    const l = item.lesson;
    return (
      <li className={base}>
        <AppBadge app={l.app} />
        <div className="min-w-0">
          <p className="truncate text-[13.5px] font-medium">{l.title}</p>
          <p className="mt-0.5 font-mono text-[11px] text-ink-3">
            {t("home.lessonMeta", { passed: l.steps_passed, total: l.steps_total, hints: l.hints, when: when(l.started_at) })}
          </p>
        </div>
        <span className="ml-auto text-xs text-ink-2">
          {l.status === "completed" ? <span className="font-semibold text-good">✓</span> : t("home.stopped")}
        </span>
      </li>
    );
  }
  const a = item.ask;
  return (
    <li className={base}>
      <AppBadge app={a.app || "?"} />
      <div className="min-w-0">
        <p className="truncate text-[13.5px] font-medium first-letter:uppercase">{a.question}</p>
        <p className="mt-0.5 font-mono text-[11px] text-ink-3">{t("home.askMeta", { secs: Math.max(1, Math.round(a.duration_ms / 1000)), when: when(a.at) })}</p>
      </div>
      <span className="ml-auto text-xs text-ink-2">{t("home.qa")}</span>
    </li>
  );
}

/** Starts a walkthrough recording from anywhere (Home banner, Walkthroughs page). */
export async function startRecording(): Promise<void> {
  hideMainWindow();
  await invoke("recorder_start");
}
