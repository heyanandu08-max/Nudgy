import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getTutor, subscribeTutor } from "./host";
import type { TutorView } from "./types";

export function StartLesson() {
  const { t } = useTranslation();
  const [goal, setGoal] = useState("");
  const [view, setView] = useState<TutorView | null>(null);
  useEffect(() => subscribeTutor(setView), []);
  const suggestions = t("tutor.suggestions", { returnObjects: true }) as string[];
  const running = view && ["planning", "instructing", "waiting", "verifying"].includes(view.phase);

  const start = (g: string) => {
    if (!g.trim()) return;
    void getTutor().start(g.trim());
    setGoal("");
  };

  return (
    <section className="space-y-3 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
      <h2 className="text-lg font-semibold">{t("tutor.startTitle")}</h2>
      <p className="text-sm text-slate-500">{t("tutor.startHelp")}</p>
      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          start(goal);
        }}
      >
        <input
          className="w-full rounded-md border border-slate-300 bg-transparent px-3 py-2 text-sm dark:border-slate-600"
          placeholder={t("tutor.goalPlaceholder")}
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          disabled={!!running}
        />
        <button
          type="submit"
          disabled={!!running || !goal.trim()}
          className="shrink-0 rounded-md bg-nudgy-500 px-4 py-2 text-sm font-medium text-white hover:bg-nudgy-600 disabled:opacity-50"
        >
          {t("tutor.start")}
        </button>
      </form>
      <div className="flex flex-wrap gap-2">
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            disabled={!!running}
            onClick={() => start(s)}
            className="rounded-full border border-slate-300 px-3 py-1 text-xs hover:border-nudgy-500 disabled:opacity-50 dark:border-slate-600"
          >
            {s}
          </button>
        ))}
      </div>
      <p className="text-xs text-slate-500">{t("tutor.orSay")}</p>
    </section>
  );
}
