export interface StepTarget {
  role: string;
  name: string;
}

export interface LessonStep {
  instruction: string;
  target: StepTarget | null;
  action_hint: string | null;
  success_check: string;
  why: string;
}

export interface LessonPlan {
  title: string;
  app: string;
  skill: string;
  skill_name: string;
  steps: LessonStep[];
}

export interface VerifyResult {
  passed: boolean;
  hint: string;
}

/** Mirrors `StepResult` in src-tauri/src/store/mod.rs. */
export interface StepResult {
  index: number;
  instruction: string;
  status: "passed" | "skipped";
  attempts: number;
  hints_used: number;
  duration_ms: number;
  mistakes: string[];
}

export type TutorPhase = "idle" | "planning" | "waiting_app" | "instructing" | "waiting" | "verifying" | "finished" | "failed";

export type TutorCommand = "done" | "skip" | "show_me" | "stop";

/** What the overlay's lesson panel renders. */
export interface TutorView {
  phase: TutorPhase;
  title: string;
  stepIndex: number;
  stepCount: number;
  instruction: string;
  hintLevel: number;
  /** App the lesson happens in (for the lesson card). */
  app: string;
  /** Last hint said for this step, shown under the instruction. */
  hint: string;
}
