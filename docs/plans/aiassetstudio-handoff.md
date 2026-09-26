# AIAssetStudio — 인수인계 (2026-09-25, 애니메이션 확장까지)

_프로젝트의 개발 현황과 구현 결정을 정리한 문서다. 세부 결정과 실측은 각 작업지시서 끝의 "구현 메모"에 있다._

## 한 줄 요약

로컬 ComfyUI 모델로 인디게임 에셋을 만드는 개인용 스튜디오다. 투명 스프라이트·아이콘, 픽셀아트 규격, 반복용 BGM·보컬 곡을 만든다. 스프라이트 애니메이션만은 클라우드(sprite-gen + codex)로 만들고, 프로젝트마다 켜야 쓴다. Claude Code가 MCP 도구로 요청하고, 사람은 웹 갤러리에서 보고 고른다.

**계획한 Phase 1~4와 후속 수정, 애니메이션 확장(Phase 1~2)까지 마치고 모두 푸시했다.** 남은 것은 사람의 판단과, 계획 밖 개선 후보뿐이다.

## 지금 상태

| 항목 | 상태 |
|---|---|
| 브랜치 | `master`. `phase-2`~`phase-4`, `pixel-grid` 브랜치는 로컬에만 있다 |
| 커밋 | Phase 1 `443ab2b` → Phase 2 `415f6ff` → Phase 3 `da9a06c` → Phase 4 `7bbed0a` → 최종 점검 `1e3c19d` → 세션 밖 실행 수정 `2d0e58d` → 픽셀아트 정수배 확대(T3.C.2) `a87319c` → 인수인계 문서 `47c6a6a` → favicon.ico `f1f9748` → 참고 이미지의 발 줄 `93bec6b`(여기까지 푸시) → 애니메이션 계획 `153f325` → 애니메이션 Phase 1 `b79c69c` → 애니메이션 Phase 2 `6079731` → 인수인계 기록 `ca94e31` → 문서 정정 `1593322` → 푸시 기록(이 문서). 2026-09-25 사용자 요청으로 모두 푸시했다 |
| 테스트 | `uv run pytest` 218개 통과(가짜 ComfyUI·가짜 sprite-gen. codex는 부르지 않는다), `uv run pytest -m gpu` 3개(image, pixel, bgm) |
| 린트·빌드 | `ruff check`, `ruff format --check`, oxlint, `npm --prefix web run build` 통과 |
| 실행 중 | 사용자 PC의 백엔드와 ComfyUI 상태는 각자 `/api/status`에서 확인한다. |
| MCP 등록 | `claude mcp add --transport stdio aiassetstudio --scope user -- uv --directory <저장소 경로> run python -m aiassetstudio mcp` |
| 사용자 데이터 | `data/`는 로컬 데이터이며 git에 포함하지 않는다. |
| 애니메이션 준비 | sprite-gen과 codex CLI가 필요하다. `/api/status`의 `animation`에서 준비 상태를 확인한다. |

### 이 문서 이후 (2026-09-25, 두 번째 세션)

