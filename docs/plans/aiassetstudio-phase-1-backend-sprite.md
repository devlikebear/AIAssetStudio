# Phase 1: 백엔드 뼈대 + 투명 스프라이트 — 작업지시서

_이 페이즈의 목표를 달성하기 위한 구체적 작업 목록. Claude Code가 위에서부터 순서대로 실행하되, 체크포인트에서 사용자 확인을 받는다._

_작성일: 2026-09-24_
_속한 로드맵: [`aiassetstudio-roadmap.md`](./aiassetstudio-roadmap.md)_
_예상 소요: 약 14시간_

## 페이즈 목표

`uv run aiassetstudio serve`로 백엔드를 띄우고 HTTP API로 프로젝트를 만든 뒤 스프라이트·아이콘 생성을 요청하면, 작업이 대기열을 거쳐 ComfyUI(Qwen-Image-2.1 + Viggle Turbo 6스텝)로 생성된다. 결과는 `data/projects/<slug>/assets/<asset_id>/`에 원본·후처리본·미리보기 PNG로 저장되고, 후처리본의 배경 알파는 0이다. 이 페이즈가 끝나면 MCP 없이도 스모크 스크립트 하나로 투명 스프라이트를 뽑을 수 있다.

## 전제 조건

- [x] ComfyUI가 `http://127.0.0.1:8188`에서 실행 중이다. 꺼져 있으면 `<ComfyUI 경로>\run_comfyui.bat`로 띄운다. 자동 실행은 Phase 2에서 만든다.
- [x] 로드맵의 "설치된 모델" 표에 있는 이미지 모델 4종과 `custom_nodes/viggle_turbo.py`가 있다.
- [x] uv 0.12 이상, git이 설치돼 있다. (2026-09-24 기준 uv 0.12.5, git 2.55 확인)
- [x] 저장소 루트는 `<저장소 경로>`다. 이미 `docs/plans/`, `spikes/`, `.claude/launch.json`이 있고 git 저장소는 아니다.

## 포함 기능

1. 프로젝트 프리셋(기본 항목) — 이름, 슬러그, 화풍 문구, 내보내기 폴더. 픽셀 규격·참고 이미지 컬럼은 DB에 미리 만들어 두고 로직은 Phase 3에서 채운다.
2. 이미지 에셋 생성 — 스프라이트·아이콘, 투명 배경 프롬프트, 후보 여러 장, 알파 정리·여백 정리·미리보기
3. 작업 대기열 — 워커 하나, GPU 작업은 한 번에 하나, 제한 시간, 취소, 유휴 시 `/free`
4. ComfyUI 사전 점검 — 필요한 노드와 모델 파일 확인

## 이 페이즈에서 하지 않는 것

- MCP 서버, 웹 갤러리, 내보내기, 백엔드·ComfyUI 자동 실행 → Phase 2
- 픽셀아트 정리, 참고 이미지 → Phase 3
- BGM, 모델 계열 전환 시 `/free` → Phase 4
- 에셋 조작용 CLI → Out of Scope

## 작업 체크리스트

### 작업 그룹 A: 프로젝트 세팅

- [x] **T1.A.1** — git 저장소와 uv 프로젝트 초기화
  - 파일: `pyproject.toml`, `.python-version`, `.gitignore`, `src/aiassetstudio/__init__.py`, `README.md`
  - 내용:
    - `git init` 후 `uv init --package --name aiassetstudio --python 3.13`로 src 레이아웃을 만든다. `uv init`이 만든 예제 코드는 지운다.
    - 의존성: `uv add fastapi "uvicorn[standard]" httpx pillow numpy pydantic`
    - 개발 의존성: `uv add --dev pytest pytest-asyncio ruff`
    - `pyproject.toml`에 추가:
      - `[project.scripts] aiassetstudio = "aiassetstudio.cli:main"`
      - `[tool.pytest.ini_options]`: `asyncio_mode = "auto"`, `markers = ["gpu: 실제 ComfyUI와 GPU가 필요한 테스트"]`, `addopts = "-m 'not gpu'"`, `testpaths = ["tests"]`
      - `[tool.ruff]`: `line-length = 120`, `target-version = "py313"`
    - `.gitignore`: `.venv/`, `data/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/`, `web/node_modules/`, `web/dist/`, `*.log`
    - `README.md`는 한 줄 소개와 "계획은 `docs/plans/aiassetstudio-roadmap.md`"만 적는다. 나머지는 Phase 2·4에서 채운다.
  - 검증: `uv run python -c "import aiassetstudio"` 성공, `uv run ruff check .` 통과

