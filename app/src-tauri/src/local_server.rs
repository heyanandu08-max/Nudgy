//! The bundled server. The all-in-one installer puts `nudgy-server(.exe)` next to the app; when
//! it is there and Nudgy points at the default local address, Nudgy starts it in the
//! background (no window) and stops it on quit, so the app works on its own. With no keys
//! it runs in practice mode. Its settings file and database live in the app's data folder.
//!
//! Builds without the bundled server (development, the plain installer) skip all of this.

use std::net::{SocketAddr, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Manager, Runtime};

use crate::settings::SettingsStore;

/// The address the app uses by default (settings.rs).
const LOCAL_URL: &str = "http://127.0.0.1:8787";
const PORT: u16 = 8787;

#[derive(Default)]
pub struct LocalServer {
    child: Mutex<Option<Child>>,
}

fn program() -> Option<PathBuf> {
    let name = if cfg!(target_os = "windows") {
        "nudgy-server.exe"
    } else {
        "nudgy-server"
    };
    let path = std::env::current_exe().ok()?.parent()?.join(name);
    path.is_file().then_some(path)
}

/// The folder holding the bundled server's `.env` and database.
pub fn home<R: Runtime>(app: &AppHandle<R>) -> Option<PathBuf> {
    app.path().app_data_dir().ok().map(|d| d.join("server"))
}

fn port_in_use() -> bool {
    let addr = SocketAddr::from(([127, 0, 0, 1], PORT));
    TcpStream::connect_timeout(&addr, Duration::from_millis(300)).is_ok()
}

/// Pure rule, so it's testable: start only when bundled, pointed at the default address and
/// nothing is listening there yet (an already running server is simply used).
pub fn should_start(bundled: bool, backend_url: &str, port_busy: bool) -> bool {
    bundled && backend_url.trim_end_matches('/') == LOCAL_URL && !port_busy
}

fn spawn(exe: &PathBuf, home: &PathBuf) -> std::io::Result<Child> {
    std::fs::create_dir_all(home)?;
    let mut cmd = Command::new(exe);
    cmd.current_dir(home)
        .env("NUDGY_HOME", home)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd.spawn()
}

/// Starts the bundled server if it should run. Called once at startup.
pub fn start<R: Runtime>(app: &AppHandle<R>) {
    app.manage(LocalServer::default());
    let url = app.state::<SettingsStore>().get().backend_url;
    let Some(exe) = program() else { return };
    if !should_start(true, &url, port_in_use()) {
        return;
    }
    let Some(home) = home(app) else { return };
    match spawn(&exe, &home) {
        Ok(child) => {
            log::info!("started the bundled server (pid {})", child.id());
            *app.state::<LocalServer>().child.lock().unwrap() = Some(child);
        }
        Err(e) => log::error!("could not start the bundled server: {e}"),
    }
}

/// Stops the bundled server (on quit, or before a restart).
pub fn stop<R: Runtime>(app: &AppHandle<R>) {
    if let Some(state) = app.try_state::<LocalServer>() {
        if let Some(mut child) = state.child.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

/// Whether this install has the bundled server, and where its settings file is (for
/// Settings → About: "add your AI keys here").
#[tauri::command]
pub fn local_server_info(app: AppHandle) -> Option<String> {
    program()?;
    home(&app).map(|h| h.join(".env").to_string_lossy().into_owned())
}

/// Opens the bundled server's settings file (`.env`) in the default text editor.
#[tauri::command]
pub fn local_server_open_settings(app: AppHandle) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    let env = home(&app).ok_or("no data folder")?.join(".env");
    if !env.exists() {
        return Err(
            "The server hasn't created its settings file yet. Try again in a few seconds.".into(),
        );
    }
    app.opener()
        .open_path(env.to_string_lossy().into_owned(), None::<&str>)
        .map_err(|e| e.to_string())
}

/// Restarts the bundled server so edited settings (keys) take effect.
#[tauri::command]
pub fn local_server_restart(app: AppHandle) -> Result<(), String> {
    let exe = program().ok_or("This install has no bundled server")?;
    stop(&app);
    // Give the port a moment to free up.
    for _ in 0..20 {
        if !port_in_use() {
            break;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
    let home = home(&app).ok_or("no data folder")?;
    let child = spawn(&exe, &home).map_err(|e| e.to_string())?;
    *app.state::<LocalServer>().child.lock().unwrap() = Some(child);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::should_start;

    #[test]
    fn starts_only_when_bundled_local_and_free() {
        assert!(should_start(true, "http://127.0.0.1:8787", false));
        assert!(should_start(true, "http://127.0.0.1:8787/", false));
        assert!(
            !should_start(false, "http://127.0.0.1:8787", false),
            "not bundled"
        );
        assert!(
            !should_start(true, "https://api.nudgy.app", false),
            "remote server"
        );
        assert!(
            !should_start(true, "http://127.0.0.1:8787", true),
            "already running"
        );
    }
}
