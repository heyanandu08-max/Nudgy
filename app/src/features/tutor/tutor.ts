import type { LessonPlan, LessonStep, StepResult, TutorCommand, TutorPhase, TutorView, VerifyResult } from "./types";

/** After the learner's last click/keypress, wait this long before checking the step. */
export const QUIET_MS = 1500;
export const MAX_HINT = 3;
/** Silent automatic checks allowed before an automatic failure produces a hint. */
const AUTO_FAILS_BEFORE_HINT = 2;

export interface TutorDeps {
  plan(goal: string): Promise<LessonPlan>;
  beginStep(): Promise<void>;
  point(step: LessonStep): Promise<boolean>;
  say(text: string): Promise<void>;
  verify(step: LessonStep, attempt: number): Promise<VerifyResult>;
  recordStart(plan: LessonPlan, goal: string): Promise<string>;
  recordStep(lessonId: string, result: StepResult): Promise<void>;
  recordFinish(lessonId: string, status: "completed" | "abandoned"): Promise<void>;
  setContext(ctx: { title: string; step_index: number; step_count: number; instruction: string } | null): Promise<void>;
  watchActivity(on: boolean): Promise<void>;
  publish(view: TutorView): void;
  now(): number;
  schedule(fn: () => void, ms: number): () => void;
  /** Localized phrases (i18n lives in the UI layer). */
  text: TutorText;
}

export interface TutorText {
  planning: string;
  quizIntro: string;
  planFailed: string;
  firstStep: string;
  stuck: string;
  verifyFailed: string;
  stopped: string;
  finished: (title: string) => string;
  praise: string[];
}

interface StepState {
  index: number;
  startedAt: number;
  attempts: number;
  hintsUsed: number;
  hintLevel: number;
  autoFails: number;
  mistakes: string[];
}

/**
 * Tutor mode state machine: instruct (speak + point) → wait for the learner to act →
 * verify → praise and continue, or escalate hints (1 verbal, 2 point, 3 point + why).
 * Never performs actions for the learner.
 */
export class Tutor {
  private phase: TutorPhase = "idle";
  private plan: LessonPlan | null = null;
  private lessonId: string | null = null;
  private step: StepState | null = null;
  private cancelTimer: (() => void) | null = null;
  /** Bumped whenever the lesson moves on, so stale async continuations bail out. */
  private gen = 0;
  private praiseIdx = 0;
  /** "done" said while the instruction was still being given. */
  private pendingDone = false;
  /** Review quiz: steps are not pointed at until the learner asks for help. */
  private quiz = false;

  constructor(private deps: TutorDeps) {}

  get view(): TutorView {
    const s = this.plan?.steps[this.step?.index ?? 0];
    return {
      phase: this.phase,
      title: this.plan?.title ?? "",
      stepIndex: this.step?.index ?? 0,
      stepCount: this.plan?.steps.length ?? 0,
      instruction: s?.instruction ?? "",
      hintLevel: this.step?.hintLevel ?? 0,
    };
  }

  get active(): boolean {
    return this.phase === "planning" || this.phase === "instructing" || this.phase === "waiting" || this.phase === "verifying";
  }

  private set(phase: TutorPhase) {
    this.phase = phase;
    this.deps.publish(this.view);
  }

  async start(goal: string): Promise<void> {
    if (this.active) await this.stop(false);
    const gen = ++this.gen;
    this.plan = null;
    this.step = null;
    this.set("planning");
    void this.deps.say(this.deps.text.planning);
    let plan: LessonPlan;
    try {
      plan = await this.deps.plan(goal);
    } catch {
      if (gen !== this.gen) return;
      this.set("failed");
      await this.deps.say(this.deps.text.planFailed);
      return;
    }
    if (gen !== this.gen) return;
    await this.run(plan, goal, false);
  }

  /** Plays a recorded walkthrough as a guided lesson. */
  async startWalkthrough(plan: LessonPlan, goal: string): Promise<void> {
    if (this.active) await this.stop(false);
    await this.run(plan, goal, false);
  }

  /** Replays a stored plan as a "can you still do this?" review quiz. */
  async startReview(plan: LessonPlan, goal: string): Promise<void> {
    if (this.active) await this.stop(false);
    await this.run(plan, goal, true);
  }

  private async run(plan: LessonPlan, goal: string, quiz: boolean): Promise<void> {
    this.plan = plan;
    this.quiz = quiz;
    this.lessonId = await this.deps.recordStart(plan, goal);
    await this.deps.watchActivity(true);
    await this.enterStep(0);
  }