- [x] **T1.A.2** — 설정 모듈
  - 파일: `src/aiassetstudio/config.py`, `tests/test_config.py`
  - 내용:
    - `@dataclass(frozen=True) class Settings`와 `def load_settings() -> Settings`. 환경 변수에서 읽고 없으면 기본값을 쓴다.

      | 필드 | 환경 변수 | 기본값 |
      |---|---|---|
      | `host` | `AIAS_HOST` | `127.0.0.1` |
      | `port` | `AIAS_PORT` | `8765` |
      | `data_dir` | `AIAS_DATA_DIR` | `<저장소 루트>/data` (`Path(__file__).resolve().parents[2] / "data"`) |
      | `comfy_url` | `AIAS_COMFY_URL` | `http://127.0.0.1:8188` |
      | `comfy_dir` | `AIAS_COMFY_DIR` | `<ComfyUI 경로>` (Phase 2 자동 실행용) |
      | `idle_free_seconds` | `AIAS_IDLE_FREE_SECONDS` | `60` |
      | `image_timeout` | `AIAS_IMAGE_TIMEOUT` | `300` (초) |
      | `bgm_timeout` | `AIAS_BGM_TIMEOUT` | `600` (초) |

  - 검증: `uv run pytest tests/test_config.py` — 기본값과 환경 변수 덮어쓰기 2케이스

### 작업 그룹 B: ComfyUI 연동

- [x] **T1.B.1** — 비동기 ComfyUI 클라이언트
  - 파일: `src/aiassetstudio/comfy/__init__.py`, `src/aiassetstudio/comfy/client.py`, `tests/fakes.py`, `tests/test_comfy_client.py`
  - 내용:
    - `class ComfyClient`: 생성자 `(base_url: str, transport: httpx.AsyncBaseTransport | None = None)`. 테스트에서 `transport`로 가짜 ComfyUI를 주입한다.
    - 메서드:
      - `async system_stats() -> dict` — `GET /system_stats`
      - `async is_up() -> bool` — 연결 실패·타임아웃이면 False
      - `async object_info() -> dict` — `GET /object_info`
      - `async list_models(folder: str) -> list[str]` — `GET /models/{folder}`
      - `async submit(graph: dict) -> str` — `POST /prompt` 본문 `{"prompt": graph, "client_id": <세션 uuid>}`, `prompt_id` 반환. 응답의 `node_errors`가 비어 있지 않거나 400이면 `ComfyPromptError(node_errors)`
      - `async wait(prompt_id: str, timeout: float, poll: float = 1.0) -> dict` — `GET /history/{prompt_id}`를 `status.completed`가 채워질 때까지 폴링. `status_str == "error"`면 `status.messages`의 `execution_error`에서 `exception_type`·`exception_message`를 꺼내 `ComfyExecutionError`. 시간을 넘기면 `ComfyTimeout`. 성공 시 history 항목(dict) 반환
      - `async fetch_output(filename: str, subfolder: str, type_: str = "output") -> bytes` — `GET /view`
      - `async free(unload_models: bool = True, free_memory: bool = True) -> None` — `POST /free`
      - `async interrupt() -> None` — `POST /interrupt`
    - 예외: `ComfyUnavailable`(연결 실패), `ComfyPromptError`, `ComfyExecutionError`, `ComfyTimeout`. 모두 `ComfyError`를 상속한다.
    - `tests/fakes.py`에 `FakeComfy` 클래스를 만든다. `httpx.MockTransport`용 핸들러로 위 엔드포인트를 흉내 낸다.
      - `/prompt`는 받은 그래프를 기록하고 새 `prompt_id`를 준다.
      - `/history/{id}`는 SaveImage 노드(`"9"`) 출력으로 `{"filename": ..., "subfolder": "aiassetstudio", "type": "output"}`을 돌려준다.
      - `/view`는 256×256 RGBA PNG를 만들어 돌려준다. 배경 알파는 2~6의 잔여값, 가운데 사각형은 불투명.
      - 실패를 흉내 내는 옵션(`fail_with="error" | "node_errors" | "hang"`)을 둔다.
  - 참조: `spikes/rgba_test.py`의 `post`·`get`·`run`, ComfyUI `server.py`의 라우트(`/prompt`, `/history/{prompt_id}`, `/view`, `/free`, `/interrupt`, `/object_info`, `/models/{folder}`, `/system_stats`)
  - 검증: `uv run pytest tests/test_comfy_client.py` — 제출 성공, `node_errors`, 실행 오류, 타임아웃, `fetch_output` 5케이스

