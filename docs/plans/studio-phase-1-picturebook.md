# Studio Phase 1: 책과 그림책 — 작업지시서

_Claude Code가 위에서부터 차례로 하되, 체크포인트에서 사용자 확인을 받는다._

_작성일: 2026-11-01_
_속한 로드맵: [`studio-roadmap.md`](./studio-roadmap.md)_
_예상 소요: 약 30시간_

## 페이즈 목표

에이전트가 MCP로 책 프로젝트를 만들고 쪽 대본, 인물·장소·소품 시트를 넣는다. 쪽별 전면 삽화를 생성하고, 사람은 갤러리에서 쪽마다 채택하거나 재작업 메모를 남긴다. 다 고르면 글자가 선택되는 PDF로 내보낸다. 이 페이즈는 이미 설치된 Qwen 모델만 쓴다. 기능 팩은 없다.

## 전제 조건

- [x] 시험 제작 완료([기록](./notes/studio-spike-2026-11-01.md))
- [x] 시험 스크립트 원본이 `<MyPCWorks>\storybook-lastwater\`에 있다(T1.A.1에서 옮긴다)
- [x] `aiassetstudio check`에서 `qwen` 계열이 준비됨

## 포함 기능

1. 책, 쪽, 시트, 용어 저장
2. 다중 참조 전면 삽화 작업
3. 쪽 단위 재생성과 후보 선택
4. 쪽별 근거 원문과 원작 변경 감지
5. 결과물 출처와 라이선스 기록
6. 갤러리 책 화면과 재작업 메모
7. PDF 내보내기

## 이 페이즈에서 하지 않는 것

- 기능 팩, 동의 화면, 음성, 영상 → Phase 2, 3
- 이미지 부분 재생성 → Next
- 쪽 대본 자동 각색 → 에이전트의 일이다. Studio는 받은 대본을 저장한다

## 작업 체크리스트

### 작업 그룹 A: 시험 코드와 장소 참조 결정

- [x] **T1.A.1** — 시험 스크립트 보관
  - 파일: `spikes/studio/render_pages.py`, `render_video.py`, `layout_book.py`, `assemble_video.py`, `gen_tts.py`
  - 내용: 스크립트를 복사하고 개인 경로를 `<...>` 표기나 인자로 바꾼다. `storyboard.json`과 작품 본문은 복사하지 않는다.
  - 검증: `git grep`으로 작품 고유명사, 줄거리 단서, `C:\Users\`가 `spikes/studio/`와 `docs/plans/`의 Studio 문서에 없음

- [x] **T1.A.2** — 장소 시트를 세 번째 참조로 넣는 시험 (GPU, 수동)
  - 파일: `spikes/studio/three_refs.py`, `docs/plans/notes/studio-three-refs.md`
  - 내용: 인물 2명 + 장소 그림 1장을 `images.image_1~3`에 넣어 같은 장면을 3회 만든다. 시간, 최저 VRAM·RAM, 장소 일치 여부를 기록한다.
  - 결정 규칙
    1. 멈춤 없고 장소가 맞으면 → 장소 시트를 참조 이미지로 쓴다(T1.C.1 `max_refs = 3`).
    2. 메모리가 넘치거나 인물이 망가지면 → 인물 참조 2장을 유지하고 장소 시트 설명을 프롬프트에 넣는다(`max_refs = 2`).
  - 검증: 사용자와 결과 합의

- [x] **T1.A.3** — 공식 Turbo로 Viggle 대체 시험 (GPU, 수동)
  - 파일: `spikes/studio/official_turbo.py`, `docs/plans/notes/studio-official-turbo.md`
  - 이유: 지금 그래프는 커스텀 노드 `viggle_turbo.py`와 라이선스 원문을 확인하지 못한 Viggle LoRA가 필요하다. 이 상태로는 Phase 3의 새 PC 설치가 불가능하다.
  - 내용: 공식 `Qwen/Qwen-Image-2.1-Turbo`의 int8 파일 `qwen_image_2.1_turbo_int8_convrot.safetensors`(6.76GB)를 8스텝, CFG 1, `er_sde`, `linear_quadratic`으로 시험한다. 같은 시드와 참조로 Viggle과 비교한다. 다운로드 전 사용자 확인을 받는다. 라이선스는 Qwen Research로 같다.
  - 결정 규칙
    1. ComfyUI 0.37.0에서 돌고 일관성이 같으면 → 책 그래프를 공식 Turbo로 만들고 Phase 3 `image-qwen21`에 넣는다.
    2. 더 높은 ComfyUI가 필요하면 → 격리 폴더에서 그 버전으로 시험하고, Phase 3 엔진 팩의 고정 버전을 그 버전으로 정한다. 기존 ComfyUI는 업데이트하지 않는다.
    3. 품질이나 일관성이 떨어지면 → 사용자와 정한다. Viggle을 쓰면 새 PC 설치는 포기하고 외부 ComfyUI 전용이 된다.
  - 검증: 사용자와 결과 합의

### 작업 그룹 B: 저장소

- [x] **T1.B.1** — 스키마 3
  - 파일: `src/aiassetstudio/store/db.py`, `store/models.py`, `tests/test_db.py`
  - 내용:
    - `SCHEMA_VERSION = 3`, `_UPGRADES[2]`와 `_SCHEMA`에 같은 표를 추가한다.
    - `books`: `id, project_id, title, source(JSON), width, height, status, created_at, updated_at`
    - `pages`: `id, book_id, number, text, image_prompt, cast(JSON), place, source_refs(JSON), image_asset_id, status, note, created_at, updated_at`. `(book_id, number)` 고유.
    - `sheets`: `id, book_id, kind(character|place|prop), name, description, asset_id, created_at`. `(book_id, kind, name)` 고유.
    - `terms`: `id, book_id, term, spoken`. 이 페이즈에서는 저장만 한다(Phase 2에서 사용).
    - `pages.status`: `draft`, `queued`, `candidate`, `approved`, `redo`.
    - `AssetKind`에 `page_image`, `book_export`, `JobKind`에 `page_image`, `book_export`를 더한다.
    - 기존 `_JSON_FIELDS`, `_encode`, `_decode`를 재사용한다.
  - 검증: `uv run pytest tests/test_db.py` (버전 2 DB가 3으로 올라가는 케이스 포함)

- [x] **T1.B.2** — 책 API
  - 파일: `src/aiassetstudio/api/app.py`, `api/schemas.py`, `tests/test_api.py`
  - 내용: `POST/GET /api/books`, `GET /api/books/{id}`(쪽, 시트, 진행 수 포함), `PUT /api/books/{id}/pages`(쪽 일괄 저장, 채택한 쪽의 `image_prompt`가 바뀌면 `draft`로 되돌림. `text`만 바뀌면 그림 채택은 유지하고, Phase 2부터 낭독만 다시 만들 대상으로 표시), `PUT /api/books/{id}/sheets`, `PUT /api/books/{id}/terms`, `PATCH /api/pages/{id}`(`status`, `note`, `image_asset_id`). 오류 문구는 영어 `HTTPException`.
  - 검증: `uv run pytest tests/test_api.py`

- [x] **T1.B.3** — 출처와 라이선스 기록
  - 파일: `src/aiassetstudio/provenance.py`(신규), `jobs/runners.py`, `tests/test_provenance.py`
  - 내용:
    - `MODEL_LICENSES: dict[str, ModelLicense]`. `ModelLicense(name, license, class_)`, `class_`는 `open | community | research_only | unknown`.
    - 값: Qwen 본체·인코더·VAE는 `research_only`, Viggle LoRA는 원문 미확인이므로 `unknown`, ACE-Step은 `open`, YuE2는 `community`.
    - 모든 실행기의 `meta`에 `models: [{file, license, class}]`를 넣는다.
    - `worst_class(assets)`를 제공한다(`research_only` > `unknown` > `community` > `open`).
  - 검증: `uv run pytest tests/test_provenance.py`

### 작업 그룹 C: 전면 삽화 작업

- [x] **T1.C.1** — 다중 참조 그래프
  - 파일: `src/aiassetstudio/comfy/graphs.py`, `tests/test_graphs.py`
  - 내용:
    - `Reference` 단일 인자를 유지하면서 `refs: Sequence[Reference]`를 받는 내부 함수로 바꾼다. 두 번째 이후는 `images.image_N`에 넣는다.
    - `qwen_text_encode`와 `qwen_t2i_turbo`가 같은 노드를 만들어야 캐시가 재사용된다(기존 주석의 조건).
    - 참조가 있으면 `cache_cpu=True`로 호출한다.
    - `MAX_PAGE_REFS`는 T1.A.2 결과로 정한다.
    - 기존 스프라이트 그래프 결과는 달라지면 안 된다.
  - 검증: `uv run pytest tests/test_graphs.py`

- [x] **T1.C.2** — 쪽 프롬프트 조립
  - 파일: `src/aiassetstudio/book_prompts.py`(신규), `tests/test_book_prompts.py`
  - 내용: `page_prompt(project_style, sheets, page) -> PagePrompt(text, ref_paths)`. 입력은 쪽의 `cast`, `place`와 시트다.
    - 참조가 있는 인물은 "첫 번째 참조는 ~" 문장, 나머지는 시트 설명을 넣는다.
    - 이름이 있는 인물이 2명 이하면 "Exactly N people" 또는 호출자가 준 조연 지시를 유지한다.
    - 장소 설명은 T1.A.2 결정에 따른다.
    - 프로젝트 화풍과 공통 금지 문구를 끝에 넣는다.
  - 검증: `uv run pytest tests/test_book_prompts.py`

- [x] **T1.C.3** — `page_image` 실행기
  - 파일: `src/aiassetstudio/jobs/runners.py`, `api/app.py`, `tests/test_runners.py`
  - 내용:
    - `run_image_job`의 인코딩 → `/free` → 생성 순서를 그대로 쓴다. 참조는 `lw_` 대신 `book_<id>_<sheet>.png`로 올린다.
    - 투명 후처리 없이 RGB PNG를 저장한다. 기본 크기는 `books.width/height`(기본 1184×880).
    - 작업 한 건은 한 쪽 한 장이다. 같은 쪽을 다시 만들면 새 에셋이 생기고, 이전 후보는 남는다.
    - `POST /api/books/{id}/generate`: `pages`(없으면 `draft`·`redo` 쪽 전체), `seed_offset`. 쪽마다 작업 하나를 넣고 `pages.status = queued`.
    - 완료되면 `status = candidate`, `image_asset_id`가 비어 있을 때만 채운다.
    - 계열은 `qwen`이라 기존 대기열 규칙을 탄다.
  - 검증: `uv run pytest tests/test_runners.py`

### 작업 그룹 D: 근거 원문과 MCP

- [x] **T1.D.1** — 원작 변경 감지
  - 파일: `api/app.py`, `tests/test_api.py`
  - 내용: `source_refs`는 `[{"node_id","content_version","label"}]`. `POST /api/books/{id}/check-sources`는 호출자가 준 현재 `{node_id: content_version}`과 비교해 바뀐 쪽을 돌려준다. Studio는 linetta를 부르지 않는다.
  - 검증: `uv run pytest tests/test_api.py`

- [x] **T1.D.2** — MCP 도구
  - 파일: `src/aiassetstudio/mcp_bridge/server.py`, `tools.py`, `studio_api.py`, `tests/test_mcp_tools.py`
  - 내용:
    - 도구: `create_book`, `set_book_pages`, `set_book_sheets`, `set_book_terms`, `get_book`, `generate_pages`, `set_page`, `check_book_sources`, `export_book`.
    - `get_book`은 쪽 번호, 상태, 사람의 재작업 메모, 갤러리 링크를 텍스트로, 대기 후보를 최대 8장 미리보기로 돌려준다(`get_job`의 `MAX_PREVIEWS` 방식).
    - 인물 시트는 기존 `generate_image`(sprite)로 만들고 `set_book_sheets`에 `asset_id`로 연결한다.
    - `INSTRUCTIONS`에 공정 순서를 추가한다: linetta에서 원작 읽기 → 쪽 대본과 근거 → 시트 → 쪽 생성 → 갤러리 검수 → 재작업 → 내보내기.
    - `INSTRUCTIONS`에 시험에서 배운 구도 규칙을 넣는다: 특징이 보이는 방향, 조연의 외형 명시, 인원수 명시, 영문 프롬프트.
    - 쪽 본문이 원문에 없는 내용을 더하면 안 된다는 규칙도 넣는다.
  - 검증: `uv run pytest tests/test_mcp_tools.py`

### 작업 그룹 E: 갤러리와 내보내기

- [x] **T1.E.1** — 책 화면
  - 파일: `web/src/App.tsx`, `web/src/api.ts`, `web/src/components/BookView.tsx`, `PageCard.tsx`
  - 내용:
    - 경로 `#/books/<id>`. 상단에 진행 수(승인/전체)와 연구 전용 표시, 쪽 카드에 그림·본문·근거 라벨·후보 전환이 있다.
    - 버튼은 채택, 재작업 요청(메모 입력)뿐이다. 재생성은 하지 않는다(기존 규칙).
    - `JobGroup`처럼 폴링으로 진행 상태를 갱신한다.
    - 기존 `index.css` 토큰을 따른다.
  - 검증: `npm run build`, `npm run lint`

