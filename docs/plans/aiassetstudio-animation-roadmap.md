# AIAssetStudio 애니메이션 — 개발 로드맵

_이 문서는 애니메이션 확장의 **총괄본**이다. Claude Code는 이 로드맵을 먼저 읽고 전체 맥락을 파악한 뒤, 각 페이즈 작업지시서로 가서 구현한다. 페이즈를 넘어갈 때는 반드시 사용자 확인을 받는다._

_작성일: 2026-09-25_
_예상 전체 소요: 약 42시간 (Phase 1 약 30시간, Phase 2 약 12시간)_
_페이즈 수: 2개_

## Overview

AIAssetStudio는 이 PC의 ComfyUI 모델로 투명 스프라이트·아이콘·BGM을 만드는 개인용 스튜디오다. Phase 1~4와 후속 작업(모델 격자 정수배, 참고 이미지 발 줄)까지 끝났다. 이번 확장은 스튜디오에서 고른 적 스프라이트 한 장으로 LAST LIGHT 규약에 맞는 애니메이션을 만든다. 규약은 32×32, 발 28번째 줄, 한 줄 10프레임(대기 4 + 이동 6)이다.

- 지금 게임의 움직임은 `Tools/build_campaign_art.py`가 기본 포즈를 1px 흔들고 발만 좌우로 민 것이다.
- 생성은 sprite-gen(aldegad/sprite-gen, Apache-2.0)을 codex provider(ChatGPT 구독 이미지 생성)로 돌린다.
- 2026-09-25 시험
  - codex로 대기·정면 걷기·공격 3줄이 모두 같은 캐릭터로 나왔다. 한 줄에 60~90초였다.
  - 다만 프레임이 기본 그림보다 약 15% 컸다(20×29 대 17×26).
  - 로컬 Qwen은 대기만 성공했다.
- 기본 그림이 OpenAI로 전송된다. 이 스튜디오에서 처음으로 클라우드를 쓰는 기능이므로, 프로젝트마다 켜야만 동작한다(사용자 결정).

## 완료 조건 (전체)

- [x] 클라우드를 켠 LAST LIGHT 프로젝트에서 Claude Code가 `generate_animation(asset_id)`로 적 애니메이션 후보를 만든다. `get_job`의 프레임 시트 미리보기로 확인하고, `export_asset`으로 `<이름>.png`(320×32), `<이름>/000~009.png`, `<이름>.json`(idle 0~3 0.18초, walk 4~9 0.1초)을 받는다.
- [x] 모든 프레임은 프로젝트 크기(32×32), 알파 0/255, 색 `max_colors` 이하다(고정 팔레트면 그 색만). 발은 프로젝트 발 줄에 선다. 대기 프레임 높이가 기본 그림과 ±1칸 안이거나, 아니면 "크기 다름"이 표시된다.
- [x] 클라우드가 꺼진 프로젝트는 애니메이션 요청을 거부하고, 아무것도 외부로 보내지 않는다. 기존 `studio.db`는 v2로 올라가도 데이터가 그대로다.
- [x] 갤러리에서 애니메이션 카드가 움직이고, 상세에서 대기·이동을 따로 재생하며 고르고 버리고 내보낸다.
- [x] 애니메이션 작업은 ComfyUI를 띄우지 않는다. 시작할 때 올라가 있던 GPU 모델은 비워 공유 GPU를 돌려준다. `studio_status`가 애니메이션 준비 상태(sprite-gen, codex 로그인)를 보인다.

## 기술 스택 / 환경

- **언어 / 런타임**: Python 3.13(uv), Node 22 — 기존과 같다
- **주요 프레임워크 / 라이브러리**: FastAPI, MCP Python SDK v2, Pillow·numpy, React 19 + Vite. 새 Python 의존성은 없다(sprite-gen은 subprocess로 부른다)
- **외부 도구**
  - sprite-gen 2.9.0(commit `b65058c`): `<sprite-gen 경로>\.venv\Scripts\sprite-gen.exe`
  - codex CLI 0.155 이상: Codex 앱의 `%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`. PATH의 0.147 독립 설치본은 새 `~/.codex/config.toml`을 못 읽는다.
