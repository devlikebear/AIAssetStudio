# Phase 2: Claude Code 연결 + 갤러리 — 작업지시서

_이 페이즈의 목표를 달성하기 위한 구체적 작업 목록. Claude Code가 위에서부터 순서대로 실행하되, 체크포인트에서 사용자 확인을 받는다._

_작성일: 2026-09-24_
_속한 로드맵: [`aiassetstudio-roadmap.md`](./aiassetstudio-roadmap.md)_
_예상 소요: 약 14시간_

## 페이즈 목표

사용자 범위로 등록한 MCP 서버로, 다른 게임 폴더에서 연 Claude Code 세션이 프로젝트를 만들고 이미지 생성을 요청하고 후보 미리보기를 직접 보고 게임 폴더로 내보낼 수 있다. 사람은 웹 갤러리에서 작업별 후보를 보고 고르거나 버린다. 백엔드가 꺼져 있으면 MCP 서버가 띄우고, ComfyUI가 꺼져 있으면 백엔드가 띄운다. 이 페이즈가 끝나면 앱의 기본 사용 흐름(시키기 → 보기 → 고르기 → 내보내기)이 처음부터 끝까지 돈다.

## 전제 조건

- [x] Phase 1 완료 및 사용자 승인
- [x] Node 22와 npm이 있다 (2026-09-24 기준 `<Node.js 설치 경로>`에 Node v22.23.2, npm 12.0.2)
- [x] Claude Code CLI(`claude`)가 있다 (2026-09-24 기준 2.1.270). MCP 등록은 사용자 설정을 바꾸는 일이므로 **등록 직전에 사용자 확인**을 받는다.

## 포함 기능

1. 내보내기 — 후처리본을 지정 폴더나 프로젝트 내보내기 폴더로 복사, 덮어쓰기 없음
2. 자동 실행 — MCP 서버가 백엔드를, 백엔드가 ComfyUI를 필요할 때 띄움
3. MCP 서버 — [UX 플로우](./ux-flow.md)의 도구 목록 (BGM 도구는 Phase 4)
4. 웹 갤러리 — 메인(작업별 후보, 필터, 대기열), 후보 상세, 프로젝트 정보(읽기 전용)

## 이 페이즈에서 하지 않는 것

- 픽셀 규격·참고 이미지 설정 → Phase 3 (MCP `create_project`·`update_project`에 인자를 추가하는 것도 Phase 3)
- `generate_bgm`, 오디오 카드 → Phase 4
- 갤러리에서 생성하기·프로젝트 편집하기 → Out of Scope

## 작업 체크리스트

### 작업 그룹 A: API 보강

- [x] **T2.A.1** — 내보내기
  - 파일: `src/aiassetstudio/api/app.py`, `src/aiassetstudio/api/schemas.py`, `src/aiassetstudio/store/files.py`, `tests/test_export.py`
  - 내용:
    - `POST /api/assets/{id}/export` 본문 `{dest_dir?: str, name?: str}` → `{"paths": [...]}`
    - 대상 폴더: `dest_dir`가 있으면 그것, 없으면 프로젝트의 `export_dir`. 둘 다 없으면 400 `"no export directory"`. 절대 경로만 받고, 없으면 만든다(`mkdir(parents=True, exist_ok=True)`).
    - 이미지 에셋은 `processed.png`를 복사한다. 파일 이름은 `name`이 있으면 영문 소문자·숫자·`_`·`-`만 남긴 `name`, 없으면 `{kind}_{project_slug}_{asset_id}`. 확장자는 원본을 따른다.
    - 같은 이름이 있으면 덮어쓰지 않고 `_2`, `_3`…을 붙인다.
    - 에셋 `meta.exports`에 `{path, at}`을 추가한다.
    - `files.unique_path(dir, stem, ext) -> Path` 도우미를 만든다.
  - 검증: `uv run pytest tests/test_export.py` — 프로젝트 폴더로 내보내기, `dest_dir` 지정, 이름 충돌 시 `_2`, 폴더 미지정 400, 상대 경로 거부