- 픽셀아트 정수배 확대(T3.C.2)를 구현하고 검증했다. 커밋 `a87319c`(`pixel-grid` 브랜치 → `master` fast-forward)이고, 이 문서와 함께 푸시했다. pytest는 168개다. 자세한 내용은 Phase 3 작업지시서 "후속: T3.C.2"에 있다.
- 사용자 결정: 1배 결과가 캔버스를 다 채우지 않아도 그대로 둔다. 기존 LAST LIGHT 에셋은 다시 처리하지 않는다.
- 세션 밖 실행 실전 확인을 통과했다. 백엔드는 실행을 시작한 클라이언트 세션이 끝난 뒤에도 동작한다.
- 코드 변경 후에는 실행 중인 백엔드를 재시작하고, MCP 도구 변경 시 Claude Code 세션도 다시 연다.
- `/favicon.ico` 404를 고쳤다. 갤러리 페이지에는 Phase 2부터 `favicon.svg`가 있었고, 브라우저가 HTML이 아닌 주소에서 따로 찾는 `favicon.ico`만 없었다. 같은 모양의 `web/public/favicon.ico`(16·32·48px)를 넣었다.
- LAST LIGHT 그림자 적을 새 백엔드로 두 번 더 뽑았다. 둘 다 후보 상태이고, 내보내지 않았다.
  - `00580bf6f205`: 예전과 같은 설명. 4장 모두 원래 크기(32px 칸, 1배)로 나왔다. 게임 아트(`ArtSource/LastLight`, 읽기만)와 비교해서 두 가지 차이를 찾았다. 발이 2px 낮았고(게임은 28번째 줄, 스튜디오는 30번째 줄), 색이 keeper를 따라 "어두운 keeper"가 됐다(게임 그림자는 보라·검정·라벤더).
  - 사용자 결정으로 고쳤다: 참고 이미지가 있는 픽셀 프로젝트의 스프라이트는 참고 이미지의 대상이 선 줄에 선다(`reference_ground`, Phase 3 작업지시서 "후속: 참고 이미지의 발 줄"). 백엔드를 다시 띄워 적용했다.
  - `ea16033ac297`: 설명에 게임 그림자의 색과 모양을 적었다("purple-black smoke ... lavender eyes ... not blue, brass or cream"). 4장 모두 보라·검정에 라벤더 눈으로 나와, 프로젝트 화풍과 참고 이미지의 keeper 색 지시를 넘었다. 발은 모두 28번째 줄이다. 다만 연기 모양이라 격자를 못 찾아 늘려 맞췄고, 그래서 게임 그림자보다 크다.
- 이 문서는 처음에 커밋하지 않기로 했다가, 사용자 요청으로 커밋하고 푸시했다.

### 애니메이션 확장 (2026-09-25, 세 번째 세션)

- 적 스프라이트 한 장으로 대기 4 + 이동 6 프레임을 LAST LIGHT 규약(32×32, 발 28번째 줄, idle 0.18초·walk 0.1초)으로 만든다. 계획: [`aiassetstudio-animation-roadmap.md`](./aiassetstudio-animation-roadmap.md). 결정과 실측은 두 작업지시서 끝의 "구현 메모"에 있다.
- 사용자 결정: 적 정면 10프레임, 클라우드는 프로젝트별로 켜기(기본 꺼짐), 내보내기는 게임 규약 그대로. 이 세션에서 그림자 적을 OpenAI로 보내는 것을 허락받았다("보내서 만들기").
- 시험(T1.A.1, [`notes/animation-trial.md`](./notes/animation-trial.md)): codex는 기본 그림보다 촘촘한 격자로 크게 그린다. 원본 줄을 두 배 칸으로 다시 추출하고, 줄마다 높이를 기본 그림에 맞춰 줄인다(kCentroid 방식). 색은 기본 그림의 색으로 맞춘다.
- 실전: lastlight의 그림자 적 `622203551b15`로 애니메이션 `958d5bfbdf52`를 만들어 `data/exports/lastlight-trial/shadow_anim.png`·`shadow_anim.json`·`shadow_anim/000~009.png`로 내보냈다. 대기·이동 18×26(기본 17×26), 5색, 80초였다. 만들 때만 lastlight의 `animation_cloud`를 켜고, 끝난 뒤 다시 껐다.
- MCP 서버와 백엔드를 다시 시작하면 최신 코드와 도구 정의가 적용된다.

## 구조

```
Claude Code 세션 ─ MCP(stdio) ─ mcp_bridge/ ─┐
웹 갤러리 (web/, http://127.0.0.1:8765/) ──────┤ HTTP
                                              ▼
             백엔드 FastAPI (api/app.py, 127.0.0.1:8765)
               ├ 작업 대기열 jobs/queue.py
               │    GPU 작업 1개씩, 같은 모델 계열 우선, 계열이 바뀌면 /free, 60초 유휴면 /free
               ├ 실행기 jobs/runners.py
               │    이미지(인코딩 분리 → 후보) / BGM(ACE-Step·YuE2) / 애니메이션(sprite-gen + codex, 클라우드)
               ├ 후처리 post/image.py, post/audio.py, post/animation.py
               ├ sprite-gen 호출 spritegen/ (하위 프로세스, codex 로그인 확인)
               ├ 저장 store/ (SQLite data/studio.db, 파일 data/projects/<slug>/…)
               └ ComfyUI 연결 comfy/ (그래프, 사전 점검, 자동 실행)
                              ▼
             ComfyUI 0.37.0 (127.0.0.1:8188, 다른 세션과 공유)
```

