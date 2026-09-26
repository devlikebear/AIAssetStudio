# AIAssetStudio — 개발 로드맵

_이 문서는 전체 개발 계획의 **총괄본**이다. Claude Code는 이 로드맵을 먼저 읽고 전체 맥락을 파악한 뒤, 각 페이즈 작업지시서로 이동해서 구현을 진행한다. 페이즈를 넘어갈 때는 반드시 사용자 확인을 받는다._

_작성일: 2026-09-24_
_예상 전체 소요: 약 50시간 (1인 + Claude Code 기준 1~2주)_
_페이즈 수: 4개_

## Overview

여러 인디게임을 혼자 만드는 개발자(본인)를 위한 **로컬 게임 에셋 스튜디오**다. 이 PC의 로컬 모델로 프로젝트마다 정한 화풍과 규격에 맞는 스프라이트, 아이콘, BGM을 만든다. 이미지는 Qwen-Image-2.1, 연주곡은 ACE-Step 1.5, 보컬 곡은 YuE2를 쓴다. 외부 API는 쓰지 않는다.

주 사용 방식은 **Claude Code에게 시키기**다. 게임 작업 중인 Claude Code 세션이 MCP 도구로 생성을 요청하고, 사람은 웹 갤러리에서 결과를 보고 고른다. 음악은 Claude가 들을 수 없으므로 BGM 선택은 항상 갤러리에서 한다.

모든 생성은 **백엔드 하나가 작업 대기열로 순서대로** 처리한다. 16GB VRAM·32GB RAM에서는 이미지 모델과 음악 모델을 동시에 올릴 수 없고, 두 작업이 동시에 GPU를 쓰면 서로 멈춘다(2026-09-24 실측). MCP 서버와 웹 갤러리는 백엔드 HTTP API만 부르고 ComfyUI나 GPU를 직접 건드리지 않는다.

기획 문서: [컨셉](./concept.md) · [PRD](./prd.md) · [우선순위](./priority.md) · [UX 플로우](./ux-flow.md)

## 완료 조건 (전체)

- [x] 다른 게임 폴더의 Claude Code 세션에서 MCP로 프로젝트를 만들고, 스프라이트·아이콘 후보를 생성해 미리보기로 확인하고, 게임 폴더로 내보낼 수 있다.
- [x] 픽셀아트 프로젝트(예: 32×32, 12색)에서 나온 후처리본이 규격 크기, 최대 색 수 이하, 이진 알파(0/255)를 지킨다.
- [x] 참고 이미지 1장을 프로젝트에 지정하면 생성에 반영되고, 이때도 투명 배경이 유지된다(또는 검증에서 정한 대체 경로로 투명 PNG가 나온다).
- [x] 연주곡 BGM이 마디 경계에 맞춘 반복용 OGG/WAV로 나오고, 반복 이음새에서 딸깍 소리가 나지 않는다. 보컬 곡(YuE2) 옵션도 동작한다. (이음새 비율은 모두 1 이하. 실제 소리는 사용자가 들어 확인할 것)
- [x] 웹 갤러리에서 작업별 후보를 보고, 고르고, 버리고, 내보낼 수 있고, 대기열 상태가 보인다.
- [x] GPU 작업은 한 번에 하나만 돌고, 이미지↔음악 모델을 바꿀 때와 대기열이 60초 이상 비었을 때 ComfyUI 메모리를 비운다.

## 기술 스택 / 환경

- **언어 / 런타임**: Python 3.13 (uv로 관리하는 별도 가상환경 `AIAssetStudio/.venv`. ComfyUI의 가상환경은 건드리지 않는다), Node 22 + npm (갤러리 빌드용)
- **백엔드**: FastAPI + uvicorn, httpx(비동기 ComfyUI 클라이언트), SQLite(표준 `sqlite3`), Pillow + numpy(이미지 후처리), soundfile + numpy(오디오 후처리), ffmpeg(OGG 인코딩)
- **MCP 서버**: MCP 공식 Python SDK v2 (`mcp>=2.2`, `from mcp.server.mcpserver import MCPServer`), stdio 방식. Claude Code가 필요할 때 띄우고, 백엔드가 꺼져 있으면 MCP 서버가 백엔드를 띄운다.
- **갤러리**: React + Vite + TypeScript. 빌드 결과(`web/dist`)를 백엔드가 `/`에서 서빙한다.
- **테스트 / 린트**: pytest + pytest-asyncio, 가짜 ComfyUI는 `httpx.MockTransport`로 만든다. 실제 GPU 테스트는 `@pytest.mark.gpu`로 분리해 기본 실행에서 뺀다. 린트·포맷은 ruff.
- **실행 환경**: Windows 11, RTX 4090 Laptop 16GB, RAM 32GB. 백엔드는 `127.0.0.1:8765`, ComfyUI는 `127.0.0.1:8188`.
- **외부 의존**: ComfyUI 0.37.0 (`<ComfyUI 경로>`)과 설치된 모델. 노드 이름과 API 그래프가 이 버전 기준이므로, ComfyUI를 업데이트하면 `aiassetstudio check`로 먼저 점검한다.

