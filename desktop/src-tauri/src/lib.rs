//! Desktop shell: start the Studio backend if it is not running, show the gallery, and
//! stop the backend on exit only when this shell started it.

use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent};

/// The backend this shell started, if any. An already-running backend is left alone.
struct SpawnedBackend(Mutex<Option<Child>>);

fn port() -> u16 {
    std::env::var("AIAS_PORT").ok().and_then(|v| v.parse().ok()).unwrap_or(8765)
}

/// GET /api/health and report whether it answered 200, without an HTTP client dependency.
fn healthy(port: u16) -> bool {
    let addr = format!("127.0.0.1:{port}");
    let Ok(mut stream) = TcpStream::connect_timeout(
        &addr.parse().expect("loopback address"),
        Duration::from_millis(500),
    ) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let request = format!("GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n");
    if stream.write_all(request.as_bytes()).is_err() {
        return false;
    }
    let mut response = [0u8; 64];
    let Ok(n) = stream.read(&mut response) else { return false };
    String::from_utf8_lossy(&response[..n]).starts_with("HTTP/1.1 200")
}

/// The repository checkout this shell lives in (dev shell: desktop/src-tauri -> repo root).
fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..")
}

fn spawn_backend(repo: &PathBuf) -> std::io::Result<Child> {
    let python = if cfg!(windows) {
        repo.join(".venv").join("Scripts").join("python.exe")
    } else {
        repo.join(".venv").join("bin").join("python")
    };
    let log_dir = repo.join("data");
    std::fs::create_dir_all(&log_dir)?;
    let log = std::fs::File::create(log_dir.join("desktop-backend.log"))?;
    let mut command = Command::new(python);
    command
        .args(["-m", "aiassetstudio", "serve"])
        .current_dir(repo)
        .stdin(Stdio::null())
        .stdout(Stdio::from(log.try_clone()?))
        .stderr(Stdio::from(log));
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    command.spawn()
}

fn show_error(window: &tauri::WebviewWindow, message: &str) {
    let script = format!("showError({})", serde_json::to_string(message).expect("a string serializes"));
    let _ = window.eval(&script);
}

/// Make sure the backend serves, then move the window from the loading page to the gallery.
fn start_and_navigate(app: tauri::AppHandle) {
    let port = port();
    let window = app.get_webview_window("main").expect("main window exists");
    if !healthy(port) {
        let repo = repo_root();
        match spawn_backend(&repo) {
            Ok(child) => *app.state::<SpawnedBackend>().0.lock().expect("not poisoned") = Some(child),
            Err(e) => {
                show_error(&window, &format!("백엔드를 시작하지 못했습니다: {e}\n\n{} 안의 .venv를 확인해 주세요.", repo.display()));
                return;
            }
        }
        let deadline = Instant::now() + Duration::from_secs(90);
        while !healthy(port) {
            if Instant::now() > deadline {
                show_error(
                    &window,
                    &format!(
                        "백엔드가 {port} 포트에서 응답하지 않습니다.\n로그: {}",
                        repo.join("data").join("desktop-backend.log").display()
                    ),
                );
                return;
            }
            std::thread::sleep(Duration::from_millis(500));
        }
    }
    let url = format!("http://127.0.0.1:{port}/").parse().expect("gallery url");
    if let Err(e) = window.navigate(url) {
        show_error(&window, &format!("갤러리를 열지 못했습니다: {e}"));
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .manage(SpawnedBackend(Mutex::new(None)))
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || start_and_navigate(handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");
    app.run(|app, event| {
        if let RunEvent::Exit = event {
            if let Some(mut child) = app.state::<SpawnedBackend>().0.lock().expect("not poisoned").take() {
                // The backend's lifespan teardown stops its TTS sidecar child process, but a hard kill
                // skips that teardown, so kill the whole process tree or the sidecar is orphaned.
                #[cfg(windows)]
                {
                    use std::os::windows::process::CommandExt;
                    let _ = Command::new("taskkill")
                        .args(["/PID", &child.id().to_string(), "/T", "/F"])
                        .creation_flags(0x0800_0000) // CREATE_NO_WINDOW
                        .output();
                }
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    });
}