## 코드 지도

- `src/aiassetstudio/config.py`: 설정(`AIAS_*` 환경 변수)
- `api/app.py`, `api/schemas.py`: HTTP API와 요청 검증
- `jobs/queue.py`: 단일 작업자 대기열. 계열이 바뀌면 메모리를 비우고 `timings.free_before`를 남긴다. 클라우드 계열(`codex`)은 ComfyUI를 띄우지 않고, 시작할 때 올라가 있던 모델을 비운다
- `jobs/runners.py`
  - `run_image_job`: 인코딩 분리, 참고 이미지 업로드, 픽셀 규격
  - `run_bgm_job`: ACE-Step 또는 YuE2, 템포 검출, 루프
  - `run_animation_job`: `animation_cloud` 재확인, 기본 스프라이트 1024px 확대, `run/gen`(프로젝트 칸)에서 codex 생성, `run/native`(두 배 칸)에서 다시 추출, `fit_frames`, 파일(`row`·`json`·`preview`·`gif`·`base`, `frames/000~009.png`)
- `comfy/graphs.py`: Qwen-Image-2.1 + Viggle Turbo, 참고 이미지(latent), ACE-Step 1.5, YuE2 그래프
- `comfy/client.py`: ComfyUI HTTP. `comfy/preflight.py`: 노드·모델 점검. `comfy/launcher.py`: ComfyUI 자동 실행
- `post/image.py`: 알파 정리, 떨어진 옅은 조각과 아이콘 고리 제거, 자르기, 아이콘 캔버스, `pixelate`. `pixelate`는 모델이 그린 칸 격자를 찾으면(`find_pixel_grid`) 칸 하나를 픽셀 하나로 되살려 정수배로만 키우고, 못 찾으면 캔버스에 맞춰 늘린다(`meta.pixel.fit`)
- `post/audio.py`: 끝 무음 자르기, 조용한 인트로 건너뛰기, 템포 검출(librosa), 마디 루프 + 크로스페이드, WAV·OGG
- `post/animation.py`: 게임 규약(`ROWS`, `game_tags`), 줄마다 기본 그림 높이로 줄이기(kCentroid), 캔버스에 맞추기, 기본 그림 색으로 맞추기, 발 줄, 한 줄 PNG·JSON·번호 시트·GIF
- `spritegen/client.py`: sprite-gen CLI를 stage마다 하위 프로세스로 부른다(PATH 앞에 codex 폴더, 취소 때 `taskkill /T`). `spritegen/access.py`: sprite-gen과 codex 로그인 확인
- `prompts.py`: 투명 문구, 스프라이트·아이콘 템플릿, 참고 이미지 편집 문구, 픽셀 문구
- `store/`
  - `db.py`: SQLite. `files.py`: 경로 규칙. `models.py`: 레코드
  - `reference.py`: 참고 이미지 사본(내용 해시 이름, 256px 이하는 최근접 정수배 확대)
- `mcp_bridge/`
  - `server.py`: 도구 13개(`generate_animation` 포함)
  - `tools.py`: 도구 로직
  - `studio_api.py`: 백엔드 HTTP 클라이언트, 백엔드 자동 실행
- `detach.py`: 세션 밖 실행(WMI). 백엔드와 ComfyUI를 이것으로 띄운다
- `cli.py`: `serve`, `check`, `mcp`
- `web/`: React 19 + Vite 갤러리(`web/src/components/*`)
- `scripts/`
  - `smoke_image.py`
  - `smoke_mcp.py`(`--generate`, `--pixel <참고>`, `--bgm --vocal`, `--animation <참고>`, `--keep-backend`)
  - `animation_trial.py`: 애니메이션 축척 시험(codex, 결과는 임시 폴더)
  - `validate_ref_rgba.py`
  - `vocal_check.py`
