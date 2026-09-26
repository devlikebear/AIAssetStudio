# AIAssetStudio — 코드베이스 분석

_이 문서는 이후 기획과 개발계획서 작성의 기반이다. 큰 변경이 있으면 갱신한다._

_작성일: 2026-09-25_
_분석 범위: 스프라이트 애니메이션 추가(sprite-gen + codex)에 필요한 부분. 작업 대기열·실행기, HTTP API, 저장소, MCP, 갤러리 작업 카드, 설정, 픽셀 후처리. LAST LIGHT 게임의 프레임 규약(읽기만)._

## 프로젝트 개요

- **목적 (한 줄)**: 이 PC의 ComfyUI 모델로 인디게임 에셋(투명 스프라이트·아이콘, 픽셀아트 규격, 반복 BGM·보컬 곡)을 만드는 개인용 스튜디오다. Claude Code가 MCP로 요청하고, 사람은 웹 갤러리에서 보고 고른다.
- **주 기술 스택**
  - 백엔드: Python, FastAPI + uvicorn, httpx(ComfyUI HTTP), SQLite(stdlib `sqlite3`)
  - 후처리: Pillow·numpy·scipy(이미지), soundfile·librosa·ffmpeg(오디오)
  - MCP: MCP Python SDK v2(`mcp.server.mcpserver.MCPServer`)
  - 갤러리: React 19 + Vite 8 + TypeScript 6(oxlint)
- **버전 / 런타임**: Python 3.13(uv, `.venv`), Node 22
- **빌드 도구**: uv, npm scripts(`web/package.json`: `build` = `tsc -b && vite build`, `lint` = oxlint)
- **실행 방식**
  - 백엔드 웹 서버(`python -m aiassetstudio serve`, 127.0.0.1:8765)가 ComfyUI(8188)를 부른다.
  - MCP stdio 서버(`python -m aiassetstudio mcp`)는 백엔드가 없으면 `detach.spawn_detached`(WMI)로 세션 밖에서 띄운다.
  - 갤러리는 백엔드가 `web/dist`를 `/`에 서빙한다.

## 디렉토리 구조 (관련 영역)

```
AIAssetStudio/
├── src/aiassetstudio/
│   ├── config.py              ← Settings(AIAS_* 환경 변수)
│   ├── api/
│   │   ├── app.py             ← POST /api/jobs/{image,bgm}, 에셋 파일·내보내기, EXPORT_FILES, MEDIA_TYPES
│   │   └── schemas.py         ← ImageJobCreate, BgmJobCreate, AssetOut
│   ├── jobs/
│   │   ├── queue.py           ← 단일 작업자, 모델 계열(family) 우선, 계열 전환 시 /free, ComfyUI 자동 실행
│   │   └── runners.py         ← RUNNERS = {"image": run_image_job, "bgm": run_bgm_job}
│   ├── post/image.py          ← pixelate(find_pixel_grid, ground), reference_ground, process_image
│   ├── store/
│   │   ├── models.py          ← JobKind·Family·AssetKind Literal
│   │   ├── db.py              ← projects·jobs·assets(kind·family는 TEXT 열)
│   │   └── files.py           ← asset_dir, to_rel/from_rel, unique_stem
│   ├── mcp_bridge/
│   │   ├── server.py          ← 도구 12개(인자 설명), INSTRUCTIONS
│   │   ├── tools.py           ← 도구 로직, get_job 텍스트·미리보기
│   │   └── studio_api.py      ← 백엔드 HTTP 클라이언트
│   └── detach.py, cli.py
├── web/src/
│   ├── api.ts, format.ts
│   └── components/            ← JobGroup(종류별 카드 분기), CandidateCard, AudioCard, DetailModal
├── tests/                     ← pytest(가짜 ComfyUI fakes.py), tests/gpu(실제 GPU, -m gpu)
└── scripts/smoke_mcp.py       ← MCP 종단검증
```

## 주요 모듈 / 파일