- [x] **T2.A.2** — ComfyUI 자동 실행
  - 파일: `src/aiassetstudio/comfy/launcher.py`, `tests/test_launcher.py`
  - 내용:
    - `class ComfyLauncher`: `async ensure(self) -> None`. 이미 떠 있으면 바로 돌아간다. 아니면 `settings.comfy_dir`의 `.venv\Scripts\python.exe main.py --port <comfy_url의 포트>`를 `cwd=comfy_dir`로 분리 실행하고, 출력은 `data/logs/comfyui.log`에 덧붙인다. 2초 간격으로 `is_up()`을 확인하며 최대 120초 기다린다.
    - Windows 분리 실행: `subprocess.Popen(..., creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True)`. ComfyUI는 백엔드가 꺼져도 계속 돈다(다른 세션과 공유하기 때문).
    - `asyncio.Lock`으로 두 번 띄우지 않게 한다. 경로가 없거나 120초 안에 안 뜨면 `ComfyUnavailable`(로그 경로 포함).
    - `JobQueue`가 작업을 실행하기 직전에 `ensure()`를 부른다. `GET /api/status?ensure=true`도 부른다.
  - 검증: `uv run pytest tests/test_launcher.py` — `Popen`과 `is_up`을 가짜로 바꿔서 이미 떠 있음, 띄우고 성공, 시간 초과, 경로 없음 4케이스

- [x] **T2.A.3** — 상태 정보 보강
  - 파일: `src/aiassetstudio/api/app.py`
  - 내용: `GET /api/status`에 `comfy.vram_free_mb`, `comfy.ram_free_mb`(ComfyUI `/system_stats`의 `devices[0].vram_free`, `system.ram_free`), 실행 중 작업의 `stage`와 경과 초, `gallery_url`(`http://127.0.0.1:8765/`)을 넣는다.
  - 검증: `tests/test_api.py`에 상태 응답 필드 검사 추가

### 작업 그룹 B: MCP 서버

- [x] **T2.B.1** — 백엔드 클라이언트와 자동 실행
  - 파일: `src/aiassetstudio/mcp_bridge/__init__.py`, `src/aiassetstudio/mcp_bridge/studio_api.py`, `src/aiassetstudio/__main__.py`, `tests/test_studio_api.py`
  - 패키지 이름을 `mcp`로 하지 않는다. 외부 SDK 패키지 `mcp`와 이름이 같아 헷갈리기 때문이다.
  - 내용:
    - 의존성 추가: `uv add "mcp>=2.2"` (MCP 공식 Python SDK v2. v1의 `FastMCP`는 v2에서 `MCPServer`로 이름이 바뀌었다)
    - `class StudioApi`: 생성자 `(base_url: str, transport: httpx.AsyncBaseTransport | None = None)`. 백엔드 REST 엔드포인트를 감싸는 메서드들(`status`, `list_projects`, `get_project`, `create_project`, `update_project`, `create_image_job`, `get_job(job_id, wait)`, `list_assets`, `set_asset_status`, `export_asset`, `cancel_job`, `get_file(asset_id, name) -> bytes`)
    - `async ensure_backend()`: `GET /api/status`(2초 제한)가 실패하면 `[sys.executable, "-m", "aiassetstudio", "serve"]`를 저장소 루트에서 분리 실행한다(출력은 `data/logs/backend.log`). 최대 30초 기다리고, 실패하면 로그 경로를 담은 오류를 낸다.
    - 두 Claude Code 세션이 동시에 백엔드를 띄우려 하면 두 번째 백엔드는 포트 충돌로 종료된다. 상태 확인만 성공하면 되므로 그대로 둔다.
    - `src/aiassetstudio/__main__.py`는 `cli.main()`을 부른다.
  - 검증: `uv run pytest tests/test_studio_api.py` — `httpx.ASGITransport`로 Phase 1 앱에 붙여 왕복 확인. FastAPI lifespan은 `async with app.router.lifespan_context(app):`로 직접 연다.