- [x] **T1.E.2** — PDF 내보내기
  - 파일: `src/aiassetstudio/post/book.py`(신규), `jobs/runners.py`, `config.py`, `pyproject.toml`, `tests/test_post_book.py`
  - 내용:
    - `reportlab`으로 표지 + 쪽 + 판권을 만든다. 레이아웃은 `spikes/studio/layout_book.py`(그림 위, 글 아래, 1480×1500 비율)를 옮긴다. 글은 이미지가 아닌 텍스트로 넣는다.
    - `Settings.book_font`(`AIAS_BOOK_FONT`, 기본 `C:\Windows\Fonts\batang.ttc`). TTC 하위 글꼴 번호를 시험해 정한다.
    - `book_export` 작업으로 처리한다(계열은 GPU를 쓰지 않는 `none`, `CLOUD_FAMILIES`처럼 대기열이 ComfyUI를 건드리지 않게 한다).
    - 승인되지 않은 쪽이 있으면 기본은 거절하고 `allow_draft=true`면 진행한다.
    - `worst_class`가 `research_only` 또는 `unknown`이면 판권에 사용 모델과 라이선스를 적고, 응답에 경고를 넣는다.
    - dev 의존 `pypdf`로 본문 추출을 시험한다.
  - 검증: `uv run pytest tests/test_post_book.py`

