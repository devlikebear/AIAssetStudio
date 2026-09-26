# 애니메이션 Phase 1: Claude Code에서 적 애니메이션 한 벌 — 작업지시서

_이 페이즈의 목표를 이루기 위한 구체적 작업 목록이다. Claude Code가 위에서부터 차례로 하되, 체크포인트에서 사용자 확인을 받는다._

_작성일: 2026-09-25_
_속한 로드맵: [`aiassetstudio-animation-roadmap.md`](./aiassetstudio-animation-roadmap.md)_
_예상 소요: 약 30시간_

## 페이즈 목표

클라우드를 켠 픽셀 프로젝트에서, Claude Code가 스프라이트 에셋 하나로 `generate_animation`을 부른다. 백엔드는 sprite-gen(codex)으로 대기 4 + 이동 6 프레임을 만든다. 결과는 프로젝트 규격(크기, 발 줄, 색)과 기본 그림의 축척에 맞춰 정리한다. `get_job`은 프레임 시트 미리보기를 돌려주고, `export_asset`은 게임 형식(`<이름>.png`, `<이름>/000~009.png`, `<이름>.json`)으로 내보낸다. 이 페이즈가 끝나면 갤러리 없이도 애니메이션을 만들어 게임 폴더에 넣을 수 있다.

## 전제 조건

- [x] 기존 Phase 1~4와 후속 작업 완료(`93bec6b`)
- [x] sprite-gen 2.9.0이 `<sprite-gen 경로>`(전용 `.venv`)에 설치돼 있다(2026-09-25)
- [x] Codex 앱의 codex CLI 0.155가 ChatGPT로 로그인돼 있다(`codex login status` → "Logged in using ChatGPT", 2026-09-25)
- [x] 실제 codex를 부르기 전에 이번 세션에서 사용자에게 전송 허락을 받는다(로드맵 "이 확장에만 있는 규칙"). 2026-09-25 "보내서 만들기"

## 포함 기능

1. 클라우드 사용 설정 — `projects.animation_cloud`(기본 꺼짐), API·MCP로 켜고 끔
2. 애니메이션 작업 — `POST /api/jobs/animation`, 실행기, sprite-gen 호출, 준비 상태 점검
3. 축척·일관성 맞추기 — 시험으로 방법을 정하고, 크기·발 줄·색 점검
4. MCP `generate_animation`과 `get_job` 미리보기
5. 게임 규약 내보내기

## 이 페이즈에서 하지 않는 것

- 갤러리 애니메이션 카드와 상세, 프로젝트 정보 표시 → Phase 2(이 페이즈에서 갤러리는 애니메이션 에셋을 무시하거나 기본 카드로 보여도 된다. 깨지지만 않으면 된다)
- 주인공 4방향, 공격 상태, 로컬 생성, 별도 대기열 → Out of Scope

## 작업 체크리스트

### 작업 그룹 A: 시험으로 방법 정하기 (먼저 한다)

시험 한 번에서 프레임이 기본 그림보다 15% 크게 나왔다(20×29 대 17×26, sprite-gen "cap" 경고). 이동 6프레임(게임 규약)은 아직 시험하지 않았다(시험은 4프레임). 이 두 가지가 뒤 작업의 방식을 정하므로 가장 먼저 한다. **실제 codex를 부르므로 사용자 허락을 받고 한다.**

- [x] **T1.A.1** — 축척 힌트와 이동 6프레임 시험 (클라우드, 수동)
  - 파일: `scripts/animation_trial.py`, `docs/plans/notes/animation-trial.md`
  - 내용:
    - 입력: 사용자 `data/`의 스프라이트 에셋 하나(읽기만). 기본값은 `622203551b15`(그림자 적, 17×26칸). processed 32×32를 최근접 32배로 키워 run 폴더의 기본 그림으로 쓴다.
    - run 폴더는 임시 폴더(`%TEMP%` 아래나 스크립트 인자)다. 사용자 `data/`에는 쓰지 않는다.
    - sprite-gen `prepare` 공통 인자
      - `--cell-size 32 --safe-margin 3`
      - `--fit-pixel-unfake --fit-palette-size 12 --fit-align-x foot-centroid --fit-align-y bottom --fit-ground-frames`
      - `--request`: states `idle`(4, loop, `"subtle breathing and blinking"`), `frontwalk`(6, loop, `"creeping walk toward the viewer"`)
    - 세 가지로 한 번씩 돌린다.
      - (a) 에셋 설명 그대로
      - (b) 에셋 설명 + 크기 힌트 `"The character is exactly {w} pixels wide and {h} pixels tall on the 32x32 grid, the same size as the base image; keep that size in every frame."` ({w}×{h}는 기본 그림 불투명 영역, 예: 17×26). 앞선 시험의 15% 확대는 sprite-gen 기본 문구("same pixel density, same body proportions")가 있는데도 일어났다. 숫자를 주면 달라지는지 본다.
      - (c) (a)의 원본 줄을 그대로 쓰고 `prepare --fit-logical-height {h}`로 다시 추출한다. codex가 문구를 따르는지와 상관없는 후처리다. 칸 상한을 기본 그림 높이로 두면, 넘치는 프레임은 kCentroid로 줄어든다(sprite-gen `pixel-unfake.md`). 줄인 프레임에서 1px 윤곽과 눈이 살아 있는지 함께 본다. 이 경우 codex를 다시 부르지 않는다.
    - codex는 `gen-set --provider codex --concurrency 2`로 부른다. 하위 프로세스 PATH 앞에 Codex 앱의 codex 폴더를 붙인다(T1.B.1의 탐색 규칙과 같게).
    - 줄마다 기록한다: 생성 시간, 프레임별 불투명 영역 크기(w×h), 발 줄, sprite-gen extract 경고 수와 내용, 대기 프레임 높이 중앙값과 기본 그림의 차이(칸).
    - 프레임 시트(8배)와 GIF를 만들어 사용자에게 보여 주고 함께 판단한다: 같은 캐릭터로 보이는가, 이동이 읽히는가, 크기가 맞는가.
  - 결정 규칙
    1. (b)에서 대기 높이 차가 ±1칸 안이면 → 크기 힌트를 기본으로 한다(T1.C.5 설명).
    2. (b)가 벗어나도 (c)가 ±1칸 안이고 윤곽이 살아 있으면 → `--fit-logical-height`를 기본으로 한다(T1.C.2 `prepare` 인자).
    3. 둘 다 안 되면 → 사용자와 정한다. 선택지는 "그대로 두고 표시", "다시 뽑기 최대 N번"이다. 다시 뽑기는 한 번에 60~90초와 구독 사용량이 든다. 결과를 이 문서의 구현 메모에 적고 T1.C.4·T1.C.5에 반영한다.
    4. 이동 6프레임이 무너지면(형태 붕괴, 칸 수 틀림) → 4프레임으로 만들고 6칸에 [0,1,2,3,2,1]로 채울지 사용자와 정한다.
  - 검증: 기록 문서 작성, 사용자와 방식 합의