- `tests/`: 가짜 ComfyUI(`fakes.py`)와 가짜 sprite-gen(`fake_spritegen.py`)으로 도는 테스트. `tests/gpu/`는 실제 GPU 테스트
- `spikes/`: 초기 실측 스크립트(참고용)

## 자주 쓰는 명령

```
uv sync
npm --prefix web install
npm --prefix web run build
uv run python -m aiassetstudio check    # ComfyUI와 qwen·ace·yue2 노드·모델 점검
uv run python -m aiassetstudio serve    # 개발용. 세션 안에서 띄우면 세션과 함께 꺼진다
uv run pytest
uv run pytest -m gpu                    # ComfyUI가 바쁘면 건너뜀
uv run ruff check . ; uv run ruff format --check .
npm --prefix web run lint ; npm --prefix web run build
```

종단검증은 MCP 클라이언트로 Claude Code와 같은 흐름을 돈다. 사용자 `data/`를 건드리지 않게 포트와 데이터 폴더를 바꿔서 한다.

```
$env:AIAS_PORT = "8766"; $env:AIAS_DATA_DIR = "<임시 폴더>"
uv run python scripts/smoke_mcp.py --pixel <참고 이미지 경로>
uv run python scripts/smoke_mcp.py --bgm --vocal
uv run python scripts/smoke_mcp.py --animation <시험 이미지 경로>
python scripts/vocal_check.py <곡 파일들>
```

`--animation`은 시험 스프라이트를 codex로 OpenAI에 보낸다(1~3분).

## 꼭 지킬 규칙 (사용자와 합의)

- LAST LIGHT 검증 에셋은 이 저장소의 `data/` 아래에 두며, 게임 프로젝트 파일은 검증 중 변경하지 않는다.
- **커밋**은 사용자가 승인한 뒤에 한다. **푸시**는 사용자가 요청할 때만 한다.
- **ComfyUI는 다른 세션과 공유한다.** GPU 작업 전에 `http://127.0.0.1:8188/queue`가 비었는지 확인한다. 사용자나 다른 세션의 프로세스와 ComfyUI를 강제로 끄지 않는다.
- **사용자 `data/`에 백엔드를 두 개 띄우지 않는다**(대기열 작업자가 둘이 된다). 시험은 `AIAS_PORT=8766`(또는 8767)과 임시 `AIAS_DATA_DIR`로 한다.
- 응답은 한국어로 한다(전역 `~/.claude/CLAUDE.md`). 생성 요청의 설명(description, brief)은 영어로 쓴다.
- **애니메이션은 그림을 OpenAI로 보낸다.** 세션마다 처음 한 번은 무엇을 보낼지 알리고 허락을 받는다. 프로젝트의 `animation_cloud`는 사용자가 정한다(기본 꺼짐). 종단검증은 임시 데이터 폴더의 시험 프로젝트로 한다. pytest는 진짜 sprite-gen이나 codex를 부르지 않는다.
- 사용자의 `~/.codex/config.toml`과 시스템 PATH는 바꾸지 않는다.

## 알아 둘 함정

- **세션 안에서 띄운 프로세스는 세션이 끝날 때 함께 죽는다**(Windows Job). 그래서 백엔드와 ComfyUI는 `detach.spawn_detached`(WMI)로 띄운다. 세션 Job은 `CREATE_BREAKAWAY_FROM_JOB`을 거부한다. 개발용으로 세션 안에서 `serve`를 띄우면 그 백엔드는 세션과 함께 꺼진다.
- **MCP 서버는 세션이 시작될 때 코드를 불러온다.** MCP 쪽 코드를 바꾸면 새 세션을 열어야 반영된다. 백엔드 코드를 바꾸면 8765 백엔드를 껐다 켠다. 끄는 명령은 README "끄기"에 있고, 끄면 다음 MCP 호출 때 새 코드로 뜬다.
- **`aiassetstudio.exe`로 띄운 프로세스가 있으면** uv가 exe를 못 바꿔 `uv sync`·`uv add`가 실패한다. 항상 `python -m aiassetstudio`를 쓴다.
- **셸 함정:**
  - Bash heredoc 안의 Python 문자열에 백슬래시(`\n`, `C:\...`)를 넣으면 실제 줄바꿈이나 CR로 망가진 적이 있다. 백슬래시가 든 편집 스크립트는 Write 도구로 파일에 쓴 뒤 실행한다.
  - 긴 heredoc이 중간에 잘린 적도 있다.
  - PowerShell 5.1에서 여러 줄 커밋 메시지는 파일로 써서 `git commit -F`로 넘긴다.
