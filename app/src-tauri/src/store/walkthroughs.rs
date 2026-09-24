//! Local walkthrough library (the .nudgy JSON documents).

use rusqlite::{params, OptionalExtension};
use serde::Serialize;

use super::{Result, Store};

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct WalkthroughRow {
    pub id: String,
    pub title: String,
    pub app: String,
    pub steps: i64,
    pub share_url: Option<String>,
    pub created_at: i64,
}

impl Store {
    pub fn walkthrough_save(
        &self,
        id: &str,
        title: &str,
        app: &str,
        json: &str,
        now: i64,
    ) -> Result<()> {
        self.with(|c| {
            c.execute(
                "INSERT INTO walkthroughs (id, title, app, json, created_at, updated_at) VALUES (?1, ?2, ?3, ?4, ?5, ?5)
                 ON CONFLICT(id) DO UPDATE SET title = excluded.title, app = excluded.app,
                   json = excluded.json, updated_at = excluded.updated_at",
                params![id, title, app, json, now],
            )
            .map(|_| ())
        })
    }

    pub fn walkthrough_list(&self) -> Result<Vec<WalkthroughRow>> {
        self.with(|c| {
            let mut st = c.prepare(
                "SELECT id, title, app, json_array_length(json, '$.steps'), share_url, created_at
                 FROM walkthroughs ORDER BY updated_at DESC",
            )?;
            let rows = st.query_map([], |r| {
                Ok(WalkthroughRow {
                    id: r.get(0)?,
                    title: r.get(1)?,
                    app: r.get(2)?,
                    steps: r.get(3)?,
                    share_url: r.get(4)?,
                    created_at: r.get(5)?,
                })
            })?;
            rows.collect()
        })
    }

    pub fn walkthrough_get(&self, id: &str) -> Result<Option<String>> {
        self.with(|c| {
            c.query_row("SELECT json FROM walkthroughs WHERE id = ?1", [id], |r| {
                r.get(0)
            })
            .optional()
        })
    }

    pub fn walkthrough_delete(&self, id: &str) -> Result<()> {
        self.with(|c| {
            c.execute("DELETE FROM walkthroughs WHERE id = ?1", [id])
                .map(|_| ())
        })
    }

    pub fn walkthrough_set_share_url(&self, id: &str, url: &str) -> Result<()> {
        self.with(|c| {
            c.execute(
                "UPDATE walkthroughs SET share_url = ?2 WHERE id = ?1",
                params![id, url],
            )
            .map(|_| ())
        })
    }
}

#[cfg(test)]
mod tests {
    use crate::store::Store;

    #[test]
    fn crud() {
        let s = Store::in_memory().unwrap();
        s.walkthrough_save("w1", "Export PDF", "Word", r#"{"steps":[{},{}]}"#, 1)
            .unwrap();
        s.walkthrough_save("w2", "Incognito", "Chrome", r#"{"steps":[{}]}"#, 2)
            .unwrap();
        s.walkthrough_save("w1", "Export as PDF", "Word", r#"{"steps":[{},{},{}]}"#, 3)
            .unwrap();
        s.walkthrough_set_share_url("w1", "https://x/w/abc")
            .unwrap();
        let list = s.walkthrough_list().unwrap();
        assert_eq!(
            list.iter()
                .map(|w| (w.id.as_str(), w.steps))
                .collect::<Vec<_>>(),
            vec![("w1", 3), ("w2", 1)]
        );
        assert_eq!(list[0].title, "Export as PDF");
        assert_eq!(list[0].share_url.as_deref(), Some("https://x/w/abc"));
        s.walkthrough_delete("w2").unwrap();
        assert!(s.walkthrough_get("w2").unwrap().is_none());
        assert!(s.walkthrough_get("w1").unwrap().is_some());
    }
}
