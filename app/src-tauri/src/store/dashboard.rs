//! Read models for the skills dashboard.

use serde::Serialize;

use super::reviews::{progress_percent, ReviewState};
use super::{Result, Store};

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct SkillCard {
    pub id: String,
    pub app: String,
    pub name: String,
    pub progress: i64,
    pub lessons: i64,
    pub due_at: Option<i64>,
    pub due: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct RecentLesson {
    pub id: String,
    pub title: String,
    pub app: String,
    pub skill_id: String,
    pub status: String,
    pub started_at: i64,
    pub steps_passed: i64,
    pub steps_total: i64,
    pub hints: i64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct WeakSpot {
    pub skill_id: String,
    pub skill_name: String,
    pub instruction: String,
    pub hints: i64,
    pub skips: i64,
}

#[derive(Debug, Clone, Serialize)]
pub struct Dashboard {
    pub skills: Vec<SkillCard>,
    pub recent: Vec<RecentLesson>,
    pub weak_spots: Vec<WeakSpot>,
}

impl Store {
    pub fn dashboard(&self, now: i64) -> Result<Dashboard> {
        let skills = self.with(|c| {
            let mut st = c.prepare(
                "SELECT s.id, s.app, s.name,
                        (SELECT COUNT(*) FROM lessons l WHERE l.skill_id = s.id AND l.status = 'completed'),
                        r.easiness, r.interval_days, r.repetitions, r.due_at, r.last_grade
                 FROM skills s LEFT JOIN reviews r ON r.skill_id = s.id
                 ORDER BY s.app, s.name",
            )?;
            let rows = st.query_map([], |r| {
                let review = match r.get::<_, Option<f64>>(4)? {
                    Some(easiness) => Some(ReviewState {
                        easiness,
                        interval_days: r.get(5)?,
                        repetitions: r.get(6)?,
                        due_at: r.get(7)?,
                        last_grade: r.get(8)?,
                    }),
                    None => None,
                };
                Ok(SkillCard {
                    id: r.get(0)?,
                    app: r.get(1)?,
                    name: r.get(2)?,
                    progress: progress_percent(review.as_ref(), r.get(3)?),
                    lessons: r.get(3)?,
                    due_at: review.map(|s| s.due_at),
                    due: review.is_some_and(|s| s.due_at <= now),
                })
            })?;
            rows.collect::<rusqlite::Result<Vec<_>>>()
        })?;

        let recent = self.with(|c| {
            let mut st = c.prepare(
                "SELECT l.id, l.title, l.app, l.skill_id, l.status, l.started_at,
                        COALESCE(SUM(s.status = 'passed'), 0),
                        (SELECT COUNT(*) FROM json_each(l.plan_json, '$.steps')),
                        COALESCE(SUM(s.hints_used), 0)
                 FROM lessons l LEFT JOIN lesson_steps s ON s.lesson_id = l.id
                 GROUP BY l.id ORDER BY l.started_at DESC LIMIT 10",
            )?;
            let rows = st.query_map([], |r| {
                Ok(RecentLesson {
                    id: r.get(0)?,
                    title: r.get(1)?,
                    app: r.get(2)?,
                    skill_id: r.get(3)?,
                    status: r.get(4)?,
                    started_at: r.get(5)?,
                    steps_passed: r.get(6)?,
                    steps_total: r.get(7)?,
                    hints: r.get(8)?,
                })
            })?;
            rows.collect::<rusqlite::Result<Vec<_>>>()
        })?;

        let weak_spots = self.with(|c| {
            let mut st = c.prepare(
                "SELECT l.skill_id, sk.name, s.instruction, SUM(s.hints_used), SUM(s.status = 'skipped')
                 FROM lesson_steps s JOIN lessons l ON l.id = s.lesson_id JOIN skills sk ON sk.id = l.skill_id
                 GROUP BY l.skill_id, s.instruction
                 HAVING SUM(s.hints_used) + 2 * SUM(s.status = 'skipped') > 0
                 ORDER BY SUM(s.hints_used) + 2 * SUM(s.status = 'skipped') DESC LIMIT 5",
            )?;
            let rows = st.query_map([], |r| {
                Ok(WeakSpot {
                    skill_id: r.get(0)?,
                    skill_name: r.get(1)?,
                    instruction: r.get(2)?,
                    hints: r.get(3)?,
                    skips: r.get(4)?,
                })
            })?;
            rows.collect::<rusqlite::Result<Vec<_>>>()
        })?;

        Ok(Dashboard {
            skills,
            recent,
            weak_spots,
        })
    }
}

#[cfg(test)]
mod tests {
    use crate::store::{reviews::DAY, StepResult, Store};

    fn step(i: u32, status: &str, hints: u32) -> StepResult {
        StepResult {
            index: i,
            instruction: format!("Step {i}"),
            status: status.into(),
            attempts: hints + 1,
            hints_used: hints,
            duration_ms: 10,
            mistakes: vec![],
        }
    }

    #[test]
    fn dashboard_reflects_lessons_and_reviews() {
        let st = Store::in_memory().unwrap();
        let plan = r#"{"steps":[{},{},{}]}"#;
        let a = st
            .lesson_start("excel.sum", "SUM", "Excel", "Totals", "g", plan, 10)
            .unwrap();
        st.lesson_step(&a, &step(0, "passed", 0), 11).unwrap();
        st.lesson_step(&a, &step(1, "passed", 3), 12).unwrap();
        st.lesson_step(&a, &step(2, "skipped", 0), 13).unwrap();
        st.lesson_finish(&a, "completed", 14).unwrap();
        st.schedule_after_lesson(&a, "excel.sum", 14).unwrap();
        let b = st
            .lesson_start("chrome.tabs", "Tabs", "Chrome", "Tabs", "g", plan, 20)
            .unwrap();
        st.lesson_finish(&b, "abandoned", 21).unwrap();

        let d = st.dashboard(14 + 2 * DAY).unwrap();
        assert_eq!(d.skills.len(), 2);
        let excel = d.skills.iter().find(|s| s.id == "excel.sum").unwrap();
        // Struggled (hints + a skip) → grade 2 → not yet recalled, but completion counts.
        assert_eq!((excel.lessons, excel.progress, excel.due), (1, 10, true));
        let chrome = d.skills.iter().find(|s| s.id == "chrome.tabs").unwrap();
        assert_eq!(
            (chrome.progress, chrome.due, chrome.due_at),
            (0, false, None)
        );

        assert_eq!(d.recent[0].title, "Tabs"); // newest first
        let totals = &d.recent[1];
        assert_eq!(
            (totals.steps_passed, totals.steps_total, totals.hints),
            (2, 3, 3)
        );

        let weak: Vec<_> = d
            .weak_spots
            .iter()
            .map(|w| (w.instruction.as_str(), w.hints, w.skips))
            .collect();
        assert_eq!(weak, vec![("Step 1", 3, 0), ("Step 2", 0, 1)]);
    }
}
