//! Spaced repetition (SM-2) over skills. A finished lesson is graded 0–5 from how it went;
//! the grade updates the skill's easiness and next due date.

use rusqlite::{params, OptionalExtension};
use serde::Serialize;

use super::{Result, Store};

pub const DAY: i64 = 86_400;

#[derive(Debug, Clone, Copy, PartialEq, Serialize)]
pub struct ReviewState {
    pub easiness: f64,
    pub interval_days: i64,
    pub repetitions: i64,
    pub due_at: i64,
    pub last_grade: i64,
}

/// Classic SM-2 (Wozniak, 1990). `grade` 0–5; ≥3 counts as recalled.
pub fn sm2(prev: Option<ReviewState>, grade: i64, now: i64) -> ReviewState {
    let grade = grade.clamp(0, 5);
    let (mut ef, mut interval, mut reps) = match prev {
        Some(p) => (p.easiness, p.interval_days, p.repetitions),
        None => (2.5, 0, 0),
    };
    if grade >= 3 {
        interval = match reps {
            0 => 1,
            1 => 6,
            _ => ((interval as f64) * ef).round() as i64,
        };
        reps += 1;
    } else {
        reps = 0;
        interval = 1;
    }
    let q = (5 - grade) as f64;
    ef = (ef + (0.1 - q * (0.08 + q * 0.02))).max(1.3);
    ReviewState {
        easiness: ef,
        interval_days: interval,
        repetitions: reps,
        due_at: now + interval * DAY,
        last_grade: grade,
    }
}

/// Summary of a finished lesson used for grading.
#[derive(Debug, Clone, Copy, Default)]
pub struct LessonOutcome {
    pub steps: i64,
    pub skipped: i64,
    pub hints: i64,
    pub abandoned: bool,
}

/// 5 = flawless, 4 = a nudge or two, 3 = needed real help, 2 = skipped a lot, 1 = gave up.
pub fn grade(o: LessonOutcome) -> i64 {
    if o.abandoned || o.steps == 0 {
        return 1;
    }
    if o.skipped * 2 > o.steps {
        return 2;
    }
    let hints_per_step = (o.hints + 2 * o.skipped) as f64 / o.steps as f64;
    match hints_per_step {
        h if h == 0.0 => 5,
        h if h <= 0.5 => 4,
        h if h <= 1.5 => 3,
        _ => 2,
    }
}

/// Mastery shown on skill cards: each successful spaced repetition adds a quarter; having
/// completed any lesson at all is worth a first 10%.
pub fn progress_percent(state: Option<&ReviewState>, completed_lessons: i64) -> i64 {
    let reps = state.map_or(0, |s| s.repetitions * 25);
    let floor = if completed_lessons > 0 { 10 } else { 0 };
    reps.max(floor).clamp(0, 100)
}

impl Store {
    pub fn review_state(&self, skill_id: &str) -> Result<Option<ReviewState>> {
        self.with(|c| {
            c.query_row(
                "SELECT easiness, interval_days, repetitions, due_at, last_grade FROM reviews WHERE skill_id = ?1",
                [skill_id],
                |r| {
                    Ok(ReviewState {
                        easiness: r.get(0)?,
                        interval_days: r.get(1)?,
                        repetitions: r.get(2)?,
                        due_at: r.get(3)?,
                        last_grade: r.get(4)?,
                    })
                },
            )
            .optional()
        })
    }

    pub fn lesson_outcome(&self, lesson_id: &str) -> Result<LessonOutcome> {
        self.with(|c| {
            c.query_row(
                "SELECT COUNT(s.idx), COALESCE(SUM(s.status = 'skipped'), 0), COALESCE(SUM(s.hints_used), 0),
                        l.status = 'abandoned'
                 FROM lessons l LEFT JOIN lesson_steps s ON s.lesson_id = l.id WHERE l.id = ?1",
                [lesson_id],
                |r| Ok(LessonOutcome { steps: r.get(0)?, skipped: r.get(1)?, hints: r.get(2)?, abandoned: r.get(3)? }),
            )
        })
    }

    /// Grades a finished lesson and moves its skill along the SM-2 schedule.
    pub fn schedule_after_lesson(
        &self,
        lesson_id: &str,
        skill_id: &str,
        now: i64,
    ) -> Result<ReviewState> {
        let outcome = self.lesson_outcome(lesson_id)?;
        let next = sm2(self.review_state(skill_id)?, grade(outcome), now);
        self.with(|c| {
            c.execute(
                "INSERT INTO reviews (skill_id, easiness, interval_days, repetitions, due_at, last_grade, last_reviewed_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)
                 ON CONFLICT(skill_id) DO UPDATE SET easiness = excluded.easiness,
                   interval_days = excluded.interval_days, repetitions = excluded.repetitions,
                   due_at = excluded.due_at, last_grade = excluded.last_grade,
                   last_reviewed_at = excluded.last_reviewed_at",
                params![skill_id, next.easiness, next.interval_days, next.repetitions, next.due_at, next.last_grade, now],
            )
        })?;
        Ok(next)
    }