- [x] **T2.B.2** — MCP 도구
  - 파일: `src/aiassetstudio/mcp_bridge/tools.py`, `src/aiassetstudio/mcp_bridge/server.py`, `tests/test_mcp_tools.py`
  - 내용:
    - 도구 로직은 `tools.py`에 일반 async 함수(`async def generate_image(api: StudioApi, ...)`)로 만들고, `server.py`에서 `MCPServer`에 얇게 등록한다. 테스트는 `tools.py` 함수를 직접 부른다.
    - `server.py`:
      ```python
      from mcp.server.mcpserver import MCPServer
      from mcp.server.mcpserver.utilities.types import Image

      mcp = MCPServer("aiassetstudio")
      # @mcp.tool()로 아래 도구 등록
      def main() -> None:
          mcp.run(transport="stdio")
      ```
    - stdio 서버이므로 **stdout에는 아무것도 출력하지 않는다.** 로그는 stderr나 `data/logs/mcp.log`로 보낸다.
    - 모든 도구는 처음에 `ensure_backend()`를 부른다.
    - 도구와 반환 형식 (도구 설명은 Claude가 읽으므로 영어로 쓴다):

      | 도구 | 인자 | 반환 |
      |---|---|---|
      | `studio_status` | 없음 | 백엔드·ComfyUI 상태, 계열별 사전 점검, VRAM·RAM 여유, 대기열, 갤러리 URL (텍스트) |
      | `list_projects` / `get_project` | `slug` | 프로젝트 요약 (텍스트) |
      | `create_project` | `slug, name, style="", export_dir=None` | 만든 프로젝트 |
      | `update_project` | `slug, name=None, style=None, export_dir=None` | 고친 프로젝트 |
      | `generate_image` | `project, kind: Literal["sprite","icon"], description, count=4, seed=None` | 작업 id와 "`get_job(job_id, wait_seconds=60)`으로 기다리라, 한 장에 10~20초"라는 안내 |
      | `get_job` | `job_id, wait_seconds=30` (최대 60) | `list[str | Image]`: 첫 항목은 상태 요약 텍스트, 완료된 이미지 작업이면 에셋마다 `"asset <id> seed=<n>"` 텍스트와 `Image(data=<preview.png 바이트>, format="png")`(최대 8장). 마지막에 갤러리 링크 `http://127.0.0.1:8765/#/jobs/<id>` |
      | `list_assets` | `project, kind=None, status=None` | 에셋 요약 목록 (텍스트) |
      | `set_asset_status` | `asset_id, status: Literal["candidate","selected","rejected"]` | 고친 에셋 |
      | `export_asset` | `asset_id, dest_dir=None, name=None` | 복사된 파일 경로 |
      | `cancel_job` | `job_id` | 취소 결과 |

    - 미리보기는 `preview.png`(긴 변 256px 이하)만 보낸다. Claude Code의 MCP 결과 한도(`MAX_MCP_OUTPUT_TOKENS` 기본 25,000)를 넘지 않게 하려는 것이다.
    - `cli.py`에 `aiassetstudio mcp` 서브커맨드를 추가해 `server.main()`을 부른다.
  - 검증: `uv run pytest tests/test_mcp_tools.py` — `FakeComfy`를 넣은 앱에 `StudioApi`를 붙이고, 프로젝트 생성 → `generate_image`(count=2) → `get_job(wait_seconds=10)` 결과에 `Image` 2개와 갤러리 링크, `set_asset_status`, `export_asset` 파일 생성, `cancel_job`

- [x] **T2.B.3** — Claude Code 등록과 사용 안내
  - 파일: `README.md`
  - 내용:
    - README에 설치(`uv sync`, `npm --prefix web install`), 실행(`uv run aiassetstudio serve`), 점검(`uv run aiassetstudio check`), MCP 등록, 사용 예시 문장 3개를 적는다.
    - 등록 명령 (**사용자 확인 후 실행**. 사용자 범위 설정 `~/.claude.json`을 바꾼다):
      ```
      claude mcp add --transport stdio aiassetstudio --scope user -- uv --directory <저장소 경로> run aiassetstudio mcp
      ```
    - 확인: `claude mcp list`에 `aiassetstudio`가 연결됨으로 보인다. 이미 열려 있는 Claude Code 세션은 새로 열어야 도구가 보인다.
  - 검증: `claude mcp list` 출력

### 작업 그룹 C: 웹 갤러리

- [x] **T2.C.1** — 프로젝트 생성과 개발 서버 설정
  - 파일: `web/` (Vite React TS 템플릿), `web/vite.config.ts`
  - 내용:
    - `npx --yes create-vite@latest web --template react-ts` 후 `npm --prefix web install`. UI 라이브러리는 넣지 않는다.
    - `vite.config.ts`: 개발 서버 프록시 `'/api' → 'http://127.0.0.1:8765'`
    - 템플릿 예제 컴포넌트와 로고는 지운다.
  - 검증: `npm --prefix web run build` 성공

