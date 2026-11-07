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

## 알려진 한계 / 다음 단계

- **개발 체크아웃 전용**: 저장소 경로를 컴파일 시점(`CARGO_MANIFEST_DIR`)에 박는다. 배포하려면 로드맵 Next의 포장 작업이 먼저다 — PyInstaller로 `aiassetstudio serve`를 얼리는 시험(`librosa`→`numba`/`llvmlite`, `scipy`, `soundfile` DLL이 험로), 그다음 Tauri sidecar로 묶기.
- 백엔드 기동 대기는 90초. 첫 import가 더 느린 PC면 로딩 페이지가 실패 메시지를 보여 주지만 백엔드는 계속 뜨는 중일 수 있다. 재실행하면 된다.
- 아이콘은 create-tauri-app 기본값이다.
- **종료는 우아하지 않다**: 이 셸은 이 코드베이스에서 처음으로 백엔드를 죽이는 주체다(MCP·CLI의 detach 경로는 절대 죽이지 않는다). Windows에서 `taskkill /T`로 트리를 함께 끝내 TTS 사이드카 고아는 막지만, FastAPI lifespan 정리는 건너뛴다. 작업이 도는 중에 창을 닫으면 그 작업은 중단되고 DB 상태 갱신도 생략된다. ComfyUI는 원래 detached라 영향 없다.
