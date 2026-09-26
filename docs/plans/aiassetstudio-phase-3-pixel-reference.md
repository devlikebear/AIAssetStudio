# Phase 3: 게임 규격 + 참고 이미지 — 작업지시서

_이 페이즈의 목표를 달성하기 위한 구체적 작업 목록. Claude Code가 위에서부터 순서대로 실행하되, 체크포인트에서 사용자 확인을 받는다._

_작성일: 2026-09-24_
_속한 로드맵: [`aiassetstudio-roadmap.md`](./aiassetstudio-roadmap.md)_
_예상 소요: 약 10시간_

## 페이즈 목표

픽셀아트 프로젝트(예: 스프라이트 32×32, 아이콘 16×16, 12색)에서 나온 후처리본이 논리 해상도, 최대 색 수, 이진 알파(0/255)를 지킨다. 프로젝트에 참고 이미지 1장을 지정하면 새 에셋의 화풍에 반영된다. 아직 확인하지 않은 "참고 이미지 + 투명 배경" 조합을 먼저 검증하고, 그 결과로 기본 경로를 정한다. 이 페이즈가 끝나면 게임에 바로 넣을 수 있는 규격의 픽셀 에셋이 나온다.

## 전제 조건

- [x] Phase 2 완료 및 사용자 승인 (2026-09-25)
- [x] 검증용 투명 참고 이미지 1장. Phase 1·2에서 만든 투명 스프라이트 중 하나를 쓰거나, 사용자가 고른 기존 게임 아트를 쓴다. 기존 게임 아트는 읽기만 하고 복사본으로 작업한다.

## 포함 기능

1. 프로젝트 규격 설정 — 픽셀아트 여부, 스프라이트 논리 해상도, 아이콘 크기, 최대 색 수, 고정 팔레트(선택), 참고 이미지
2. 픽셀 정리 후처리 — 격자 정리, 팔레트 제한, 이진 알파, 정수배 확대 미리보기
3. 참고 이미지 반영 — 업로드, 그래프, 투명 배경 검증과 대체 경로

## 이 페이즈에서 하지 않는 것

- 4방향 시트, 애니메이션 프레임 → Out of Scope (MVP 이후 첫 확장 후보)
- 참고 이미지 2장 이상 → Out of Scope (16GB에서 VRAM 미검증)
- BGM → Phase 4

## 작업 체크리스트

### 작업 그룹 A: 참고 이미지 + 투명 배경 검증 (먼저 한다)

이 조합은 따로따로만 확인했다. 투명 배경은 참고 이미지 없는 생성에서, 참고 이미지는 불투명 이미지 편집에서만 확인했다. `TextEncodeQwenImage21` 노드는 참고 이미지의 알파를 흰 배경에 합쳐서 비전 인코더에 넘기고, VAE를 연결하면 4채널 그대로 잠재 공간에도 넣는다. 결과가 투명하게 나오는지는 직접 뽑아 봐야 안다. 이후 작업이 이 결과에 따라 달라지므로 가장 먼저 한다.

- [x] **T3.A.1** — 참고 이미지 업로드
  - 파일: `src/aiassetstudio/comfy/client.py`, `tests/test_comfy_client.py`
  - 내용: `async upload_image(path: Path, name: str, subfolder: str = "aiassetstudio") -> str` — `POST /upload/image` multipart(`image`, `subfolder`, `type=input`, `overwrite=true`). 돌려받은 이름을 `"{subfolder}/{name}"` 형태로 반환한다(LoadImage 입력값).
  - 검증: `uv run pytest tests/test_comfy_client.py -k upload`