### 작업 그룹 B: 설정, DB, 클라우드 허락

- [x] **T1.B.1** — 설정과 외부 도구 찾기
  - 파일: `src/aiassetstudio/config.py`, `tests/test_config.py`
  - 내용:
    - `Settings`에 추가
      - `sprite_gen: str = r"<sprite-gen 경로>\.venv\Scripts\sprite-gen.exe"`(`AIAS_SPRITE_GEN`)
      - `codex_dir: str = ""`(`AIAS_CODEX_DIR`, 빈 값이면 자동 탐색)
      - `animation_timeout: float = 900`(`AIAS_ANIMATION_TIMEOUT`)
    - `def find_codex_dir(settings) -> Path | None` — `codex_dir`가 있으면 그것을 쓴다. 없으면 `%LOCALAPPDATA%\OpenAI\Codex\bin\*\codex.exe` 가운데 수정 시각이 가장 늦은 것의 폴더를 쓴다. 모두 없으면 None(PATH의 `codex`에 맡긴다).
    - PATH의 0.147이 새 설정을 못 읽는 문제(`codebase-analysis.md` "sprite-gen")를 주석에 적는다.
  - 참조: 기존 `_ENV` 매핑과 `load_settings`
  - 검증: `uv run pytest tests/test_config.py`. 환경 변수 덮어쓰기, 가짜 LOCALAPPDATA 폴더 두 개 중 최신 선택

- [x] **T1.B.2** — DB 스키마 v2: `projects.animation_cloud`
  - 파일: `src/aiassetstudio/store/db.py`, `src/aiassetstudio/store/models.py`, `tests/test_db.py`
  - 내용:
    - **먼저** 지금의 v1 스키마 SQL(`db._SCHEMA` 전체)을 `tests/test_db.py`의 상수 `_SCHEMA_V1`로 복사해 둔다. `_SCHEMA`를 고친 뒤에는 v1 DB를 만들 방법이 없다.
    - `SCHEMA_VERSION = 2`. `_SCHEMA`의 `projects`에 `animation_cloud INTEGER NOT NULL DEFAULT 0`을 넣는다.
    - `_migrate`는 v0이면 새 스키마로 만든다. v1이면 `ALTER TABLE projects ADD COLUMN animation_cloud INTEGER NOT NULL DEFAULT 0` 후 `user_version = 2`로 한다. 한 트랜잭션으로 한다.
      - `NOT NULL DEFAULT <상수>`의 `ADD COLUMN`은 SQLite가 테이블을 다시 만들지 않고 허용하는 형태다. "더 낫게" 바꾸지 않는다.
    - `PROJECT_FIELDS`에 `"animation_cloud"`를 넣고, `Project.animation_cloud: bool = False`를 둔다.
  - 검증: `uv run pytest tests/test_db.py`
    - `_SCHEMA_V1`로 만들고 `user_version = 1`로 둔 DB(프로젝트 1개, 작업 1개)를 열면 v2가 된다. 프로젝트와 작업이 그대로 있고 `animation_cloud=False`다.
    - 새 DB는 바로 v2다.

