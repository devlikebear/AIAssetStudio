# 애니메이션 Phase 2: 갤러리에서 보고 고르기 — 작업지시서

_이 페이즈의 목표를 이루기 위한 구체적 작업 목록이다. Claude Code가 위에서부터 차례로 하되, 체크포인트에서 사용자 확인을 받는다._

_작성일: 2026-09-25_
_속한 로드맵: [`aiassetstudio-animation-roadmap.md`](./aiassetstudio-animation-roadmap.md)_
_예상 소요: 약 12시간_

## 페이즈 목표

갤러리에서 애니메이션 후보가 실제로 움직인다. 카드에서는 10프레임이 게임 시간대로 이어 재생된다. 상세에서는 대기와 이동을 따로 재생하고, 10프레임을 나란히 보고, 고르고 버리고 내보낸다. 프로젝트 정보에는 클라우드 설정과 애니메이션 준비 상태가 보인다. 이 페이즈가 끝나면 Claude Code로 만든 애니메이션을 사람이 갤러리에서 보고 고를 수 있다.

## 전제 조건

- [x] 애니메이션 Phase 1 완료(`b79c69c`). 사용자는 "개발완료까지 진행"으로 두 페이즈를 한 번에 맡겼다
- [x] Phase 1 종단검증 데이터(임시 폴더, `smoke-anim` 프로젝트)가 남아 있거나 다시 만들 수 있다(`smoke_mcp.py --animation --keep-backend`)

## 포함 기능

1. 애니메이션 카드 — 정수배 확대, 태그 시간대로 반복 재생, 고르기·버리기
2. 상세 화면 — 대기·이동·전체 재생, 10프레임 보기, 크기·발 줄·색·경고, 내보내기
3. 프로젝트 정보와 상태 — 클라우드 설정, 애니메이션 준비 상태, 작업 단계 이름
4. 문서 정리 — README, 인수인계, 로드맵 최종 점검

## 이 페이즈에서 하지 않는 것

- 갤러리에서 애니메이션 만들기 버튼, 클라우드 설정 바꾸기 → Out of Scope(갤러리는 읽기 전용 원칙. 설정은 MCP `update_project`)
- 프레임 편집(순서 바꾸기, 빼기) → Out of Scope
- 주인공 4방향 보기 → Out of Scope

## 작업 체크리스트

### 작업 그룹 A: 타입과 재생

- [x] **T2.A.1** — 타입과 표시 문구
  - 파일: `web/src/api.ts`, `web/src/format.ts`
  - 내용:
    - `AssetKind`에 `'animation'`, `Job.kind`에 `'animation'`, `Project.animation_cloud: boolean`을 넣는다.
    - `Status.animation?: { ok: boolean; reason?: string | null }`
    - `AnimationMeta`를 둔다. 필드는 `animation: { frames: number; cell: [number, number]; tags: { name: string; from: number; to: number; duration: number }[] }`, `fit: { base_size, idle_height, size_ok, ground_row, colors_used }`, `cloud: { provider: string }`, `spritegen?: { warnings: string[] }`이다. `AssetMeta`에 선택 필드로 넣는다.
    - `KIND_LABEL.animation = '애니메이션'`
    - `STAGE_LABEL['generating rows (codex)'] = '줄 생성 중(codex)'`
  - 참조: 기존 `PixelMeta`, `PixelFit`(선택 필드, 예전 에셋에 없음)
  - 검증: `npm --prefix web run build`

- [x] **T2.A.2** — 프레임 재생 훅
  - 파일: `web/src/hooks.ts`
  - 내용:
    - `useFramePlayer(tags, range: 'all' | 'idle' | 'walk', playing: boolean) -> number`: 현재 프레임 번호를 돌려준다. 태그의 `duration`(초)마다 다음 프레임으로 가고, 범위 끝에서 처음으로 돈다.
    - `setTimeout` 하나로 돌리고, 언마운트하거나 인자가 바뀌면 정리한다.
    - 가려진 탭에서는 브라우저가 타이머를 늦출 수 있다. 문제 삼지 않는다(인수인계 "미리보기 창이 가려지면" 함정 참고. 확인은 `javascript_tool`로).
  - 검증: 빌드. 동작은 T2.C.1에서 브라우저로 확인한다.