- [x] **T3.A.2** — 참고 이미지 그래프
  - 파일: `src/aiassetstudio/comfy/graphs.py`, `tests/test_graphs.py`
  - 내용:
    - `def qwen_ref_turbo(prompt, seed, prefix, ref_name: str, mode: Literal["latent", "vision"], width=1024, height=1024, cache_cpu: bool = False) -> dict`
    - 투명도를 살려서 참고 이미지를 넣는 연결: `LoadImage(image=ref_name)` → `JoinImageWithAlpha(image=[load, 0], alpha=[load, 1])` → `TextEncodeQwenImage21`의 입력 키 `"images.image_1"`.
      - LoadImage는 RGB 이미지와 `1 - 알파` 마스크를 따로 내보낸다. JoinImageWithAlpha가 마스크를 다시 뒤집어 4채널로 합친다(둘 다 ComfyUI 코드로 확인).
      - 입력 키 `"images.image_1"`은 저장된 UI 워크플로 `qwen_image_2_1_edit_int8.json`의 입력 이름에서 확인했다. 첫 제출에서 `node_errors`가 나오면 `GET /object_info/TextEncodeQwenImage21`로 키 형식을 다시 확인한다.
    - `mode="latent"`: 인코더에 `vae`를 연결한다(비전 인코더 + 참고 잠재). `mode="vision"`: `vae`를 연결하지 않는다(비전 인코더만 참고).
    - 잠재 크기는 인코더의 `latent` 출력이 아니라 `EmptyLatentImage(width, height)`를 쓴다. 편집이 아니라 화풍 참고라서 출력 크기를 참고 이미지 비율에 묶을 이유가 없다.
    - `cache_cpu=True`면 `ViggleTurboLora`와 `BasicGuider` 사이에 `QwenImage21Cache(device="cpu")`를 넣는다. 참고 이미지 1장 편집 때 피크 VRAM이 약 15GB였다.
  - 검증: `uv run pytest tests/test_graphs.py -k ref`

- [x] **T3.A.3** — 검증 실행과 기록 (GPU, 수동) — 기본 경로 합의: `latent` + 편집 문구, 스프라이트에만 적용 (2026-09-25, [결과](./notes/ref-rgba-validation.md))
  - 파일: `scripts/validate_ref_rgba.py`, `docs/plans/notes/ref-rgba-validation.md`
  - 내용:
    - 투명 참고 이미지 1장으로 `mode="latent"` 2장, `mode="vision"` 2장을 만든다. 프롬프트는 투명 문구 + `"Use picture 1 only as a style reference for palette, outline, shading and proportions. Draw a new subject: a small slime monster."`
    - 장마다 기록: 알파 통계(`alpha_stats`), 생성 시간, 생성 전후 `nvidia-smi --query-gpu=memory.used --format=csv`로 본 VRAM, 결과 파일 경로
    - 사용자에게 결과를 보여주고 함께 판단한다: 투명 배경이 유지되는가, 화풍이 참고 이미지를 따르는가, 참고 이미지의 구도를 그대로 베끼지 않는가
    - 판단 결과와 수치를 `ref-rgba-validation.md`에 적는다.
  - 결정 규칙:
    1. `latent`가 투명 유지 + 화풍 반영 → 기본값 `latent`
    2. `latent`는 투명이 깨지고 `vision`은 유지 → 기본값 `vision`
    3. 둘 다 투명이 깨짐 → 참고 이미지를 쓸 때만 **단색 배경 키잉**으로 바꾼다. 투명 문구 대신 `"on a plain solid #00FF00 background"`로 생성하고, 후처리에서 초록 배경을 빼서 알파를 만든다. 픽셀아트처럼 경계가 딱딱한 그림에서는 이 방식이 잘 맞는다. 이 경우 T3.C.1(`post/image.py`)에 `chroma_key(img, color=(0,255,0), tolerance=...)`를 추가하고, T3.C.3 실행기에서 참고 이미지를 쓸 때 이 함수를 거치게 한다.
    4. VRAM이 16GB를 넘어 공유 메모리로 넘치면 `cache_cpu=True`를 기본으로 한다.
  - 검증: 기록 파일 작성, 사용자와 기본 경로 합의

### 작업 그룹 B: 프로젝트 규격 설정

- [x] **T3.B.1** — 규격 필드를 API·MCP에 노출
  - 파일: `src/aiassetstudio/api/schemas.py`, `src/aiassetstudio/api/app.py`, `src/aiassetstudio/mcp_bridge/tools.py`, `src/aiassetstudio/mcp_bridge/server.py`, `web/src/components/ProjectInfo.tsx`, `tests/test_api.py`, `tests/test_mcp_tools.py`
  - 내용:
    - 필드: `pixel_art: bool`, `logical_width`·`logical_height`(스프라이트, 8~256), `icon_size`(정사각형, 8~256, 없으면 `logical_width`. **사용자 결정 (c), 2026-09-25: 픽셀아트가 아닌 프로젝트에도 적용한다.** 값이 있으면 아이콘 후처리본을 그 크기의 정사각형으로 줄인다), `max_colors`(2~64), `palette`(선택, `"#rrggbb"` 목록, 2~64개), `reference_image`(선택, 절대 경로)
    - `pixel_art=True`면 `logical_width`, `logical_height`, `max_colors`가 필수다.
    - `reference_image`를 받으면 PNG/JPEG인지, 긴 변 4096px 이하인지 확인하고 `data/projects/<slug>/reference/ref.png`로 복사한다(원본 경로는 건드리지 않는다). 빈 문자열이면 참고 이미지를 해제한다.
    - MCP `create_project`·`update_project`에 같은 인자를 추가한다. 도구 설명에 "reference image must be an absolute path; it is copied into the studio" 문구를 넣는다.
    - 갤러리 프로젝트 정보에 규격과 참고 이미지 썸네일을 보여준다.
  - 검증: `uv run pytest tests/test_api.py tests/test_mcp_tools.py` — 필수 필드 누락 422, 팔레트 형식 오류 422, 참고 이미지 복사·해제