- [x] **T1.B.3** — API와 MCP에서 켜고 끄기
  - 파일: `src/aiassetstudio/api/schemas.py`, `src/aiassetstudio/api/app.py`, `src/aiassetstudio/mcp_bridge/server.py`, `src/aiassetstudio/mcp_bridge/tools.py`, `tests/test_api.py`, `tests/test_mcp_tools.py`
  - 내용:
    - `ProjectCreate.animation_cloud: bool = False`, `ProjectUpdate.animation_cloud: bool | None = None`. `NOT_NULL_PROJECT_FIELDS`에 넣어서 null이면 그대로 둔다.
    - MCP `create_project`·`update_project`에 `animation_cloud`를 추가한다. 설명: `"Allow animation jobs to send this project's sprites to OpenAI (Codex CLI, ChatGPT subscription). Off by default."`
    - `_project_text`에 한 줄 추가한다.
      - 켜짐: `"  animation: allowed (sends sprites to OpenAI via codex)"`
      - 꺼짐: `"  animation: off (update_project animation_cloud=true to allow; it sends sprites to OpenAI)"`
    - MCP `tools.update_project`: `animation_cloud`를 **`CLEARED_BY_ZERO`에 넣지 않는다.** `False == 0`이라 넣으면 `False`가 "지우기"(None)로 바뀐다. `False`를 실제 값으로 그대로 넘긴다(Phase 3 구현 메모의 `pixel_art` 사례).
  - 참조: `pixel_art`를 다루는 기존 방식(API는 `NOT_NULL_PROJECT_FIELDS`로 null을 무시, MCP는 생략하면 그대로 둠)
  - 검증: `uv run pytest tests/test_api.py tests/test_mcp_tools.py -k "project or animation"`
    - `update_project(animation_cloud=False)`가 켜진 설정을 끈다(`test_mcp_tools.py`의 `pixel_art=False` 시험과 같은 모양).

### 작업 그룹 C: 작업, 대기열, 실행기

- [x] **T1.C.1** — 작업 종류와 대기열 규칙
  - 파일: `src/aiassetstudio/store/models.py`, `src/aiassetstudio/jobs/queue.py`, `tests/test_queue.py`
  - 내용:
    - `JobKind`에 `"animation"`, `Family`에 `"codex"`, `AssetKind`에 `"animation"`을 넣는다.
    - `queue.py`에 `CLOUD_FAMILIES = ("codex",)`를 둔다. 이 계열 작업은 다음과 같이 다룬다.
      - `launcher.ensure()`(ComfyUI 실행)를 하지 않는다.
      - **시작할 때 모델이 올라가 있으면 먼저 `/free`를 부르고** `models_loaded=False`, `current_family=None`으로 둔다.
        - 이유: 작업하는 1~3분 동안 GPU를 쓰지 않는데, 작업자가 바쁘면 `_idle()`의 60초 유휴 해제가 돌지 않는다. 그동안 공유 GPU를 붙잡지 않고 다른 세션에 돌려준다(기존 "60초 유휴면 해제" 정책과 같은 뜻).
        - 작업 `timings.free_before = true`를 남긴다(`ctx.freed_before`).
      - 끝난 뒤 `current_family`와 `models_loaded`를 바꾸지 않는다(`_run` 161~163행의 갱신을 이 계열에서는 건너뛴다).
    - 시간 제한은 `animation_timeout`이다(`_run`의 `timeout` 선택에 kind `"animation"` 추가).
    - 주석: 클라우드 작업은 GPU를 쓰지 않지만 MVP는 같은 대기열을 쓴다(로드맵 Out of Scope "별도 클라우드 대기열").
  - 검증: `uv run pytest tests/test_queue.py -k "cloud or family"`
    - codex 작업은 `launcher.ensure`를 부르지 않는다.
    - image → codex → image 순서에서 `free`는 codex 시작 때 1번이다. 뒤의 image 작업 앞에서는 0번이다(이미 비어 있음).
    - codex만 두 번 연속이면 `free`는 0번이다.

- [x] **T1.C.2** — sprite-gen 호출기
  - 파일: `src/aiassetstudio/spritegen/__init__.py`, `src/aiassetstudio/spritegen/client.py`, `tests/fake_spritegen.py`, `tests/test_spritegen.py`
  - 내용:
    - `class SpriteGenError(RuntimeError)`: 메시지와 sprite-gen 보고(`report: dict | None`)
    - `@dataclass class SpriteGen`
      - 필드: `cmd: list[str]`(기본 `[settings.sprite_gen]`, 테스트는 `[sys.executable, "tests/fake_spritegen.py"]`), `codex_dir: Path | None`, `timeout: float`
      - `async def run(self, tool: str, *args: str) -> dict`
        - `asyncio.create_subprocess_exec`로 부른다. 환경은 부모 환경에 `PYTHONIOENCODING=utf-8`을 더하고, `codex_dir`가 있으면 PATH 앞에 붙인다.
        - stdout의 마지막 JSON 객체를 읽는다. 종료 코드가 0이 아니거나 `ok`가 false면 `errors`를 담아 `SpriteGenError`를 낸다.
        - 취소되면 하위 프로세스를 `kill()`하고 다시 올린다.
      - 도구별 메서드
        - `prepare(run_dir, base, cell_w, cell_h, safe_margin, palette_size, description, states: dict)`: states를 `request.json`에 써서 `--request`로 넘긴다.
        - `gen_set(run_dir, concurrency=2)`: `--provider codex`
        - `extract(run_dir)`, `compose(run_dir)`, `inspect(run_dir)`
    - `tests/fake_spritegen.py`: sprite-gen CLI의 흉내다.
      - `prepare`는 `sprite-request.json`과 `base-source.png`를 쓴다.
      - `gen-set`은 아무것도 보내지 않는다.
      - `extract`는 기본 그림을 줄마다 1px씩 흔든 `frames/<state>/frame-N.png`와 `frames/frames-manifest.json`을 쓴다.
      - `compose-atlas`는 `sprite-sheet-alpha.png`와 `manifest.json`(`frame_layout.rows[state]`의 x·y·w·h)을 쓴다.
      - 환경 변수로 실패(`ok: false`)와 느린 응답을 흉내 낼 수 있다.
  - 참조: `post/audio.encode_ogg`(외부 프로그램 오류를 도메인 예외로), sprite-gen `docs/run-contract.md`(stage 입출력, run 폴더 구조)
  - 검증: `uv run pytest tests/test_spritegen.py`
    - 성공 JSON 해석
    - `ok:false`면 `SpriteGenError`에 errors가 담김
    - 취소하면 하위 프로세스가 죽음
    - PATH 앞에 codex 폴더가 붙음(가짜가 받은 PATH를 기록해 확인)

