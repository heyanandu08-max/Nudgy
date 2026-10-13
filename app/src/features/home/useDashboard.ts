import { useCallback, useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export interface SkillCard {
  id: string;
  app: string;
  name: string;
  progress: number;
  lessons: number;
  due_at: number | null;
  due: boolean;
}
export interface RecentLesson {
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
export interface RecentAsk {
  question: string;
  app: string;
  duration_ms: number;
  at: number;
}
export interface WeakSpot {
  skill_id: string;
  skill_name: string;
  instruction: string;
  hints: number;
  skips: number;
}
export interface DashboardData {
  skills: SkillCard[];
  recent: RecentLesson[];
  weak_spots: WeakSpot[];
  recent_asks: RecentAsk[];
}

const EMPTY: DashboardData = { skills: [], recent: [], weak_spots: [], recent_asks: [] };

export function useDashboard(): DashboardData {
  const [data, setData] = useState<DashboardData>(EMPTY);
  const refresh = useCallback(() => {
    if (isTauri()) invoke<DashboardData>("dashboard").then(setData).catch(() => setData(EMPTY));
  }, []);
  useEffect(() => {
    refresh();
    if (!isTauri()) return;
    const off = listen("progress-changed", refresh);
    const offWipe = listen("data-wiped", refresh);
    return () => {
      void off.then((f) => f());
      void offWipe.then((f) => f());
    };
  }, [refresh]);
  return data;
}