- [x] **T2.C.2** — API 클라이언트
  - 파일: `web/src/api.ts`
  - 내용: 백엔드 응답 타입(`Project`, `Job`, `Asset`, `Status`)과 함수(`getStatus`, `listProjects`, `getProject`, `listJobs(project)`, `listAssets(filters)`, `setAssetStatus`, `exportAsset`, `cancelJob`). 오류는 메시지를 담은 `ApiError`로 던진다.
  - 검증: `npm --prefix web run build` (타입 검사 포함)

- [x] **T2.C.3** — 갤러리 메인
  - 파일: `web/src/App.tsx`, `web/src/components/JobGroup.tsx`, `web/src/components/CandidateCard.tsx`, `web/src/components/QueuePanel.tsx`, `web/src/components/StatusBanner.tsx`, `web/src/App.css`
  - 내용:
    - 해시 라우팅: `#/p/<slug>`(프로젝트), `#/jobs/<id>`(해당 작업 묶음으로 스크롤하고 강조). 서버 쪽 라우팅이 필요 없게 하려는 것이다.
    - 상단: 프로젝트 선택, 종류(sprite/icon)·상태(후보/선택/버림) 필터
    - 본문: 작업별 묶음(작업 설명, 종류, 상태, 생성 시각) 안에 후보 카드 그리드. 카드 배경은 체크무늬(CSS `conic-gradient`). 픽셀아트 프로젝트면 `image-rendering: pixelated`. 카드에서 바로 고르기·버리기.
    - 오른쪽: 대기열 패널. `GET /api/jobs?status=active`를 2초마다 불러 실행 중 작업의 단계·경과 시간과 대기 목록을 보여준다. 최근 실패 작업은 오류 메시지와 함께 남긴다.
    - 상태별 화면은 [UX 플로우](./ux-flow.md)의 "갤러리 메인"을 따른다. 프로젝트가 없으면 Claude Code에 보낼 요청 예시와 MCP 등록 명령을 보여준다. 백엔드나 ComfyUI 문제는 상단 배너로 알린다.
    - 진행 중 작업은 자리 표시 카드로 보이고, 끝나면 후보로 바뀐다(목록을 3초 간격으로 다시 불러온다).
  - 검증: `npm --prefix web run build` / 수동: 아래 체크포인트

- [x] **T2.C.4** — 후보 상세와 프로젝트 정보
  - 파일: `web/src/components/DetailModal.tsx`, `web/src/components/ProjectInfo.tsx`
  - 내용:
    - 상세: 원본/후처리본 전환, 확대, 생성 기록(프롬프트·시드·모델·알파 통계), 고르기·버리기·내보내기(파일 이름 입력 선택). 내보낸 뒤 실제 경로나 오류를 보여준다. 같은 작업의 이전/다음 후보로 이동.
    - 프로젝트 정보: 화풍 문구, 내보내기 폴더 (읽기 전용. 편집은 MCP로)
  - 검증: `npm --prefix web run build`

- [x] **T2.C.5** — 백엔드에서 갤러리 서빙
  - 파일: `src/aiassetstudio/api/app.py`
  - 내용: API 라우트 뒤에 `StaticFiles(directory=<저장소>/web/dist, html=True)`를 `/`에 붙인다. `web/dist`가 없으면 `/`에서 "`npm --prefix web run build`를 먼저 실행하라"는 짧은 HTML을 준다.
  - 검증: 빌드 후 `uv run aiassetstudio serve` → 브라우저에서 `http://127.0.0.1:8765/`

---

## ✅ Phase 2 Checkpoint

**구현 확인:**
- [x] 모든 작업 체크박스 완료
- [x] 백엔드가 꺼진 상태에서 첫 MCP 도구 호출이 백엔드를 띄운다
- [ ] ComfyUI가 꺼진 상태에서 생성 요청을 하면 백엔드가 ComfyUI를 띄우고(120초 이내) 작업을 끝낸다 — 단위 테스트만, 실제 확인은 선택 항목으로 남김
- [x] 갤러리에서 고른 상태가 `list_assets`에 바로 반영된다