- [x] **T1.C.3** — 준비 상태 점검
  - 파일: `src/aiassetstudio/spritegen/access.py`, `src/aiassetstudio/api/app.py`, `src/aiassetstudio/mcp_bridge/tools.py`, `tests/test_spritegen.py`, `tests/test_api.py`
  - 내용:
    - `async def animation_status(settings) -> dict`
      - 반환: `{ok, reason, sprite_gen, codex, login}`
      - sprite-gen 실행 파일이 있는지 본다.
      - codex(`find_codex_dir`)로 `codex login status`를 부른다. "Logged in"이 들어 있으면 `login: "ready"`다.
      - 60초 동안 결과를 저장해 둔다(`Services.preflight`와 같은 방식).
    - `/api/status`에 `"animation": {...}`을 더한다.
    - MCP `studio_status`에 한 줄 더한다: `"animation (sprite-gen + codex): ready"` 또는 `"animation: not ready (<reason>)"`
  - 검증: `uv run pytest tests/test_spritegen.py tests/test_api.py -k status`. 가짜 codex 스크립트로 로그인됨·안 됨·없음

- [x] **T1.C.4** — 프레임 정리 (게임 규격)
  - 파일: `src/aiassetstudio/post/animation.py`, `tests/test_post_animation.py`
  - 내용:
    - `GAME_TAGS = {"idle": (range(0, 4), 0.18), "walk": (range(4, 10), 0.1)}`. 근거: `Tools/archive_campaign_art.lua`의 태그와 `duration`
    - `def load_frames(run_dir: Path, states: list[str]) -> list[Image.Image]`: `manifest.json`의 `frame_layout.rows`로 `sprite-sheet-alpha.png`에서 잘라, 상태 순서대로 이어 붙인다(idle 4 + frontwalk 6 = 10).
    - `def fit_frames(frames, spec: PixelSpec, base: Image.Image) -> tuple[list[Image.Image], dict]`
      - 프레임은 이미 칸 크기다. 알파를 0/255로 다시 확인한다.
      - 고정 팔레트가 있으면 프레임 전체에서 쓰인 색마다 가장 가까운 팔레트 색으로 한 번에 바꾼다. 프레임끼리 색이 흔들리지 않게 하려는 것이다. 없으면 `max_colors`만 점검한다.
      - 발 줄: 프레임마다 가장 아래 불투명 줄을 `spec.height - spec.ground - 1`에 맞춰 세로로만 옮긴다.
      - 보고: `base_size`, `frame_sizes`, `idle_height`(대기 프레임 높이 중앙값), `size_ok`(±1칸), `ground_row`, `colors_used`
    - `def game_row(frames) -> Image.Image`: 10칸을 한 줄로 잇는다(320×32).
    - `def game_json(spec, name) -> dict`: `{"frame_width", "frame_height", "frames": 10, "tags": [{"name": "idle", "from": 0, "to": 3, "duration": 0.18}, {"name": "walk", "from": 4, "to": 9, "duration": 0.1}]}`
    - `def contact_sheet(frames, zoom=4) -> Image.Image`: 10칸 한 줄에 칸 번호와 발 줄 선을 넣는다(MCP 미리보기).
    - `def animated_gif(frames, zoom=4) -> bytes`: 태그 시간대로 반복한다(Phase 2 카드용. 여기서 만들어 둔다).
  - 참조: `post/image.py`의 `_final_colors`·`_color_distance`(팔레트), `reference_ground`(발 줄 규칙)
  - 검증: `uv run pytest tests/test_post_animation.py`
    - 합성 10프레임(발 줄이 1칸 어긋난 것 포함)이 발 줄에 맞춰진다.
    - 팔레트 밖 색이 모두 팔레트 색이 되고, 같은 원래 색은 모든 프레임에서 같은 색이 된다.
    - 320×32 줄, JSON 태그, 크기 판정(±1)