## 구현 메모 (2026-11-01)

지시서와 달라진 점이다.

- 쪽의 인물 열은 `cast`가 SQLite 키워드라 `people`로 했다. 소품을 위한 `props`를 더했다. 시험에서 소품 실패가 3쪽이었다.
- 라이선스 기록은 기존 `meta.models`(역할 → 파일) 형식을 깨지 않도록 `meta.licenses`에 넣었다.
- 장소 시트는 빈 불투명 그림이어야 해서 `POST /api/sheets/{id}/generate`와 MCP `generate_sheet`를 더했다(T1.A.2 결과). 인물 시트는 기존 스프라이트 경로를 쓴다.
- 쪽 상태 `queued`는 `release_idle_pages`가 정리한다. 실패, 취소, 재시작을 한곳에서 처리한다.
- `get_book`의 대기 쪽 미리보기는 채택된 그림만 보낸다.
- MCP `set_page`에는 `approved`가 없다. 승인은 사람이 갤러리에서만 한다.
- 공식 Turbo로 전환했다(`notes/studio-official-turbo.md`). 책의 작업 계열은 `qwen_turbo`이고, 기존 스프라이트는 계속 Viggle을 쓴다.
- 쪽의 `place`와 `props`가 시트 이름이 아니면 그대로 프롬프트에 들어가므로 영어로 적어야 한다. 한글로 적으니 장소가 사라졌다.
- 한 인물의 쌍둥이도 전용 시트가 필요하다. 설명만으로는 참조 인물의 옷과 얼굴로 그려졌다.
- 책 작업은 프로젝트의 작업 목록에서 빼고 책 화면에서 본다.
- PDF 글꼴은 Windows Batang을 기본으로 임베드한다. 공개 배포 전에 글꼴 라이선스를 확인한다.