- **미리보기 창이 가려지면** requestAnimationFrame, ResizeObserver, 스크린샷이 멈추고 뷰포트가 0×0이 된다. `resize_window`로 크기를 에뮬레이트하고 `javascript_tool`로 확인한다.
- **이미지:**
  - VAE 디코드가 텍스트 인코더와 한 프롬프트에 있으면 40초~6분 멈췄다. 그래서 인코딩 전용 프롬프트 → `/free(unload_models, free_memory=False)` → 후보 순서로 돌린다(구현됨).
  - 참고 이미지는 `latent` + 편집 문구에서만 새 대상을 그렸다(사용자 결정). 스프라이트에만 쓰고, 참고 이미지의 자세와 윤곽을 따라가는 경향이 있다.
  - 아이콘에 원형 고리가 가끔 붙는다. 문구로는 줄지 않았고, 후처리로 지운다.
- **애니메이션:**
  - PATH의 `codex`(0.147 독립 설치본)는 새 `~/.codex/config.toml`을 못 읽고 끝난다. Codex 앱의 CLI(`%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`)를 sprite-gen 하위 프로세스의 PATH 앞에 붙인다(`config.find_codex_dir`, `AIAS_CODEX_DIR`).
  - sprite-gen 2.9.0의 `--fit-logical-height`는 아무것도 줄이지 않는다(누르는 기능이 2026-07에 빠졌다). 남은 축소는 "칸 - 여백" 상한뿐이고, 줄마다 가장 큰 프레임 기준이라 줄 사이 크기가 달라진다. 그래서 두 배 칸으로 다시 추출한다.
  - sprite-gen `palette.lock.json`은 12색이어도 프레임에는 16~19색이 있었다. 색은 스튜디오가 맞춘다.
  - `gen-set`의 stdout 끝은 JSON이 아니라 표다. 결과는 `reports/gen-set/set.report.json`에서 읽는다. `codex login status`는 결과를 stderr에 찍는다. sprite-gen에는 `--version`이 없다.
  - sprite-gen은 Windows 콘솔(cp949)에 한국어·대시를 못 찍고 죽는다. `PYTHONIOENCODING=utf-8`로 부른다.
- **음악:**
  - ACE-Step은 요청과 다른 템포로 만들 때가 있다(96 → 98.01 BPM). 그래서 템포를 검출한 뒤 그 템포의 마디로 자른다. librosa 첫 호출은 numba 컴파일에 약 11초가 걸린다.
  - YuE2는 템포 입력이 없어서 스타일 문장에 "N BPM"을 붙인다.
  - Demucs 보컬 비율은 플루트 같은 선율을 보컬로 셀 수 있다(2.8% 사례).

## 남은 일

### 사람이 할 것

0. **애니메이션 판단.** `data/exports/lastlight-trial/shadow_anim*`(또는 갤러리 `http://127.0.0.1:8765/#/p/lastlight`의 애니메이션 카드)이 게임에 넣을 만한지 본다. 애니메이션 로드맵 최종 체크리스트의 시나리오 1이다. 새 Claude Code 세션에서 "lastlight 애니메이션 클라우드 켜줘" → "그림자 적으로 애니메이션 만들어줘"를 한 번 해 보면 MCP 흐름도 확인된다.
1. **LAST LIGHT 결과 판단.** 로드맵 최종 체크리스트의 마지막 항목이다.
   - 갤러리: `http://127.0.0.1:8765/#/p/lastlight`
   - 파일: `data/exports/lastlight-trial/`
   - Claude가 고른 것: 그림자 1, 랜턴 2, 기름 1. 그림자 4는 keeper를 닮아 버렸다. BGM 2곡은 후보로 두었다.
   - 두 번째 세션에서 새로 뽑은 그림자 적 2묶음도 같은 갤러리에 있다(`#/jobs/00580bf6f205`, `#/jobs/ea16033ac297`, 위 "이 문서 이후").
