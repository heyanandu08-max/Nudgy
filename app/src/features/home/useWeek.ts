import { useCallback, useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export interface Totals {
  lessons: number;
  steps: number;
  questions: number;
  skills: number;
}

/** Mirrors store::WeekProgress. */
export interface WeekProgress {
  this_week: Totals;
  last_week: Totals;
  streak: number;
  best_streak: number;
  learned_today: boolean;
  /** Oldest first, today last. */
  days: boolean[];
}

export function useWeek(): WeekProgress | null {
  const [week, setWeek] = useState<WeekProgress | null>(null);
  const refresh = useCallback(() => {
    if (!isTauri()) return;
    const offsetMinutes = -new Date().getTimezoneOffset();
    invoke<WeekProgress>("week_progress", { offsetMinutes })
      .then(setWeek)
      .catch(() => setWeek(null));
  }, []);
  useEffect(() => {
    refresh();
    if (!isTauri()) return;
    const offs = [listen("progress-changed", refresh), listen("data-wiped", refresh), listen("tauri://focus", refresh)];
    return () => offs.forEach((p) => void p.then((f) => f()));
  }, [refresh]);
  return week;
}

/** Monday-based week id, e.g. "2026-10-12", for "show the recap once a week". */
export function weekId(d = new Date()): string {
  const monday = new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7));
  const p = (n: number) => String(n).padStart(2, "0");
  return `${monday.getFullYear()}-${p(monday.getMonth() + 1)}-${p(monday.getDate())}`;
}
