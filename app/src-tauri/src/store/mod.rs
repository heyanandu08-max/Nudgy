//! Local learning data in SQLite: skills, lessons, steps, mistakes, reviews (SM-2) and
//! walkthroughs. Lives in the app data dir; never synced unless the user shares something.

use std::path::Path;
use std::sync::Mutex;

use rusqlite::{params, Connection, OptionalExtension};
use serde::{Deserialize, Serialize};

mod schema;

pub struct Store {
    conn: Mutex<Connection>,
}

pub type Result<T> = std::result::Result<T, String>;

fn e(err: rusqlite::Error) -> String {
    err.to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct StepResult {
    pub index: u32,
    pub instruction: String,
    /// "passed" | "skipped"
    pub status: String,
    pub attempts: u32,
    pub hints_used: u32,
    pub duration_ms: u64,
    pub mistakes: Vec<String>,
}

impl Store {
    pub fn open(path: &Path) -> Result<Store> {
        if let Some(dir) = path.parent() {
            std::fs::create_dir_all(dir).map_err(|x| x.to_string())?;
        }
        Self::init(Connection::open(path).map_err(e)?)
    }

    pub fn in_memory() -> Result<Store> {
        Self::init(Connection::open_in_memory().map_err(e)?)
    }

    fn init(conn: Connection) -> Result<Store> {
        conn.pragma_update(None, "journal_mode", "WAL").map_err(e)?;
        conn.pragma_update(None, "foreign_keys", "ON").map_err(e)?;
        schema::migrate(&conn)?;
        Ok(Store {
            conn: Mutex::new(conn),
        })
    }

    pub(crate) fn with<T>(&self, f: impl FnOnce(&Connection) -> rusqlite::Result<T>) -> Result<T> {
        f(&self.conn.lock().unwrap()).map_err(e)
    }

    /// Records a lesson start; creates the skill if new. Returns the lesson id.
    pub fn lesson_start(
        &self,
        skill: &str,
        skill_name: &str,
        app: &str,
        title: &str,
        goal: &str,
        plan_json: &str,
        now: i64,
    ) -> Result<String> {
        let id = uuid::Uuid::new_v4().to_string();
        self.with(|c| {
            c.execute(
                "INSERT INTO skills (id, app, name, created_at) VALUES (?1, ?2, ?3, ?4)
                 ON CONFLICT(id) DO UPDATE SET name = excluded.name",
                params![skill, app, skill_name, now],
            )?;
            c.execute(
                "INSERT INTO lessons (id, skill_id, title, app, goal, plan_json, status, started_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, 'active', ?7)",
                params![id, skill, title, app, goal, plan_json, now],
            )?;
            Ok(())
        })?;
        Ok(id)
    }

    pub fn lesson_step(&self, lesson_id: &str, r: &StepResult, now: i64) -> Result<()> {
        self.with(|c| {
            c.execute(
                "INSERT INTO lesson_steps (lesson_id, idx, instruction, status, attempts, hints_used, duration_ms, finished_at)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8)
                 ON CONFLICT(lesson_id, idx) DO UPDATE SET status = excluded.status,
                   attempts = excluded.attempts, hints_used = excluded.hints_used,
                   duration_ms = excluded.duration_ms, finished_at = excluded.finished_at",
                params![lesson_id, r.index, r.instruction, r.status, r.attempts, r.hints_used, r.duration_ms as i64, now],
            )?;
            for m in &r.mistakes {
                c.execute(
                    "INSERT INTO mistakes (lesson_id, step_idx, hint, at) VALUES (?1, ?2, ?3, ?4)",
                    params![lesson_id, r.index, m, now],
                )?;
            }
            Ok(())
        })
    }

    /// Marks a lesson finished ("completed" | "abandoned") and returns its skill id.
    pub fn lesson_finish(&self, lesson_id: &str, status: &str, now: i64) -> Result<String> {
        self.with(|c| {
            c.execute(
                "UPDATE lessons SET status = ?2, finished_at = ?3 WHERE id = ?1",
                params![lesson_id, status, now],
            )?;
            c.query_row(
                "SELECT skill_id FROM lessons WHERE id = ?1",
                [lesson_id],
                |r| r.get(0),
            )
        })
    }

    pub fn lesson_plan(&self, lesson_id: &str) -> Result<Option<String>> {
        self.with(|c| {
            c.query_row(
                "SELECT plan_json FROM lessons WHERE id = ?1",
                [lesson_id],
                |r| r.get(0),
            )
            .optional()
        })
    }

    /// Wipes all local learning data ("Delete my data").
    pub fn wipe(&self) -> Result<()> {
        self.with(|c| c.execute_batch(schema::WIPE))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn step(i: u32, status: &str, attempts: u32, mistakes: &[&str]) -> StepResult {
        StepResult {
            index: i,
            instruction: format!("step {i}"),
            status: status.into(),
            attempts,
            hints_used: attempts.saturating_sub(1),
            duration_ms: 1000,
            mistakes: mistakes.iter().map(|s| s.to_string()).collect(),
        }
    }

    #[test]
    fn records_a_lesson_end_to_end() {
        let s = Store::in_memory().unwrap();
        let id = s
            .lesson_start(
                "excel.sum",
                "SUM",
                "Excel",
                "Totals",
                "sum a column",
                "{}",
                100,
            )
            .unwrap();
        s.lesson_step(&id, &step(0, "passed", 1, &[]), 110).unwrap();
        s.lesson_step(
            &id,
            &step(1, "passed", 3, &["try the Home tab", "look top left"]),
            120,
        )
        .unwrap();
        assert_eq!(s.lesson_finish(&id, "completed", 130).unwrap(), "excel.sum");
        let (status, mistakes): (String, i64) = s
            .with(|c| {
                c.query_row(
                    "SELECT status, (SELECT COUNT(*) FROM mistakes WHERE lesson_id = l.id) FROM lessons l WHERE id = ?1",
                    [&id],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
            })
            .unwrap();
        assert_eq!((status.as_str(), mistakes), ("completed", 2));
        assert_eq!(s.lesson_plan(&id).unwrap().as_deref(), Some("{}"));
    }

    #[test]
    fn step_results_are_upserted() {
        let s = Store::in_memory().unwrap();
        let id = s.lesson_start("a.b", "B", "A", "T", "g", "{}", 1).unwrap();
        s.lesson_step(&id, &step(0, "skipped", 1, &[]), 2).unwrap();
        s.lesson_step(&id, &step(0, "passed", 2, &[]), 3).unwrap();
        let n: i64 = s
            .with(|c| c.query_row("SELECT COUNT(*) FROM lesson_steps", [], |r| r.get(0)))
            .unwrap();
        assert_eq!(n, 1);
    }

    #[test]
    fn wipe_clears_everything_and_reopens_cleanly() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("nudgy.db");
        let s = Store::open(&path).unwrap();
        s.lesson_start("a.b", "B", "A", "T", "g", "{}", 1).unwrap();
        s.wipe().unwrap();
        drop(s);
        let s = Store::open(&path).unwrap();
        let n: i64 = s
            .with(|c| c.query_row("SELECT COUNT(*) FROM lessons", [], |r| r.get(0)))
            .unwrap();
        assert_eq!(n, 0);
    }
}