- [x] **T1.B.2** — 이미지 API 그래프 빌더
  - 파일: `src/aiassetstudio/comfy/graphs.py`, `tests/test_graphs.py`
  - 내용:
    - 모델 파일 이름을 상수로 둔다: `QWEN_UNET`, `QWEN_TE`, `QWEN_VAE`, `VIGGLE_LORA` (로드맵 표의 파일명)
    - `def qwen_t2i_turbo(prompt: str, seed: int, prefix: str, width: int = 1024, height: int = 1024) -> dict` — `spikes/rgba_test.py`의 `graph(..., turbo=True)`를 그대로 옮긴다. 노드 구성: `UNETLoader` → `ViggleTurboLora`(strength 1.0) → `BasicGuider`, `CLIPLoader`(type `qwen_image`) → `TextEncodeQwenImage21`(negative_prompt `""`, resolution 1024), `EmptyLatentImage`, `RandomNoise`, `KSamplerSelect`(euler), `ViggleTurboSigmas`(nodes `"1.0, 0.9375, 0.875, 0.75, 0.5, 0.25"`), `SamplerCustomAdvanced`, `VAEDecode`, `SaveImage`
    - SaveImage 노드 id를 `QWEN_OUTPUT_NODE = "9"`로 공개한다.
    - `filename_prefix`는 `f"aiassetstudio/{prefix}"`로 해서 ComfyUI 출력이 `output/aiassetstudio/` 아래에 모이게 한다.
  - 검증: `uv run pytest tests/test_graphs.py` — 모든 링크 `[node_id, index]`가 존재하는 노드를 가리키는지, 시드·프롬프트·크기가 들어갔는지

- [x] **T1.B.3** — 사전 점검
  - 파일: `src/aiassetstudio/comfy/preflight.py`, `tests/test_preflight.py`
  - 내용:
    - `REQUIRED: dict[str, Requirement]` — 이번 페이즈는 `"qwen"` 계열만. 노드: `UNETLoader`, `CLIPLoader`, `VAELoader`, `TextEncodeQwenImage21`, `EmptyLatentImage`, `ViggleTurboLora`, `BasicGuider`, `RandomNoise`, `KSamplerSelect`, `ViggleTurboSigmas`, `SamplerCustomAdvanced`, `VAEDecode`, `SaveImage`. 모델: 폴더별 파일(`diffusion_models`, `text_encoders`, `vae`, `loras`)
    - `async def check(client: ComfyClient) -> dict[str, FamilyStatus]` — `FamilyStatus(ok: bool, missing_nodes: list[str], missing_models: list[str])`. ComfyUI가 꺼져 있으면 모든 계열을 `ok=False`, 사유 `"comfyui_down"`으로.
    - 이유: ComfyUI를 업데이트하다 노드 이름이 바뀌면 생성이 조용히 실패한다. 빠진 것을 이름으로 알려주는 게 목적이다.
  - 검증: `uv run pytest tests/test_preflight.py` — 모두 있음, 노드 누락, 모델 누락, ComfyUI 꺼짐 4케이스

### 작업 그룹 C: 저장소

- [x] **T1.C.1** — SQLite 스키마와 저장 함수
  - 파일: `src/aiassetstudio/store/__init__.py`, `src/aiassetstudio/store/db.py`, `src/aiassetstudio/store/models.py`, `tests/test_db.py`
  - 내용:
    - `class Database`: 생성자 `(path: Path)`. 표준 `sqlite3`, `check_same_thread=False`, `threading.Lock`으로 쓰기를 보호한다. `PRAGMA journal_mode=WAL`, `PRAGMA foreign_keys=ON`. `PRAGMA user_version`으로 스키마 버전 1을 기록한다.
    - 테이블:
      - `projects(id INTEGER PK, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, style TEXT NOT NULL DEFAULT '', export_dir TEXT, pixel_art INTEGER NOT NULL DEFAULT 0, logical_width INTEGER, logical_height INTEGER, icon_size INTEGER, max_colors INTEGER, palette TEXT, reference_image TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)` — 픽셀 규격·참고 이미지 컬럼은 Phase 3에서 쓴다.
      - `jobs(id TEXT PK, project_id INTEGER NOT NULL REFERENCES projects(id), kind TEXT NOT NULL, family TEXT NOT NULL, params TEXT NOT NULL, status TEXT NOT NULL, stage TEXT, error TEXT, timings TEXT, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT)` — `kind`: `image`|`bgm`, `family`: `qwen`|`ace`|`yue2`, `status`: `queued`|`running`|`done`|`failed`|`cancelled`
      - `assets(id TEXT PK, job_id TEXT NOT NULL REFERENCES jobs(id), project_id INTEGER NOT NULL REFERENCES projects(id), kind TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'candidate', seed INTEGER, files TEXT NOT NULL, meta TEXT NOT NULL, created_at TEXT NOT NULL)` — `kind`: `sprite`|`icon`|`bgm`, `status`: `candidate`|`selected`|`rejected`
    - id는 `uuid4().hex[:12]`. 시각은 UTC ISO 8601. JSON 컬럼은 `json.dumps(..., ensure_ascii=False)`.
    - `store/models.py`에 pydantic 모델 `Project`, `Job`, `Asset`.
    - 함수: `create_project`, `get_project(slug)`, `list_projects`, `update_project(slug, **fields)`, `create_job`, `get_job`, `list_jobs(project=None, statuses=None)`, `next_queued_job(prefer_family: str | None)`, `update_job(job_id, **fields)`, `mark_stale_running_failed()`, `create_asset`, `get_asset`, `list_assets(project=None, kind=None, status=None, job_id=None)`, `update_asset_status(asset_id, status)`
    - `next_queued_job`: `status='queued'` 중에서 `prefer_family`와 같은 계열을 먼저, 그다음 `created_at` 순.
  - 검증: `uv run pytest tests/test_db.py` — 프로젝트·작업·에셋 왕복, 슬러그 중복 거부, `next_queued_job`의 계열 우선순위, 오래된 running 정리