- [x] **T1.C.5** — 애니메이션 실행기
  - 파일: `src/aiassetstudio/jobs/runners.py`, `tests/test_runners.py`
  - 내용:
    - `async def run_animation_job(ctx, job)`. `params`는 `asset_id`, `count`(1~2, 기본 1)다.
    - 실행 직전에도 확인한다. 프로젝트의 `animation_cloud`가 꺼져 있으면 `ValueError("animation is not allowed for this project: ...")`로 실패한다. 요청 뒤에 꺼진 경우를 막는 것이다.
    - 후보마다 다음을 한다.
      1. `asset_dir(new_id)`와 그 아래 `run/`을 만든다.
      2. 기본 스프라이트의 `processed.png`를 최근접으로 `1024 // max(w, h)`배 키워 `run/base.png`에 둔다.
      3. `prepare`: 칸 = 프로젝트 `logical_width`×`logical_height`, `safe_margin` = 프로젝트 발 줄(참고 이미지가 있으면 `reference_ground`, 없으면 `PIXEL_MARGIN`), `palette_size` = `max_colors`, 설명 = 기본 에셋의 `meta.description`(+ T1.A.1에서 정한 크기 힌트), states `idle` 4 + `frontwalk` 6
      4. 단계 표시 `"generating rows (codex)"`로 `gen_set`
      5. `extract` → `compose` → `inspect`(경고만 남긴다)
      6. `load_frames` → `fit_frames` → 파일을 쓴다. 파일 역할과 이름은 `row`=`row.png`, `json`=`animation.json`, `preview`=`preview.png`(프레임 시트), `gif`=`preview.gif`, `base`=`base.png`다. 프레임은 `frames/000.png`~`009.png`로 두고, meta에 목록을 남긴다.
    - `meta`
      - `description`, `base_asset`
      - `animation: {frames: 10, tags, cell}`
      - `fit`(T1.C.4 보고)
      - `cloud: {provider: "codex", sent: ["base.png", "layout guides", "prompts"]}`
      - `spritegen: {version, warnings, inspect}`
      - `timings: {prepare, generate, extract, postprocess}`
    - `RUNNERS["animation"] = run_animation_job`
    - `SpriteGenError`는 그대로 올려서 작업이 `failed`가 되게 한다(대기열이 `error`에 메시지를 남긴다).
  - 참조: `run_bgm_job`(후보 루프, 단계, meta·timings, 외부 도구 실패 처리)
  - 검증: `uv run pytest tests/test_runners.py -k animation`(가짜 sprite-gen)
    - 10프레임, 32×32, 발 줄, 파일 역할이 맞다.
    - 클라우드가 꺼져 있으면 실패하고, 가짜에 `gen-set` 호출이 0번이다.
    - sprite-gen이 실패하면 작업이 이유를 남기고 `failed`가 된다.

- [x] **T1.C.6** — 작업 API와 내보내기
  - 파일: `src/aiassetstudio/api/schemas.py`, `src/aiassetstudio/api/app.py`, `tests/test_api.py`, `tests/test_export.py`
  - 내용:
    - `class AnimationJobCreate(BaseModel)`: `project`, `asset_id`, `count: int = Field(1, ge=1, le=2)`
    - `POST /api/jobs/animation`
      - 프로젝트가 없으면 404다.
      - `animation_cloud`가 꺼져 있으면 422다(메시지에 켜는 법).
      - 픽셀 프로젝트가 아니면 422다.
      - 에셋이 없거나 다른 프로젝트 것이면 404이고, 스프라이트가 아니면 422다.
      - 통과하면 `create_job(project.id, "animation", "codex", params)` 후 `notify()`
      - `params`에 기본 에셋의 `meta.description`을 `description`으로 복사해 둔다(갤러리와 `get_job`의 작업 제목. `jobTitle`이 `params.description`을 쓴다).
    - `list_assets`의 kind 필터에 `"animation"`, `MEDIA_TYPES`에 `.gif`(`image/gif`)와 `.json`(`application/json`)을 더한다.
    - 내보내기: `_export`에 애니메이션 분기를 둔다.
      - **`EXPORT_FILES` 조회보다 앞에서** `asset.kind == "animation"`으로 나눈다. `EXPORT_FILES`에 `"animation": (("row",),)`처럼 넣으면 기존 코드가 줄 이미지 하나만 내보내고 끝난다(조용한 부분 내보내기).
      - `<stem>.png`(row), `<stem>.json`, `<stem>/000.png`~`009.png`를 만든다.
      - 이름은 `unique_stem(dest, stem, [".png", ".json", ""])`로 정한다. 빈 확장자 `""`가 `dest/<stem>` 폴더도 확인해서, 셋 중 하나라도 있으면 `_2`를 붙인다.
      - `meta.exports`에 세 경로(PNG, JSON, 폴더)를 남긴다.
  - 참조: `POST /api/jobs/bgm`, `EXPORT_FILES["bgm"]`(한 이름으로 두 파일)
  - 검증: `uv run pytest tests/test_api.py tests/test_export.py -k animation`. 거부 조건 4가지, 두 번 내보내면 `_2`, 파일 12개(PNG 11 + JSON 1)

### 작업 그룹 D: MCP

- [x] **T1.D.1** — `generate_animation`과 `get_job`
  - 파일: `src/aiassetstudio/mcp_bridge/server.py`, `src/aiassetstudio/mcp_bridge/tools.py`, `src/aiassetstudio/mcp_bridge/studio_api.py`, `tests/test_mcp_tools.py`
  - 내용:
    - `generate_animation(asset_id, count=1)` 도구의 설명: `"Queue an idle (4 frames) + walk (6 frames) animation of a sprite, in the project's pixel-art size. Sends the sprite (enlarged), a layout guide and a prompt to OpenAI through the Codex CLI (ChatGPT subscription); only projects with animation_cloud on. Takes 1-3 minutes per candidate."`
    - `studio_api.create_animation_job(project?, asset_id, count)`: 에셋에서 프로젝트를 찾아 부른다.
    - `get_job`: 애니메이션 에셋이면 `_animation_text(a)`와 미리보기 PNG(`preview`)를 돌려준다.
      - 텍스트: 프레임 수, 크기와 기본 그림 대비, 발 줄, 색 수, 경고, `"made with codex (cloud)"`
      - `size_ok`가 false면 `"frames differ in size from the base sprite (idle 20x29 vs base 17x26)"`처럼 적는다.
    - `INSTRUCTIONS`
      - "with local models (no cloud)"를 "Images and music use local models; animations (generate_animation) are the one exception: they use the Codex CLI in the cloud, only where the project allows it"로 바꾼다.
      - 흐름에 `generate_animation -> get_job -> export_asset`을 더한다.
    - `list_assets`의 kind Literal에 `"animation"`을 더한다.
  - 참조: `generate_bgm`, `_song_text`, `_pixel_note`
  - 검증: `uv run pytest tests/test_mcp_tools.py -k animation`(가짜 sprite-gen, 끝까지)

