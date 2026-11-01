# Studio Phase 3: 움직이는 그림책 — 작업지시서

_Claude Code가 위에서부터 차례로 하되, 체크포인트에서 사용자 확인을 받는다._

_작성일: 2026-11-01_
_속한 로드맵: [`studio-roadmap.md`](./studio-roadmap.md)_
_예상 소요: 약 22시간_

## 페이즈 목표

영상 팩을 설치하면 채택된 쪽 그림으로 클립을 만든다. 쪽마다 전체 클립, 앞부분만, 원본 그림 확대 중 하나를 골라 낭독·자막과 합쳐 MP4로 내보낸다. 시험에서 Wan은 인물을 이탈시키거나 작은 외형 특징을 지웠으므로, 사람이 승인한 원본 그림을 언제든 대체재로 쓸 수 있어야 한다. ComfyUI와 이미지 모델도 팩으로 설치해 새 PC에서도 시작할 수 있게 한다.

## 전제 조건

- [ ] Phase 2 체크포인트 통과
- [ ] 사용자가 시험 합본 영상을 재생해 왕복 재생을 판단했다(T3.A.1)

## 포함 기능

1. ComfyUI 엔진 팩, 이미지 팩, 영상 팩
2. `clip` 작업과 쪽별 움직임 지시
3. 갤러리 클립 검수
4. 쪽별 표현 방식 선택
5. 낭독·자막 영상 합치기

## 이 페이즈에서 하지 않는 것

- LTX-2.5(게이트 모델, 사용자 토큰 필요), 모델이 생성하는 음성 → Next
- 배경음악, 전환 효과, 타임라인 편집
- ComfyUI 자동 업데이트. 팩은 고정 버전이다

## 작업 체크리스트

### 작업 그룹 A: 재생 방식 결정

- [ ] **T3.A.1** — 왕복 재생 판단 (수동)
  - 파일: 시험 기록 문서에 결과 추가
  - 내용: 사용자가 시험 합본에서 물이 나오는 쪽을 재생해 본다.
  - 결정 규칙
    1. 왕복이 자연스러우면 → `loop_mode` 기본값 `pingpong`.
    2. 역재생이 거슬리면 → 기본값 `hold`(클립을 한 번 재생하고 마지막 프레임을 천천히 확대).
  - 검증: 사용자 결정 기록

### 작업 그룹 B: 엔진과 모델 팩

- [ ] **T3.B.1** — `engine-comfyui` 팩
  - 파일: `packs/catalog/engine-comfyui.json`, `packs/manager.py`, `config.py`, `tests/test_pack_manager.py`
  - 내용:
    - `engine: comfy_engine`. T1.A.3에서 정한 고정 태그(기본 `v0.37.0`)를 `data/packs/engine-comfyui/ComfyUI`에 clone하고 uv venv를 만든다. 이미지와 영상 그래프를 그 버전에서 다시 검증한다. 허용 호스트에 `github.com/comfyanonymous/ComfyUI`를 추가한다.
    - `AIAS_COMFY_DIR`이 있거나 형제 폴더 ComfyUI가 있으면 **외부 모드**다. 팩을 설치하라고 하지 않고 기존 ComfyUI를 쓴다. 외부 ComfyUI를 업데이트하거나 수정하지 않는다.
    - 라이선스 원문을 목록에 넣고 동의를 받는다.
    - `Settings`에서 설치된 팩을 `comfy_dir`로 찾는 `resolve_comfy()`를 추가한다.
  - 검증: `uv run pytest tests/test_pack_manager.py`, 임시 데이터 폴더에서 수동 설치