### 작업 그룹 C: 픽셀 정리 후처리

- [x] **T3.C.1** — `pixelate` (색 고르는 순서를 바꿈, 아래 구현 메모)
  - 파일: `src/aiassetstudio/post/image.py`, `tests/test_post_image.py`
  - 내용:
    - `def pixelate(img: Image.Image, width: int, height: int, max_colors: int, palette: list[tuple[int,int,int]] | None = None) -> Image.Image`
    - 순서:
      1. `clean_alpha` → `trim_to_content(pad=0)`
      2. 가로세로 비율을 유지한 채 `width×height` 안에 들어가는 셀 격자를 정한다(가장자리 1칸 여백).
      3. 원본을 `max_colors * 2`색으로 미리 줄인다(`Image.quantize(method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)`).
      4. 셀마다 불투명 픽셀이 절반 이상이면 불투명으로 두고, 그 셀의 **최빈 색**을 쓴다. 절반 미만이면 투명.
      5. 최종 색 제한: `palette`가 있으면 가장 가까운 팔레트 색으로 바꾸고, 없으면 `max_colors`색으로 줄인다(디더링 없음).
      6. 알파는 0 또는 255만 남긴다.
    - 셀마다 한 점만 뽑는 최근접 축소를 쓰지 않는 이유: Qwen이 그린 픽셀아트는 겉보기 픽셀 크기가 균일하지 않아서, 한 점만 뽑으면 경계가 뭉개지거나 점이 튄다(2026-09 관찰). LAST LIGHT의 아트 처리 방식(최근접 축소 → 가장 가까운 팔레트 색 → 이진 알파)을 출발점으로 삼되, 표본 추출만 최빈 색으로 바꾼다.
    - `def upscale_nearest(img, max_side: int = 256) -> Image.Image` — 정수배 최근접 확대 미리보기
  - 검증: `uv run pytest tests/test_post_image.py -k pixelate`
    - 합성 왕복 테스트: 16×16, 6색 스프라이트를 최근접 40배 확대 → 가장자리 흐림(가우시안 반경 3), 색 흔들림(±6), 배경 잔여 알파(2~6)를 넣는다 → `pixelate(16, 16, 6)` → 원본과 95% 이상 같은 픽셀, 색 6개 이하, 알파는 0과 255만
    - 고정 팔레트: 결과 색이 모두 팔레트 안에 있다
    - 가로로 긴 입력이 비율을 지키며 들어간다

- [x] **T3.C.2** — (조건부) 격자 크기 추정 — Phase 3에서는 하지 않았고(T3.D.2 결과가 뭉개지지 않았다), 2026-09-25 후속 작업으로 했다 (아래 "후속: T3.C.2")
  - 파일: `src/aiassetstudio/post/image.py`
  - 내용: T3.D.2의 GPU 결과가 뭉개질 때만 한다. `estimate_cell_size(img) -> float | None` — 후보 크기 k(4~64)마다 k배 축소 후 다시 확대한 이미지와 원본의 차이를 재서 가장 작은 k를 고른다. 찾으면 3단계 전에 원본을 k로 나눈 크기로 먼저 줄인다.
  - 검증: 합성 테스트(알려진 k=24 확대 이미지에서 24±1 추정)

