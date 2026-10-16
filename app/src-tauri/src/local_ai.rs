//! Nudgy's built-in AI: free models running on this PC, no API keys.
//!
//! The all-in-one installer ships two open-source engines next to the app (llama.cpp's
//! `llama-server` and whisper.cpp's `whisper-server`, in `engines/`). The models are too big
//! for the installer, so the first time the user turns the built-in AI on, Nudgy downloads them
//! once into its data folder (resumable, with progress). Then it starts both engines in the
//! background, points the bundled server at them (its `.env`), and restarts that server.
//! Every later launch starts the engines straight away.
//!
//! Builds without the engines (development, plain installers) report `unavailable`.

use std::collections::BTreeMap;
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, Runtime};

use crate::local_server;

pub const LLM_PORT: u16 = 8790;
pub const STT_PORT: u16 = 8791;

/// What gets downloaded on first use. Gemma 3 4B (vision, multilingual, commercial use allowed
/// under the Gemma terms) with its image projector, and Whisper base (MIT) for speech.
pub struct ModelFile {
    pub name: &'static str,
    pub url: &'static str,
    /// Rough size for the progress bar before the server reports the real one.
    pub approx_bytes: u64,
}

pub const MODELS: &[ModelFile] = &[
    ModelFile {
        name: "gemma-3-4b-it-Q4_K_M.gguf",
        url: "https://huggingface.co/ggml-org/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q4_K_M.gguf",
        approx_bytes: 2_490_000_000,
    },
    ModelFile {
        name: "mmproj-model-f16.gguf",
        url: "https://huggingface.co/ggml-org/gemma-3-4b-it-GGUF/resolve/main/mmproj-model-f16.gguf",
        approx_bytes: 851_000_000,
    },
    ModelFile {
        name: "ggml-base.bin",
        url: "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin",
        approx_bytes: 148_000_000,
    },
];

#[derive(Debug, Clone, Serialize, PartialEq)]
#[serde(tag = "state", rename_all = "snake_case")]
pub enum Status {
    /// This install has no engines (dev build or plain installer).
    Unavailable,
    /// Engines are here; the models have not been downloaded yet.
    NotSetUp {
        download_bytes: u64,
    },
    Downloading {
        file: String,
        done: u64,
        total: u64,
    },
    Starting,
    Ready,
    Failed {
        message: String,
    },
}

#[derive(Default)]
pub struct LocalAi {
    status: Mutex<Option<Status>>,
    engines: Mutex<Vec<Child>>,
}

fn exe(name: &str) -> String {
    if cfg!(target_os = "windows") {
        format!("{name}.exe")
    } else {
        name.to_string()
    }
}

fn engines_dir<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    let dir = app.path().resource_dir().ok()?.join("engines");
    let llama = dir.join("llama").join(exe("llama-server"));
    let whisper = dir.join("whisper").join(exe("whisper-server"));
    (llama.is_file() && whisper.is_file()).then_some(dir)
}

fn models_dir<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    app.path().app_data_dir().ok().map(|d| d.join("models"))
}

fn models_ready(dir: &Path) -> bool {
    MODELS.iter().all(|m| dir.join(m.name).is_file())
}

fn set<R: Runtime>(app: &AppHandle<R>, s: Status) {
    *app.state::<LocalAi>().status.lock().unwrap() = Some(s.clone());
    let _ = app.emit("ai-status", &s);
}

fn current<R: Runtime>(app: &AppHandle<R>) -> Status {
    let have = app.state::<LocalAi>().status.lock().unwrap().clone();
    have.unwrap_or(Status::Unavailable)
}

/// The keys the bundled server needs to use the engines. Only changes settings that are
/// still on practice mode or unset, so keys someone added by hand are kept.
pub fn env_with_local_ai(existing: &str) -> String {
    let wanted: BTreeMap<&str, String> = BTreeMap::from([
        ("NUDGY_LLM_PROVIDER", "local".to_string()),
        ("NUDGY_STT_PROVIDER", "local_whisper".to_string()),
        ("NUDGY_TTS_PROVIDER", "system".to_string()),
        (
            "NUDGY_LOCAL_LLM_URL",
            format!("http://127.0.0.1:{LLM_PORT}"),
        ),
        (
            "NUDGY_LOCAL_STT_URL",
            format!("http://127.0.0.1:{STT_PORT}"),
        ),
        ("NUDGY_MAX_ELEMENTS", "80".to_string()),
    ]);
    let replaceable = |key: &str, value: &str| {
        let v = value.trim();
        match key {
            "NUDGY_LLM_PROVIDER" | "NUDGY_STT_PROVIDER" | "NUDGY_TTS_PROVIDER" => {
                v.is_empty() || v == "fake" || v == "system"
            }
            _ => true,
        }
    };
    let mut seen = Vec::new();
    let mut out: Vec<String> = existing
        .lines()
        .map(|line| {
            let Some((key, value)) = line.split_once('=') else {
                return line.to_string();
            };
            let key = key.trim();
            match wanted.get(key) {
                Some(new) if !line.trim_start().starts_with('#') => {
                    seen.push(key.to_string());
                    if replaceable(key, value) {
                        format!("{key}={new}")
                    } else {
                        line.to_string()
                    }
                }
                _ => line.to_string(),
            }
        })
        .collect();
    let missing: Vec<_> = wanted
        .iter()
        .filter(|(k, _)| !seen.iter().any(|s| s == *k))
        .collect();
    if !missing.is_empty() {
        out.push(String::new());
        out.push("# Nudgy's built-in AI (set by the app)".into());
        out.extend(missing.into_iter().map(|(k, v)| format!("{k}={v}")));
    }
    out.join("\n") + "\n"
}

