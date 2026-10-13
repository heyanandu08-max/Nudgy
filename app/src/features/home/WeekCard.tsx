import { useState } from "react";
import { useTranslation } from "react-i18next";
import { weekId, type WeekProgress } from "./useWeek";

const SEEN_KEY = "nudgy.weekRecapSeen";

function seenRecap(): string | null {
  try {
    return localStorage.getItem(SEEN_KEY);
  } catch {
    return null;
  }
}

/** This week at a glance: the streak, which days you learned, and what you got done. On the
 *  first visit of a new week it leads with a recap of last week. */
export function WeekCard({ week }: { week: WeekProgress }) {
  const { t, i18n } = useTranslation();
  const thisWeek = weekId();
  const [seen, setSeen] = useState(seenRecap);
  const last = week.last_week;
  const showRecap = seen !== thisWeek && last.lessons + last.questions > 0;
  const dismiss = () => {
    try {
      localStorage.setItem(SEEN_KEY, thisWeek);
    } catch {
      // per-viewer convenience only
    }
    setSeen(thisWeek);
  };

  // Day initials for the last 7 days, today last.
  const dayName = new Intl.DateTimeFormat(i18n.language, { weekday: "narrow" });
  const labels = week.days.map((_, i) => dayName.format(new Date(Date.now() - (6 - i) * 86_400_000)));
  const w = week.this_week;

  return (
    <section className="mt-9 rounded-card border border-line-2 bg-white p-5">
      {showRecap && (
        <div className="mb-4 flex items-start gap-3 border-b border-line-2 pb-4">
          <p className="text-[13px] leading-[1.5]">
            <b className="font-semibold">{t("week.recapTitle")}</b> {t("week.recap", {
              lessons: t("week.n.lessons", { count: last.lessons }),
              steps: t("week.n.steps", { count: last.steps }),
              questions: t("week.n.questions", { count: last.questions }),
            })}
          </p>
          <button type="button" onClick={dismiss} className="ml-auto shrink-0 text-xs text-ink-2 hover:text-ink">
            {t("week.gotIt")}
          </button>
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
        <div>
          <p className="text-[28px] leading-none font-semibold tracking-[-.02em]">{week.streak > 0 ? t("week.streak", { count: week.streak }) : t("week.noStreak")}</p>
          <p className="mt-1.5 font-mono text-[11px] text-ink-3">
            {week.streak === 0
              ? t("week.startToday")
              : week.learned_today
                ? t("week.best", { count: week.best_streak })
                : t("week.keepItGoing")}
          </p>
        </div>
        <ol className="flex gap-1.5" aria-label={t("week.daysLabel")}>
          {week.days.map((on, i) => (
            <li key={i} className="flex flex-col items-center gap-1">
              <span className={`h-6 w-6 rounded-full border ${on ? "border-ink bg-ink" : "border-line-2 bg-paper"} ${i === 6 ? "ring-2 ring-accent/40 ring-offset-1" : ""}`} />
              <span className="font-mono text-[10px] text-ink-3">{labels[i]}</span>
              <span className="sr-only">{on ? t("week.learned") : t("week.notLearned")}</span>
            </li>
          ))}
        </ol>
        <dl className="ml-auto grid grid-cols-3 gap-6 text-right">
          {(["lessons", "steps", "questions"] as const).map((k) => (
            <div key={k}>
              <dd className="text-[20px] leading-none font-semibold">{w[k]}</dd>
              <dt className="mt-1 font-mono text-[11px] text-ink-3">{t(`week.${k}`)}</dt>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
}