**자동 검증:**
- [x] 전체 테스트: `uv run pytest`
- [x] 린트: `uv run ruff check .` 와 `uv run ruff format --check .`
- [x] 갤러리 빌드: `npm --prefix web run build`
- [x] GPU 테스트: `uv run pytest -m gpu`

**수동 확인 (실제 Claude Code 세션):**
- [x] 사용자 확인 후 MCP를 사용자 범위로 등록하고 `claude mcp list`에서 연결 확인
- [x] 백엔드를 끈 상태로, 이 저장소가 아닌 다른 작업 폴더에서 새 Claude Code 세션을 연다
- [x] "에셋 스튜디오 상태 알려줘" → `studio_status`가 백엔드를 띄우고 상태를 보여준다
- [x] "demo 프로젝트 만들어줘. 화풍은 cute chibi fantasy, 내보내기 폴더는 `<저장소 경로>\data\exports\e2e`" → `create_project`
- [x] "칼 아이콘 4장 뽑아줘" → `generate_image` → `get_job`의 미리보기 4장이 대화에 보인다
- [x] 결과의 갤러리 링크를 열어 한 장을 고른다
- [x] "고른 아이콘 내보내줘" → `export_asset` → 해당 폴더에 PNG가 생긴다. 한 번 더 내보내면 `_2`가 붙는다

**완료 처리:**
1. 위 항목이 모두 통과하면 Claude Code는 사용자에게 완료한 작업, 자동 검증 결과, 수동 확인 결과를 보고한다.
2. 사용자가 "Phase 2 완료, 다음 진행"이라고 승인하면 커밋하고 Phase 3로 간다.
3. 체크포인트가 실패하면 실패 항목을 보고하고, 원인을 분석해 수정한 뒤 다시 검증한다.

## 구현 메모 (2026-09-25, 사용자 확인 전)

계획과 다르게 하거나 더한 것:
- **MCP 등록과 백엔드 자동 실행은 `python -m aiassetstudio ...`** 로 한다(`aiassetstudio.exe` 대신). 등록 명령은 `claude mcp add --transport stdio aiassetstudio --scope user -- uv --directory <저장소 경로> run python -m aiassetstudio mcp`이다. `aiassetstudio.exe`로 띄운 프로세스가 있으면 uv가 그 파일을 다시 쓰지 못해 `uv sync`/`uv add`가 실패한다(2026-09-25 실제로 겪음).
- **`GET /api/health` 추가**: MCP 서버의 백엔드 생존 확인용이다. `/api/status`는 ComfyUI에도 요청해서, ComfyUI가 멈추면 도구 호출마다 느려진다. 확인 제한 시간은 5초다(계획 2초). 포트가 응답하는데 200이 아니면(예: `/api/health`가 없는 Phase 1 백엔드) 새로 띄우지 않고 "예전 백엔드를 끄고 다시 시도"라는 오류를 바로 낸다. 새로 띄우면 포트 충돌로 30초만 기다리게 되기 때문이다.
- **ComfyUI 자동 실행은 작업 태스크 안에서, 실행기 제한 시간 밖에서** 한다. 띄우는 동안에도 취소할 수 있고, 최대 120초가 이미지 제한 시간(300초)을 깎지 않는다. 실패하면 `failed`, 오류는 `comfyui_down: <원인과 로그 경로>`(Phase 1은 `comfyui_down`만)이다. 테스트 설정은 `comfy_dir`를 없는 폴더로 둬서 실제 ComfyUI가 뜨지 않게 했다.
- `/api/status` 보강: `comfy.vram_free_mb`·`ram_free_mb`, `queue.current {id, project, kind, stage, elapsed_s}`(기존 `running` id는 유지), `gallery_url`, `?ensure=true`.
- `aiassetstudio serve --data-dir` 옵션을 더했다. `--host`·`--port`도 이제 `gallery_url`에 반영된다.
- `scripts/smoke_mcp.py` 추가: MCP 서버를 stdio로 띄워 도구 목록, 상태, (`--generate`) 생성, 미리보기, 고르기, 내보내기를 한 바퀴 돈다. 포트 8766과 임시 데이터로 GPU까지 통과했다. Python MCP 클라이언트는 서버를 Job Object(`KILL_ON_JOB_CLOSE`)로 묶어서 스크립트가 끝날 때 서버가 띄운 백엔드도 함께 끈다. 이것은 이 스크립트에서만 생기는 일이다. `uv run`은 자손을 죽이지 않았고(uv를 강제 종료해도 분리된 자식이 살아남음), 가상환경 python 런처의 Job은 `SILENT_BREAKAWAY_OK`다. Claude Code에서 세션을 닫았을 때 백엔드가 살아남는지는 수동 확인에서 볼 것.
- **갤러리**: "암실의 밀착 인화지" 디자인이다. 작업마다 필름 한 줄로 번호 붙은 프레임을 놓고, 고르면 노란 그리스펜슬 동그라미, 버리면 빨간 X를 그린다. 글꼴은 IBM Plex Sans KR·Mono를 `@fontsource`로 번들해 오프라인에서도 된다. 체크무늬 밝기 전환(브라우저 저장), 단계 이름 한국어 표시, "MCP 요청 문장 복사"(실패 작업·후보 상세), 휴대폰 폭 한 열 배치를 넣었다.
- 갤러리 안정성: 백그라운드 탭에서도 첫 로딩은 한다(이후 폴링만 쉰다). 대화상자는 비동기 `close` 이벤트에 기대지 않고 닫기 버튼·Esc(`cancel`)·배경 클릭에서 바로 닫는다. `#/jobs/<id>` 스크롤은 즉시 이동이다. 창이 가려진 미리보기에서 부드러운 스크롤과 `close` 이벤트가 멈추는 것을 확인하고 바꿨다.