- [x] **T2.A.3** — 애니메이션 카드
  - 파일: `web/src/components/AnimationCard.tsx`, `web/src/components/JobGroup.tsx`, `web/src/App.tsx`, `web/src/App.css`
  - 내용:
    - `AnimationCard`
      - `row` 파일(10칸 한 줄)을 CSS 배경으로 쓴다. `background-size`를 `(10 × 칸 너비 × zoom)px`로 하고, `background-position`을 `-(현재 프레임 × 칸 너비 × zoom)px`로 옮긴다.
      - 새 클래스 `.frame-anim`에 `image-rendering: pixelated`를 직접 준다. 기존 `.pixelated` 규칙은 `<img>`용이라, 배경 이미지 `div`에는 따로 줘야 한다. 기존 `is-whole`의 `transform: none` 규칙(App.css)도 같이 따른다.
      - zoom은 `useWholeZoom(cell w, cell h)`로 정한다(기존 픽셀 카드와 같은 정수배 규칙).
      - 발 줄 선은 얇게 켤 수 있다(기본 끔).
    - 카드 아래 줄은 기존 카드와 같다(번호, 고르기, 버리기, `PencilMark`). 작은 표시 두 개를 더한다.
      - 클라우드: "codex"
      - `fit.size_ok`가 false면 "크기 다름"
    - `JobGroup`에서 `asset.kind === 'animation'`이면 `AnimationCard`를 쓴다.
    - `App.tsx`의 종류 필터에 `'animation'`('애니메이션')을 더한다.
  - 참조: `AudioCard.tsx`(종류별 카드, 칩, `PencilMark`), `CandidateCard.tsx`(`useWholeZoom`, `pixelated is-whole`)
  - 검증: `npm --prefix web run lint`, `npm --prefix web run build`

### 작업 그룹 B: 상세와 프로젝트 정보

- [x] **T2.B.1** — 상세 화면
  - 파일: `web/src/components/DetailModal.tsx`, `web/src/components/AnimationCard.tsx`(재생 부품을 함께 쓴다), `web/src/App.css`
  - 내용:
    - 애니메이션 에셋이면 보기 선택을 `재생` / `프레임`으로 바꾼다.
      - `재생`: 범위 `전체 / 대기 / 이동`(segmented), 재생·멈춤, 배율(맞춤 / 1× / 2× / 4×, 기존 zoom 규칙)
      - `프레임`: 10칸을 번호와 함께 나란히 둔다(정수배). 대기 0~3번과 이동 4~9번을 구분선으로 나눈다.
    - `facts`에 더한다.
      - 기본 스프라이트(`meta.base_asset`, 복사 버튼)
      - `프레임 32×32 · 대기 높이 26 (기본 26) · 발 28번째 줄 · 사용 색 11/12`
      - 경고(`spritegen.warnings` 앞 3개, 더 있으면 개수)
      - `codex(클라우드)로 만듦`
    - 내보내기 폼은 그대로 쓴다(이름 입력). 결과 표시에 파일 12개를 적는다.
  - 참조: 기존 BGM 분기(`song`), 픽셀 표시(`pixelView`, `useWholeZoom`), `pixelFitText`
  - 검증: 빌드. 동작은 T2.C.1에서 확인한다.

- [x] **T2.B.2** — 프로젝트 정보와 준비 상태
  - 파일: `web/src/components/ProjectInfo.tsx`, `web/src/App.tsx`(상태를 넘김)
  - 내용:
    - 행 추가 `['애니메이션', …]`
      - 켜짐: `'클라우드(codex) 허용 — 스프라이트가 OpenAI로 전송됨'`
      - 꺼짐: `'꺼짐 — Claude Code에서 update_project animation_cloud=true'`
    - 켜져 있는데 `status.animation.ok`가 false면 그 아래에 `'지금은 만들 수 없음: <reason>'`을 적는다.
    - 전역 배너(`StatusBanner`)에는 넣지 않는다. 애니메이션을 안 쓰는 프로젝트에는 소음이다.
  - 검증: 빌드

### 작업 그룹 C: 확인과 문서

- [x] **T2.C.1** — 브라우저 확인
  - 파일: 없음(확인만)
  - 내용:
    - 준비: Phase 1 종단검증 데이터로 8766 백엔드를 띄운다(`smoke_mcp.py --animation --keep-backend` 또는 남은 폴더 재사용).
    - 브라우저에서 `http://127.0.0.1:8766/#/p/smoke-anim`을 열고 확인한다.
      1. 카드가 움직인다. `javascript_tool`로 배경 위치가 시간에 따라 바뀌는지 본다.
      2. 정수배로 보인다(칸 크기 × zoom이 정수).
      3. 상세의 범위 전환(대기는 0~3번만, 이동은 4~9번만)과 멈춤이 된다.
      4. 프레임 보기에 10칸이 있다.
      5. 내보내기가 파일 12개를 만든다.
      6. 프로젝트 정보에 애니메이션 행이 있다.
    - 콘솔 오류가 없어야 한다. 스크린샷을 남긴다. 끝나면 8766 백엔드를 끈다.
  - 검증: 위 6가지 통과, 스크린샷