- [x] **T1.C.2** — 파일 배치 도우미
  - 파일: `src/aiassetstudio/store/files.py`, `tests/test_files.py`
  - 내용:
    - 배치: `data/studio.db`, `data/projects/<slug>/assets/<asset_id>/{raw.png, processed.png, preview.png}`, `data/logs/`
    - `validate_slug(slug)` — 정규식 `^[a-z0-9][a-z0-9-]{1,40}$`, 어기면 `ValueError`
    - `project_dir(settings, slug) -> Path`, `asset_dir(settings, slug, asset_id) -> Path`(없으면 만든다), `to_rel(settings, path) -> str`, `from_rel(settings, rel) -> Path`. DB에는 `data_dir` 기준 상대 경로를 저장한다.
  - 검증: `uv run pytest tests/test_files.py`

### 작업 그룹 D: 이미지 파이프라인

- [x] **T1.D.1** — 프롬프트 조립
  - 파일: `src/aiassetstudio/prompts.py`, `tests/test_prompts.py`
  - 내용:
    - Qwen-Image-2.1 모델 카드의 투명 이미지 형식: 앞 `"This is an RGBA image with transparency. "`, 뒤 `" The image has alpha channel and the background is transparent."`
    - 종류별 템플릿:
      - `sprite`: `"A single game sprite of {description}. Full body, centered, one subject only, no ground, no cast shadow, no text."`
      - `icon`: `"A single game item icon of {description}. Centered, the object fills about 80% of the frame, no frame, no border, no ring, no text."` — 2026-09-24 테스트에서 포션 아이콘에 요청하지 않은 둥근 유리 테두리가 생겼다. "no frame, no border, no ring"은 그 대응이다.
    - 프로젝트 화풍 문구가 있으면 `"Art style: {style}."`를 붙인다.
    - `def build_image_prompt(project: Project, kind: str, description: str) -> str`
  - 검증: `uv run pytest tests/test_prompts.py` — 앞뒤 투명 문구, 화풍 포함·생략, 종류별 문구

- [x] **T1.D.2** — 이미지 후처리 v1 (알파 정리)
  - 파일: `src/aiassetstudio/post/__init__.py`, `src/aiassetstudio/post/image.py`, `tests/test_post_image.py`
  - 내용:
    - `clean_alpha(img: Image.Image, threshold: int = 16) -> Image.Image` — 알파가 `threshold` 미만이면 0으로, 알파 0인 픽셀의 RGB도 0으로 만든다. 2026-09-24 실측에서 배경 알파가 0이 아니라 1~8(약 1%)로 남았다. RGB를 0으로 하는 이유는 게임 엔진이 이중선형 필터로 확대할 때 배경색이 가장자리로 번지지 않게 하기 위해서다. 유리처럼 원래 반투명한 부분(16 이상)은 그대로 둔다.
    - `alpha_stats(img) -> dict` — `transparent`(알파 0 비율), `opaque`(255 비율), `partial`(그 사이), `border_mean`(가장자리 32px 띠의 평균 알파)
    - `trim_to_content(img, pad: int = 8) -> Image.Image` — 알파>0 영역의 경계 상자에 여백을 붙여 자른다. 내용이 없으면 원본을 돌려준다.
    - `square_canvas(img, pad_ratio: float = 0.06) -> Image.Image` — 아이콘용. 정사각형 투명 캔버스 가운데에 놓는다.
    - `make_preview(img, max_side: int = 256) -> Image.Image` — 긴 변이 `max_side`를 넘으면 LANCZOS로 줄인다.
    - `process_image(raw: Image.Image, kind: str) -> Image.Image` — sprite: `clean_alpha` → `trim_to_content`, icon: `clean_alpha` → `trim_to_content` → `square_canvas`
  - 검증: `uv run pytest tests/test_post_image.py` — 잔여 알파 배경이 0이 되는지, 유리 같은 반투명(알파 100) 유지, 빈 이미지 처리, 미리보기 크기, 아이콘 정사각형

