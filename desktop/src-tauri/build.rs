fn main() {
    // bundle.resources lists backend/, which only scripts/freeze_backend.py fills; dev builds
    // without a frozen backend must still compile, so make sure the folder exists.
    std::fs::create_dir_all("backend").expect("can create the backend resource folder");
    tauri_build::build()
}
