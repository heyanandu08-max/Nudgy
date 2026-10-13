import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AppBadge } from "../../components/ui";

export interface CourseLesson {
  id: string;
  title: string;
  done: boolean;
}

/** One course: progress, Start / Continue the next lesson, or pick any lesson. */
export function CourseCard({
  title,
  app,
  summary,
  lessons,
  busy,
  onStart,
}: {
  title: string;
  app: string;
  summary: string;
  lessons: CourseLesson[];
  busy: boolean;
  onStart: (lessonId: string) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const finished = lessons.filter((l) => l.done).length;
  const next = lessons.find((l) => !l.done);
  const pct = lessons.length ? Math.round((finished / lessons.length) * 100) : 0;
  return (
    <li className={`flex flex-col rounded-card border bg-white p-[18px] ${expanded ? "border-ink min-[900px]:col-span-2" : "border-line-2"}`}>
      <div className="flex items-start gap-3">
        <AppBadge app={app} />
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          {summary && <p className="mt-0.5 text-[12.5px] text-ink-2">{summary}</p>}
        </div>
      </div>
      <div className="mt-auto h-4 shrink-0" />
      <div className="h-1 overflow-hidden rounded bg-line" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={title}>
        <i className="block h-full bg-ink" style={{ width: `${pct}%` }} />
      </div>
      <div className="mt-3 flex items-center gap-2">
        <span className="font-mono text-[11px] text-ink-3">{t("courses.progress", { done: finished, total: lessons.length })}</span>
        <button type="button" className="ml-auto text-xs text-ink-2 hover:text-ink" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
          {expanded ? t("courses.hideLessons") : t("courses.showLessons")}
        </button>
        {next ? (
          <button
            type="button"
            disabled={busy}
            onClick={() => onStart(next.id)}
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
          {lessons.map((l, i) => (
            <li key={l.id} className="flex items-center gap-3 py-2.5">
              <span
                className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border font-mono text-[11px] ${l.done ? "border-ink bg-ink text-white" : "border-line-2 text-ink-3"}`}
                aria-hidden
              >
                {l.done ? "✓" : i + 1}
              </span>
              <span className="flex-1 text-[13px]">
                {l.title}
                <span className="sr-only">{l.done ? t("courses.done") : ""}</span>
              </span>
              <button type="button" disabled={busy} onClick={() => onStart(l.id)} className="text-xs text-ink-2 hover:text-ink disabled:opacity-40">
                {l.done ? t("courses.again") : t("courses.learn")}
              </button>
            </li>
          ))}
        </ol>
      )}
    </li>
  );
}