- [x] **T1.D.3** — 이미지 작업 실행기
  - 파일: `src/aiassetstudio/jobs/__init__.py`, `src/aiassetstudio/jobs/runners.py`, `tests/test_runners.py`
  - 내용:
    - `@dataclass class RunContext`: `db`, `comfy`, `settings`, `cancel_requested: Callable[[], bool]`
    - `async def run_image_job(ctx: RunContext, job: Job) -> None`
      - `params`: `kind`, `description`, `count`(1~8), `seed`(없으면 랜덤). 후보 i의 시드는 `seed + i`.
      - 한 작업의 후보들은 같은 프롬프트로 연속 제출한다. ComfyUI가 텍스트 인코딩 결과를 캐시하므로 텍스트 인코더를 한 번만 부른다. 프롬프트를 바꾸면 인코더를 다시 불러오다 190초가 걸린 사례가 있다.
      - 후보마다: 그래프 제출 → `wait(timeout=settings.image_timeout)` → 출력 이미지 `fetch_output` → `raw.png` 저장 → `process_image` → `processed.png` → `make_preview` → `preview.png` → `assets` 행 추가
      - 각 후보 전에 `stage`를 `"generating {i+1}/{count}"`로, 후처리 중에는 `"postprocess {i+1}/{count}"`로 갱신한다. 후보 사이에 `cancel_requested()`를 확인해 True면 `JobCancelled` 예외를 던진다.
      - 에셋 `meta`: `prompt`, `seed`, `models`(본체·텍스트 인코더·VAE·LoRA 파일명), `steps: 6`, `sampler: "euler"`, `comfy_prompt_id`, `alpha_raw`, `alpha_processed`(`alpha_stats` 결과), `timings`(단계별 초)
  - 검증: `uv run pytest tests/test_runners.py` — `FakeComfy`로 후보 2장 생성, 파일 3종 생성, meta 필드, 취소 시 중단

- [x] **T1.D.4** — 작업 대기열
  - 파일: `src/aiassetstudio/jobs/queue.py`, `tests/test_queue.py`
  - 내용:
    - `class JobQueue`: 생성자 `(db, comfy, settings, runners: dict[str, Runner])`. `Runner = Callable[[RunContext, Job], Awaitable[None]]`, 키는 `job.kind`.
    - `async start()` — `db.mark_stale_running_failed()`(재시작으로 끊긴 작업을 `failed`, 오류 `"interrupted by restart"`로)를 실행하고 워커 태스크를 띄운다. `async stop()` — 워커를 취소하고 기다린다.
    - `notify()` — 새 작업이 들어왔을 때 워커를 깨운다(`asyncio.Event`).
    - 워커 루프:
      1. `db.next_queued_job(prefer_family=self.current_family)`
      2. 없으면 `idle_free_seconds`까지 이벤트를 기다린다. 시간이 지났고 모델이 올라가 있으면 `comfy.free()` 후 `current_family = None`
      3. 있으면 `running` 표시 → `asyncio.wait_for(runner(ctx, job), timeout)`(image는 `image_timeout`, bgm은 `bgm_timeout`) → 성공 `done`, 시간 초과는 `comfy.interrupt()` 후 `failed`(`"timeout after N s"`), `JobCancelled`는 `cancelled`, 그 밖의 예외는 `failed`(예외 메시지)
      4. 끝나면 `current_family = job.family`, `models_loaded = True`
    - `async cancel(job_id) -> Job` — `queued`면 바로 `cancelled`. `running`이면 취소 플래그를 세우고 `comfy.interrupt()`를 부른다.
    - GPU 작업은 이 워커 하나만 한다. 동시에 두 작업을 돌리지 않는다.
    - ComfyUI가 꺼져 있으면 작업을 `failed`(오류 `"comfyui_down"`)로 기록한다. ComfyUI 자동 실행은 Phase 2(T2.A.2)에서 만들므로 이번 페이즈에서 미리 만들지 않는다.
  - 검증: `uv run pytest tests/test_queue.py` — 가짜 실행기로 FIFO 순서, 계열 우선, 시간 초과 → failed, 대기 중 취소, 실행 중 취소, 재시작 정리, 유휴 `free` 1회(테스트에서 `idle_free_seconds=0.2`)

### 작업 그룹 E: HTTP API와 실행

