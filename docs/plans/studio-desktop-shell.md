# Studio 데스크톱 셸 (Tauri)

2026-11-07, 사용자 결정으로 로드맵의 "데스크톱 앱은 만들지 않는다"를 번복하고 얇은 셸을 만들었다. 로드맵 Next 항목에 적어 둔 모양 그대로다: 기존 React 갤러리를 그대로 쓰고, Rust는 백엔드 실행과 종료만 맡는다.

## 무엇인가

`desktop/`의 Tauri 2 앱. 실행하면:

1. `127.0.0.1:8765`(또는 `AIAS_PORT`)의 `/api/health`를 확인한다.
2. 백엔드가 없으면 저장소의 `.venv\Scripts\python.exe -m aiassetstudio serve`를 자식 프로세스로 띄운다. 로그는 `data/desktop-backend.log`.
3. health가 200을 주면 창을 갤러리 `http://127.0.0.1:8765/`로 옮긴다. 그 전까지는 로딩 페이지(`desktop/src/index.html`).
4. 창을 닫으면 **셸이 직접 띄운 백엔드만** 종료한다. 이미 돌고 있던 백엔드(MCP나 CLI가 띄운 것)는 건드리지 않는다.

공정 로직, IPC, 트레이, 설치 프로그램, 자동 업데이트는 없다. 갤러리와 백엔드 코드는 바뀌지 않았다.

## 실행

```
cd desktop
npm install
npm run tauri dev
```

갤러리는 백엔드가 서빙하는 `web/dist`를 보므로, 갤러리를 고친 뒤에는 `web`에서 `npm run build`가 필요하다(개발 중 HMR이 필요하면 기존처럼 Vite 개발 서버를 따로 쓴다).

## 구조

- `desktop/src/index.html` — 로딩 페이지. Rust가 실패하면 `showError(message)`를 호출한다.
- `desktop/src-tauri/src/lib.rs` — health 확인(의존성 없는 소켓 HTTP), 백엔드 spawn/kill, 창 전환.
- 창이 원격 URL(`http://127.0.0.1:8765/`)을 보므로 Tauri IPC는 갤러리에 노출되지 않는다.

## 배포 (2026-11-07 추가)

포장 시험([`notes/studio-pyinstaller-freeze.md`](./notes/studio-pyinstaller-freeze.md)) 성공 후 릴리즈 파이프라인을 붙였다.

- **설치 폴더와 데이터 폴더는 분리된다**: productName이 "AI Asset Studio"라 NSIS가 `%LOCALAPPDATA%\AI Asset Studio`에 설치하고, frozen 백엔드 데이터는 `%LOCALAPPDATA%\AIAssetStudio\data`다. 처음에 productName이 AIAssetStudio였을 때 설치 폴더와 데이터 폴더가 겹쳐 업데이트·제거와 충돌했고, 그래서 이름을 띄어쓰기로 바꿨다.
- **포장**: `scripts/freeze_backend.py`가 임시 venv에 PyInstaller로 백엔드를 one-folder로 얼려 `desktop/src-tauri/backend/`(gitignore)에 놓고, `web/dist`를 exe 옆에 복사한 뒤 selftest를 돌린다. frozen 백엔드의 기본 `data_dir`는 `%LOCALAPPDATA%\AIAssetStudio\data`다(`config.py`의 frozen 분기).
- **셸의 분기**: 리소스에 `backend/aiassetstudio-backend.exe`가 있으면(설치된 앱) 그것을 띄우고 로그는 앱 로그 폴더에, 없으면(개발) 기존대로 체크아웃 `.venv`를 쓴다.
- **자동 업데이트**: `tauri-plugin-updater`. 갤러리가 뜬 뒤 GitHub 릴리즈의 `latest.json`을 확인하고, 사용자가 대화상자에서 동의하면 **셸이 띄운 백엔드를 먼저 종료하고**(설치 파일이 backend/*.dll을 덮어써야 하므로) 설치 후 재시작한다. 피드가 안 닿으면 로그만 남기고 갤러리는 그대로 연다. 서명 키는 개발 PC `%USERPROFILE%\.tauri\aiassetstudio.key`(백업 필수 — 잃으면 설치된 앱들이 영영 업데이트 못 받는다), 공개 키는 `tauri.conf.json`.
- **릴리즈 CI**: `.github/workflows/release.yml`. `desktop-v*` 태그를 푸시하면 windows 러너가 갤러리 빌드 → 백엔드 포장(selftest 포함) → `tauri-action`으로 설치 파일과 `latest.json`을 릴리즈에 올린다. 저장소 시크릿 `TAURI_SIGNING_PRIVATE_KEY`가 필요하다. 업데이터가 `/releases/latest/download/latest.json`을 보므로, 데스크톱 릴리즈가 저장소의 latest가 아니게 되면(다른 종류의 릴리즈를 올리면) 업데이트가 멈춘다.
- **설치된 앱의 데이터는 개발 데이터와 다르다**: frozen 기본 data_dir가 `%LOCALAPPDATA%`라서, MCP/CLI가 띄운 개발 백엔드가 이미 돌고 있을 때만 설치된 앱에서도 저장소의 프로젝트가 보인다. ComfyUI 경로도 `AIAS_COMFY_DIR` 환경 변수를 주지 않으면 설치 폴더 기준으로 찾는다.

## 알려진 한계
- 백엔드 기동 대기는 90초. 첫 import가 더 느린 PC면 로딩 페이지가 실패 메시지를 보여 주지만 백엔드는 계속 뜨는 중일 수 있다. 재실행하면 된다.
- 아이콘은 create-tauri-app 기본값이다.
- **종료는 우아하지 않다**: 이 셸은 이 코드베이스에서 처음으로 백엔드를 죽이는 주체다(MCP·CLI의 detach 경로는 절대 죽이지 않는다). Windows에서 `taskkill /T`로 트리를 함께 끝내 TTS 사이드카 고아는 막지만, FastAPI lifespan 정리는 건너뛴다. 작업이 도는 중에 창을 닫으면 그 작업은 중단되고 DB 상태 갱신도 생략된다. ComfyUI는 원래 detached라 영향 없다.