### 설치된 모델 (2026-09-24 기준, 모두 ComfyUI `models/` 아래)

| 용도 | 파일 |
|---|---|
| 이미지 본체 | `diffusion_models/qwen_image_2.1_int8_convrot.safetensors` |
| 이미지 텍스트 인코더 | `text_encoders/qwen3vl_8b_int8_convrot.safetensors` |
| 이미지 VAE (RGBA 4채널) | `vae/qwen_image_2.1_vae_bf16.safetensors` |
| 이미지 고속 LoRA (6스텝) | `loras/Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r128.safetensors` + 커스텀 노드 `custom_nodes/viggle_turbo.py` |
| 연주곡 | `diffusion_models/acestep_v1.5_turbo.safetensors`, `text_encoders/qwen_0.6b_ace15.safetensors`, `text_encoders/qwen_4b_ace15.safetensors`, `vae/ace_1.5_vae.safetensors` |
| 보컬 곡 | `checkpoints/yue2_3b_int8_convrot.safetensors` |

### 검증된 레퍼런스 코드 (그대로 옮겨 쓸 것)

- `spikes/rgba_test.py` — Qwen-Image-2.1 + Viggle Turbo 투명 배경 API 그래프, 제출·대기 루프
- `spikes/acestep_bgm_test.py` — ACE-Step 1.5 연주곡 API 그래프
- `<ComfyUI 경로>\user\yue2_tools\yue2_run.py` — YuE2 보컬 곡 API 그래프(ABC 모드)
- `<ComfyUI 경로>\user\yue2_tools\vocal_energy.py` — HDemucs 보컬 비율 측정 (ai-toolkit 가상환경에서 실행)
- `<게임 프로젝트 경로>\Tools\build_game_art.py`의 `extract()` — 최근접 축소 → 고정 팔레트 매핑 → 이진 알파

## Out of Scope

MVP에서 명시적으로 뺀 것. 구현 중에 "이것도 필요한가?" 싶으면 여기를 본다.

- **4방향 시트, 애니메이션 프레임(걷기 등)**: 프레임 간 일관성 검증이 따로 필요하다. MVP 이후 첫 확장 후보.
- **타일셋, 배경, 초상화**: MVP를 키운다. v1.1 후보.
- **효과음**: 설치된 모델로는 만들 수 없다.
- **CLI (에셋 조작용)**: MCP로 충분하다. `aiassetstudio serve|mcp|check` 같은 실행용 명령만 둔다.
- **갤러리에서 생성하기, 갤러리에서 프로젝트 편집하기**: 생성과 편집은 MCP로만 한다. 갤러리는 보기·고르기·내보내기만.
- **LoRA 학습 UI, 프로젝트별 LoRA 연결**: 다음 버전 후보.
- **엔진별 임포트 자동화(Unity 임포트 설정, .meta)**: 폴더로 내보내기까지만.
- **공개 배포(설치 안내, 모델 다운로드 관리, GPU 사양 대응)**: 본인 전용.
- **악보(ABC) 편집 UI, 이미지 부분 편집(인페인팅)**: MVP 흐름 밖.
- **ComfyUI 출력 폴더 정리**: ComfyUI `output/aiassetstudio/` 아래 원본이 쌓이는 것은 그대로 둔다.

## 페이즈 구성

각 페이즈는 **수직 슬라이스**다. 끝나면 실제로 돌아가는 무언가가 남는다.

### Phase 1: 백엔드 뼈대 + 투명 스프라이트 — HTTP로 요청하면 투명 PNG가 나온다

- **목표**: 백엔드를 띄우고 HTTP API로 프로젝트를 만든 뒤 스프라이트·아이콘 생성을 요청하면, 대기열을 거쳐 프로젝트 폴더에 원본·후처리본·미리보기 PNG가 생긴다. 후처리본의 배경 알파는 0이다.
- **포함 기능**: 프로젝트 프리셋(기본 항목), 이미지 에셋 생성(투명 배경 + 알파 정리), 작업 대기열, ComfyUI 사전 점검
- **예상 소요**: 약 14시간
- **작업지시서**: [`aiassetstudio-phase-1-backend-sprite.md`](./aiassetstudio-phase-1-backend-sprite.md)
- **Checkpoint 요약**: 스모크 스크립트로 요청 → 투명 PNG 2장, 테두리 알파 0, `uv run pytest` 통과

### Phase 2: Claude Code 연결 + 갤러리 — 다른 세션에서 뽑고, 갤러리에서 고르고, 내보낸다