- [x] **T1.E.1** — FastAPI 앱
  - 파일: `src/aiassetstudio/api/__init__.py`, `src/aiassetstudio/api/app.py`, `src/aiassetstudio/api/schemas.py`, `tests/conftest.py`, `tests/test_api.py`
  - 내용:
    - `def create_app(settings: Settings, comfy_transport: httpx.AsyncBaseTransport | None = None) -> FastAPI`. lifespan에서 `Database` 열기, `ComfyClient` 만들기, `JobQueue.start()`, 종료 시 `stop()`.
    - 엔드포인트:

      | 메서드·경로 | 내용 |
      |---|---|
      | `GET /api/status` | `{"backend": "ok", "comfy": {"up": bool}, "preflight": {...}, "queue": {"running": id 또는 null, "queued": n}}` |
      | `POST /api/projects` | `{slug, name, style?, export_dir?}` → 201 + 프로젝트. 슬러그 중복 409, 형식 오류 422 |
      | `GET /api/projects`, `GET /api/projects/{slug}` | 목록, 단건(없으면 404) |
      | `PATCH /api/projects/{slug}` | `name`, `style`, `export_dir` 수정 |
      | `POST /api/jobs/image` | `{project, kind: "sprite"|"icon", description(1~500자), count=4(1~8), seed?}` → 202 + `{"job_id"}`. 대기열 `notify()` |
      | `GET /api/jobs/{id}?wait=0..60` | 작업 + 에셋 목록. `wait`초 동안 끝날 때까지 0.5초 간격으로 기다렸다가 응답(롱 폴링) |
      | `GET /api/jobs?project=&status=` | 목록. `status=active`는 queued+running |
      | `POST /api/jobs/{id}/cancel` | 취소 |
      | `GET /api/assets?project=&kind=&status=&job_id=` | 목록 |
      | `GET /api/assets/{id}`, `PATCH /api/assets/{id}` | 단건, `{status}` 변경 |
      | `GET /api/assets/{id}/files/{name}` | `raw`/`processed`/`preview` 파일 응답 |

    - 에셋 응답의 `files`는 파일 경로 대신 위 파일 URL로 준다.
    - 백엔드는 `127.0.0.1`에만 연다.
    - `tests/conftest.py`: 임시 `data_dir`의 `Settings`, `FakeComfy` transport를 넣은 `create_app`, `TestClient` 픽스처
  - 검증: `uv run pytest tests/test_api.py` — 프로젝트 생성 → 이미지 작업(count=2) → `?wait=10`으로 완료 → 에셋 2개와 파일 3종, 후처리본 테두리 알파 0 / 없는 프로젝트 404 / 잘못된 kind 422 / 취소

- [x] **T1.E.2** — 실행 명령
  - 파일: `src/aiassetstudio/cli.py`
  - 내용:
    - `argparse` 서브커맨드. `aiassetstudio serve [--host] [--port]`는 `uvicorn.run(create_app(load_settings()), ...)`.
    - `aiassetstudio check`는 ComfyUI 상태와 사전 점검 결과를 사람이 읽기 좋게 출력한다. 빠진 게 있으면 종료 코드 1.
    - Phase 2에서 `mcp` 서브커맨드를 추가한다.
  - 검증: `uv run aiassetstudio check` → ComfyUI 실행 중이면 `qwen: ok`

- [x] **T1.E.3** — 스모크 스크립트
  - 파일: `scripts/smoke_image.py`
  - 내용: 실행 중인 백엔드에 httpx로 요청한다. 프로젝트 `smoke`가 없으면 만들고, 스프라이트 2장을 요청한 뒤 `GET /api/jobs/{id}?wait=60`을 끝날 때까지 반복한다. 각 에셋의 파일 경로와 `alpha_processed`를 출력하고, 실패하거나 `border_mean`이 0이 아니면 종료 코드 1. PowerShell에서 JSON을 따옴표로 넘기는 번거로움을 피하려고 스크립트로 만든다.
  - 검증: 아래 Checkpoint의 수동 확인

- [x] **T1.E.4** — 실제 GPU 테스트
  - 파일: `tests/gpu/__init__.py`, `tests/gpu/test_image_e2e.py`
  - 내용: `@pytest.mark.gpu`. 실제 ComfyUI(`AIAS_COMFY_URL`)로 `create_app`을 띄우고 임시 프로젝트에 스프라이트 1장을 요청한다(`wait` 반복, 최대 300초). 후처리본의 테두리 32px 알파가 모두 0이고 불투명 픽셀 비율이 1% 이상인지 확인한다. ComfyUI가 꺼져 있으면 skip.
  - 검증: `uv run pytest -m gpu -k image`

---

## ✅ Phase 1 Checkpoint

**구현 확인:**
- [x] 모든 작업 체크박스 완료
- [x] 스프라이트·아이콘 요청이 대기열을 거쳐 순서대로 처리된다
- [x] 후처리본의 배경 알파가 0이고, 원래 반투명한 부분은 남아 있다
- [x] `aiassetstudio check`가 빠진 노드·모델을 이름으로 보여준다

**자동 검증:**
- [x] 전체 테스트: `uv run pytest`
- [x] 린트: `uv run ruff check .` 와 `uv run ruff format --check .`
- [x] GPU 테스트 (ComfyUI 실행 중): `uv run pytest -m gpu -k image`

**수동 확인:**
- [x] 터미널 1: `uv run aiassetstudio serve` / 터미널 2: `uv run python scripts/smoke_image.py` → 스프라이트 2장 생성, 종료 코드 0
- [x] `data/projects/smoke/assets/<id>/processed.png`를 열어 배경이 투명하고 피사체가 잘리지 않았는지 눈으로 확인
- [x] 생성 후 60초 넘게 아무 요청이 없으면 백엔드 로그에 `/free` 호출이 찍히고, `nvidia-smi`에서 ComfyUI의 VRAM 사용량이 내려간다