| 모듈 / 파일 | 역할 | 비고 |
|---|---|---|
| `jobs/queue.py` | GPU 작업 하나씩. `next_queued_job(prefer_family)`, 작업마다 ComfyUI 자동 실행, 계열이 바뀌면 `/free`, 60초 유휴면 `/free` | 클라우드 작업은 ComfyUI가 필요 없다. 실행·해제를 건너뛸 방법이 있어야 한다 |
| `jobs/runners.py` | 작업 하나를 에셋으로 바꾼다. 후보 루프, 단계(stage) 갱신, meta·timings, `asset_dir`에 파일 | `run_bgm_job`이 외부 도구(ffmpeg)를 쓰는 본보기다 |
| `api/app.py` | 작업 생성(`create_job(project_id, kind, family, params)` → `queue.notify()`), 파일 제공, 내보내기 | `EXPORT_FILES`가 종류별로 내보낼 파일 묶음을 정한다(BGM은 WAV+OGG를 한 이름으로) |
| `store/models.py` | `JobKind = image, bgm`, `Family = qwen, ace, yue2`, `AssetKind = sprite, icon, bgm` | 새 종류는 Literal만 늘리면 된다(DB는 TEXT) |
| `post/image.py` | 격자 찾기, 원래 크기 복원, 정수배, 발 줄(`ground`), 색 제한 | 애니메이션 프레임의 축척·발 줄·팔레트 맞추기에 다시 쓸 수 있다 |
| `mcp_bridge/tools.py` | `generate_bgm`, `_song_text`, `_pixel_note` | 결과를 Claude가 읽을 텍스트와 미리보기로 만든다 |
| `web/src/components/JobGroup.tsx` | `asset.kind === 'bgm'`이면 AudioCard, 아니면 CandidateCard | 새 AnimationCard 분기 자리 |

## 코딩 컨벤션

### 네이밍
- **파일명**: snake_case(`post/image.py`), TS 컴포넌트는 PascalCase(`AudioCard.tsx`)
- **타입명**: PascalCase(`PixelSpec`, `GridAxis`, `RunContext`)
- **함수/변수**: Python은 snake_case(`run_bgm_job`), TS는 camelCase(`pixelFitText`)
- **상수**: UPPER_SNAKE(`GRID_MAX_MIXED`, `EXPORT_FILES`). 실측 근거를 주석에 적는다.

### 에러 핸들링
- 도메인 예외를 쓴다: `ComfyError`/`ComfyUnavailable`, `JobCancelled`, `ReferenceImageError`, `AudioEncodeError`.
- API는 `HTTPException(status, "영어 문장")`, MCP는 `BackendError` → `ToolError`다.
- 대기열이 예외를 받아 작업 `status="failed"`, `error=str(e)`로 남긴다.
- 외부 도구 실패가 전체 실패가 아닐 때는 meta에 남기고 계속한다.
  ```python
  try:
      encode_ogg(directory / f"{stem}.wav", directory / f"{stem}.ogg", ffmpeg)
      files[f"{stem}_ogg"] = f"{stem}.ogg"
  except AudioEncodeError as e:  # keep the WAV; the song took half a minute or more of GPU time
      stats["ogg_error"] = str(e)
  ```

### 로깅
- **라이브러리**: stdlib `logging`(`log = logging.getLogger(__name__)`)
- **포맷**: plain text, %-포맷(`log.info("job %s started (%s/%s)", ...)`). MCP 로그는 `data/logs/mcp.log`다.
- **레벨 컨벤션**: 정상 흐름은 info, 복구 가능한 실패는 warning, 예상 못 한 크래시는 exception

### 주석 스타일
- **언어**: 코드 주석과 docstring은 영어, 문서(docs/plans)는 한국어다.
- **형식**: 모듈·함수 docstring에 "왜"와 실측(날짜, 수치)을 적는다.
- **밀도**: 결정 근거가 있는 곳에 짧게 단다.
- **사용자 문구**: 갤러리는 한국어, MCP 텍스트는 영어(Claude가 읽음)다.

### Import 정렬
- **도구**: ruff(isort 규칙), `ruff format`
- **그룹핑**: 표준 라이브러리, 서드파티, 로컬(상대 import `..store.db`)

## 테스트 전략

