# AIAssetStudio desktop shell

A thin Tauri 2 shell: it starts the Studio backend from this checkout's `.venv` if it is not
already running, shows the existing gallery (`http://127.0.0.1:8765/`) in a window, and stops
the backend on exit only when the shell started it. No pipeline logic lives here.

```
npm install
npm run tauri dev
```

See [docs/plans/studio-desktop-shell.md](../docs/plans/studio-desktop-shell.md).