**완료 처리:**
1. 위 항목이 모두 통과하면 Claude Code는 사용자에게 완료한 작업, 자동 검증 결과, 수동 확인이 필요한 항목을 보고한다.
2. 사용자가 "Phase 1 완료, 다음 진행"이라고 승인하면 커밋하고 Phase 2로 간다.
3. 체크포인트가 실패하면 실패 항목을 보고하고, 원인을 분석해 수정한 뒤 다시 검증한다.

## 구현 메모 (2026-09-24, 사용자 승인 전)

계획과 다르게 한 것:
- **텍스트 인코딩을 별도 프롬프트로 먼저 실행** (`jobs/runners.py`, `comfy/graphs.py`의 `qwen_text_encode`): 작업마다 ① 인코딩 전용 프롬프트(`CLIPLoader` → `TextEncodeQwenImage21` → `PreviewAny`) → ② `POST /free {"unload_models": true, "free_memory": false}`(모델만 내리고 노드 캐시는 유지) → ③ 후보 그래프(캐시된 인코딩 재사용) 순서로 돈다. 체크포인트 뒤 포션 아이콘 작업이 VAE 디코드에서 6분 넘게 멈춰 300초 시간 초과로 실패했다. 샘플링은 13초였다. 로그를 보면 텍스트 인코더가 같은 프롬프트에서 돈 5번 중 3번 VAE 디코드가 40초~6분 이상 걸렸다(나머지는 1~2초). Windows에서 VRAM이 넘치면 OOM 대신 시스템 RAM으로 넘쳐 느려지므로, ComfyUI의 타일 디코드 대비책이 작동하지 않는 것으로 보인다. 분리 후 후보 10장의 디코드는 모두 0.7~1.0초였다(`spikes/encode_first_test.py`, 백엔드 실행 2회). 비용은 작업당 인코딩 약 5초 + 본체 재로드 약 4초. `VAEDecodeTiled`는 멈춤은 없었지만 스프라이트 몸통에 세로 이음새(알파 차이 최대 49)가 보여 쓰지 않았다(`spikes/vae_decode_test.py`). `PreviewAny`를 사전 점검 노드에 추가했다.
- **피사체와 떨어진 옅은 잡티 제거** (`post/image.py`의 `drop_detached_faint`, 의존성 `scipy` 추가): 2026-09-25 사용자 스모크 실행에서 한 장이 테두리 검사에 실패했다. 모델이 슬라임 뒤에 알파 8~15짜리 가로 띠를 그렸고, 띠 양 끝(화면 가장자리)의 알파 16~21 점들이 정리 뒤에도 남아 잘라내기가 화면 전체 폭(1024×553)이 되었다. 알파 16 이상 픽셀을 8방향으로 이어진 무리로 나누고, 알파 128 이상 픽셀이 16개 미만인 무리를 지운다(최대 알파가 낮은 반투명 피사체는 기준을 최대 알파의 절반으로 낮춘다). 피사체에 붙은 옅은 광채는 남는다. 기존 결과물 8장에 적용하면 그 한 장만 440×418로 바뀌고 나머지는 그대로다.
- **여백 8px → 32px** (`post/image.py`의 `TRIM_PAD`): 테두리 검사 띠가 32px인데 여백이 8px이면 잘라낸 스프라이트마다 `border_mean > 0`이 되어 스모크·API·GPU 검사가 모두 실패한다. 잘라내기는 캔버스를 늘리지 않으므로, 피사체가 원본 가장자리에 닿으면 여전히 `border_mean > 0`으로 드러난다. `alpha_stats`에 `border_max`를 더했다.
- **ComfyUI 중단은 이 앱의 프롬프트만**: `interrupt(prompt_id)`로 대상 지정, ComfyUI 대기열에 남은 프롬프트는 `delete_queued`로 뺀다. 프롬프트 id는 앱이 만들어 제출한다(응답 전에 취소돼도 대상을 안다). 다른 세션과 ComfyUI를 같이 쓰기 때문이다.
- **실행 중 취소는 작업 태스크를 바로 취소**: 프롬프트가 다른 세션 작업 뒤에서 기다리는 중이면 interrupt가 듣지 않아 제한 시간까지 매달리기 때문이다.
- 백엔드 종료 시 실행 중이던 작업은 `failed`("interrupted by shutdown")로 기록한다(재시작 정리는 계획대로).
- `/api/status`의 사전 점검은 60초 캐시(`/object_info`가 1.8MB, 약 0.8초).
- ruff 대상에서 `spikes/`, `docs/` 제외: ruff 0.16이 마크다운 코드 블록까지 포맷한다.
- Starlette 1.7 TestClient의 `httpx2` 권장 경고는 pytest 설정에서 숨겼다(앱은 계획대로 httpx).
- `.claude/launch.json`에 `backend`(`uv run aiassetstudio serve`, 8765) 추가.