- [x] **T3.C.3** — 실행기에 규격 적용
  - 파일: `src/aiassetstudio/jobs/runners.py`, `src/aiassetstudio/post/image.py`, `tests/test_runners.py`
  - 내용:
    - `project.pixel_art`면 sprite는 `pixelate(logical_width, logical_height, ...)`, icon은 `pixelate(icon_size, icon_size, ...)`로 `processed.png`를 만든다. 미리보기는 `upscale_nearest`.
    - 픽셀아트 프로젝트의 프롬프트에 `"pixel art, crisp hard-edged pixels, limited palette, no anti-aliasing"`을 더한다(`prompts.py`).
    - 참고 이미지가 있으면 작업 시작 때 한 번 업로드하고, T3.A.3에서 정한 경로(`latent`/`vision`/단색 키잉)로 생성한다.
    - `meta`에 `pixel: {width, height, colors_used, palette}`, `reference: {mode, file}`를 남긴다.
  - 검증: `uv run pytest tests/test_runners.py` — 픽셀 프로젝트에서 처리본 크기·색 수·알파, 참고 이미지가 있으면 업로드 1회

### 작업 그룹 D: 갤러리와 실측

- [x] **T3.D.1** — 갤러리 픽셀 표시
  - 파일: `web/src/components/CandidateCard.tsx`, `web/src/components/DetailModal.tsx`
  - 내용: 픽셀 프로젝트는 논리 해상도 원본을 `image-rendering: pixelated`로 정수배 확대해 보여준다. 상세에 "논리 크기 32×32, 사용 색 11/12"처럼 규격 정보를 표시한다.
  - 검증: `npm --prefix web run build`

- [x] **T3.D.2** — 실제 GPU 테스트 (참고 이미지 생성까지 더함, 58초)
  - 파일: `tests/gpu/test_pixel_e2e.py`
  - 내용: `@pytest.mark.gpu`. 픽셀 프로젝트(32×32, 12색)에 스프라이트 2장, 아이콘(16×16) 1장을 요청한다. 처리본이 규격 크기 이내이고 색 12개 이하, 알파가 0과 255뿐인지 확인한다.
  - 검증: `uv run pytest -m gpu -k pixel`

---

## ✅ Phase 3 Checkpoint

**구현 확인:**
- [x] 모든 작업 체크박스 완료 (T3.C.2는 조건을 채우지 않아 하지 않음. 2026-09-25 후속으로 함, 구현 메모 끝)
- [x] 참고 이미지 검증 기록(`docs/plans/notes/ref-rgba-validation.md`)이 있고, 기본 경로를 사용자와 합의했다
- [x] 픽셀 프로젝트의 처리본이 규격을 지킨다
- [x] 참고 이미지를 지정한 프로젝트에서도 투명 PNG가 나온다

**자동 검증:**
- [x] 전체 테스트: `uv run pytest` (128 passed)
- [x] 린트: `uv run ruff check .` 와 `uv run ruff format --check .`
- [x] 갤러리 빌드: `npm --prefix web run build` (oxlint도 통과)
- [x] GPU 테스트: `uv run pytest -m gpu -k pixel` (58초). 공용 fixture로 옮긴 `-k image`도 다시 통과(16초)
- [x] 종단검증: `scripts/smoke_mcp.py --pixel` (MCP stdio → 백엔드 → ComfyUI → 내보내기, 아래 구현 메모)

**수동 확인:**
- [x] Claude Code 세션에서 "demo 프로젝트를 32×32, 12색 픽셀아트로 바꾸고 참고 이미지는 `<경로>`로 해줘" → `update_project` (MCP 클라이언트로 대신 확인, 임시 데이터)
- [x] "슬라임 몬스터 스프라이트 4장" → 갤러리에서 확대해 보면 픽셀이 또렷하고, 참고 이미지와 화풍이 비슷하다 (갤러리 정수배 표시는 브라우저로, 그림은 직접 보고 확인)
- [x] 고른 스프라이트를 내보내면 32×32 PNG가 나온다

**완료 처리:**
1. 위 항목이 모두 통과하면 Claude Code는 사용자에게 완료한 작업, 자동 검증 결과, 참고 이미지 검증 결론을 보고한다.
2. 사용자가 "Phase 3 완료, 다음 진행"이라고 승인하면 커밋하고 Phase 4로 간다.
3. 체크포인트가 실패하면 실패 항목을 보고하고, 원인을 분석해 수정한 뒤 다시 검증한다.


## 구현 메모 (2026-09-25, 사용자 확인 전)