  private async enterStep(index: number): Promise<void> {
    const plan = this.plan!;
    const gen = ++this.gen;
    this.clearTimer();
    this.pendingDone = false;
    this.step = { index, startedAt: this.deps.now(), attempts: 0, hintsUsed: 0, hintLevel: 0, autoFails: 0, mistakes: [] };
    const step = plan.steps[index];
    this.set("instructing");
    await this.deps.setContext({ title: plan.title, step_index: index, step_count: plan.steps.length, instruction: step.instruction });
    await this.deps.beginStep();
    if (gen !== this.gen) return;
    const intro = this.quiz ? this.deps.text.quizIntro : this.deps.text.firstStep;
    const prefix = index === 0 ? `${intro} ` : "";
    await this.deps.say(prefix + step.instruction);
    if (gen !== this.gen) return;
    if (!this.quiz) await this.deps.point(step).catch(() => false);
    if (gen !== this.gen) return;
    this.set("waiting");
    if (this.pendingDone) {
      this.pendingDone = false;
      await this.check("done");
    }
  }

  onActivity(): void {
    if (this.phase !== "waiting") return;
    this.clearTimer();
    this.cancelTimer = this.deps.schedule(() => void this.check("auto"), QUIET_MS);
  }

  async command(cmd: TutorCommand): Promise<void> {
    if (!this.plan || !this.step || !this.active) return;
    switch (cmd) {
      case "done":
        if (this.phase === "instructing") this.pendingDone = true;
        else await this.check("done");
        return;
      case "skip":
        await this.finishStep("skipped");
        return;
      case "show_me":
        return this.showMe();
      case "stop":
        return this.stop(true);
    }
  }

  private async check(source: "auto" | "done"): Promise<void> {
    if (this.phase !== "waiting" || !this.plan || !this.step) return;
    this.clearTimer();
    const gen = this.gen;
    const st = this.step;
    const step = this.plan.steps[st.index];
    st.attempts++;
    this.set("verifying");
    let res: VerifyResult;
    try {
      res = await this.deps.verify(step, st.attempts);
    } catch {
      if (gen !== this.gen) return;
      this.set("waiting");
      await this.deps.say(this.deps.text.verifyFailed);
      return;
    }
    if (gen !== this.gen) return;

    if (res.passed) {
      await this.deps.say(res.hint || this.nextPraise());
      await this.finishStep("passed");
      return;
    }

    if (source === "auto" && ++st.autoFails < AUTO_FAILS_BEFORE_HINT) {
      this.set("waiting"); // they may still be mid-action: stay quiet
      return;
    }
    st.autoFails = 0;
    st.mistakes.push(res.hint);
    st.hintLevel = Math.min(MAX_HINT, st.hintLevel + 1);
    st.hintsUsed++;
    let line = res.hint;
    if (st.hintLevel >= 3 && step.why) line += ` ${step.why}`;
    if (st.attempts > MAX_HINT) line += ` ${this.deps.text.stuck}`;
    this.set("waiting");
    await this.deps.say(line);
    if (gen !== this.gen) return;
    if (st.hintLevel >= 2) await this.deps.point(step).catch(() => false);
  }

  private async showMe(): Promise<void> {
    const st = this.step!;
    const step = this.plan!.steps[st.index];
    st.hintsUsed++;
    st.hintLevel = Math.max(st.hintLevel, 2);
    this.deps.publish(this.view);
    await this.deps.say(step.why ? `${step.why} ${step.instruction}` : step.instruction);
    await this.deps.point(step).catch(() => false);
  }

  private async finishStep(status: "passed" | "skipped"): Promise<void> {
    const plan = this.plan!;
    const st = this.step!;
    this.gen++;
    this.clearTimer();
    await this.deps.recordStep(this.lessonId!, {
      index: st.index,
      instruction: plan.steps[st.index].instruction,
      status,
      attempts: Math.max(st.attempts, status === "passed" ? 1 : 0),
      hints_used: st.hintsUsed,
      duration_ms: Math.max(0, this.deps.now() - st.startedAt),
      mistakes: st.mistakes,
    });
    if (st.index + 1 < plan.steps.length) {
      await this.enterStep(st.index + 1);
    } else {
      await this.finish("completed");
    }
  }

  async stop(announce = true): Promise<void> {
    if (!this.active) return;
    if (this.lessonId) await this.finish("abandoned", announce);
    else {
      this.gen++;
      this.set("idle");
    }
  }

  private async finish(status: "completed" | "abandoned", announce = true): Promise<void> {
    this.gen++;
    this.clearTimer();
    const title = this.plan?.title ?? "";
    if (this.lessonId) await this.deps.recordFinish(this.lessonId, status);
    this.lessonId = null;
    await this.deps.watchActivity(false);
    await this.deps.setContext(null);
    this.set(status === "completed" ? "finished" : "idle");
    if (announce) await this.deps.say(status === "completed" ? this.deps.text.finished(title) : this.deps.text.stopped);
  }

  private nextPraise(): string {
    const p = this.deps.text.praise;
    return p[this.praiseIdx++ % p.length];
  }

  private clearTimer() {
    this.cancelTimer?.();
    this.cancelTimer = null;
  }
}