- [x] **T2.C.2** — 문서와 최종 점검
  - 파일: `README.md`, `docs/plans/aiassetstudio-handoff.md`, `docs/plans/aiassetstudio-animation-roadmap.md`(최종 체크리스트), 두 작업지시서의 구현 메모
  - 내용:
    - README 갤러리 절에 애니메이션 카드와 상세를 적는다.
    - 인수인계 문서에 새 상태를 적는다(커밋, 테스트 수, 애니메이션 준비 방법, 남은 일: 주인공 4방향 등).
    - 로드맵 최종 체크리스트를 채운다. 시나리오 1(LAST LIGHT 실전)은 사용자 판단 항목으로 남긴다.
  - 검증: 문서 검토

---

## ✅ 애니메이션 Phase 2 Checkpoint

**구현 확인:**
- [x] 모든 작업 체크박스 완료
- [x] 애니메이션 카드가 태그 시간대로 움직이고, 상세에서 대기·이동을 따로 재생한다
- [x] 예전 에셋(이미지, BGM)과 필터가 그대로 동작한다

**자동 검증:**
- [x] 갤러리: `npm --prefix web run lint`, `npm --prefix web run build`
- [x] 백엔드 회귀: `uv run pytest`(218개)
- [x] 린트: `uv run ruff check .`, `uv run ruff format --check .`

**수동 확인:**
- [x] T2.C.1의 브라우저 확인 6가지(측정값은 아래 구현 메모. 스크린샷은 파일로 남기지 않았고, 작업 세션 대화에만 있다)
- [ ] 사용자가 사용자 `data/`의 LAST LIGHT 애니메이션(Phase 1 수동 확인에서 만든 것)을 갤러리에서 보고, 고르고, 내보낸다(`http://127.0.0.1:8765/#/p/lastlight`, 백엔드를 다시 띄운 뒤)
  - 애니메이션 `958d5bfbdf52`가 lastlight 갤러리에 있다. 8765 백엔드는 Phase 2 코드로 다시 띄웠다(인수인계 문서).

**완료 처리:**
1. 위 항목을 모두 통과하면 Claude Code는 사용자에게 보고한다(한 작업, 자동 검증 결과, 스크린샷, 수동 확인이 필요한 항목).
2. 사용자가 "애니메이션 Phase 2 완료"라고 승인하면 커밋한다. 로드맵 최종 체크리스트로 마무리한다.
3. 체크포인트가 실패하면 실패 항목을 보고하고, 원인을 찾아 고친 뒤 다시 검증한다.

---

## 참고 자료

- 로드맵: [`aiassetstudio-animation-roadmap.md`](./aiassetstudio-animation-roadmap.md)
- Phase 1: [`aiassetstudio-animation-phase-1-claude-code.md`](./aiassetstudio-animation-phase-1-claude-code.md)(에셋 파일 역할과 `meta` 형식)
- 코드베이스 분석: [`codebase-analysis.md`](./codebase-analysis.md)
- 기존 갤러리: `web/src/components/AudioCard.tsx`, `CandidateCard.tsx`, `DetailModal.tsx`, `web/src/hooks.ts`(`useWholeZoom`)

## 메모 / 주의

- 픽셀아트는 정수배로만 확대한다(`useWholeZoom`, `transform` 금지 — App.css 주석). 배경 위치도 정수 px로 옮긴다.
- 미리보기 창이 가려지면 타이머, rAF, ResizeObserver가 멈출 수 있다. 확인은 `resize_window`와 `javascript_tool`로 한다(인수인계 함정).
- 갤러리는 읽기 전용이다. 설정 변경은 MCP로만 한다(기존 `ProjectInfo`의 안내 문구 유지).

## 구현 메모

_(구현하면서 계획과 다르게 한 것, 실측, 후속 수정을 여기에 적는다.)_

### 구현 (2026-09-25)