2. **BGM 청취.** 반복 지점의 딸깍 소리와 자연스러움을 확인한다. 과거 임시 검증 자료는 보존되지 않을 수 있으므로 새 검증에서 만든 후보를 듣는다.
3. ~~**세션 밖 실행 실전 확인.**~~ 통과했다(위 "이 문서 이후").

### 다음 개발 후보 (계획 밖, 사용자와 정할 것)

- ~~**픽셀아트 비정수배 확대.**~~ 두 번째 세션에서 구현했다(`a87319c`). 간격 최빈값 대신 색 경계의 주기 분석으로 모델 격자를 찾는다. 격자가 고르지 않으면 예전처럼 늘려 맞춘다.
- **참고 이미지 영향 조절.** 참고 이미지가 자세와 윤곽을 끌어온다(적 4가 keeper를 닮음). 문구 보강이나 강도 조절을 실험해 볼 수 있다. 색은 설명에 적는 것만으로 바뀌었다(`ea16033ac297`). 대신 연기처럼 격자 없이 그려져 늘려 맞춰졌다.
- **확장.** 로드맵 Out of Scope의 첫 확장 후보는 4방향 시트와 애니메이션 프레임이다. v1.1 후보는 타일셋, 배경, 초상화다.
  - ~~**애니메이션(적 정면 10프레임, sprite-gen + codex)**~~ 끝냈다(위 "애니메이션 확장").
  - 애니메이션 다음 후보(애니메이션 로드맵 Out of Scope): 주인공 4방향(방향마다 기준 그림이 필요하다), 공격 등 다른 상태(codex 시험은 성공), 다시 뽑기, 별도 클라우드 대기열, 보스 48×48 확인.
  - codex가 그린 모양은 줄마다 다를 수 있다. 종단검증의 넓은 망토 그림자는 대기 폭 31칸, 이동 폭 19칸이었다. 크기 판정은 대기만 본다.
- ~~**사소한 것.** 갤러리에 favicon이 없다(`/favicon.ico` 404).~~ 고쳤다(`web/public/favicon.ico`).

## 새 세션 첫 단계

1. `git status -sb`, `git log --oneline -3`로 `master`와 `origin/master`가 같은지, 작업 트리가 깨끗한지 확인한다.
2. `curl http://127.0.0.1:8765/api/status`로 백엔드, ComfyUI, 사전 점검 상태를 본다. 꺼져 있으면 MCP 도구 호출(`studio_status`)이 백엔드를 띄운다.
3. `uv run pytest -q`로 218개 통과를 확인한다.
4. 사용자에게 위 "남은 일" 중 무엇부터 할지 묻거나, 받은 지시를 시작한다.

## 참고 문서

- 로드맵: `docs/plans/aiassetstudio-roadmap.md` (끝에 최종 점검 기록)
- 작업지시서: `docs/plans/aiassetstudio-phase-{1,2,3,4}-*.md`. 끝의 "구현 메모"에 계획과 다르게 한 것, 실측, 후속 수정이 있다
- 애니메이션: `docs/plans/aiassetstudio-animation-{roadmap,prd,phase-1-claude-code,phase-2-gallery}.md`, 시험 기록 `docs/plans/notes/animation-trial.md`, 코드 분석 `docs/plans/codebase-analysis.md`
- 참고 이미지 검증: `docs/plans/notes/ref-rgba-validation.md`
- README: 설치, 실행, MCP 등록, 끄기, 문제 해결
- 기획: `concept.md`, `prd.md`, `priority.md`, `ux-flow.md`

## 새 세션 시작 문장 (예시)

> `docs/plans/aiassetstudio-handoff.md`를 읽고 이어서 해줘. 먼저 현재 상태를 확인하고, 남은 일 중 무엇부터 할지 알려줘.
