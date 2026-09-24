import { invoke, isTauri } from "@tauri-apps/api/core";
import { create } from "zustand";

/** Mirrors `access.state()` in backend/app/services/access.py. The server decides all of it. */
export interface LessonQuota {
  used: number;
  limit: number;
  left: number;
  resets_at: string;
}

export interface Access {
  /** Set only in the last 30 days before free access ends. */
  notice: { free_until: string; lessons_per_month: number } | null;
  /** This account has a monthly lesson cap right now. */
  capped: boolean;
  lessons: LessonQuota | null;
  /** Price labels per billing interval, sent only to capped users when billing is set up. */
  offer: Partial<Record<Interval, string>> | null;
}

export type Interval = "month" | "year";

export const NO_ACCESS_INFO: Access = { notice: null, capped: false, lessons: null, offer: null };

/** Show the "lessons left" note when this many (or fewer) are left. */
export const NEAR_CAP = 1;

interface AccessState {
  access: Access;
  refresh: () => Promise<void>;
}

/** Offline or unknown means "show nothing": the server still enforces the cap. */
export const useAccess = create<AccessState>((set) => ({
  access: NO_ACCESS_INFO,
  refresh: async () => {
    if (!isTauri()) return;
    try {
      set({ access: await invoke<Access>("access_get") });
    } catch {
      set({ access: NO_ACCESS_INFO });
    }
  },
}));

export function outOfLessons(a: Access): boolean {
  return a.capped && a.lessons !== null && a.lessons.left === 0;
}

/** Dates from the server are UTC calendar dates; format them in UTC so every OS and
 * time zone shows the same day. Monthly reset dates are always under a month away, so they
 * skip the year; the (further away) free-access date keeps it. */
export function formatDay(iso: string, language: string, withYear = false): string {
  return new Intl.DateTimeFormat(language, { month: "short", day: "numeric", ...(withYear && { year: "numeric" }), timeZone: "UTC" }).format(new Date(iso));
}
