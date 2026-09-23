import { describe, expect, it } from "vitest";
import { QUIET_MS, Tutor, type TutorDeps } from "./tutor";
import type { LessonPlan, StepResult, TutorView, VerifyResult } from "./types";

const PLAN: LessonPlan = {
  title: "Totals",
  app: "Excel",
  skill: "excel.sum",
  skill_name: "SUM",
  steps: Array.from({ length: 5 }, (_, i) => ({
    instruction: `Do step ${i + 1}.`,
    target: i === 1 ? null : { role: "button", name: `B${i}` },
    action_hint: "click",
    success_check: `step ${i + 1} done`,
    why: `Because ${i + 1}.`,
  })),
};

function harness(verdicts: VerifyResult[] = []) {
  let clock = 0;
  const timers: { fn: () => void; at: number; live: boolean }[] = [];
  const said: string[] = [];
  const pointed: string[] = [];
  const steps: StepResult[] = [];
  const finished: string[] = [];
  const views: TutorView[] = [];
  const contexts: unknown[] = [];
  const activity: boolean[] = [];
  const verifyCalls: number[] = [];
  const deps: TutorDeps = {
    plan: async () => PLAN,
    beginStep: async () => {},
    point: async (s) => (pointed.push(s.instruction), true),
    say: async (t) => void said.push(t),
    verify: async (_s, attempt) => (verifyCalls.push(attempt), verdicts.shift() ?? { passed: true, hint: "" }),
    recordStart: async () => "lesson-1",
    recordStep: async (_id, r) => void steps.push(r),
    recordFinish: async (_id, status) => void finished.push(status),
    setContext: async (c) => void contexts.push(c),
    watchActivity: async (on) => void activity.push(on),
    publish: (v) => void views.push(v),
    now: () => clock,
    schedule: (fn, ms) => {
      const t = { fn, at: clock + ms, live: true };
      timers.push(t);
      return () => (t.live = false);
    },
    text: {
      planning: "planning",
      quizIntro: "Quick review!",
      planFailed: "plan failed",
      firstStep: "Let's start.",
      stuck: "Say skip if stuck.",
      verifyFailed: "couldn't check",
      stopped: "stopped",
      finished: (t) => `finished ${t}`,
      praise: ["Great!", "Nice!"],
    },
  };
  const tick = async (ms: number) => {
    clock += ms;
    for (const t of timers.filter((t) => t.live && t.at <= clock)) {
      t.live = false;
      t.fn();
    }
    await flush();
  };
  return { deps, said, pointed, steps, finished, views, contexts, activity, verifyCalls, tick };
}

const flush = () => new Promise((r) => setTimeout(r, 0));

