//! Weekly progress and the learning streak (all local).
//!
//! A "learning day" is a local calendar day with at least one lesson, review or question.
//! Days are counted in the user's time zone: the caller passes its UTC offset.

use std::collections::BTreeSet;

use serde::Serialize;

use super::reviews::DAY;
use rusqlite::OptionalExtension;

use super::{Result, Store};

#[derive(Debug, Clone, Serialize, PartialEq, Default)]
pub struct Totals {
    pub lessons: i64,
    pub steps: i64,
    pub questions: i64,
    pub skills: i64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct WeekProgress {
    /// The last 7 days, today included.
    pub this_week: Totals,
    /// The 7 days before that, to compare against.
    pub last_week: Totals,
    /// Learning days in a row, ending today (or yesterday, so the streak isn't lost before
    /// the user had a chance to learn today).
    pub streak: i64,
    pub best_streak: i64,
    pub learned_today: bool,
    /// Oldest first: whether each of the last 7 days was a learning day.
    pub days: Vec<bool>,
}

fn day_of(ts: i64, offset: i64) -> i64 {
    (ts + offset).div_euclid(DAY)
}

/// How a finished lesson went, for the team onboarding report (metadata only).
#[derive(Debug, Clone, PartialEq)]
pub struct RunSummary {
    pub goal: String,
    pub status: String,
    pub steps_total: i64,
    pub steps_passed: i64,
    pub hints: i64,
    /// The step that took the most help (hints, or 2 per skip); on an abandoned run with no
    /// such step, the step they stopped at.
    pub stuck_step: Option<i64>,
}

impl Store {
    pub fn run_summary(&self, lesson_id: &str) -> Result<Option<RunSummary>> {
        self.with(|c| {
            let head = c
                .query_row(
                    "SELECT goal, status, (SELECT COUNT(*) FROM json_each(plan_json, '$.steps'))
                     FROM lessons WHERE id = ?1",
                    [lesson_id],
                    |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?, r.get(2)?)),
                )
                .optional()?;
            let Some((goal, status, steps_total)) = head else {
                return Ok(None);
            };
            let (steps_passed, hints, reached): (i64, i64, i64) = c.query_row(
                "SELECT COALESCE(SUM(status = 'passed'), 0), COALESCE(SUM(hints_used), 0), COUNT(*)
                 FROM lesson_steps WHERE lesson_id = ?1",
                [lesson_id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )?;
            let hardest: Option<i64> = c
                .query_row(
                    "SELECT idx FROM lesson_steps WHERE lesson_id = ?1
                       AND hints_used + 2 * (status = 'skipped') > 0
                     ORDER BY hints_used + 2 * (status = 'skipped') DESC, idx LIMIT 1",
                    [lesson_id],
                    |r| r.get(0),
                )
                .optional()?;
            let stuck_step = hardest
                .or_else(|| (status == "abandoned" && reached < steps_total).then_some(reached));
            Ok(Some(RunSummary {
                goal,
                status,
                steps_total,
                steps_passed,
                hints,
                stuck_step,
            }))
        })
    }

    /// Which of these lesson goals have been completed at least once (for course progress).
    pub fn completed_goals(&self, goals: &[String]) -> Result<Vec<String>> {
        self.with(|c| {
            let mut st = c.prepare(
                "SELECT 1 FROM lessons WHERE goal = ?1 AND status = 'completed' LIMIT 1",
            )?;
            let mut done = Vec::new();
            for g in goals {
                if st.exists([g])? {
                    done.push(g.clone());
                }
            }
            Ok(done)
        })
    }

    fn totals(&self, from: i64, to: i64) -> Result<Totals> {
        self.with(|c| {
            let (lessons, skills): (i64, i64) = c.query_row(
                "SELECT COUNT(*), COUNT(DISTINCT skill_id) FROM lessons
                 WHERE status = 'completed' AND finished_at >= ?1 AND finished_at < ?2",
                [from, to],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )?;
            let steps: i64 = c.query_row(
                "SELECT COUNT(*) FROM lesson_steps
                 WHERE status = 'passed' AND finished_at >= ?1 AND finished_at < ?2",
                [from, to],
                |r| r.get(0),
            )?;
            let questions: i64 = c.query_row(
                "SELECT COUNT(*) FROM asks WHERE at >= ?1 AND at < ?2",
                [from, to],
                |r| r.get(0),
            )?;
            Ok(Totals {
                lessons,
                steps,
                questions,
                skills,
            })
        })
    }

    /// `offset` is the local time zone's offset from UTC in seconds (east positive).
    pub fn week_progress(&self, now: i64, offset: i64) -> Result<WeekProgress> {
        let days: BTreeSet<i64> = self.with(|c| {
            let mut st = c.prepare(
                "SELECT started_at FROM lessons
                 UNION SELECT last_reviewed_at FROM reviews
                 UNION SELECT at FROM asks",
            )?;
            let rows = st.query_map([], |r| r.get::<_, i64>(0))?;
            rows.map(|t| t.map(|t| day_of(t, offset))).collect()
        })?;

        let today = day_of(now, offset);
        let start_of_today = today * DAY - offset;
        let week_start = start_of_today - 6 * DAY;
        let tomorrow = start_of_today + DAY;

        let learned_today = days.contains(&today);
        let mut streak = 0;
        let mut d = if learned_today { today } else { today - 1 };
        while days.contains(&d) {
            streak += 1;
            d -= 1;
        }
        let (mut best, mut run, mut prev) = (0, 0, i64::MIN);
        for &d in &days {
            run = if prev != i64::MIN && d == prev + 1 {
                run + 1
            } else {
                1
            };
            best = best.max(run);
            prev = d;
        }

        Ok(WeekProgress {
            this_week: self.totals(week_start, tomorrow)?,
            last_week: self.totals(week_start - 7 * DAY, week_start)?,
            streak,
            best_streak: best,
            learned_today,
            days: (0..7).map(|i| days.contains(&(today - 6 + i))).collect(),
        })
    }
}