- [ ] **T3.B.2** — `image-qwen21`, `video-wan22` 팩
  - 파일: `packs/catalog/image-qwen21.json`, `packs/catalog/video-wan22.json`, `comfy/preflight.py`, `tests/test_preflight.py`
  - 내용:
    - `engine: comfy_models`. 파일은 현재 ComfyUI의 `models/<folder>/`에 넣고 `pack_installs.files`에 기록한다. 기존 파일이 있고 sha256이 같으면 내려받지 않고, 삭제 때도 지우지 않는다(`adopted` 표시).
    - `image-qwen21`: `class: research_only`. 요약에 비상업은 연구·평가 목적이라는 정의를 적는다. 공식 Turbo(sha256은 `notes/studio-official-turbo.md`), 텍스트 인코더, VAE를 넣는다. Viggle LoRA와 커스텀 노드는 넣지 않는다.
    - `video-wan22`: `Comfy-Org/Wan-2.2`의 `split_files` 6개, 37.8GB, Apache 2.0.
      - `wan2.2_i2v_high_noise_14B_fp8_scaled.safetensors`, `wan2.2_i2v_low_noise_14B_fp8_scaled.safetensors`
      - `wan2.2_i2v_lightx2v_4steps_lora_v1_high_noise.safetensors`, `..._low_noise.safetensors`
      - `umt5_xxl_fp8_e4m3fn_scaled.safetensors`, `wan_2.1_vae.safetensors`
    - `preflight.REQUIRED`에 `wan` 계열 추가: `UNETLoader`, `LoraLoaderModelOnly`, `ModelSamplingSD3`, `CLIPLoader`, `CLIPTextEncode`, `VAELoader`, `LoadImage`, `WanImageToVideo`, `KSamplerAdvanced`, `VAEDecode`, `CreateVideo`, `SaveVideo`.
    - `SaveVideo` 필수 입력은 `video, filename_prefix, format`이다(0.37.0 기준).
  - 검증: `uv run pytest tests/test_preflight.py`

- [ ] **T3.B.3** — 스프라이트와 아이콘을 공식 Turbo로 전환
  - 파일: `comfy/graphs.py`, `jobs/runners.py`, `comfy/preflight.py`, `tests/test_runners.py`, `tests/gpu/`
  - 이유: 새 PC의 `image-qwen21` 팩에는 Viggle이 없다. 인물 시트도 스프라이트 경로로 만든다.
  - 내용: `run_image_job`의 그래프를 `qwen_book_page`와 같은 구성으로 바꾼다. 투명 출력은 시험에서 확인했지만 픽셀아트 격자, 참조 이미지, 애니메이션 기준 그림의 회귀는 확인하지 않았다. 기존 GPU 테스트와 LAST LIGHT 프로젝트로 비교한 뒤 바꾼다. 결과가 달라지면 Viggle이 있는 외부 ComfyUI 경로를 유지할지 사용자와 정한다.
  - 검증: `uv run pytest -m gpu`

### 작업 그룹 C: 클립

- [ ] **T3.C.1** — Wan 그래프
  - 파일: `comfy/graphs.py`, `tests/test_graphs.py`
  - 내용: `spikes/studio/render_video.py`의 `graph()`를 `wan_i2v_lightning(prompt, image, seed, prefix, width, height, frames)`로 옮긴다. 상수 주석에 실측을 적는다(832×624, 81프레임, 클립당 약 190초, RAM 여유 최저 1.8GB). 부정 프롬프트는 CFG 1에서 무시된다고 주석에 남긴다.
  - 검증: `uv run pytest tests/test_graphs.py`

- [ ] **T3.C.2** — `clip` 실행기
  - 파일: `store/db.py`, `jobs/runners.py`, `jobs/queue.py`, `config.py`, `api/app.py`, `tests/test_runners.py`
  - 내용:
    - `pages`에 `motion_prompt, motion_still(bool), clip_asset_id, clip_status, clip_method, clip_head_s`.
    - 프롬프트는 `motion_prompt` + 제자리 지시 + 화풍 문구. 제자리 지시는 시험의 문구를 쓰고 `motion_still=false`면 뺀다.
    - `POST /api/books/{id}/clips`: 채택된 그림이 있는 쪽만 받는다. 쪽마다 작업 하나, 계열 `wan`.
    - `Settings.clip_timeout = 900`. 시작 전 ComfyUI `/system_stats`의 RAM 여유가 6GB 미만이면 경고를 `meta`에 남기고 진행한다. 시험에서는 시작 시 약 8~10GB 여유로 완주했고 최저 1.8GB까지 내려갔다.
    - `AssetKind`에 `clip`. 파일: mp4, 첫 프레임, 끝 프레임 PNG.
  - 검증: `uv run pytest tests/test_runners.py`