    /// Skills whose review is due, most overdue first.
    pub fn due_skills(&self, now: i64) -> Result<Vec<(String, String)>> {
        self.with(|c| {
            let mut st = c.prepare(
                "SELECT s.id, s.name FROM reviews r JOIN skills s ON s.id = r.skill_id
                 WHERE r.due_at <= ?1 ORDER BY r.due_at",
            )?;
            let rows = st.query_map([now], |r| Ok((r.get(0)?, r.get(1)?)))?;
            rows.collect()
        })
    }

    /// The most recent lesson plan for a skill, replayed as a review quiz.
    pub fn latest_plan_for_skill(&self, skill_id: &str) -> Result<Option<String>> {
        self.with(|c| {
            c.query_row(
                "SELECT plan_json FROM lessons WHERE skill_id = ?1 ORDER BY started_at DESC LIMIT 1",
                [skill_id],
                |r| r.get(0),
            )
            .optional()
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::store::StepResult;

    #[test]
    fn sm2_intervals_grow_1_6_then_by_easiness() {
        let a = sm2(None, 5, 0);
        assert_eq!((a.interval_days, a.repetitions), (1, 1));
        assert!((a.easiness - 2.6).abs() < 1e-9);
        let b = sm2(Some(a), 5, 0);
        assert_eq!((b.interval_days, b.repetitions), (6, 2));
        let c = sm2(Some(b), 4, 0);
        assert_eq!(c.interval_days, (6.0 * 2.7_f64).round() as i64);
        assert_eq!(c.due_at, c.interval_days * DAY);
    }

    #[test]
    fn sm2_lapse_resets_and_easiness_has_a_floor() {
        let mut s = sm2(None, 5, 0);
        s = sm2(Some(s), 5, 0);
        let lapse = sm2(Some(s), 1, 100);
        assert_eq!(
            (lapse.interval_days, lapse.repetitions, lapse.due_at),
            (1, 0, 100 + DAY)
        );
        let mut hard = sm2(None, 0, 0);
        for _ in 0..20 {
            hard = sm2(Some(hard), 0, 0);
        }
        assert!((hard.easiness - 1.3).abs() < 1e-9);
    }

    #[test]
    fn grading() {
        let o = |steps, skipped, hints| LessonOutcome {
            steps,
            skipped,
            hints,
            abandoned: false,
        };
        assert_eq!(grade(o(5, 0, 0)), 5);
        assert_eq!(grade(o(5, 0, 2)), 4);
        assert_eq!(grade(o(5, 0, 5)), 3);
        assert_eq!(grade(o(5, 1, 6)), 2);
        assert_eq!(grade(o(5, 3, 0)), 2);
        assert_eq!(
            grade(LessonOutcome {
                abandoned: true,
                ..o(5, 0, 0)
            }),
            1
        );
        assert_eq!(grade(o(0, 0, 0)), 1);
    }

    #[test]
    fn progress_in_quarters() {
        assert_eq!(progress_percent(None, 0), 0);
        assert_eq!(progress_percent(None, 1), 10);
        let s = sm2(None, 5, 0);
        assert_eq!(progress_percent(Some(&s), 1), 25);
        let s = sm2(
            Some(sm2(Some(sm2(Some(sm2(Some(s), 5, 0)), 5, 0)), 5, 0)),
            5,
            0,
        );
        assert_eq!(progress_percent(Some(&s), 5), 100);
    }

    #[test]
    fn lesson_finish_schedules_review_and_due_query() {
        let st = Store::in_memory().unwrap();
        let id = st
            .lesson_start("excel.sum", "SUM", "Excel", "T", "g", "{\"steps\":[]}", 0)
            .unwrap();
        for i in 0..4 {
            st.lesson_step(
                &id,
                &StepResult {
                    index: i,
                    instruction: "x".into(),
                    status: "passed".into(),
                    attempts: 1,
                    hints_used: 0,
                    duration_ms: 1,
                    mistakes: vec![],
                },
                0,
            )
            .unwrap();
        }
        st.lesson_finish(&id, "completed", 0).unwrap();
        let r = st.schedule_after_lesson(&id, "excel.sum", 0).unwrap();
        assert_eq!((r.last_grade, r.interval_days), (5, 1));
        assert!(st.due_skills(DAY - 1).unwrap().is_empty());
        assert_eq!(
            st.due_skills(DAY).unwrap(),
            vec![("excel.sum".to_string(), "SUM".to_string())]
        );
        assert_eq!(
            st.latest_plan_for_skill("excel.sum").unwrap().as_deref(),
            Some("{\"steps\":[]}")
        );
    }
}