수동 확인 결과 (2026-09-25, 별도 Claude Code 세션):
- 사용자가 MCP를 등록했고 `claude mcp list`에 `√ Connected`로 나왔다.
- 체크리스트 5단계를 모두 통과했다.
  - `studio_status`가 백엔드를 자동으로 띄웠다(09:59, `python -m aiassetstudio serve`).
  - demo 프로젝트를 만들었다. 없던 내보내기 폴더도 문제없었다.
  - 칼 아이콘 4장의 미리보기가 대화에 나왔다. 작업은 38초 걸렸다.
  - 갤러리 링크(앱 내 브라우저)에서 03을 골랐고, `list_assets`에 바로 반영됐다.
  - 두 번 내보내니 `icon_demo_688bacf87b03.png`와 `_2.png`가 생겼고 두 파일은 같다.
- 확인에서 나온 것:
  - **아이콘 여백이 두 번 붙었다.** 내보낸 칼 아이콘이 959×959였다. 32px 여백으로 자른 뒤 6%를 또 더했기 때문이다. 아이콘은 여백 없이 자른 뒤 "6%, 최소 32px"를 한 번만 두게 고쳤다(그 칼은 888×888). 크기는 여전히 내용 크기를 따른다. 고정 크기는 사용자 결정 (c)에 따라 Phase 3에서 프로젝트 `icon_size`를 일반 프로젝트에도 적용해 맞춘다.
  - 시작 시 VRAM 여유가 3.6GB였다. Claude의 GPU 테스트가 모델을 올린 채 끝났기 때문이다. 이제 백엔드는 종료할 때 모델이 올라가 있으면 `/free`를 부른다.
  - 4장 중 2장에 원형 테두리가 있었다(알려진 문제, Phase 3).
  - MCP가 띄운 백엔드가 10:09:22 무렵 종료 기록 없이 사라졌다. 다른 프로젝트 세션도 Claude(이 저장소 세션)도 끄는 명령은 없었고, Windows 오류 이벤트도 없었다. 원인은 모른다. 다음 MCP 호출 때 자동으로 다시 뜬다. 10:15에 새 코드로 다시 띄웠고, 오래 살아 있는지 지켜볼 것.
- 하지 않은 것: ComfyUI 자동 실행(선택), 세션을 닫은 뒤 백엔드 생존 확인(선택).