#[cfg(test)]
mod tests {
    use crate::store::{reviews::DAY, StepResult, Store};

    fn passed(i: u32) -> StepResult {
        StepResult {
            index: i,
            instruction: format!("Step {i}"),
            status: "passed".into(),
            attempts: 1,
            hints_used: 0,
            duration_ms: 10,
            mistakes: vec![],
        }
    }

    const NOW: i64 = 100 * DAY + 10 * 3600; // 10:00 UTC on day 100

    #[test]
    fn empty_store_has_no_streak() {
        let p = Store::in_memory().unwrap().week_progress(NOW, 0).unwrap();
        assert_eq!((p.streak, p.best_streak, p.learned_today), (0, 0, false));
        assert_eq!(p.days, vec![false; 7]);
    }

    #[test]
    fn counts_the_week_and_the_streak() {
        let st = Store::in_memory().unwrap();
        // Questions on days 97, 98, 99 (yesterday); a lesson today; one 10 days ago.
        for d in [97, 98, 99] {
            st.record_ask("how?", "Excel", 10, d * DAY + 60).unwrap();
        }
        let a = st
            .lesson_start("excel.sum", "SUM", "Excel", "Totals", "g", "{}", NOW - 60)
            .unwrap();
        st.lesson_step(&a, &passed(0), NOW - 30).unwrap();
        st.lesson_finish(&a, "completed", NOW).unwrap();
        let old = st
            .lesson_start(
                "word.styles",
                "Styles",
                "Word",
                "Styles",
                "g",
                "{}",
                90 * DAY,
            )
            .unwrap();
        st.lesson_finish(&old, "completed", 90 * DAY + 60).unwrap();
        // Last week (days 87-93): that one and another.
        let lw = st
            .lesson_start("excel.sum", "SUM", "Excel", "Totals", "g", "{}", 92 * DAY)
            .unwrap();
        st.lesson_finish(&lw, "completed", 92 * DAY + 60).unwrap();

        let p = st.week_progress(NOW, 0).unwrap();
        assert_eq!(p.this_week.lessons, 1);
        assert_eq!(p.this_week.steps, 1);
        assert_eq!(p.this_week.questions, 3);
        assert_eq!(p.this_week.skills, 1);
        assert_eq!(p.last_week.lessons, 2);
        assert_eq!((p.streak, p.best_streak, p.learned_today), (4, 4, true));
        assert_eq!(p.days, vec![false, false, false, true, true, true, true]);

        // Tomorrow, before learning anything: the streak still stands.
        assert_eq!(st.week_progress(NOW + DAY, 0).unwrap().streak, 4);
        // Two days later it's gone, but the best is remembered.
        let later = st.week_progress(NOW + 2 * DAY, 0).unwrap();
        assert_eq!((later.streak, later.best_streak), (0, 4));
    }

    #[test]
    fn completed_goals_only_counts_finished_lessons() {
        let st = Store::in_memory().unwrap();
        let a = st
            .lesson_start("excel.sum", "SUM", "Excel", "SUM", "Add up", "{}", 1)
            .unwrap();
        st.lesson_finish(&a, "completed", 2).unwrap();
        let b = st
            .lesson_start("excel.chart", "Chart", "Excel", "Chart", "Chart", "{}", 3)
            .unwrap();
        st.lesson_finish(&b, "abandoned", 4).unwrap();
        let goals = ["Add up", "Chart", "Freeze"].map(String::from);
        assert_eq!(st.completed_goals(&goals).unwrap(), vec!["Add up"]);
    }

    #[test]
    fn run_summary_finds_where_they_got_stuck() {
        let st = Store::in_memory().unwrap();
        let plan = r#"{"steps":[{},{},{}]}"#;
        let a = st
            .lesson_start("w", "W", "SAP", "W", "walkthrough:w1", plan, 1)
            .unwrap();
        st.lesson_step(&a, &passed(0), 2).unwrap();
        let mut hard = passed(1);
        hard.hints_used = 3;
        st.lesson_step(&a, &hard, 3).unwrap();
        st.lesson_finish(&a, "completed", 4).unwrap();
        let s = st.run_summary(&a).unwrap().unwrap();
        assert_eq!(
            (
                s.goal.as_str(),
                s.steps_total,
                s.steps_passed,
                s.hints,
                s.stuck_step
            ),
            ("walkthrough:w1", 3, 2, 3, Some(1))
        );

        // Gave up on the third step without asking for help: that's where they stopped.
        let b = st
            .lesson_start("w", "W", "SAP", "W", "walkthrough:w1", plan, 5)
            .unwrap();
        st.lesson_step(&b, &passed(0), 6).unwrap();
        st.lesson_step(&b, &passed(1), 7).unwrap();
        st.lesson_finish(&b, "abandoned", 8).unwrap();
        assert_eq!(st.run_summary(&b).unwrap().unwrap().stuck_step, Some(2));
        assert_eq!(st.run_summary("nope").unwrap(), None);
    }

    #[test]
    fn days_follow_the_local_time_zone() {
        let st = Store::in_memory().unwrap();
        // 23:30 UTC on day 99 is 01:30 on day 100 two hours east.
        st.record_ask("how?", "Excel", 10, 100 * DAY - 1800)
            .unwrap();
        assert!(st.week_progress(NOW, 2 * 3600).unwrap().learned_today);
        assert!(!st.week_progress(NOW, 0).unwrap().learned_today);
    }
}