- **목표**: 사용자 범위로 등록한 MCP 서버로 다른 게임 폴더의 Claude Code 세션에서 생성·미리보기·내보내기가 되고, 웹 갤러리에서 후보를 고를 수 있다. 백엔드와 ComfyUI가 꺼져 있으면 자동으로 뜬다.
- **포함 기능**: MCP 서버, 웹 갤러리, 내보내기, 백엔드·ComfyUI 자동 실행
- **예상 소요**: 약 14시간
- **작업지시서**: [`aiassetstudio-phase-2-mcp-gallery.md`](./aiassetstudio-phase-2-mcp-gallery.md)
- **Checkpoint 요약**: 실제 Claude Code 세션에서 생성 → 미리보기 → 갤러리 선택 → 내보내기 한 바퀴

### Phase 3: 게임 규격 + 참고 이미지 — 정한 규격대로 픽셀 스프라이트가 나온다

- **목표**: 픽셀아트 프로젝트의 후처리본이 논리 해상도·최대 색 수·이진 알파를 지키고, 참고 이미지 1장이 화풍에 반영된다. 참고 이미지 + 투명 배경 조합을 검증해 기본 경로를 정한다.
- **포함 기능**: 프로젝트 프리셋(픽셀 규격, 참고 이미지), 픽셀 정리 후처리, 아이콘 규격
- **예상 소요**: 약 10시간
- **작업지시서**: [`aiassetstudio-phase-3-pixel-reference.md`](./aiassetstudio-phase-3-pixel-reference.md)
- **Checkpoint 요약**: 32×32·12색 프로젝트에서 나온 후처리본이 규격 검사 통과, 참고 이미지 검증 기록 작성

### Phase 4: BGM — 반복 재생용 연주곡과 보컬 곡 옵션

- **목표**: 브리프로 연주곡 후보(ACE-Step)를 만들고, 무음을 자르고 마디 경계에 맞춰 반복용 OGG/WAV로 정리한다. 보컬 곡(YuE2)도 옵션으로 된다. 이미지↔음악 모델 전환 시 메모리를 비운다.
- **포함 기능**: BGM 생성, 오디오 후처리, 모델 전환 규칙, 갤러리 오디오 재생
- **예상 소요**: 약 12시간
- **작업지시서**: [`aiassetstudio-phase-4-bgm.md`](./aiassetstudio-phase-4-bgm.md)
- **Checkpoint 요약**: 90초 연주곡 → 반복 파일 길이가 마디 배수, 이음새 급변 없음, 보컬 비율 2% 미만

## 페이즈 간 의존성

```
Phase 1 (백엔드 + 이미지 한 장)
  └─→ Phase 2 (MCP + 갤러리)
        ├─→ Phase 3 (픽셀 규격 + 참고 이미지)
        └─→ Phase 4 (BGM)
```

**병렬 가능성**: Phase 3과 Phase 4는 Phase 2 완료 후 서로 독립이다. 기본 순서는 3 → 4다(검증이 더 많이 된 이미지 쪽을 먼저 굳힌다).

## 페이즈 간 전환 규칙

각 페이즈는 다음 조건을 만족해야 완료로 본다.

1. 작업지시서의 모든 체크박스 완료
2. Checkpoint 블록의 모든 검증 통과
3. 사용자가 명시적으로 "Phase N 완료 확인, 다음 진행" 승인

Checkpoint가 실패하면 Claude Code가 실패 원인을 보고하고, 사용자와 함께 원인을 파악해 수정한 뒤 재검증한다. 재검증 통과 후 사용자 승인을 받고 다음 페이즈로 간다.

**커밋 규칙**: 커밋은 체크포인트를 통과하고 사용자가 승인했을 때 한다. 원격 저장소 푸시는 사용자가 요청할 때만 한다.

## 운영 주의 사항

- **ComfyUI는 다른 세션과 공유된다.** 다른 프로젝트의 별도 Claude Code 세션이 같은 ComfyUI로 LoRA 학습·YuE2·Whisper 작업을 돌리면 이 앱의 작업이 느려지거나 멈춘다. 앱은 다른 프로세스를 강제로 끄지 않는다. `studio_status`에 VRAM·RAM 여유를 보여주는 것으로 대응한다.
- **RAM 32GB가 빠듯하다.** 텍스트 인코더를 다시 불러오다 이미지 한 장에 190초가 걸린 사례가 있다. 한 작업의 후보들은 같은 프롬프트로 연속 생성해서 ComfyUI의 텍스트 인코딩 캐시를 활용한다.
- **라이선스**: Qwen-Image-2.1과 Viggle Turbo LoRA는 비상업(연구·평가) 라이선스, YuE2는 개인 창작자 결과물 판매 허용, ACE-Step 1.5는 MIT다. 개인·무료 게임 용도로 사용자가 수용했다. 에셋 기록(meta)에 사용한 모델 이름을 남긴다.