계획과 다르게 하거나 더한 것:
- **참고 이미지 기본 경로** (T3.A.3 사용자 결정): `latent` + 편집 문구("Replace the subject of picture 1 with X. Keep the same art style, palette, outline and shading as picture 1. ..."), 스프라이트에만 쓴다. 계획서의 "화풍 참고" 문구는 참고 이미지의 대상을 베껴서 쓰지 않는다. 아이콘은 참고 이미지가 있어도 일반 문구로 만든다.
- **참고 이미지 사본은 내용 해시 이름**(`data/projects/<slug>/reference/<sha256 앞 12자>.png`)으로 둔다(계획은 `ref.png`). 참고 이미지를 바꾸거나 해제해도 예전 사본은 지우지 않는다. 에셋 `meta.reference.file`이 만들 때 쓴 그림을 계속 가리키게 하려는 것이다. DB의 `reference_image`에는 이 사본의 상대 경로가 들어가고, 원본 경로는 기록하지 않는다.
- **작은 참고 이미지는 최근접 정수배로 키워서** 저장한다. 긴 변 256px 이하면 1024에 가깝게 키운다(32×32는 32배). `TextEncodeQwenImage21`이 참고 이미지를 약 1024×1024로 lanczos 리샘플해서, 작은 픽셀아트가 흐려지기 때문이다. LAST LIGHT 검증도 이 조건으로 했다.
- `GET /api/projects/{slug}/reference`를 더했다(갤러리 썸네일용).
- **PATCH 검사**: `pixel_art`의 필수 필드는 보낸 필드만이 아니라 합친 결과로 검사한다(`{pixel_art: true}`만 보내면 422). null은 `name`·`style`·`pixel_art`는 그대로 두고 나머지는 지운다. MCP `update_project`는 생략하면 그대로 두고, 크기·색 수는 0, 팔레트는 `[]`, 참고 이미지·내보내기 폴더는 `""`로 지운다(`False == 0`인 `pixel_art`는 따로 다룬다).
- **`pixelate`의 색 고르는 순서를 바꿨다.** 계획은 "`max_colors*2`색 미디언 컷 → 셀 최빈 색 → `max_colors`로 줄임"이다. 합성 테스트에서 두 가지가 깨졌다.
  1. 픽셀 수 기준 미디언 컷이 작지만 뚜렷한 색(노란 눈)을 몸통 색에 섞어 버렸다.
  2. 한 색이 비슷한 음영 여러 개로 나뉘면 셀 투표가 갈라져 다수 색이 셀을 잃었다(왕복 테스트 72%).

  그래서 최종 색을 그림 전체에서 먼저 정하고 셀은 그중에서 투표한다. 순서: 256색 미디언 컷 → (팔레트가 있으면 가장 가까운 팔레트 색으로) → "가장 가까운 두 색 중 드문 쪽을 흔한 쪽에 합치기"를 `max_colors`까지 반복 → 셀마다 불투명 픽셀이 절반 이상이면 그 셀 픽셀의 다수 색. 새 중간색이 생기지 않고, 멀리 떨어진 작은 색이 끝까지 남는다. 팔레트와 `max_colors`가 둘 다 있으면 팔레트 색만, `max_colors`개 이하로 쓴다. 1024 그림 하나에 약 0.1초.
- 스프라이트는 캔버스 아래쪽 여백 1칸 위에 발을 맞춘다(`anchor="bottom"`). LAST LIGHT 스프라이트가 모두 발을 같은 줄(y≈28)에 둔다. 아이콘은 가운데에 둔다.
- `alpha_stats`에 `border_band`를 더했다. 규격 크기로 줄인 처리본(픽셀아트, `icon_size`)은 테두리 1px로 잰다. 32px 띠로 재면 32×32 그림 전체가 테두리가 된다.
- 픽셀 미리보기는 `upscale_nearest`(≤256px, 32px면 8배)다. 일반 프로젝트 아이콘은 `icon_size`가 있으면 lanczos로 그 크기에 맞춘다(사용자 결정 (c)).
- 실행기: 참고 이미지는 작업마다 한 번 `aiassetstudio/ref_<slug>.png`로 올린다(같은 이름 덮어쓰기, LoadImage가 내용으로 바뀜을 안다). 인코딩 프롬프트와 후보 그래프에 같은 참고 노드를 넣어 캐시를 재사용한다. `meta.reference {mode, file}`, 작업 `timings.upload_reference`, `workflow: "qwen_ref_turbo"`를 남긴다. 사본 파일이 없으면 "update_project로 다시 지정하라"는 오류로 실패한다.
- 갤러리: 픽셀 여부는 프로젝트가 아니라 에셋 `meta.pixel`로 정한다. 나중에 프로젝트 규격을 바꿔도 예전 후보가 제 모습으로 보인다. 카드와 상세의 "맞춤"은 논리 크기 그림을 들어가는 가장 큰 정수배로 보여 준다(`useWholeZoom`). 크기는 요소가 붙을 때와 그 직후에 재고, 이후에는 ResizeObserver로 잰다. 가려진 탭에서는 ResizeObserver가 늦게 와서 1배로 남는 것을 확인하고 고쳤다. 상세에 "논리 크기 32×32 · 사용 색 9/12", 고정 팔레트, 참고 이미지 사용을 표시한다. 프로젝트 정보에는 규격, 일반 프로젝트의 아이콘 크기, 팔레트, 참고 이미지 썸네일을 넣었다.
- GPU 테스트는 `tests/gpu/conftest.py`의 `real_client`·`run_job`을 같이 쓰고, ComfyUI가 다른 프롬프트를 처리 중이면 건너뛴다.