그대로 둔 것(검토 필요):
- 작업 제한 시간은 계획대로 **작업 전체**에 `image_timeout`(300초)을 건다. 인코딩 분리 뒤 8장 작업은 약 65초(인코딩 5 + 재로드 4 + 8×7초) 예상이라 그대로 두었다. RAM 압박으로 느려지는 일이 다시 보이면 후보당 제한으로 바꾸는 것을 검토한다.
- **아이콘에 원형 테두리가 자주 생긴다.** 2026-09-24에 만든 아이콘 5장 중 4장에 원이나 붓자국 같은 호가 있었다(포션 4/4, 칼 1/2). "no frame, no border, no ring" 문구로는 막히지 않는다. 테두리는 본체와 떨어진 무리지만 대부분 불투명하게 그려져 있다(알파 중간값 144~255, 옅은 것은 1장). 칼 아이콘에서는 테두리가 칼보다 픽셀이 많았다. 그래서 위의 잡티 제거로도 지워지지 않는다. 잘라내기가 테두리까지 포함해 물체가 캔버스의 절반 크기로 들어간다. 테두리 검사는 정사각형 캔버스가 여백을 붙인 덕분에 통과한 것일 뿐이다. 스프라이트(슬라임·해골 10장)에는 없었다. 해결 후보: 아이콘 템플릿에서 "icon" 표현을 빼는 등 프롬프트 수정. Phase 3 "아이콘 규격" 작업과 함께 정할 것.
- 피사체 안쪽 알파가 255가 아니라 192~254인 픽셀이 많다(후처리본 부분 알파 35~54%). 픽셀아트는 Phase 3에서 이진 알파로 정리되지만, 일반 화풍 프로젝트에서는 피사체가 아주 약간 비쳐 보일 수 있다. 사용자 결정 필요.
- `/free` 플래그는 ComfyUI 전체에 걸린다. 인코딩 프롬프트를 낼 때 다른 세션의 프롬프트가 돌고 있으면, 모델 내리기가 그쪽 프롬프트 뒤에 적용된다. 그러면 이 앱의 인코딩 뒤에는 텍스트 인코더가 남아 있어 1장째가 예전처럼 멈출 수 있다. ComfyUI를 같이 쓸 때만 생기는 일이고, 그때는 시간 초과로 처리된다.
- Phase 4 참고: ACE-Step 그래프도 텍스트 인코더와 VAE 디코드가 한 프롬프트에 있다. 같은 멈춤이 보이면 같은 방식(인코딩 분리)을 검토할 것.

실측 (RTX 4090 Laptop):
- GPU 테스트: 스프라이트 1장 생성 12~16초, 원본 테두리 알파 평균 0.61 → 후처리 0.
- 스모크(인코딩 분리 후): 2장 24초 = 인코딩 약 5초 + 10.1초 + 7.1초. 분리 전에는 56초(1장째 48.6초, 그중 VAE 디코드 40.7초).
- 포션 아이콘 2장(분리 전에는 시간 초과로 실패): 인코딩 5.1초 + 11.2초 + 7.1초.
- 작업 종료 60초 뒤 `/free` 로그, VRAM 9.6~13.7GB → 1.3GB (2회 확인).

---

## 참고 자료

- 로드맵: [`aiassetstudio-roadmap.md`](./aiassetstudio-roadmap.md)
- UX 플로우: [`ux-flow.md`](./ux-flow.md)
- 실측 스크립트: `spikes/rgba_test.py` (그래프·제출·대기 로직의 원본)
- ComfyUI 라우트: `<ComfyUI 경로>\server.py`
- 투명 배경 실측(2026-09-24): 1024², 6스텝 약 18초. 배경 알파 1~8 잔여, 피사체 가장자리에 부분 알파

## 메모 / 주의

- ComfyUI가 다른 세션과 공유된다. 테스트 중 다른 세션이 GPU를 쓰고 있으면 GPU 테스트가 느려질 수 있다. 다른 프로세스를 강제로 끄지 않는다.
- ComfyUI의 출력 파일은 `ComfyUI/output/aiassetstudio/`에 남는다. 앱은 `/view`로 받아서 자기 `data/`에 저장하고, ComfyUI 쪽 파일은 지우지 않는다.
- DB 스키마의 픽셀 규격·참고 이미지 컬럼은 이번 페이즈에서 비워 둔다. 마이그레이션을 피하려고 미리 만든 것이다.

---
_다음 페이즈: Phase 2 — Claude Code 연결 + 갤러리 → [`aiassetstudio-phase-2-mcp-gallery.md`](./aiassetstudio-phase-2-mcp-gallery.md)_