- **재생 훅** `useFramePlayer(tags, range, playing)`: 갤러리는 몇 초마다 새 에셋 객체를 받아 온다. 효과(effect)의 입력을 문자열·숫자로만 둬서(프레임 순서 키, 현재 칸, 그 칸의 시간), 새로 받아 올 때마다 타이머가 처음부터 다시 도는 끊김을 막았다. 범위를 바꾸면 그 범위의 첫 칸부터 돈다. 재생 순서는 `format.ts`의 `playOrder`다.
- **카드**: `row.png`을 배경으로 쓰는 `AnimationFrame`을 카드와 상세가 함께 쓴다. 카드는 항상 재생한다. 아래 줄의 시드 자리에 `codex`와 `크기 다름` 표시를 둔다.
- **상세**: `재생` 보기의 멈춤 버튼은 멈춘 뒤 `다시 재생`이 된다. 처음에는 `재생`이었는데, 보기 탭 `재생`과 이름이 같아 헷갈렸다(시험 스크립트도 엉뚱한 버튼을 눌렀다). `발 줄` 버튼은 두 보기 모두에서 발 줄 아래에 선을 긋는다. `프레임` 보기의 배율은 10칸에 간격 몫 12%를 더한 폭으로 정한다.
- **상세 정보**: 기본 스프라이트(작은 그림, id, 복사), 규격(`프레임 32×32 × 10 · 발 28번째 줄 · 사용 색 5/12 (기본 그림의 색)`과 대기·이동·기본 크기), 경고(스튜디오 경고, sprite-gen `inspect` 오류, sprite-gen 경고 순으로 앞 3개와 나머지 개수), 만든 곳(`codex(클라우드)로 만듦 · sprite-gen 2.9.0`)을 보인다. 이미지용 항목(시드, 프롬프트, 모델, 알파)은 숨긴다.
  - sprite-gen 경고는 격자 검출에 관한 영어 원문이라 길다(예: "harmonic/collapsed misdetection"). 계획대로 그대로 보인다.
- **백엔드 한 줄 추가**: "사용 색 5/12"를 보이려고 `meta.animation.max_colors`를 넣었다(`runners.run_animation_job`). 이 전에 만든 애니메이션은 사용 색 수만 보인다.
- **단계 이름**: `preparing`(sprite-gen 준비 중), `generating rows (codex)`(줄 생성 중(codex)), `extracting frames`(프레임 추출 중). 끝에 ` 1/2`가 붙어도 옮긴다.
- **작업 이름표와 MCP 문장**: 종류는 "애니메이션", "같은 설정 복사"는 `generate_animation(asset_id="…", count=1)`이다.

### T2.C.1 브라우저 확인 (2026-09-25)

8766 백엔드를 Phase 1 종단검증 데이터(임시 폴더, `smoke-anim`)로 띄워 확인했다. 미리보기 창이 가려져 있어 뷰포트를 1280×800으로 에뮬레이트했다.

1. 카드가 움직인다. 배경 위치가 `0 → -160 → … → -1440px`로 바뀌었다(칸 32 × 5배).
2. 정수배다. 카드 5배(160px, 배경 1600px), 상세 17배(544px, 배경 5440px), 프레임 보기 2배(64px)였다. `image-rendering: pixelated`
3. 상세에서 `대기`는 0~3번만, `이동`은 4~9번만 돌았다. `멈춤`이면 한 칸에 머물고, `다시 재생`이면 다시 돈다.
4. 프레임 보기에 000~009 10칸이 있다. `대기 · 180ms` 4칸과 `이동 · 100ms` 6칸이 구분선으로 나뉜다.
5. 상세에서 내보내기를 하면 파일 12개(PNG 11, JSON 1)가 생긴다. 결과 칸에 경로 셋과 "(한 줄 PNG, JSON, 폴더 안 프레임 PNG 10장)"이 나온다. 시험 프로젝트에는 내보내기 폴더가 없어서 API로 임시 폴더를 줬다.
6. 프로젝트 정보에 `애니메이션: 클라우드(codex) 허용 — 스프라이트가 OpenAI로 전송됨` 행이 있다.
- 콘솔 오류는 없었다. 종류 필터(`애니메이션`, `스프라이트`, `모든 종류`)와 기존 스프라이트 카드(`pixelated is-whole`)도 그대로다.
- 알려진 함정을 다시 봤다. 가려진 창에서는 ResizeObserver가 돌지 않는다. 그래서 뷰포트를 바꾼 뒤에도, 이미 떠 있던 재생 보기는 1배로 남았다. 보기를 바꿔 다시 붙이면 17배로 맞았다. 보이는 창에서는 크기가 바뀔 때마다 다시 잰다.

---
_이 로드맵의 마지막 페이즈다. 끝나면 로드맵 "최종 완료 체크리스트"로 간다._