실측 (2026-09-25, `uv run pytest -m gpu -k pixel`, 58초 통과):
- 32×32·12색·아이콘 16 프로젝트. 슬라임 스프라이트 2장(9색, 5색), 물약 아이콘 16×16(8색), 첫 스프라이트를 참고 이미지로 한 망령 스프라이트(9색). 모두 규격 크기, 알파 0/255, 여백 1칸이 투명했다.
- 작업당 인코딩은 참고 이미지가 없으면 4~5초, 있으면 8.1초다(한 번만). 후보당 생성은 6~11초로 참고 이미지와 상관없고, 픽셀 정리는 0.1~0.2초다.
- **T3.C.2는 하지 않았다.** 결과는 또렷하다(셀마다 한 색이라 구조상 흐려질 수 없다). 다만 모델이 아주 작게 그린 슬라임(1024 캔버스에서 약 64px)은 30칸으로 약 2.1배 키워지면서 눈 모양이 조금 일그러졌다. 계획의 추정 방법("되돌린 이미지와 차이가 가장 작은 k")은 항상 가장 작은 k를 고르므로 그대로는 쓸 수 없다. 개선한다면 색 경계 사이 거리의 최빈값으로 모델의 픽셀 크기를 추정한 뒤 정수배로만 키우는 방식이 후보다(LAST LIGHT 결과에서 31~32px를 찾았다).

종단검증 (2026-09-25, 사용자 지시 "모든 페이즈 완료해서 푸시까지, 페이즈 완료 시 종단검증 필수"):
- 수동 확인 3단계를 Claude Code 대신 MCP 클라이언트로 돌렸다: `scripts/smoke_mcp.py --pixel <참고 이미지>`. Claude Code처럼 MCP 서버를 stdio로 띄우고 도구를 부른다. 사용자 `data/`를 건드리지 않게 `AIAS_PORT=8766`, 임시 `AIAS_DATA_DIR`로 했다. 참고 이미지는 LAST LIGHT keeper(읽기만)다.
  - `create_project`(32×32, 12색, 아이콘 16, 참고 이미지) → 슬라임 스프라이트 4장 → 물약 아이콘 1장 → 스프라이트·아이콘 고르고 내보내기.
  - 확인한 것: 스프라이트 4장 모두 `reference.mode = latent`, 원본 테두리 알파 평균 약 3(투명), 7~11색. 아이콘에는 참고 이미지를 쓰지 않았다. 내보낸 파일은 32×32(9색)와 16×16(5색)이고 알파는 0/255뿐이다.
- **종단검증에서 찾아 고친 것: 아이콘 고리.** 물약 아이콘 두 번 모두 요청하지 않은 원형 고리를 달고 나왔다. 첫 번째는 반투명 호(알파 최대 140~171, 알파 128 이상이 4~7%), 두 번째는 불투명한 6px 원(바운딩 박스 1024×1022, 채움 0.08)이었다. 고리가 자르기 범위를 화면 전체로 넓혀서 16×16 아이콘의 물약이 작아지고 고리 조각이 남았다. 아이콘에만 두 가지 정리를 더했다.
  1. 떨어진 조각 중 알파 128 이상이 25% 미만인 조각을 지운다(`ICON_MIN_CORE_SHARE`). 가장 큰 대상은 항상 남긴다.
  2. 대상 중심을 둘러싸고 자기 바운딩 박스의 20% 미만만 채우는 떨어진 조각(고리·틀)을 지운다(`drop_surrounding_frames`). 반짝이 같은 작은 조각은 남는다.

  `pixelate`는 불투명 픽셀(알파 128 이상) 기준으로 자른다. 옅은 픽셀은 어차피 결과에 남지 않으므로 옅은 후광이 대상을 작게 만들지 않게 했다. 두 물약을 다시 처리하니 고리 없이 캔버스를 채웠고, 고친 코드로 종단검증을 다시 돌려 통과했다.