---

### ✅ Checkpoint: Phase 1 완료 확인

**구현 확인:**
- [x] 기존 스프라이트, BGM, 애니메이션 작업이 그대로 동작한다.
- [x] 쪽을 다시 만들어도 이전 후보가 남고 채택을 바꿀 수 있다.
- [x] 채택한 쪽의 그림 프롬프트를 바꾸면 `draft`로 돌아가고, 본문만 바꾸면 그림 채택이 유지된다.

**실행 확인:**
- [x] `uv run pytest`, `uv run ruff check .`, `npm run lint`, `npm run build`
- [x] GPU 종단검증 `uv run pytest -m gpu tests/gpu/test_book_e2e.py`: 2쪽 책 생성부터 PDF까지

**수동 확인:**
- [ ] 다른 폴더의 Claude Code 세션에서 linetta 작품 일부를 읽어 8쪽 이상 책을 만든다.
- [ ] 갤러리에서 재작업 메모를 남기면 에이전트가 `get_book`으로 읽고 다시 만든다.
- [x] PDF에서 글자를 선택할 수 있고 한글이 깨지지 않는다.

**이 체크포인트를 통과하면 사용자에게 확인 요청 후 Phase 2로 진행.**
실패하면 실패 항목을 보고하고, 원인을 함께 파악해 수정한 뒤 다시 검증한다.