- **위치**: 별도 `tests/`(`test_<모듈>.py`), 실제 GPU 테스트는 `tests/gpu/`(marker `gpu`, 기본 제외)
- **스타일**: 단위와 통합을 섞는다. 백엔드 흐름은 가짜 ComfyUI(`tests/fakes.py`의 `FakeComfy`, httpx MockTransport)로 끝까지 돌린다(`test_runners.py`, `test_mcp_tools.py`).
- **비동기**: pytest-asyncio `asyncio_mode = "auto"`
- **목(mock)**: 전송 계층을 갈아 끼운다(`transport=fake.transport`). `monkeypatch`로 모듈 속성을 바꾼다.
- **실행 명령**: `uv run pytest`(현재 171개), `uv run pytest -m gpu`

## 빌드 / 검증 명령 (개발계획서 Checkpoint에 활용)

| 목적 | 명령 |
|---|---|
| 테스트 실행 | `uv run pytest` |
| GPU 테스트 | `uv run pytest -m gpu`(ComfyUI 대기열이 비었을 때) |
| 린트 | `uv run ruff check .` / `npm --prefix web run lint` |
| 포맷 | `uv run ruff format --check .` |
| 갤러리 빌드 | `npm --prefix web run build` |
| 로컬 실행 | `uv run python -m aiassetstudio serve`(개발용), 사용자 백엔드는 MCP `studio_status`가 띄운다 |
| 종단검증 | `$env:AIAS_PORT="8766"; $env:AIAS_DATA_DIR="<임시>"; uv run python scripts/smoke_mcp.py ...` |

## 기존 유사 기능 (모방 대상)

| 새 기능 | 모방 대상 | 어떤 부분을 모방 |
|---|---|---|
| 애니메이션 작업 API | `POST /api/jobs/bgm` + `BgmJobCreate` | 요청 검증, 작업 생성(kind·family·params), `queue.notify()` |
| 애니메이션 실행기 | `run_bgm_job`(`jobs/runners.py`) | 후보 루프, stage 갱신, 외부 도구 호출과 실패 처리, meta·timings, 파일 역할 매핑 |
| sprite-gen 호출 | `post/audio.encode_ogg`(ffmpeg subprocess), `detach.py` | 외부 CLI를 부르고 오류를 도메인 예외로 바꾸는 방식 |
| 프레임 규격 맞추기 | `post/image.pixelate`, `reference_ground`, `find_pixel_grid` | 축척, 발 줄, 팔레트, 격자 |
| 갤러리 카드 | `AudioCard.tsx` + `JobGroup.tsx` 분기 | 종류별 카드. 새 AnimationCard는 GIF 재생 |
| MCP 도구 | `generate_bgm` + `_song_text` | 작업 등록 도구, 결과 설명 텍스트, "사용자가 갤러리에서 확인" 안내 |
| 내보내기 | `EXPORT_FILES["bgm"]`(WAV+OGG를 한 이름으로) | 아틀라스 PNG와 manifest JSON(과 프레임 PNG)을 한 이름으로 |
| 종단검증 | `scripts/smoke_mcp.py --bgm` | MCP로 생성, 확인, 내보내기 한 바퀴 |

## sprite-gen (외부 도구, 2026-09-25 시험)

- 설치 위치와 성격
  - `<sprite-gen 경로>`에 있다(Apache-2.0, 2.9.0, 얕은 복제).
  - 전용 가상환경 `.venv`와 CLI `.venv\Scripts\sprite-gen.exe`가 있다. AIAssetStudio와 의존성을 나누려면 import하지 않고 subprocess로 부른다.
- 흐름
  - `prepare`: base 그림, 칸 32, 12색, 발 정렬. `sprite-request.json`, 상태별 프롬프트, 배치 가이드를 만든다.
  - `gen-set --provider codex`: 상태마다 가로 줄 1장을 `raw/<state>.png`에 쓴다.
  - `extract`: 크로마 또는 투명 배경을 빼고, 픽셀 격자를 맞추고, 12색 팔레트를 고정한다.
  - `compose-atlas`: `sprite-sheet-alpha.png`와 `manifest.json`(`frame_layout.rows[state]`의 x·y·w·h, fps·loop)을 만든다.
  - `preview`: `qa/<state>.gif`를 만든다.
- 결과는 JSON 한 개를 stdout에 쓴다(`ok`, `errors`, `warnings`).
- codex 경로
  - PATH에서 먼저 잡히는 `codex`는 예전 독립 설치본 0.147.0이라, Codex 앱의 새 설정(`~/.codex/config.toml`)을 읽지 못한다.
  - Codex 앱에 포함된 CLI를 사용한다. 설치 경로는 `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`에서 찾는다.
  - sprite-gen은 `shutil.which("codex")`로 찾으므로, 하위 프로세스 PATH 앞에 올바른 폴더를 붙이면 된다.
