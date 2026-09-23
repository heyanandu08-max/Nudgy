import { invoke } from "@tauri-apps/api/core";
import { emit, listen } from "@tauri-apps/api/event";
import i18n from "../../i18n";
import { Tutor } from "./tutor";
import type { LessonPlan, TutorCommand, TutorView } from "./types";

/**
 * The single Tutor instance, hosted by the (usually hidden) main window. Wires the pure
 * state machine to Tauri: commands for capture/verify/speak/point/store, events for input
 * activity, spoken intents and the overlay's lesson buttons.
 */
let tutor: Tutor | null = null;
const listeners = new Set<(v: TutorView) => void>();

export function subscribeTutor(fn: (v: TutorView) => void): () => void {
  listeners.add(fn);
  if (tutor) fn(tutor.view);
  return () => listeners.delete(fn);
}

export function getTutor(): Tutor {
  if (tutor) return tutor;
  const t = (key: string, opts?: Record<string, unknown>) => i18n.t(key, opts);
  tutor = new Tutor({
    plan: (goal) => invoke<LessonPlan>("lesson_plan", { goal }),
    beginStep: () => invoke("lesson_begin_step"),
    point: (step) =>
      invoke<boolean>("lesson_point", {
        target: step.target,
        description: step.instruction,
        hint: step.action_hint,
      }),
    say: (text) => invoke("speak", { text }),
    verify: (step, attempt) => invoke("lesson_verify", { step, attempt }),
    recordStart: (plan, goal) => invoke<string>("lesson_record_start", { plan, goal }),
    recordStep: (lessonId, result) => invoke("lesson_record_step", { lessonId, result }),
    recordFinish: (lessonId, status) => invoke("lesson_record_finish", { lessonId, status }),
    setContext: (context) => invoke("lesson_set_context", { context }),
    watchActivity: (on) => invoke("activity_watch", { on }),
    publish: (view) => {
      void emit("lesson-state", view);
      listeners.forEach((fn) => fn(view));
    },
    now: () => Date.now(),
    schedule: (fn, ms) => {
      const id = setTimeout(fn, ms);
      return () => clearTimeout(id);
    },
    text: {
      get planning() {
        return t("tutor.say.planning");
      },
      get planFailed() {
        return t("tutor.say.planFailed");
      },
      get firstStep() {
        return t("tutor.say.firstStep");
      },
      get stuck() {
        return t("tutor.say.stuck");
      },
      get verifyFailed() {
        return t("tutor.say.verifyFailed");
      },
      get stopped() {
        return t("tutor.say.stopped");
      },
      finished: (title) => t("tutor.say.finished", { title }),
      get praise() {
        return i18n.t("tutor.say.praise", { returnObjects: true }) as unknown as string[];
      },
    },
  });

  void listen("user-activity", () => tutor?.onActivity());
  void listen<TutorCommand>("lesson-command", (e) => void tutor?.command(e.payload));
  void listen<{ intent: string; lesson_goal: string | null }>("ask-intent", (e) => {
    const { intent, lesson_goal } = e.payload;
    if (intent === "start_lesson" && lesson_goal) void tutor?.start(lesson_goal);
    else if (intent === "stop_lesson") void tutor?.command("stop");
    else if (intent === "done" || intent === "skip" || intent === "show_me") void tutor?.command(intent);
  });
  // An overlay that (re)loads asks for the current state.
  void listen("lesson-state-request", () => tutor && void emit("lesson-state", tutor.view));
  return tutor;
}