### 작업 그룹 E: 검증과 문서

- [x] **T1.E.1** — 종단검증 `smoke_mcp.py --animation`
  - 파일: `scripts/smoke_mcp.py`
  - 내용:
    - 흐름
      1. `--animation <참고 이미지>`로 픽셀 프로젝트 `smoke-anim`(32×32, 12색, 참고 이미지, `animation_cloud=true`)를 만든다.
      2. 스프라이트 1장을 뽑는다(GPU).
      3. `generate_animation`(codex, 클라우드)을 부르고 `get_job`으로 끝까지 기다린다.
      4. 미리보기가 1장 이상인지 본다.
      5. `export_asset`으로 내보낸 뒤 파일을 점검한다: `<이름>.png` 320×32, `<이름>/000~009.png` 32×32, 알파 0/255, 색 12개 이하, JSON 태그, 발 줄 28.
    - 클라우드가 꺼진 프로젝트에 요청하면 거부되는지도 본다.
    - `AIAS_PORT=8766`과 임시 `AIAS_DATA_DIR`로만 돌린다. 시작 전에 보낼 것(시험 스프라이트 1장)을 출력한다.
  - 검증: 사용자 허락 뒤 `uv run python scripts/smoke_mcp.py --animation <게임 프로젝트 경로>\ArtSource\LastLight\keeper\000.png` 통과

- [x] **T1.E.2** — 문서
  - 파일: `README.md`, 이 문서의 "구현 메모"
  - 내용:
    - README에 애니메이션 절을 새로 둔다.
      - 클라우드 설정을 켜야 하고, 무엇이 OpenAI로 가는지 적는다.
      - sprite-gen 설치 명령(`git clone --depth 1`, `uv venv`, `uv pip install -e .`)을 적는다.
      - codex 로그인과 PATH 문제(`AIAS_CODEX_DIR`)를 적는다.
      - 게임 형식 내보내기를 설명한다.
    - `MCP_ADD_COMMAND` 등 기존 안내는 그대로 둔다.
  - 검증: 문서 검토

---

## ✅ 애니메이션 Phase 1 Checkpoint

**구현 확인:**
- [x] 모든 작업 체크박스 완료
- [x] T1.A.1 결론(크기 힌트, 이동 6프레임)이 구현 메모와 실행기에 반영됐다
- [x] 클라우드가 꺼진 프로젝트는 API, 실행기, MCP 모두에서 거부되고, sprite-gen `gen-set`이 불리지 않는다

**자동 검증:**
- [x] 전체 테스트: `uv run pytest`
- [x] 이 페이즈 테스트: `uv run pytest tests/test_spritegen.py tests/test_post_animation.py -k "animation or spritegen"`, `uv run pytest -k animation`
- [x] 린트: `uv run ruff check .`, `uv run ruff format --check .`
- [x] 갤러리 빌드가 깨지지 않는다: `npm --prefix web run build`(새 kind로 타입이 깨지지 않는지)
- [x] 종단검증: `smoke_mcp.py --animation`(사용자 허락 뒤, 실제 codex). 2026-09-25 통과: 8766·임시 데이터, 320×32 줄, 10프레임 32×32, 발 줄 28, 7색, JSON 태그

**수동 확인:**
- [ ] 새 Claude Code 세션에서 할 것
  1. "lastlight 프로젝트에 애니메이션 클라우드 켜줘"
  2. "그림자 적 `<id>`로 애니메이션 만들어줘"
  3. `get_job` 프레임 시트가 보이고, 텍스트에 크기·발 줄·경고가 나온다
  - 같은 흐름을 이 세션에서 HTTP API로 한 번 돌렸다(2026-09-25 19:13). 이 세션의 MCP 서버는 옛 코드라 `generate_animation`이 없다. lastlight의 `animation_cloud`를 켜고, 그림자 적 `622203551b15`(T1.A.1에서 이미 보낸 그림)로 애니메이션 `958d5bfbdf52`를 만든 뒤 다시 껐다. 80초가 걸렸고, 대기·이동 18×26(기본 17×26), 발 28번째 줄, 5색, 크기 판정 통과였다. 새 세션의 MCP 확인은 사용자가 한다.
- [ ] "`data/exports/lastlight-trial/`로 `shadow_anim` 이름으로 내보내줘"
  - `shadow_anim.png`, `shadow_anim/000~009.png`, `shadow_anim.json`이 생긴다(위 애니메이션으로 만들어 두었다)
  - 이미지 뷰어에서 10프레임이 게임 프레임처럼 보인다(사용자 판단)
- [x] 8765 백엔드를 다시 띄운 뒤 `studio_status`에 애니메이션 준비 상태가 나온다(2026-09-25 19:10, `/api/status` animation ready. 이 세션의 MCP 서버는 옛 코드라 새 세션에서 한 줄이 보인다)

**완료 처리:**
1. 위 항목을 모두 통과하면 Claude Code는 사용자에게 보고한다.
   - 한 작업 요약
   - 자동 검증 결과
   - T1.A.1 시험 결론
   - 수동 확인이 필요한 항목