describe("Tutor", () => {
  it("runs a 5-step lesson to completion via activity + quiet period", async () => {
    const h = harness();
    const t = new Tutor(h.deps);
    await t.start("sum a column");
    expect(t.view).toMatchObject({ phase: "waiting", stepIndex: 0, stepCount: 5 });
    expect(h.said).toContain("Let's start. Do step 1.");
    expect(h.pointed).toEqual(["Do step 1."]);

    for (let i = 0; i < 5; i++) {
      t.onActivity();
      await h.tick(QUIET_MS - 1);
      expect(h.steps.length).toBe(i); // not yet: still within the quiet period
      await h.tick(1);
    }
    expect(h.steps.map((s) => s.status)).toEqual(Array(5).fill("passed"));
    expect(h.finished).toEqual(["completed"]);
    expect(t.view.phase).toBe("finished");
    expect(h.said.at(-1)).toBe("finished Totals");
    expect(h.activity).toEqual([true, false]);
    expect(h.contexts.at(-1)).toBeNull();
    expect(h.contexts[0]).toEqual({ title: "Totals", step_index: 0, step_count: 5, instruction: "Do step 1." });
  });

  it("escalates hints on failed 'done': verbal, then point, then point + why", async () => {
    const fail = (hint: string) => ({ passed: false, hint });
    const h = harness([fail("h1"), fail("h2"), fail("h3"), fail("h4"), { passed: true, hint: "Yes!" }]);
    const t = new Tutor(h.deps);
    await t.start("x");
    h.pointed.length = 0;

    await t.command("done");
    expect(h.said.at(-1)).toBe("h1");
    expect(h.pointed).toEqual([]); // level 1 is verbal only
    await t.command("done");
    expect(h.said.at(-1)).toBe("h2");
    expect(h.pointed.length).toBe(1); // level 2 points
    await t.command("done");
    expect(h.said.at(-1)).toBe("h3 Because 1.");
    await t.command("done");
    expect(h.said.at(-1)).toBe("h4 Because 1. Say skip if stuck.");
    expect(t.view.hintLevel).toBe(3);
    await t.command("done");
    expect(h.said).toContain("Yes!");
    expect(h.steps[0]).toMatchObject({ status: "passed", attempts: 5, hints_used: 4, mistakes: ["h1", "h2", "h3", "h4"] });
    expect(h.verifyCalls).toEqual([1, 2, 3, 4, 5]);
    expect(t.view.stepIndex).toBe(1);
  });

  it("stays quiet on the first automatic failure (learner may be mid-action)", async () => {
    const h = harness([{ passed: false, hint: "a" }, { passed: false, hint: "b" }]);
    const t = new Tutor(h.deps);
    await t.start("x");
    const before = h.said.length;
    t.onActivity();
    await h.tick(QUIET_MS);
    expect(h.said.length).toBe(before);
    expect(t.view.hintLevel).toBe(0);
    t.onActivity();
    await h.tick(QUIET_MS);
    expect(h.said.at(-1)).toBe("b");
    expect(t.view.hintLevel).toBe(1);
  });

  it("activity restarts the quiet period", async () => {
    const h = harness();
    const t = new Tutor(h.deps);
    await t.start("x");
    t.onActivity();
    await h.tick(1000);
    t.onActivity();
    await h.tick(1000);
    expect(h.verifyCalls).toEqual([]);
    await h.tick(QUIET_MS);
    expect(h.verifyCalls).toEqual([1]);
  });

  it("skip records a skipped step and moves on; show me explains and points", async () => {
    const h = harness();
    const t = new Tutor(h.deps);
    await t.start("x");
    await t.command("show_me");
    expect(h.said.at(-1)).toBe("Because 1. Do step 1.");
    expect(h.pointed.at(-1)).toBe("Do step 1.");
    await t.command("skip");
    expect(h.steps[0]).toMatchObject({ index: 0, status: "skipped", hints_used: 1 });
    expect(t.view.stepIndex).toBe(1);
  });

  it("stop abandons the lesson", async () => {
    const h = harness();
    const t = new Tutor(h.deps);
    await t.start("x");
    await t.command("stop");
    expect(h.finished).toEqual(["abandoned"]);
    expect(t.view.phase).toBe("idle");
    expect(h.said.at(-1)).toBe("stopped");
    expect(h.activity).toEqual([true, false]);
    await t.command("done"); // ignored once stopped
    expect(h.verifyCalls).toEqual([]);
  });

  it("a failed plan ends in 'failed' with a spoken apology", async () => {
    const h = harness();
    h.deps.plan = async () => {
      throw new Error("nope");
    };
    const t = new Tutor(h.deps);
    await t.start("x");
    expect(t.view.phase).toBe("failed");
    expect(h.said.at(-1)).toBe("plan failed");
  });

  it("'done' during the instruction is checked once the step is ready", async () => {
    const h = harness();
    let release!: () => void;
    h.deps.beginStep = () => new Promise<void>((r) => (release = r));
    const t = new Tutor(h.deps);
    const started = t.start("x");
    await flush();
    expect(t.view.phase).toBe("instructing");
    await t.command("done");
    expect(h.verifyCalls).toEqual([]);
    h.deps.beginStep = async () => {};
    release();
    await started;
    await flush();
    expect(h.verifyCalls).toEqual([1]);
  });

  it("review quiz replays a stored plan without pointing until help is needed", async () => {
    const h = harness([{ passed: false, hint: "h1" }, { passed: false, hint: "h2" }]);
    let planned = false;
    h.deps.plan = async () => ((planned = true), PLAN);
    const t = new Tutor(h.deps);
    await t.startReview(PLAN, "review:excel.sum");
    expect(planned).toBe(false);
    expect(h.said[0]).toBe("Quick review! Do step 1.");
    expect(h.pointed).toEqual([]);
    await t.command("done");
    expect(h.pointed).toEqual([]); // hint 1 is verbal
    await t.command("done");
    expect(h.pointed).toEqual(["Do step 1."]); // hint 2 points
  });
});