후속 수정 (2026-09-25, 백엔드가 사라진 원인):
- Claude Code 세션 안에서 띄운 프로세스는 `DETACHED_PROCESS`를 줘도 그 세션의 Windows Job에 남아서, 세션이 끝날 때 함께 죽는다. 10:09(다른 프로젝트 세션)와 14:38(이 저장소 세션)의 사망이 모두 세션 종료 시각과 맞았다. 같은 방식으로 띄운 10:41 백엔드는 세션이 살아 있는 동안 몇 시간을 버텼다.
  - 세션 Job은 `CREATE_BREAKAWAY_FROM_JOB`을 거부한다(권한 거부).
  - 세션 Job의 플래그는 0x0이라, 종료 방식(Job 닫힘인지 세션 쪽 정리인지)은 확인하지 못했다.
  - WMI(`Win32_Process.Create`)로 띄운 프로세스는 다른 Job에 들어간다(`BREAKAWAY_OK`·`SILENT_BREAKAWAY_OK`, 메모리·프로세스 제한 없음). 같은 Windows 세션에서 돌고, 세션이 끝나도 살아남았다.
- 수정: `src/aiassetstudio/detach.py`의 `spawn_detached`로 백엔드(MCP 서버의 `_spawn_backend`)와 ComfyUI(`ComfyLauncher`)를 WMI로 띄운다. WMI는 호출자의 환경 변수와 출력 연결을 넘기지 않는다. 그래서 짧은 런처 단계(`python -m aiassetstudio.detach <base64 사양>`)가 `AIAS_*`와 PATH, 작업 폴더, 로그 파일을 적용한 뒤 실제 프로세스를 띄운다. WMI가 실패하면 직접 띄우고 경고를 남긴다. 백엔드 명령줄에는 `--host --port --data-dir`를 적어 어느 백엔드인지 명령줄로 알 수 있게 했다.
- 확인한 것:
  - 시험용 Job을 강제 종료하면 예전 방식으로 띄운 자식은 죽고 `spawn_detached` 자식은 산다(`tests/test_detach.py`).
  - MCP 클라이언트가 끝날 때 자식을 모두 죽이는 `smoke_mcp.py` 실행 뒤에도 백엔드가 살아 있었다. 그래서 스모크는 자기가 띄운 백엔드를 끝에서 끈다(`--keep-backend`로 남길 수 있다).
  - 새 8765 백엔드가 WMI로 ComfyUI를 띄웠고(31초), 거기서 GPU 이미지 테스트가 통과했다.

남은 것(사용자 확인 필요):
- T2.B.3의 MCP 등록(사용자 설정 `~/.claude.json`을 바꿈)과 다른 폴더의 Claude Code 세션에서 하는 수동 확인.
- ComfyUI 자동 실행을 실제로 보려면 지금 켜져 있는 ComfyUI(`run_comfyui.bat` 콘솔)를 닫아야 한다.
- 사용자가 8765에 띄워 둔 백엔드는 Phase 1 코드다. 수동 확인 전에 끄거나 다시 띄운다(끄면 MCP가 새 코드로 띄운다).

---

## 참고 자료

- 로드맵: [`aiassetstudio-roadmap.md`](./aiassetstudio-roadmap.md)
- UX 플로우 (도구·화면·상태·엣지케이스): [`ux-flow.md`](./ux-flow.md)
- MCP Python SDK v2: https://github.com/modelcontextprotocol/python-sdk (예제 `examples/mcpserver/screenshot.py`가 `Image` 반환 방식)
- Claude Code MCP 문서: https://code.claude.com/docs/en/mcp (등록 명령, 도구 시간 제한, 결과 크기 한도)

## 메모 / 주의

- Claude Code의 MCP 도구 시간 제한 기본값은 약 28시간이라 `get_job`의 60초 대기는 문제없다. 그래도 도구가 오래 붙잡고 있지 않도록 대기는 60초로 제한한다.
- MCP 결과에 넣는 이미지는 미리보기만 보낸다. 원본(1024²)을 넣으면 결과 크기 한도를 넘을 수 있다.
- 백엔드와 ComfyUI를 분리 실행하므로 Claude Code 세션을 닫아도 계속 돈다. 끄는 방법(작업 관리자, 또는 이후 `aiassetstudio stop` 추가)을 README에 적는다.

---
_다음 페이즈: Phase 3 — 게임 규격 + 참고 이미지 → [`aiassetstudio-phase-3-pixel-reference.md`](./aiassetstudio-phase-3-pixel-reference.md)_