- 품질과 시간(그림자 적 1장, 32×32)
  - codex로 idle·정면 걷기·공격이 모두 성공했다. 한 줄에 62~86초, 3줄 동시에 87초다.
  - 다만 프레임이 약 20×29로 기본 그림(17×26)보다 15% 크다(높이 29칸 cap 경고).
  - 로컬 Qwen은 idle만 성공했다(줄 한 장 약 10초). 걷기·공격은 실패했다.

## 게임 쪽 프레임 규약 (LAST LIGHT, 읽기 전용 참고)

- `Tools/build_campaign_art.py`가 캐릭터마다 32×32(보스 48×48) 10프레임을 만든다.
  - 0~3번은 대기다. 1px 위아래 흔들림 `[0,0,-1,-1]`.
  - 4~9번은 이동이다. 발 아래 8줄을 좌우 반씩 `[0,1,1,0,-1,-1]`로 번갈아 밀고, 흔들림도 이어진다.
- 모두 기본 포즈 한 장을 코드로 움직인 것이다. 발은 `size-3-높이` 자리, 즉 32줄 중 28번째 줄에 선다.
- 출력
  - 프레임 파일: `ArtSource/LastLight/<이름>/<줄×10+프레임:03>.png`
  - 아틀라스: `Assets/_Game/Resources/CampaignArt/<이름>.png`(가로 10칸 × 줄 수)
- 색: 고정 팔레트 20색(`PALETTE`)
- 방향
  - keeper는 4줄이다(정면, 오른쪽, 뒤, 왼쪽).
  - 그림자 적 3종은 정면 1줄씩이다.
  - Aseprite 원본(태그, 프레임 시간)은 `Tools/archive_campaign_art.lua`가 만든다.

## 주의 사항 / 특이점

- **로컬 전용 원칙**
  - MCP `INSTRUCTIONS`가 "local models (no cloud)"라고 적혀 있다.
  - 애니메이션을 codex로 하면 기본 그림이 OpenAI로 나가므로, 문구와 동의 흐름을 바꿔야 한다.
- **대기열은 GPU용 단일 작업자다.**
  - 클라우드 작업을 그대로 넣으면 ComfyUI 자동 실행과 계열 전환 `/free`가 괜히 일어난다.
  - 60~90초 동안 GPU 작업도 기다리게 된다.
- **작업 시간 제한**: 이미지는 300초, BGM은 600초(`Settings`)다. 애니메이션은 줄 수 × 약 90초에 여유를 더해야 한다.
- **`Asset.files`**: 역할 → 경로다(이미지는 `raw/processed/preview.png`, BGM은 역할마다 이름). `MEDIA_TYPES`에 `.gif`·`.json`이 있는지 확인해야 한다(Windows mimetypes가 빠뜨리는 형식이 있다는 주석).
- **MCP 코드 변경**: 새 Claude Code 세션을 열어야 반영된다. 백엔드 코드 변경은 8765 백엔드를 다시 띄워야 한다.
- **Literal**: `JobKind`, `Family`, `AssetKind`와 `list_assets`의 kind 필터(API `Literal["sprite","icon","bgm"]`, MCP 같음)를 함께 늘려야 한다.
- 게임 프로젝트 파일은 검증 중 변경하지 않는다. 에셋 내보내기는 프로젝트 `export_dir`로 한다.

## 관련 문서

- README: `README.md`
- 인수인계: `docs/plans/aiassetstudio-handoff.md`
- 로드맵: `docs/plans/aiassetstudio-roadmap.md`(Out of Scope: "4방향 시트, 애니메이션 프레임"이 첫 확장 후보)
- 작업지시서 형식: `docs/plans/aiassetstudio-phase-{1,2,3,4}-*.md`(T 번호 작업, Checkpoint, 구현 메모)
- 시험 기록: Claude 메모리 `aiassetstudio-sprite-gen-idea.md`

---
_이 문서는 애니메이션 개발계획서와 다음 세션에서 참조된다. 프로젝트 구조가 크게 바뀌면 갱신한다._
