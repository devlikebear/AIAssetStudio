//! Desktop shell: start the Studio backend if it is not running, show the gallery, check for
//! updates, and stop the backend on exit only when this shell started it.

use std::io::{Read, Write};
use std::net::TcpStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons};
use tauri_plugin_updater::UpdaterExt;

/// The backend this shell started, if any. An already-running backend is left alone.
struct SpawnedBackend(Mutex<Option<Child>>);

/// A Windows Job Object with KILL_ON_JOB_CLOSE: the spawned backend and all its descendants
/// (the TTS sidecar reparents when the backend dies first) go down with this shell even when the
/// shell is force-killed and the RunEvent::Exit taskkill never runs — the OS closes the handle.
#[cfg(windows)]
mod job {
    use std::os::windows::io::AsRawHandle;

    use windows_sys::Win32::Foundation::CloseHandle;
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JobObjectExtendedLimitInformation, SetInformationJobObject,
    };

    pub struct Job(*mut core::ffi::c_void);
    // The handle is a kernel object; using it from any thread is fine.
    unsafe impl Send for Job {}
    unsafe impl Sync for Job {}

    impl Job {
        pub fn new() -> Option<Job> {
            unsafe {
                let handle = CreateJobObjectW(std::ptr::null(), std::ptr::null());
                if handle.is_null() {
                    return None;
                }
                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                let set = SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    &info as *const _ as *const _,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                );
                if set == 0 {
                    CloseHandle(handle);
                    return None;
                }
                Some(Job(handle))
            }
        }

        pub fn assign(&self, child: &std::process::Child) {
            unsafe {
                AssignProcessToJobObject(self.0, child.as_raw_handle());
            }
        }
    }

    impl Drop for Job {
        fn drop(&mut self) {
            unsafe {
                CloseHandle(self.0);
            }
        }
    }
}

#[cfg(windows)]
struct BackendJob(Option<job::Job>);

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

/// The repository checkout this shell was built in (dev runs: desktop/src-tauri -> repo root).
fn repo_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..").join("..")
}

/// The backend command and its log folder: the bundled frozen exe when this is an installed app,
/// else the dev checkout's venv. The frozen backend keeps its data in %LOCALAPPDATA% (config.py).
fn backend_command(app: &tauri::AppHandle) -> std::io::Result<(Command, PathBuf)> {
    if let Ok(resources) = app.path().resource_dir() {
        let bundled = resources.join("backend").join("aiassetstudio-backend.exe");
        if bundled.is_file() {
            let mut command = Command::new(&bundled);
            command.arg("serve").current_dir(bundled.parent().expect("exe has a folder"));
            let logs = app.path().app_log_dir().map_err(std::io::Error::other)?;
            return Ok((command, logs));
        }
    }
    let repo = repo_root();
    let python = if cfg!(windows) {
        repo.join(".venv").join("Scripts").join("python.exe")
    } else {
        repo.join(".venv").join("bin").join("python")
    };
    let mut command = Command::new(python);
    command.args(["-m", "aiassetstudio", "serve"]).current_dir(&repo);
    Ok((command, repo.join("data")))
}

fn spawn_backend(mut command: Command, log_dir: PathBuf) -> std::io::Result<Child> {
    std::fs::create_dir_all(&log_dir)?;
    let log = std::fs::File::create(log_dir.join("desktop-backend.log"))?;
    command.stdin(Stdio::null()).stdout(Stdio::from(log.try_clone()?)).stderr(Stdio::from(log));
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    command.spawn()
}

/// Stop the backend this shell started, if any. The backend's lifespan teardown stops its TTS
/// sidecar child process, but a hard kill skips that teardown, so kill the whole process tree
/// or the sidecar is orphaned.
fn kill_spawned_backend(app: &tauri::AppHandle) {
    if let Some(mut child) = app.state::<SpawnedBackend>().0.lock().expect("not poisoned").take() {
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

fn show_error(window: &tauri::WebviewWindow, message: &str) {
    let script = format!("showError({})", serde_json::to_string(message).expect("a string serializes"));
    let _ = window.eval(&script);
}

/// Ask about a pending update and install it. The update replaces the bundled backend's files,
/// so the backend this shell started is stopped first or the installer finds them locked.
/// Any failure only logs: an unreachable update feed must never block the gallery.
fn check_updates(app: &tauri::AppHandle) {
    let updater = match app.updater() {
        Ok(updater) => updater,
        Err(e) => return eprintln!("updater unavailable: {e}"),
    };
    let update = match tauri::async_runtime::block_on(updater.check()) {
        Ok(Some(update)) => update,
        Ok(None) => return,
        Err(e) => return eprintln!("update check failed: {e}"),
    };
    let wanted = app
        .dialog()
        .message(format!(
            "새 버전 {}이(가) 있습니다 (현재 {}).\n지금 설치할까요? 설치 후 앱이 다시 시작됩니다.",
            update.version,
            app.package_info().version
        ))
        .title("AI Asset Studio 업데이트")
        .buttons(MessageDialogButtons::OkCancelCustom("설치".into(), "나중에".into()))
        .blocking_show();
    if !wanted {
        return;
    }
    kill_spawned_backend(app);
    match tauri::async_runtime::block_on(update.download_and_install(|_, _| {}, || {})) {
        // On Windows the installer takes over and the app exits by itself; restart() is the fallback.
        Ok(()) => app.restart(),
        Err(e) => {
            eprintln!("update install failed: {e}");
            if let Some(window) = app.get_webview_window("main") {
                show_error(&window, &format!("업데이트 설치에 실패했습니다: {e}\n앱을 다시 시작하면 다시 시도합니다."));
            }
        }
    }
}

/// Make sure the backend serves, then move the window from the loading page to the gallery.
fn start_and_navigate(app: tauri::AppHandle) {
    let port = port();
    let window = app.get_webview_window("main").expect("main window exists");
    if !healthy(port) {
        let (command, log_dir) = match backend_command(&app) {
            Ok(found) => found,
            Err(e) => return show_error(&window, &format!("백엔드를 찾지 못했습니다: {e}")),
        };
        let log_path = log_dir.join("desktop-backend.log");
        match spawn_backend(command, log_dir) {
            Ok(child) => {
                #[cfg(windows)]
                if let Some(job) = &app.state::<BackendJob>().0 {
                    job.assign(&child);
                }
                *app.state::<SpawnedBackend>().0.lock().expect("not poisoned") = Some(child);
            }
            Err(e) => return show_error(&window, &format!("백엔드를 시작하지 못했습니다: {e}")),
        }
        let deadline = Instant::now() + Duration::from_secs(90);
        while !healthy(port) {
            if Instant::now() > deadline {
                return show_error(
                    &window,
                    &format!("백엔드가 {port} 포트에서 응답하지 않습니다.\n로그: {}", log_path.display()),
                );
            }
            std::thread::sleep(Duration::from_millis(500));
        }
    }
    let url = format!("http://127.0.0.1:{port}/").parse().expect("gallery url");
    if let Err(e) = window.navigate(url) {
        return show_error(&window, &format!("갤러리를 열지 못했습니다: {e}"));
    }
    check_updates(&app);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default()
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .manage(SpawnedBackend(Mutex::new(None)));
    #[cfg(windows)]
    let builder = builder.manage(BackendJob(job::Job::new()));
    let app = builder
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || start_and_navigate(handle));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");
    app.run(|app, event| {
        if let RunEvent::Exit = event {
            kill_spawned_backend(app);
        }
    });
}