fn configure_server_env<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let home = local_server::home(app).ok_or("no data folder")?;
    fs::create_dir_all(&home).map_err(|e| e.to_string())?;
    let path = home.join(".env");
    let existing = fs::read_to_string(&path).unwrap_or_default();
    fs::write(&path, env_with_local_ai(&existing)).map_err(|e| e.to_string())
}

fn spawn_engine(program: &Path, args: &[String], log: &Path) -> std::io::Result<Child> {
    let mut cmd = Command::new(program);
    cmd.args(args)
        .current_dir(program.parent().unwrap_or(Path::new(".")))
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(
            fs::File::create(log)
                .map(Stdio::from)
                .unwrap_or(Stdio::null()),
        );
    local_server::hide_window(&mut cmd);
    cmd.spawn()
}

/// Starts both engines (if not already running) and switches the server over to them.
fn start_engines<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let engines = engines_dir(app).ok_or("This install has no built-in AI engines")?;
    let models = models_dir(app).ok_or("no data folder")?;
    set(app, Status::Starting);
    stop_engines(app);
    let threads = std::thread::available_parallelism()
        .map(|n| n.get().saturating_sub(1).max(1))
        .unwrap_or(4)
        .to_string();
    let m = |name: &str| models.join(name).to_string_lossy().into_owned();
    let llama = spawn_engine(
        &engines.join("llama").join(exe("llama-server")),
        &[
            "-m".into(),
            m(MODELS[0].name),
            "--mmproj".into(),
            m(MODELS[1].name),
            "--host".into(),
            "127.0.0.1".into(),
            "--port".into(),
            LLM_PORT.to_string(),
            "-c".into(),
            "8192".into(),
            "-t".into(),
            threads.clone(),
            "--jinja".into(),
        ],
        &models.join("llama-server.log"),
    )
    .map_err(|e| format!("could not start the AI engine: {e}"))?;
    let whisper = spawn_engine(
        &engines.join("whisper").join(exe("whisper-server")),
        &[
            "-m".into(),
            m(MODELS[2].name),
            "--host".into(),
            "127.0.0.1".into(),
            "--port".into(),
            STT_PORT.to_string(),
            "-t".into(),
            threads,
        ],
        &models.join("whisper-server.log"),
    )
    .map_err(|e| format!("could not start the speech engine: {e}"))?;
    *app.state::<LocalAi>().engines.lock().unwrap() = vec![llama, whisper];
    configure_server_env(app)?;
    local_server::restart(app)?;
    set(app, Status::Ready);
    log::info!("built-in AI started");
    Ok(())
}

