# 백엔드 PyInstaller one-folder 포장 시험 (2026-11-07)

스크립트: `scripts/backend_launcher.py` (엔트리 + selftest; 시험 당시 `spikes/studio/pyinstaller_launcher.py`였고 정식 승격됨), 빌드는 `scripts/freeze_backend.py`. 데스크톱 셸(Tauri)을 개발 체크아웃 없이 배포할 수 있는지 보려고, `aiassetstudio serve` 백엔드를 PyInstaller one-folder로 얼려 봤다. **결론: 된다.** 숨은 임포트 수술 없이 한 번에 빌드됐고, 얼린 exe로 `/api/health` 200, 갤러리 `/`와 JS 번들 서빙, librosa·numba·soundfile 임포트와 numba 커널 컴파일(beat_track)까지 확인했다. 환경은 Windows 11, Python 3.13, PyInstaller 6.22.3(hooks-contrib 2026.9)이다.

## 구성

저장소 .venv는 건드리지 않고 임시 venv를 따로 만들었다.

```
uv venv <작업폴더>\venv --python 3.13
uv pip install --python <작업폴더>\venv\Scripts\python.exe <저장소> pyinstaller
```

엔트리는 `python -m aiassetstudio`와 같은 일을 하는 한 장짜리 런처(`from aiassetstudio.cli import main; main()`)에, serve만으로는 지나지 않는 무거운 오디오 스택을 검증하는 `selftest` 명령(librosa/numba/soundfile/scipy/reportlab 임포트 + `librosa.beat.beat_track` 실행)을 붙였다.

```
pyinstaller --noconfirm --onedir --name aiassetstudio-backend ^
  --collect-all librosa --collect-submodules uvicorn launcher.py
```

- `--collect-all librosa`, `--collect-submodules uvicorn`: librosa는 lazy_loader로, uvicorn은 importlib 문자열로 서브모듈을 골라서 선제로 넣었다. 빼면 깨지는지는 시험하지 않았다.
- scipy, soundfile(libsndfile DLL), numba/llvmlite는 hooks-contrib 기본 훅으로 전부 해결됐다. 추가 hidden-import 없음.
- 임시 venv는 uv.lock이 아니라 그 시점 최신으로 해석됐지만, librosa 1.0.0·reportlab 5.1.0 등 lock과 같은 버전이 잡혔다.
- 빌드 약 2분, 산출물 300MB.

## 결과

| 확인 | 결과 |
|---|---|
| `aiassetstudio-backend.exe selftest` | numpy 2.5.4, scipy 1.18.1, soundfile 0.14.0(libsndfile 1.2.2), numba 0.68.1, librosa 1.0.0, reportlab 5.1.0 전부 임포트, beat_track OK |
| `serve --port 8799 --data-dir <임시>` 후 `/api/health` | 200 `{"backend":"ok"}` |
| `/` (갤러리) | 200, index.html 서빙 (브라우저 렌더링은 안 봄) |
| `/assets/index-*.js` | 200, 277KB — StaticFiles 마운트 정상 |
| `/api/status`의 `repo_dir` | `<dist>\aiassetstudio-backend` — 아래 참조 |

빌드 경고는 무해한 것뿐: numba의 선택적 TBB 스레딩 레이어용 `tbb12.dll` 미발견(기본 스레딩 레이어로 동작), `tzdata`·`pycparser.lextab` 등 흔한 미발견 경고.

## frozen 환경의 REPO_ROOT

`config.py`의 `REPO_ROOT = Path(__file__).resolve().parents[2]`는 one-folder에서 `__file__`이 `<dist>\aiassetstudio-backend\_internal\aiassetstudio\config.pyc`가 되므로 **exe 폴더(`<dist>\aiassetstudio-backend`)를 가리킨다.** `/api/status`의 `repo_dir`로 실측 확인했다. 따라서:

- `GALLERY_DIST = REPO_ROOT/web/dist` → **exe 옆에 `web\dist`를 복사해 두면 그대로 서빙된다.** (이번 시험은 빌드 후 복사. `--add-data`는 `_internal` 밑에 넣어 경로가 어긋나므로 쓰지 않았다.)
- 기본 `data_dir = REPO_ROOT/data` → **exe 폴더 안에 데이터를 쓴다.** Program Files처럼 쓰기 금지인 곳에 설치하면 깨지므로, 배포 시에는 `--data-dir`나 `AIAS_DATA_DIR`로 `%LOCALAPPDATA%` 같은 사용자 폴더를 줘야 한다(Tauri 셸이 넘겨주면 됨).

## 배포까지 가려면 남는 일

1. **`serve --detach`와 MCP의 백엔드 자동 기동이 깨진다.** `mcp_bridge/studio_api.py:124`가 `[sys.executable, "-m", "aiassetstudio", ...]`로 백엔드를 띄우는데, frozen에서는 `sys.executable`이 exe 자신이고 `-m`을 모른다. `sys.frozen`이면 `[sys.executable, "serve", ...]`로 분기하면 된다. 전경 `serve`만 쓰는 Tauri 셸에는 당장 영향 없음.
2. `config.py`에 frozen 분기(`getattr(sys, "frozen", False)`)를 두고 data_dir 기본값을 사용자 폴더로 옮기는 편이 안전하다.
3. web/dist를 exe 옆에 놓는 복사 단계를 빌드 스크립트(또는 Tauri 번들)에 넣는다.
4. ComfyUI·기능 팩 venv·ffmpeg·sprite-gen 등 외부 실행 파일 경로는 이번 시험 범위 밖. frozen 백엔드에서도 전부 환경 변수/설정으로 바깥을 가리키므로 원리상 문제 없지만 실측은 안 했다.
5. 산출물 300MB는 numba/llvmlite(약 40MB+)·scipy가 대부분. librosa를 BGM 팩으로 분리하면 줄일 수 있으나 당장 필요하지는 않다.