- 아이콘 문구도 비교했다. 현재 문구, "icon"을 뺀 문구 두 가지를 물건 4종 × 2장으로 일반·픽셀 문구 각각 돌렸다(40장). 고리는 한 장도 나오지 않았다. 고리는 시드에 따라 가끔 나오는 것으로 보고 문구는 그대로 두었다. 뺀 문구 하나는 옅은 조각이 더 많이 나왔다.
- 사용자 `data/`의 8765 백엔드(10:41에 띄움)와 열려 있는 Claude Code 세션의 MCP 서버는 아직 Phase 2 코드다. 백엔드는 모르는 필드를 조용히 버리므로, 다음에 쓰기 전에 다시 띄워야 한다(최종 점검 전에 한다).

후속: T3.C.2 모델 격자 찾기와 정수배 확대 (2026-09-25, 인수인계 "다음 개발 후보" 중 사용자가 고름):
- 문제: 모델이 작게 그린 대상을 30칸에 맞춰 늘리면 모델 픽셀 하나가 1칸이 되기도 2칸이 되기도 해서 눈과 외곽선 모양이 흐트러졌다(GPU 테스트의 작은 슬라임, 254px 대상을 30칸으로).
- 방식(`post/image.py`의 `find_pixel_grid`, `_native_pixels`):
  1. 이웃 픽셀 사이 색 경계(premultiplied RGB나 알파가 24 이상 차이, 흐린 경계는 가장 센 곳 하나)를 가로·세로로 센다.
  2. 칸 크기 4~128px마다 경계 위치를 그 주기의 각도로 보고 합친 길이(규칙성, 0~1)와 위상을 구한다.
  3. 참 크기의 1/2, 1/3에서도 규칙성이 똑같이 높고 배수에서는 낮다. 그래서 두 축을 합친 가장 센 크기에서 시작해, 규칙성의 60% 이상을 지키는 가장 큰 배수로 올라간다.
  4. 축마다 그 크기의 ±20% 안에서 다듬는다(모델의 칸은 정사각형이 아닐 때가 있다: 작은 슬라임 16.2×14px). 위상 후보는 경계가 가리키는 위상, 대상 양끝, 대상 폭을 칸 수로 고르게 나눈 것이다. 이 가운데 칸 안이 가장 한 색에 가까운 것을 쓴다.
  5. 칸마다 절반 이상 불투명하면 다수 색이다(기존 투표와 같다).
  6. 판정: 축마다 경계가 걸린 격자선 6개 이상(민무늬 사각형 거르기), 규칙성 0.5 이상, 칸 가로/세로 0.8~1.25, 섞인 칸(한 색도 70%를 넘지 못하는 칸) 12% 이하.
  7. 통과하고 캔버스(여백 1칸 제외)에 들어가면 가장 큰 정수배(1배 포함)로 키운다. 아니면 예전처럼 늘려 맞춘다. 늘려 맞춘 결과는 예전과 픽셀까지 같다(아래 42장으로 확인).
- 쓰지 않은 방법: 계획의 "되돌린 이미지와 차이가 가장 작은 k"는 항상 가장 작은 k를 고른다. 인수인계의 "경계 간격 최빈값"은 칸이 고르지 않은 그림에서 흔들렸다(대상 끝의 흐린 그림자 한 줄에도 칸 수가 틀어짐).
- 실측 42장(LAST LIGHT 8장, Phase 3 종단검증 10장, GPU 테스트 4장, 아이콘 고리 실험 16장, 참고 이미지 검증 4장):
  - 원래 크기 12장:
    - 참고 이미지로 만든 스프라이트 17장 중 11장. LAST LIGHT 4장은 모두 32px 칸, 18×25~26칸, 1배다. 1장은 2배다.
    - 참고 이미지 없이 만든 슬라임 2장 중 1장. 작은 슬라임이고 16×13칸, 1배다.
    - 참고 이미지가 있어도 칸 크기가 늘 32px는 아니었다(31~38px).
  - 늘려 맞춤 30장:
    - 아이콘 23장 모두. 격자가 없거나 고르지 않았다.
    - 참고 이미지 스프라이트 6장. 5장은 격자가 고르지 않았다. 망령 1장은 칸이 26×48이라 32×32에 들어가지 않았다.
    - 참고 없는 슬라임 1장. 격자가 고르지 않았다.
  - 판정 전 결과를 눈으로 보고, 나쁜 7장이 모두 걸러지는 기준을 골랐다. 걸러진 것 중 1장(참고 이미지 슬라임, 규칙성 0.49)은 되살린 결과도 괜찮았다. 잘못 거르면 예전 결과가 나올 뿐이라 거르는 쪽으로 잡았다.