pub fn stop_engines<R: Runtime>(app: &AppHandle<R>) {
    if let Some(state) = app.try_state::<LocalAi>() {
        for mut child in state.engines.lock().unwrap().drain(..) {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

/// At startup: work out the status, and start the engines if the models are already here.
pub fn init<R: Runtime>(app: &AppHandle<R>) {
    app.manage(LocalAi::default());
    let (Some(_), Some(models)) = (engines_dir(app), models_dir(app)) else {
        set(app, Status::Unavailable);
        return;
    };
    if models_ready(&models) {
        let app = app.clone();
        std::thread::spawn(move || {
            if let Err(e) = start_engines(&app) {
                log::error!("built-in AI: {e}");
                set(&app, Status::Failed { message: e });
            }
        });
    } else {
        let missing = MODELS
            .iter()
            .filter(|m| !models.join(m.name).is_file())
            .map(|m| m.approx_bytes)
            .sum();
        set(
            app,
            Status::NotSetUp {
                download_bytes: missing,
            },
        );
    }
}

async fn download<R: Runtime>(app: &AppHandle<R>, dir: &Path, m: &ModelFile) -> Result<(), String> {
    let target = dir.join(m.name);
    if target.is_file() {
        return Ok(());
    }
    let part = dir.join(format!("{}.part", m.name));
    let mut done = fs::metadata(&part).map(|md| md.len()).unwrap_or(0);
    let client = reqwest::Client::builder()
        .connect_timeout(std::time::Duration::from_secs(20))
        .build()
        .map_err(|e| e.to_string())?;
    let mut req = client.get(m.url);
    if done > 0 {
        req = req.header("Range", format!("bytes={done}-"));
    }
    let mut resp = req
        .send()
        .await
        .map_err(|e| format!("download failed (are you online?): {e}"))?;
    if !resp.status().is_success() {
        return Err(format!("download failed: {} ({})", resp.status(), m.name));
    }
    let resumed = resp.status() == reqwest::StatusCode::PARTIAL_CONTENT;
    if !resumed {
        done = 0;
    }
    let total = resp
        .content_length()
        .map(|n| n + done)
        .unwrap_or(m.approx_bytes);
    let mut file = fs::OpenOptions::new()
        .create(true)
        .append(resumed)
        .write(true)
        .truncate(!resumed)
        .open(&part)
        .map_err(|e| e.to_string())?;
    let mut last = 0u64;
    while let Some(chunk) = resp
        .chunk()
        .await
        .map_err(|e| format!("download interrupted: {e}"))?
    {
        file.write_all(&chunk)
            .map_err(|e| format!("couldn't save the download: {e}"))?;
        done += chunk.len() as u64;
        if done - last > 8_000_000 {
            last = done;
            set(
                app,
                Status::Downloading {
                    file: m.name.into(),
                    done,
                    total,
                },
            );
        }
    }
    file.flush().map_err(|e| e.to_string())?;
    drop(file);
    fs::rename(&part, &target).map_err(|e| e.to_string())
}

/// "Set up the built-in AI": downloads what's missing (resuming partial files), then starts it.
#[tauri::command]
pub async fn ai_setup(app: AppHandle) -> Result<(), String> {
    if matches!(current(&app), Status::Downloading { .. } | Status::Starting) {
        return Ok(());
    }
    engines_dir(&app).ok_or("This install has no built-in AI engines")?;
    let dir = models_dir(&app).ok_or("no data folder")?;
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let result: Result<(), String> = async {
        for m in MODELS {
            download(&app, &dir, m).await?;
        }
        let a = app.clone();
        tauri::async_runtime::spawn_blocking(move || start_engines(&a))
            .await
            .map_err(|e| e.to_string())?
    }
    .await;
    if let Err(e) = &result {
        set(&app, Status::Failed { message: e.clone() });
    }
    result
}

#[tauri::command]
pub fn ai_status(app: AppHandle) -> Value {
    json!(current(&app))
}

#[cfg(test)]
mod tests {
    use super::env_with_local_ai;

    #[test]
    fn switches_practice_mode_to_local_ai() {
        let env = "NUDGY_ENV=dev\nNUDGY_LLM_PROVIDER=fake\nNUDGY_STT_PROVIDER=fake\nNUDGY_TTS_PROVIDER=fake\n";
        let out = env_with_local_ai(env);
        assert!(out.contains("NUDGY_ENV=dev"));
        assert!(out.contains("NUDGY_LLM_PROVIDER=local\n"));
        assert!(out.contains("NUDGY_STT_PROVIDER=local_whisper\n"));
        assert!(out.contains("NUDGY_TTS_PROVIDER=system\n"));
        assert!(out.contains("NUDGY_LOCAL_LLM_URL=http://127.0.0.1:8790"));
        // Running it again changes nothing.
        assert_eq!(env_with_local_ai(&out), out);
    }

    #[test]
    fn keeps_keys_someone_set_up_by_hand() {
        let env =
            "NUDGY_LLM_PROVIDER=anthropic\nANTHROPIC_API_KEY=sk-x\n# NUDGY_STT_PROVIDER=fake\n";
        let out = env_with_local_ai(env);
        assert!(out.contains("NUDGY_LLM_PROVIDER=anthropic\n"));
        assert!(out.contains("ANTHROPIC_API_KEY=sk-x"));
        assert!(out.contains("# NUDGY_STT_PROVIDER=fake")); // comments untouched
        assert!(out.contains("NUDGY_STT_PROVIDER=local_whisper"));
    }

    #[test]
    fn writes_a_fresh_file_when_there_is_none() {
        let out = env_with_local_ai("");
        assert!(out.contains("NUDGY_LLM_PROVIDER=local"));
    }
}