2. 사용자가 "애니메이션 Phase 1 완료, 다음 진행"이라고 승인하면 커밋하고 Phase 2로 간다.
3. 체크포인트가 실패하면 실패 항목을 보고하고, 원인을 찾아 고친 뒤 다시 검증한다.

---

## 참고 자료

- 로드맵: [`aiassetstudio-animation-roadmap.md`](./aiassetstudio-animation-roadmap.md)
- PRD: [`aiassetstudio-animation-prd.md`](./aiassetstudio-animation-prd.md)
- 코드베이스 분석: [`codebase-analysis.md`](./codebase-analysis.md)
- sprite-gen: `<sprite-gen 경로>\docs\run-contract.md`(stage 입출력, run 폴더), `pixel-unfake.md`(칸·팔레트·발 정렬), `states-and-frames.md`(프레임 수 권장), `SKILL.md`(에이전트 계약)
- 게임 규약(읽기만): `<게임 프로젝트 경로>\Tools\build_campaign_art.py`(10프레임, 발 줄), `Tools\archive_campaign_art.lua`(태그, 시간)

## 메모 / 주의

- sprite-gen은 import하지 않는다. 전용 가상환경의 CLI를 subprocess로 부른다. 결과 JSON 형식이 바뀔 수 있으므로 필요한 키(`ok`, `errors`, `warnings`, `frame_layout.rows`)만 읽고, 없으면 분명한 오류를 낸다. 쓴 버전은 meta에 남긴다.
- sprite-gen `curated/` 규약(run-contract §2-c): 사람이 고른 결과는 `curation.json`에 남고 `frames/`에는 남지 않는다. 이 페이즈는 curation을 쓰지 않으므로 compose 결과(아틀라스 + manifest)를 쓴다.
- codex 한 줄에 60~90초가 걸린다. 후보 2개 × 2줄이면 5분 가까이 대기열을 잡는다. 기본 `count`는 1이다.
- 발 줄은 sprite-gen의 `--safe-margin`(위아래 같음)으로 맞추고, `fit_frames`에서 한 번 더 확인한다.
- 실제 codex 시험은 그림이 외부로 나간다. 테스트(pytest)는 절대 진짜 sprite-gen이나 codex를 부르지 않는다(가짜만).

## 구현 메모

_(구현하면서 계획과 다르게 한 것, 실측, 후속 수정을 여기에 적는다.)_

### T1.A.1 시험 결론 (2026-09-25) → 방식 (d)

기록: [`notes/animation-trial.md`](./notes/animation-trial.md). 줄여 말하면 다음과 같다.

- 계획의 (c) `--fit-logical-height`는 sprite-gen 2.9.0에서 아무것도 줄이지 않는다. 논리 높이로 누르는 기능이 2026-07에 빠졌고, 칸 32에 26을 주면 경고만 난다. 남은 축소는 물리 상한(칸 - 여백 = 29)뿐이다. 이 상한이 줄마다 가장 큰 프레임을 기준으로 줄여서, 걷기 시작하면 적이 3칸 커졌다(대기 25, 이동 28).
- codex는 기본 그림보다 촘촘한 격자로 크게 그린다(대기 33~40칸, 기본 26칸). 크기 힌트의 효과는 판단할 수 없었다(한 번씩만 시험). 방식 (d)가 크기를 맞추므로 힌트는 쓰지 않는다.
- 이동 6프레임은 두 번 다 성공했다. 4프레임 대체(규칙 4)는 쓰지 않는다.
- 방식 (d): 원본 줄을 두 배 칸(64)으로 다시 추출해 원래 크기의 프레임을 얻는다. 줄마다 높이 중앙값을 기본 그림 높이에 맞춰 줄인다. 결과는 대기와 이동 모두 26칸이다.
- sprite-gen `palette.lock.json`은 12색이지만, 프레임에는 16~19색이 있었다. 색 수는 스튜디오가 맞춘다.

이에 따라 아래 작업의 내용을 바꾼다(체크박스 본문보다 이 메모가 우선한다).

- **T1.C.2** `prepare(run_dir, base, cell_w, cell_h, safe_margin, palette_size, description, states)`의 칸 크기는 호출하는 쪽이 정한다. 생성 run은 프로젝트 칸이고, 추출 run은 두 배 칸이다. `--fit-logical-height`는 쓰지 않는다.
  - `gen-set`은 stdout 끝이 JSON이 아니라 표다. 결과는 종료 코드와 `reports/gen-set/set.report.json`으로 읽는다(`ok`는 성공한 줄 수, `failed`는 실패한 상태 목록, `items[].error`).
  - 나머지 stage(`prepare`, `extract`, `compose-atlas`, `inspect`)는 stdout 마지막에 JSON 객체 하나를 찍는다.
- **T1.C.4** `fit_frames(frames: dict[state, list], spec, base)`
  - 입력은 추출 run의 원래 크기 프레임(두 배 칸)이다.
  - 줄마다 배율 = min(1, 기본 그림 높이 / 그 줄 높이 중앙값). 칸 전체를 kCentroid 방식으로 줄인다. 칸 색은 우세 군집에서 가장 흔한 색을 쓴다(새 색 없음).
  - 줄마다 가로 가운데에 놓고, 프레임마다 발을 `spec.height - spec.ground - 1`에 세운다.
  - 색은 10프레임을 함께 기본 그림의 색으로 붙인다(구현 메모 "색" 참고). 순서는 줄이기 → 색이다.
  - 줄인 프레임이 캔버스를 넘으면 잘라 내되, 경고를 남긴다. 줄 배율이 0.5보다 작아도 경고한다(디테일이 뭉개진다).
  - 크기 판정 `size_ok`는 대기 중앙값이 기본 그림과 높이 ±1칸, 폭 ±2칸 안인지다. 보고에는 대기와 이동 각각의 중앙값 크기(w×h), 줄 배율, 경고를 남긴다.