- [ ] **T3.C.3** — 클립 검수 화면과 MCP
  - 파일: `web/src/components/PageCard.tsx`, `mcp_bridge/server.py`, `tools.py`, `tests/test_mcp_tools.py`
  - 내용:
    - 쪽 카드에 영상 탭: `<video>`, 첫·끝 프레임, 표현 방식(`full`, `head`, `still`), 앞부분 초 입력, 채택, 재작업 메모.
    - `generate_clips`, `set_page_motion`. `get_book`은 끝 프레임을 미리보기로 준다. 에이전트가 이탈을 볼 수 있어야 하기 때문이다.
    - `INSTRUCTIONS`에 움직임 규칙을 적는다: 제자리 지시는 본문에, 작은 외형 특징이 줄거리에 중요한 쪽은 `still`을 기본으로 고려한다.
    - 영상 파일 응답의 `Range` 지원과 `MEDIA_TYPES`의 mp4를 확인한다.
  - 검증: `uv run pytest tests/test_api.py tests/test_mcp_tools.py`, `npm run build`

### 작업 그룹 D: 합치기

- [ ] **T3.D.1** — 영상 조립
  - 파일: `src/aiassetstudio/post/video.py`(신규), `jobs/runners.py`, `tests/test_post_video.py`
  - 내용:
    - `spikes/studio/assemble_video.py`를 옮긴다.
    - 프레임 수는 **누적 시간**으로 계산한다: `round(end * fps) - round(start * fps)`. 시험에서 쪽별 반올림은 0.3초 밀렸다.
    - `full`, `head`, `still`, `loop_mode`를 처리한다. `still`은 채택된 그림을 4:3으로 자르고 7% 천천히 확대한다.
    - 자막은 ASS(`Malgun Gothic`, 치환 전 본문). 쪽 낭독 시간과 맞춘다.
    - 페이드 인 0.8초, 아웃 1.2초, H.264 CRF 20, AAC 160k, `+faststart`.
    - ffmpeg 9에는 `-vsync`가 없으므로 `-fps_mode`를 쓴다.
    - `export_book(format="mp4")`, 계열 `none`. 낭독이나 표현 방식이 비어 있는 쪽이 있으면 거절한다.
    - `worst_class`가 `research_only`나 `unknown`이면 마지막 화면과 응답에 사용 모델을 표시한다.
  - 검증: `uv run pytest tests/test_post_video.py`

---

### ✅ Checkpoint: Phase 3 완료 확인

**구현 확인:**
- [ ] 외부 ComfyUI가 있으면 팩 설치를 요구하지 않고 수정하지도 않는다.
- [ ] `adopted` 파일은 팩 삭제 후에도 남는다.
- [ ] 영상 길이가 낭독 길이와 프레임 단위로 일치하고 쪽 경계에서 자막이 어긋나지 않는다.
- [ ] 기존 공정과 팩이 그대로 동작한다.

**실행 확인:**
- [ ] `uv run pytest`, `uv run ruff check .`, `npm run lint`, `npm run build`
- [ ] GPU 종단검증 `uv run pytest -m gpu tests/gpu/test_motion_book.py`: 2쪽

**수동 확인:**
- [ ] 임시 데이터 폴더에서 ComfyUI, 이미지, 영상 팩을 순서대로 설치해 1쪽짜리 영상을 만든다.
- [ ] 사용자가 12쪽 영상을 재생해 쪽별 방식을 고르고 내보낸다.

**이 체크포인트를 통과하면 사용자에게 확인 요청 후 Phase 4로 진행.**
실패하면 실패 항목을 보고하고, 원인을 함께 파악해 수정한 뒤 다시 검증한다.