- **저장소 / DB**: SQLite `data/studio.db`. 스키마 v1에서 v2로 올린다(`projects.animation_cloud`).
- **실행 환경**: Windows, 이 PC. 8765 백엔드는 세션 밖(WMI)에서 돈다.

코드 구조와 컨벤션은 [`codebase-analysis.md`](./codebase-analysis.md)에 있다.

## Out of Scope

- 주인공 4방향: 방향마다 기준 그림이 필요하고 시험하지 않았다(다음 확장 1순위).
- 공격 등 다른 상태: 게임에 규약이 없다.
- 로컬(Qwen) 생성: 대기만 성공했다.
- Grok 이미지·영상: 로그인이 없다.
- 별도 클라우드 대기열: MVP는 기존 대기열을 같이 쓴다. 애니메이션이 도는 동안 GPU 작업은 기다린다.
- 갤러리의 "애니메이션 만들기" 버튼: 주 사용 방식이 MCP다.
- 보스 48×48 보장: 동작은 할 수 있지만 시험하지 않는다.
- Aseprite 파일 직접 만들기: 게임의 `archive_campaign_art.lua`가 PNG로 만든다.

## 페이즈 구성

각 페이즈는 **수직 슬라이스**다. 끝나면 실제로 쓸 수 있는 흐름이 하나 생긴다.

### Phase 1: Claude Code에서 적 애니메이션 한 벌 — 요청부터 게임 형식 내보내기까지

- **목표**: 클라우드를 켠 프로젝트에서 Claude Code가 스프라이트 하나로 애니메이션을 만들고, 미리보기로 확인하고, 게임 형식으로 내보낸다.
- **포함 기능**: 클라우드 사용 설정(API·MCP), 애니메이션 작업(sprite-gen + codex), 축척·일관성 맞추기, MCP `generate_animation`·`get_job` 미리보기, 게임 규약 내보내기
- **예상 소요**: 약 30시간
- **작업지시서**: [`aiassetstudio-animation-phase-1-claude-code.md`](./aiassetstudio-animation-phase-1-claude-code.md)
- **Checkpoint 요약**: `smoke_mcp.py --animation`(실제 codex, 임시 데이터)이 320×32 줄, 10프레임, JSON을 내보내고, 크기·발 줄·색 점검을 통과한다.

### Phase 2: 갤러리에서 보고 고르기 — 움직임을 눈으로 확인

- **목표**: 갤러리에서 애니메이션이 움직이는 것을 보고, 대기·이동을 따로 재생하며 고르고 버리고 내보낸다. 프로젝트 정보와 상태 표시에 클라우드 설정과 준비 상태가 보인다.
- **포함 기능**: 애니메이션 카드와 상세, 프로젝트 정보와 상태 표시, 문서 정리
- **예상 소요**: 약 12시간
- **작업지시서**: [`aiassetstudio-animation-phase-2-gallery.md`](./aiassetstudio-animation-phase-2-gallery.md)
- **Checkpoint 요약**: 브라우저에서 Phase 1 결과가 정수배로 움직이고, 상세의 재생·고르기·내보내기가 동작한다.

## 페이즈 간 의존성

```
Phase 1 (백엔드 + MCP: 만들고 확인하고 내보내기)
  └─→ Phase 2 (갤러리: 보고 고르기)
```

**병렬 가능성**: 없다. Phase 2의 화면은 Phase 1이 만든 에셋 형식(`meta.animation`, 파일 역할)을 쓴다.

**가장 큰 위험**: Phase 1의 첫 시험(T1.A.1, 축척과 이동 6프레임)이다.
- codex가 크기 힌트를 따르지 않고 `--fit-logical-height` 후처리도 윤곽을 망가뜨리면, "다시 뽑기"를 넣어야 한다.
- 다시 뽑기는 후보 하나에 60~90초와 ChatGPT 구독 사용량이 더 든다. 예상 시간(30시간)도 늘어날 수 있다.
- 결과가 나오면 사용자와 방식을 다시 정한다.

## 페이즈 간 전환 규칙

각 페이즈는 다음 조건을 만족해야 완료로 본다.

