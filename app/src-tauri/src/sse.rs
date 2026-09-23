//! Incremental Server-Sent Events parser for the /v1/ask stream.

#[derive(Debug, Clone, PartialEq)]
pub struct SseEvent {
    pub event: String,
    pub data: String,
}

#[derive(Default)]
pub struct SseParser {
    buf: String,
}

impl SseParser {
    /// Feeds raw bytes (may split anywhere, even inside UTF-8 sequences — callers pass
    /// through `push_bytes`) and returns every complete event.
    pub fn push(&mut self, chunk: &str) -> Vec<SseEvent> {
        self.buf.push_str(&chunk.replace("\r\n", "\n"));
        let mut out = Vec::new();
        while let Some(end) = self.buf.find("\n\n") {
            let frame: String = self.buf.drain(..end + 2).collect();
            let mut event = String::from("message");
            let mut data: Vec<&str> = Vec::new();
            for line in frame.lines() {
                if let Some(v) = line.strip_prefix("event:") {
                    event = v.trim().to_string();
                } else if let Some(v) = line.strip_prefix("data:") {
                    data.push(v.strip_prefix(' ').unwrap_or(v));
                }
            }
            if !data.is_empty() {
                out.push(SseEvent {
                    event,
                    data: data.join("\n"),
                });
            }
        }
        out
    }
}

/// Accumulates bytes and only hands complete UTF-8 to the parser.
#[derive(Default)]
pub struct Utf8Buffer {
    pending: Vec<u8>,
}

impl Utf8Buffer {
    pub fn push_bytes(&mut self, bytes: &[u8]) -> String {
        self.pending.extend_from_slice(bytes);
        match std::str::from_utf8(&self.pending) {
            Ok(s) => {
                let s = s.to_string();
                self.pending.clear();
                s
            }
            Err(e) => {
                let valid = e.valid_up_to();
                let s = String::from_utf8_lossy(&self.pending[..valid]).into_owned();
                self.pending.drain(..valid);
                s
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_events_split_across_chunks() {
        let mut p = SseParser::default();
        assert!(p.push("event: transcript\ndata: {\"text\"").is_empty());
        let ev = p.push(":\"hi\"}\n\nevent: done\ndata: {}\n\n");
        assert_eq!(
            ev,
            vec![
                SseEvent {
                    event: "transcript".into(),
                    data: "{\"text\":\"hi\"}".into()
                },
                SseEvent {
                    event: "done".into(),
                    data: "{}".into()
                },
            ]
        );
    }

    #[test]
    fn handles_crlf_and_multiline_data() {
        let mut p = SseParser::default();
        let ev = p.push("event: x\r\ndata: a\r\ndata: b\r\n\r\n");
        assert_eq!(
            ev,
            vec![SseEvent {
                event: "x".into(),
                data: "a\nb".into()
            }]
        );
    }

    #[test]
    fn utf8_split_mid_character() {
        let bytes = "é—".as_bytes();
        let mut b = Utf8Buffer::default();
        let mut s = b.push_bytes(&bytes[..1]);
        s += &b.push_bytes(&bytes[1..4]);
        s += &b.push_bytes(&bytes[4..]);
        assert_eq!(s, "é—");
    }
}