- **T1.C.5** 후보마다 run 폴더가 둘이다.
  - `run/gen`: 프로젝트 칸. `prepare` → `gen_set`만 한다.
  - `run/native`: 두 배 칸. `prepare` → `run/gen/raw/*.png` 복사 → `extract` → `compose` → `inspect`
  - 크기 힌트는 넣지 않는다. 설명은 기본 에셋의 `meta.description` 그대로다.

### 구현하면서 바꾼 것 (2026-09-25)

- **색**: 계획은 "고정 팔레트면 그 색, 없으면 `max_colors`만 점검"이었다. 시험 프레임에 16~19색이 있어 점검만으로는 안 된다. 10프레임의 색을 모두 기본 그림의 색으로 붙인다(프레임에 있는 색마다 redmean 거리로 가장 가까운 색, 한 번의 매핑). 고정 팔레트가 있으면 기본 그림의 색을 먼저 팔레트에 붙인다.
  - 이유: 게임에서 멈춘 스프라이트와 움직이는 스프라이트의 색이 같아야 한다. 색 수도 저절로 `max_colors` 이하가 된다.
  - 비교: 시험 프레임을 자기 색 12개로 접은 것과 나란히 봤다. 둘 다 쓸 만했고, 기본 그림 색 쪽이 톤이 기본 그림과 같았다(시험 에셋은 11색 중 6색을 썼다).
- **캔버스에 맞추기**: 대기 3번 프레임(두건 끝)이 기본 높이로 줄이면 29칸을 넘어, 발 줄 위에 들어가지 않고 1칸 잘렸다. 줄 배율을 "가장 큰 프레임이 발 줄 위(와 가로 캔버스)에 들어가는 값"으로도 제한한다. 이때 `meta.fit.rows.<tag>.fitted_to_canvas = true`다. 시험 에셋은 대기 높이가 26 대신 25가 됐다.
- **여백**: 두 run 모두 `--safe-margin`을 주지 않는다(sprite-gen 기본값, 칸의 9.4%: 32칸이면 3). 발 줄은 `fit_frames`가 프로젝트 발 줄(참고 이미지의 `reference_ground`, 없으면 1칸 여백)에 맞춘다. 생성 run의 여백은 배치 가이드에만 쓰이고, 발 줄 1칸짜리 프로젝트에서도 codex가 칸 끝까지 그리지 않게 한다.
- **단계 이름**: `preparing` → `generating rows (codex)` → `extracting frames` → `postprocess 1/1`. 후보가 둘이면 앞의 셋 끝에 ` 1/2`가 붙는다. 시작할 때 GPU 모델을 비우면 그 전에 `freeing memory`가 있다.
- **파일**: `row.png`, `animation.json`, `preview.png`(10칸 번호·발 줄 선이 있는 4배 시트), `preview.gif`(4배, 게임 시간), `base.png`(기본 스프라이트 사본), `frames/000~009.png`, `run/`(sprite-gen 작업 폴더 두 개, 원본 줄과 보고서 포함). 프레임 경로는 `meta.animation.files`에 있다.
- **내보내기 JSON**: `animation.json`을 그대로 복사하지 않고 `name`과 `image`를 내보낸 이름(`_2` 포함)으로 바꿔 쓴다.
- **sprite-gen 호출**: `AIAS_SPRITE_GEN`이 `.py`로 끝나면 이 Python으로 실행한다(테스트의 `tests/fake_spritegen.py`). 취소·시간 초과 때는 `taskkill /T /F`로 sprite-gen과 그 아래 codex까지 끝낸다. 버전은 sprite-gen 가상환경의 `sprite_gen-*.dist-info`에서 읽는다(`--version`이 없다). 창이 뜨지 않게 `CREATE_NO_WINDOW`로 띄운다.
- **codex 로그인 확인**: `codex login status`는 결과("Logged in using ChatGPT")를 stderr에 찍는다. 두 스트림을 합쳐 본다. 준비되지 않은 동안은 매번 다시 확인하고, 준비되면 60초 동안 결과를 쓴다.
- **대기열**: 클라우드 작업 앞의 `/free`가 실패하면(ComfyUI가 꺼져 있는 등) 모델이 그대로 올라가 있다고 본다. `current_family`도 그대로 둬서, 다음 다른 계열 작업이 먼저 비운다.
- **Phase 2에서 더한 것**: `meta.animation.max_colors`(갤러리의 "사용 색 5/12"). Phase 1 커밋 뒤의 한 줄이다.
- **테스트 설정**: `tests/conftest.py`의 기본 `settings`는 sprite-gen과 codex 경로를 없는 곳으로 둔다. 애니메이션 테스트는 `animation_settings`(가짜 sprite-gen)를 쓴다. 어떤 테스트도 진짜 sprite-gen이나 codex를 부르지 않는다.

---
_다음 페이즈: 애니메이션 Phase 2 — 갤러리에서 보고 고르기 → [`aiassetstudio-animation-phase-2-gallery.md`](./aiassetstudio-animation-phase-2-gallery.md)_