1. 작업지시서의 모든 체크박스 완료
2. Checkpoint 블록의 모든 검증 통과
3. 사용자가 명시적으로 "Phase N 완료 확인, 다음 진행"을 승인

Checkpoint가 실패하면 원인을 보고하고, 사용자와 함께 원인을 찾아 고친 뒤 다시 검증한다. 재검증을 통과하고 사용자가 승인하면 다음 페이즈로 간다.

**이 확장에만 있는 규칙**
- 실제 codex를 부르는 시험은 기본 그림을 OpenAI로 보낸다. 세션마다 처음 한 번은 사용자에게 무엇을 보낼지 알리고 허락을 받는다. 그다음 종단검증은 임시 데이터 폴더의 시험 프로젝트로만 한다.
- 커밋은 사용자 승인 뒤에만 한다. 푸시는 요청할 때만 한다.
- 게임 프로젝트에는 직접 쓰지 않는다. 게임 아트와 규약은 읽기 전용으로 참고한다.

## 최종 완료 체크리스트 (전 페이즈 종료 후)

- [x] 모든 페이즈 Checkpoint 통과(자동 검증과 브라우저 확인. 사람이 할 수동 확인은 아래 시나리오 1)
- [x] 전체 테스트: `uv run pytest`(218개)
- [x] 린트: `uv run ruff check .`, `uv run ruff format --check .`, `npm --prefix web run lint`, `npm --prefix web run build`
- [ ] 시나리오 1: Claude Code에서 LAST LIGHT 그림자 적으로 애니메이션을 만들어 `data/exports/lastlight-trial/`에 내보내고, 사용자가 게임에 넣을 만한지 판단
  - 만들고 내보내기까지 했다(2026-09-25, 애니메이션 `958d5bfbdf52` → `data/exports/lastlight-trial/shadow_anim.png`·`.json`·폴더). **사용자 판단이 남았다.**
- [x] 시나리오 2: 클라우드가 꺼진 프로젝트에서 요청하면 거부된다(API 422, 실행기, MCP. 테스트와 `smoke_mcp.py --animation`)
- [x] Out of Scope 항목을 구현하지 않았다
- [x] 기존 컨벤션(`codebase-analysis.md`)을 지켰다
- [x] 문서: README(애니메이션, 클라우드 설정, codex·sprite-gen 준비, 갤러리), 인수인계 문서

### 최종 점검 기록 (2026-09-25)

- 커밋: 계획 `153f325` → Phase 1 `b79c69c` → Phase 2 `6079731`. 2026-09-25 사용자 요청으로 푸시했다.
- T1.A.1 시험으로 방식을 바꿨다. 크기 힌트와 `--fit-logical-height` 대신, 원본 줄을 두 배 칸으로 다시 추출하고 줄마다 기본 그림 높이로 줄인다(`notes/animation-trial.md`, Phase 1 구현 메모).
- 실제 codex로 세 번 만들었다. 시험 에셋(4줄), 종단검증(8766, 임시 데이터), LAST LIGHT 그림자 적(8765, 사용자 데이터)이다. 한 줄에 51~73초였다.
- 사용자 `data/studio.db`는 스키마 v2로 올라갔다. 올리기 전 사본이 `data/backups/studio-before-v2-2026-09-25.db`에 있다.

## 참고 자료

- 코드베이스 분석: [`codebase-analysis.md`](./codebase-analysis.md)
- PRD: [`aiassetstudio-animation-prd.md`](./aiassetstudio-animation-prd.md)
- sprite-gen 문서: `<sprite-gen 경로>\docs\`(`run-contract.md`, `pixel-unfake.md`, `states-and-frames.md`, `gen.md`)
- 게임 프레임 규약(읽기만): `<게임 프로젝트 경로>\Tools\build_campaign_art.py`, `Tools\archive_campaign_art.lua`
- 시험 기록: Claude 메모리 `aiassetstudio-sprite-gen-idea.md`

---
_Claude Code 사용 시: 이 로드맵을 먼저 읽고 전체 맥락을 파악한다. 그다음 Phase 1 작업지시서로 가서 구현을 시작한다. 페이즈 전환은 반드시 사용자의 명시적 승인 뒤에 한다._
