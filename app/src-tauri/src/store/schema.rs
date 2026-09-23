use rusqlite::Connection;

/// Ordered migrations; index + 1 is stored in `PRAGMA user_version`.
const MIGRATIONS: &[&str] = &[
    // 1 — learning data
    "CREATE TABLE skills (
        id TEXT PRIMARY KEY,           -- e.g. excel.sum_and_currency
        app TEXT NOT NULL,
        name TEXT NOT NULL,
        created_at INTEGER NOT NULL
     );
     CREATE TABLE lessons (
        id TEXT PRIMARY KEY,
        skill_id TEXT NOT NULL REFERENCES skills(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        app TEXT NOT NULL,
        goal TEXT NOT NULL,
        plan_json TEXT NOT NULL,
        status TEXT NOT NULL,          -- active | completed | abandoned
        started_at INTEGER NOT NULL,
        finished_at INTEGER
     );
     CREATE INDEX lessons_skill ON lessons(skill_id, started_at);
     CREATE TABLE lesson_steps (
        lesson_id TEXT NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
        idx INTEGER NOT NULL,
        instruction TEXT NOT NULL,
        status TEXT NOT NULL,          -- passed | skipped
        attempts INTEGER NOT NULL,
        hints_used INTEGER NOT NULL,
        duration_ms INTEGER NOT NULL,
        finished_at INTEGER NOT NULL,
        PRIMARY KEY (lesson_id, idx)
     );
     CREATE TABLE mistakes (
        id INTEGER PRIMARY KEY,
        lesson_id TEXT NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
        step_idx INTEGER NOT NULL,
        hint TEXT NOT NULL,
        at INTEGER NOT NULL
     );
     CREATE TABLE reviews (
        skill_id TEXT PRIMARY KEY REFERENCES skills(id) ON DELETE CASCADE,
        easiness REAL NOT NULL,
        interval_days INTEGER NOT NULL,
        repetitions INTEGER NOT NULL,
        due_at INTEGER NOT NULL,
        last_grade INTEGER NOT NULL,
        last_reviewed_at INTEGER NOT NULL
     );",
    // 2 — recorded walkthroughs (Phase 6)
    "CREATE TABLE walkthroughs (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        app TEXT NOT NULL,
        json TEXT NOT NULL,            -- the .nudgy document
        share_url TEXT,
        created_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL
     );",
];

pub const WIPE: &str = "DELETE FROM mistakes; DELETE FROM lesson_steps; DELETE FROM reviews;
    DELETE FROM lessons; DELETE FROM skills; DELETE FROM walkthroughs; VACUUM;";

pub fn migrate(conn: &Connection) -> Result<(), String> {
    let current: usize = conn
        .query_row("PRAGMA user_version", [], |r| r.get::<_, i64>(0))
        .map_err(|e| e.to_string())? as usize;
    for (i, sql) in MIGRATIONS.iter().enumerate().skip(current) {
        conn.execute_batch(&format!(
            "BEGIN; {sql} PRAGMA user_version = {}; COMMIT;",
            i + 1
        ))
        .map_err(|e| format!("migration {}: {e}", i + 1))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn migrations_are_idempotent() {
        let c = Connection::open_in_memory().unwrap();
        migrate(&c).unwrap();
        migrate(&c).unwrap();
        let v: i64 = c
            .query_row("PRAGMA user_version", [], |r| r.get(0))
            .unwrap();
        assert_eq!(v as usize, MIGRATIONS.len());
    }
}