## 최종 완료 체크리스트 (전 페이즈 종료 후)

- [x] 모든 페이즈 Checkpoint 통과 (사람 귀가 필요한 Phase 4 청취 확인 2개는 남음)
- [x] 전체 테스트: `uv run pytest` (155 passed)
- [x] GPU 테스트 (ComfyUI 실행 중): `uv run pytest -m gpu` (3 passed, 136초)
- [x] 린트: `uv run ruff check .` 와 `uv run ruff format --check .`
- [x] 갤러리 빌드: `npm --prefix web run build`
- [x] **LAST LIGHT 실전 테스트** (다른 Claude Code 세션에서 MCP로): — MCP 클라이언트로 대신 실행(2026-09-25, 사용자 `data/`, 8765 백엔드)
  - [x] `lastlight` 프로젝트 생성: 픽셀아트, 32×32, 12색, 화풍 문구는 `<게임 프로젝트 경로>\ArtSource\LastLight\keeper-turnaround-prompt.txt` 참고, 참고 이미지는 사용자가 고른 기존 LAST LIGHT 아트 1장 (참고 이미지: `keeper/000.png`, 읽기만)
  - [x] 적 스프라이트 4장, 아이템 아이콘 4장, 전투 BGM 2곡 생성 (전투 BGM 브리프는 `<게임 프로젝트 경로>\Docs\NEXT-MILESTONE.md`의 공통 음악 브리프)
  - [x] 갤러리에서 고르고 `data/exports/lastlight-trial/`로 내보내기. 게임 프로젝트 폴더에는 직접 쓰지 않는다. (후보 전부 내보냄. 이미지는 미리보기를 보고 고름: 그림자 1, 랜턴 2, 기름 1 고르기, 그림자 4는 참고 이미지와 너무 닮아 버리기. BGM은 청취 평가를 위해 후보로 둠)
  - [ ] 사용자가 결과를 보고 "게임에 넣을 만하다 / 아니다"를 판단 — **사용자 판단 대기**
- [x] Out of Scope 항목을 구현하지 않았는지 확인
- [x] README에 설치·실행·MCP 등록·사용 예시 정리

## 최종 점검 기록 (2026-09-25)

- 사용자 지시("모든 페이즈 완료해서 푸시까지, 페이즈 완료 시 종단검증 필수")에 따라 Phase 3·4를 이어서 끝냈다. 페이즈마다 MCP 클라이언트로 Claude Code와 같은 도구 흐름을 도는 종단검증(`scripts/smoke_mcp.py --pixel`, `--bgm --vocal`)을 통과한 뒤 커밋했다: Phase 3 `da9a06c`, Phase 4 `7bbed0a`.
- LAST LIGHT 실전 테스트(사용자 `data/`의 `lastlight` 프로젝트, `data/exports/lastlight-trial/`):
  - 적 그림자 스프라이트 4장(32×32, 10~12색): 1~3은 두건 쓴 그림자에 빛나는 눈으로, keeper와 같은 화풍이다. 4는 keeper를 거의 그대로 닮았다(참고 이미지가 자세·모양을 끌어오는 알려진 경향).
  - 아이템 아이콘 4장(랜턴 2, 램프 기름 병 2, 32×32, 9~12색).
  - 전투 BGM 2곡(100 BPM 요청 → 100.003·100.01 BPM 검출, 35·36마디 루프, 이음새 비율 0.024·0.005, 보컬 0.1%·0.0%).
- 사람 확인이 남은 것: LAST LIGHT 결과가 게임에 넣을 만한지, BGM 이음새와 음악적 자연스러움(청취), Phase 4 마을 곡 중 보컬 2.8%로 잰 곡(플루트로 보임).

## 참고 자료

- 컨셉: [`concept.md`](./concept.md)
- PRD: [`prd.md`](./prd.md)
- 우선순위: [`priority.md`](./priority.md)
- UX 플로우 (MCP 도구 목록 포함): [`ux-flow.md`](./ux-flow.md)
- 실측 스크립트: `spikes/`
- Claude 메모리(이 프로젝트): `<Claude 프로젝트 메모리>aiassetstudio-feasibility.md`
- ComfyUI·ai-toolkit 설치 기록: `<다른 프로젝트 메모리>` (`comfyui-local-install.md`, `ai-toolkit-qwen21-lora.md`)

---
_Claude Code 사용 시: 이 로드맵을 먼저 읽고 전체 맥락을 파악한다. 그다음 Phase 1 작업지시서로 이동해 구현을 시작한다. 페이즈 전환은 반드시 사용자의 명시적 승인 후에 한다._