- 한 장에 약 0.33초가 더 든다.
- 기록: `meta.pixel.fit` = `{fit: "native", scale, cell_px, native_size}` 또는 `{fit: "stretch", reason, (cell_px, native_size)}`. reason은 `no grid`, `uneven grid`, `larger than the canvas`, `empty`다. 판정 값은 `meta.postprocess.pixelate.grid`에 있다. 갤러리 상세 "규격"과 MCP `get_job`이 이를 보여 준다.
- 결과로 달라지는 것: 1배면 캔버스를 다 채우지 않는다(LAST LIGHT 스프라이트는 30줄에서 25~26줄로). 대신 참고 이미지(32×32를 32배 키운 것)와 픽셀 크기가 같다. keeper 원본은 32×32 캔버스에서 18×26이고, 새 그림자 적은 16~18×25~26이다. 예전 방식은 19~21×30으로 keeper보다 약 1.15배 컸다.

후속: 참고 이미지의 발 줄 (2026-09-25):
- 새 방식으로 뽑은 LAST LIGHT 그림자 적을 게임 아트(`ArtSource/LastLight`, 읽기만)와 비교했다. keeper, 그림자, 캠페인 적 모두 32×32 프레임에서 28번째 줄(애니메이션 중 29)에 선다. 스튜디오는 여백 1칸 위인 30번째 줄에 세워서 2px 낮았다.
- 사용자 결정으로, 참고 이미지가 있는 픽셀 프로젝트의 스프라이트는 참고 이미지의 대상이 선 줄에 세운다(`reference_ground`). 참고 이미지 사본에서 불투명(알파 128 이상) 대상 아래의 빈 줄 비율을 캔버스 줄 수로 바꾼다. 최소 1줄(여백), 최대 캔버스의 1/4이다.
- 원래 크기 경로와 늘려 맞추기 경로 모두 위 여백 1칸부터 그 줄까지 안에 맞춘다. 아이콘은 가운데에 두므로 영향이 없다.
- 확인: LAST LIGHT 참고 이미지의 바닥 줄은 3이다. 그림자 적 4장(작업 `00580bf6f205`)은 발이 30번째 줄에서 28번째 줄로 올라가고, 그림은 픽셀 하나까지 같다.

---

## 참고 자료

- 로드맵: [`aiassetstudio-roadmap.md`](./aiassetstudio-roadmap.md)
- PRD의 "검증 필요" 절: [`prd.md`](./prd.md)
- `TextEncodeQwenImage21` 코드: `<ComfyUI 경로>\comfy_extras\nodes_qwen.py` (참고 이미지 크기 조정, 알파 처리)
- `JoinImageWithAlpha`: `<ComfyUI 경로>\comfy_extras\nodes_compositing.py`, `LoadImage`: `<ComfyUI 경로>\nodes.py`
- 픽셀 정리 출발점: `<게임 프로젝트 경로>\Tools\build_game_art.py`의 `extract()` (읽기만)
- 편집 워크플로 원본: `<ComfyUI 경로>\user\default\workflows\qwen_image_2_1_edit_int8.json`

## 메모 / 주의

- 참고 이미지가 있으면 생성마다 참고 이미지 인코딩이 더해져 느려진다. 실측 시간을 `meta.timings`에 남겨 두고, 너무 느리면 사용자와 상의한다.
- 픽셀 정리는 "게임에 넣을 수 있는 규격"을 보장하는 것이지 그림 품질을 높이는 것이 아니다. 품질은 후보를 여러 장 뽑아 고르는 것으로 해결한다.
- 고정 팔레트가 있으면 색이 크게 바뀔 수 있다. 사용자가 원하면 팔레트 없이 `max_colors`만 쓰는 쪽을 기본으로 둔다.

---
_다음 페이즈: Phase 4 — BGM → [`aiassetstudio-phase-4-bgm.md`](./aiassetstudio-phase-4-bgm.md)_
