# Studio Phase 2: 기능 팩과 오디오북 — 작업지시서

_Claude Code가 위에서부터 차례로 하되, 체크포인트에서 사용자 확인을 받는다._

_작성일: 2026-11-01_
_속한 로드맵: [`studio-roadmap.md`](./studio-roadmap.md)_
_예상 소요: 약 32시간_

## 페이즈 목표

CLI가 PC 환경을 점검하고 Studio를 준비한다. 갤러리의 기능 팩 화면에서 음성 팩의 크기와 라이선스를 확인해 동의하면, 갤러리나 CLI로 설치할 수 있다. Studio는 전용 환경과 모델을 내려받고 오디오북 기능을 켠다. 에이전트는 낭독 대본과 발음 사전을 넣고, 사람은 쪽별로 들어보고 고른다. 결과는 MP3로 내보낸다. 설치 구조는 tars `internal/localembed`의 방식(uv 환경, 전용 `HF_HOME`, 루프백 서버, 상태 조회)을 본뜬다.

## 전제 조건

- [x] Phase 1 체크포인트 통과
- [x] `uv`가 PATH에 있다
- [x] 사용자가 시험 낭독을 들었다(T2.A.1)

## 포함 기능

1. 기능 팩 목록과 설치 상태
2. 라이선스 동의와 기록
3. 다운로드, 체크섬, 이어받기, 삭제
4. 음성 사이드카와 대기열 통합
5. 낭독 작업과 발음 사전(낭독자 한 명)
6. 갤러리 오디오 검수와 MP3 내보내기
7. 환경 점검과 설치 CLI: `doctor`, `setup`, `pack`, `serve --detach`

## 이 페이즈에서 하지 않는 것

- ComfyUI와 이미지·영상 팩 → Phase 3
- 다화자 낭독 → T2.A.1 결정으로 제외. 음성 모델을 바꿀 때 다시 본다
- 음성 복제, Whisper 자동 점검 → Next
- 팩의 자동 업데이트 → 새 팩 버전은 다시 동의하고 설치한다

## 작업 체크리스트

### 작업 그룹 A: 음성 결정 (먼저 한다)

- [x] **T2.A.1** — 사용자 청취 (수동)
  - 파일: `docs/plans/notes/studio-spike-2026-11-01.md`에 결과 추가
  - 내용: 사용자가 시험 낭독 전체와 대화 샘플을 듣고 정한다.
  - 결정 규칙
    1. 낭독이 쓸 만하면 → 그대로 진행한다.
    2. 낭독은 되지만 다화자 억양이 어색하면 → 단일 낭독만 MVP로 하고 T2.D.3의 화자 지정을 뺀다.
    3. 낭독 품질이 부족하면 → 멈춘다. Ming-3.0-tts, Chatterbox Multilingual V3를 같은 대본으로 시험해 고른다. 안 되면 사용자와 공정 순서를 다시 정한다.
  - 검증: 사용자 결정 기록
  - 결과(2026-11-01): 결정 2번. 단일 낭독만 MVP로 한다.

### 작업 그룹 B: 기능 팩

- [x] **T2.B.1** — 팩 목록 형식
  - 파일: `src/aiassetstudio/packs/__init__.py`, `packs/catalog.py`, `packs/catalog/speech-ko.json`, `tests/test_pack_catalog.py`
  - 내용:
    - `PackSpec`: `id, title, feature(audiobook 등), version, engine(python_sidecar|comfy_models|comfy_engine), licenses[], files[], requirements, python, torch_index, tested{vram_gb, ram_gb, disk_gb, os}, gated, excluded_regions`
    - `licenses[]`: `id, name, class, url, sha256, summary_ko`. 요약은 "상업 사용", "지역 제한", "연구 전용"을 사실대로 적는다.
    - `files[]`: `repo, path, dest, size, sha256`. 호스트는 `huggingface.co`만 허용한다.
    - 잘못된 목록은 로드 시 예외로 막는다. `excluded_regions`에 `KR`이 있는 팩은 기본 목록에서 제외한다.
    - `speech-ko`: Qwen3-TTS 1.7B CustomVoice, Python 3.12, Apache 2.0. 실제 파일 크기와 sha256은 Hugging Face에서 받아 채운다.
  - 검증: `uv run pytest tests/test_pack_catalog.py`

- [x] **T2.B.2** — 동의 기록
  - 파일: `store/db.py`, `packs/consent.py`, `tests/test_pack_consent.py`
  - 내용:
    - 스키마 4: `pack_consents(pack_id, pack_version, license_id, license_sha256, accepted_at)`, `pack_installs(pack_id, version, status, error, files(JSON), installed_at)`.
    - 설치 시작 시 현재 목록의 모든 `license_id + sha256`에 동의 기록이 있어야 한다. 없으면 `ConsentRequired`.
    - 라이선스 원문을 내려받아 sha256이 다르면 `LicenseChanged`로 설치를 막고, 팩 화면에 "라이선스가 바뀌었음"을 표시한다.
  - 검증: `uv run pytest tests/test_pack_consent.py`

- [x] **T2.B.3** — 다운로드와 설치
  - 파일: `packs/manager.py`, `packs/download.py`, `tests/test_pack_manager.py`
  - 내용:
    - 설치 폴더 `data/packs/<id>/`. 그 안에 `.venv`, 전용 `hf/`, `server.py`, `install.log`. 전역 Hugging Face 캐시를 건드리지 않는다.
    - 다운로드: `httpx` 스트리밍, `.part` 이어받기(`Range`), 완료 후 sha256 검증, 이름 변경. 실패는 상태와 로그로 남긴다.
    - 환경: `uv venv --python`, `uv pip install`. torch는 **마지막에** 기존 torch를 `uv pip uninstall`한 뒤 `torch_index`에서 설치한다. `qwen-tts`가 CPU torch로 덮은 시험 사례를 막기 위해서다. 끝에 `torch.cuda.is_available()`을 검사하고 실패하면 설치 실패로 처리한다.
    - 시작 전 빈 디스크가 `disk_gb`보다 적으면 거절한다.
    - 진행률은 `install` 작업의 `stage`로 노출한다.
    - 삭제: `pack_installs.files`에 기록한 경로와 폴더만 지운다.
    - 테스트는 `Runner` 주입과 `httpx.MockTransport`로 네트워크 없이 한다. `tars/internal/localembed/manager_test.go`의 시나리오를 참고한다.
  - 검증: `uv run pytest tests/test_pack_manager.py`

- [x] **T2.B.4** — 팩 API와 갤러리 화면
  - 파일: `api/app.py`, `web/src/components/PacksView.tsx`, `web/src/api.ts`, `tests/test_api.py`
  - 내용:
    - `GET /api/packs`, `POST /api/packs/{id}/accept`, `POST /api/packs/{id}/install`, `POST /api/packs/{id}/cancel`, `DELETE /api/packs/{id}`.
    - API에는 로그인이 없고 보호는 `TrustedHostMiddleware`뿐이다(`api/app.py`). 쓰기 경로는 `X-Studio-Client` 헤더로 구분한다. 사용자 지정 헤더라 CORS를 허용하지 않는 한 다른 사이트의 요청은 막힌다. CORS는 켜지 않는다.
      - `accept`: `gallery`만 허용한다.
      - `install`, `cancel`, `DELETE`: `gallery`와 `cli`를 허용한다. 동의 기록이 없으면 어느 쪽이든 `ConsentRequired`다.
    - MCP `studio_api.py`는 이 헤더를 보내지 않는다. CLI에는 동의 명령을 만들지 않는다. 이것은 에이전트가 실수로 동의하지 못하게 하는 장치이지, 같은 PC의 악성 프로세스를 막는 보안 경계는 아니다.
    - 화면: 기능, 크기, 시험 사양, 라이선스 이름과 원문 링크, 요약, 체크박스, 설치·취소·삭제, 진행률, 로그 꼬리.
    - 동의 체크박스는 라이선스마다 따로 둔다. 미리 체크하지 않는다.
  - 검증: `uv run pytest tests/test_api.py`, `npm run build`, `npm run lint`

- [x] **T2.B.5** — MCP 조회
  - 파일: `mcp_bridge/server.py`, `tools.py`, `tests/test_mcp_tools.py`
  - 내용: `list_packs` 추가. 상태와 갤러리 링크만 돌려준다. 설치와 동의 도구는 만들지 않는다. `INSTRUCTIONS`에 "필요한 팩이 없으면 사람에게 갤러리 동의를 요청하고, 설치는 갤러리나 `aiassetstudio pack install`로 한다"를 적는다.
  - 검증: `uv run pytest tests/test_mcp_tools.py`

- [x] **T2.B.6** — 환경 점검 `doctor`
  - 파일: `src/aiassetstudio/doctor.py`(신규), `cli.py`, `tests/test_doctor.py`
  - 내용:
    - `aiassetstudio doctor [--json]`. 항목마다 `{id, status(ok|warn|fail), detail, fix}`. `fix`는 사람이 읽을 안내이며, 자동 실행할 명령이 아니다.
    - 항목: OS, NVIDIA GPU와 드라이버(`nvidia-smi`), VRAM, RAM, 빈 디스크, uv, ffmpeg, ComfyUI(모드, 버전, `VERIFIED_COMFYUI` 일치), 백엔드, 포트 8765·8188·8766, 글꼴.
    - 기존 `check`의 계열 점검은 `comfy/preflight.py`를 그대로 쓴다. `check` 명령은 유지한다.
    - 16GB 미만 VRAM이나 32GB 미만 RAM은 `warn`이다. 시험 사양과 다르다는 뜻으로 쓴다.
    - 치명적 항목이 `fail`이면 exit 1. 에이전트가 읽을 수 있게 JSON 키를 고정한다.
  - 검증: `uv run pytest tests/test_doctor.py`

- [x] **T2.B.7** — `setup`, `serve --detach`, `pack` 명령
  - 파일: `cli.py`, `src/aiassetstudio/detach.py`, `mcp_bridge/studio_api.py`, `tests/test_cli.py`
  - 내용:
    - `aiassetstudio setup [--json]`: 멱등. 데이터 폴더 준비, DB 마이그레이션, 외부 ComfyUI 찾기, 백엔드 시작, 갤러리 URL 출력. 무엇도 내려받지 않는다.
    - `aiassetstudio serve --detach`: `StudioApi.ensure_backend`가 쓰는 `spawn_detached` 경로를 재사용한다. 이미 떠 있으면 그대로 둔다.
    - `aiassetstudio pack list|status|install <id>|cancel <id>|remove <id> [--json]`: 백엔드 HTTP API를 호출한다. 헤더는 `X-Studio-Client: cli`.
    - `install`은 작업을 등록하고 바로 끝난다. 긴 대기는 `pack status`로 확인한다(tars 호출 제한 때문).
    - `ConsentRequired`면 exit 3과 갤러리의 해당 팩 URL을 출력한다. 에이전트가 사람에게 전달할 값이다.
    - `pack accept` 명령은 만들지 않는다.
  - 검증: `uv run pytest tests/test_cli.py`

### 작업 그룹 C: 음성 사이드카

- [x] **T2.C.1** — 사이드카 서버
  - 파일: `src/aiassetstudio/packs/assets/tts_server.py`, `packs/sidecar.py`, `tests/test_sidecar.py`
  - 내용:
    - `tts_server.py`: 팩의 venv에서 실행하는 루프백 FastAPI. `GET /health`, `POST /speak`(`text, speaker, instruct`), 결과는 WAV 파일 경로. `spikes/studio/gen_tts.py`의 호출을 쓴다(`attn_implementation="sdpa"`, `torch.bfloat16`).
    - `SidecarManager(pack, port)`: `ensure()`, `stop()`, `is_up()`. `ComfyLauncher`처럼 잠금으로 한 번만 시작한다. 인증이 없으므로 루프백만 허용한다.
    - 작업 시작 시 올리고, 유휴나 계열 전환 시 내린다. ComfyUI와 달리 다른 세션과 공유하지 않으므로 프로세스를 끝낸다.
  - 검증: `uv run pytest tests/test_sidecar.py`

- [x] **T2.C.2** — 대기열 통합
  - 파일: `jobs/queue.py`, `tests/test_queue.py`
  - 내용:
    - `SIDECAR_FAMILIES = ("tts",)`. 이 계열은 ComfyUI를 시작하지 않는다.
    - 계열 전환 규칙: `tts`로 갈 때 `comfy.free()`, ComfyUI 계열로 갈 때 사이드카 종료.
    - `_idle`에서 사이드카도 내린다.
    - 기존 `CLOUD_FAMILIES` 동작을 바꾸지 않는다.
  - 검증: `uv run pytest tests/test_queue.py`

### 작업 그룹 D: 오디오북

- [x] **T2.D.1** — 낭독 대본과 발음 사전
  - 파일: `store/db.py`, `src/aiassetstudio/narration.py`, `tests/test_narration.py`
  - 내용:
    - `pages`에 `narration_asset_id`, `narration_status`. 낭독자는 `pages.text`를 읽는다.
    - 낭독 목소리는 `narration.py`의 상수(`Sohee`와 낭독 지시)로 둔다. 책별 설정은 만들지 않는다.
    - `apply_terms(text, terms)`: 긴 용어부터 치환한다. 시험에서 성과 호칭을 붙여 쓰면 발음이 바로잡혔다. 테스트에는 작품 고유명사가 아닌 가상 값을 쓴다.
    - 화면 자막과 PDF는 치환 전 `text`를 쓴다.
  - 검증: `uv run pytest tests/test_narration.py`

- [x] **T2.D.2** — `narration` 실행기
  - 파일: `jobs/runners.py`, `api/app.py`, `post/audio.py`, `tests/test_runners.py`
  - 내용:
    - `POST /api/books/{id}/narrate`: 쪽마다 작업 하나, 계열 `tts`. 팩이 없으면 409와 갤러리 안내.
    - 쪽마다 WAV 하나로 저장하고 메타에 길이를 남긴다.
    - `AssetKind`에 `narration` 추가, `meta.models`에 라이선스 기록.
  - 검증: `uv run pytest tests/test_runners.py`

- [x] **T2.D.3** — 낭독 MCP 도구
  - 파일: `mcp_bridge/server.py`, `tools.py`
  - 내용: `generate_narration(book_id, pages?)`. 화자 지정(`set_book_voices`, `set_page_narration`)은 T2.A.1 결정 2번으로 뺐다. 이 도구는 원래 지시서에 빠져 있던 낭독 시작 경로를 채운다.
  - 검증: `uv run pytest tests/test_mcp_tools.py`

- [x] **T2.D.4** — 듣기와 MP3 내보내기
  - 파일: `web/src/components/PageCard.tsx`, `post/audio.py`, `jobs/runners.py`, `tests/test_post_audio.py`
  - 내용:
    - 쪽 카드에 탭(그림, 낭독)과 `<audio>`, 채택, 재작업 메모를 추가한다. 기존 `AudioCard`의 재생 방식을 쓴다.
    - `export_book(format="mp3")`: 쪽 사이 1.2초, `loudnorm=I=-18:TP=-2:LRA=11`, 128k. `meta`에 쪽별 시작 시각을 남긴다(Phase 3 자막 근거).
  - 검증: `uv run pytest tests/test_post_audio.py`, `npm run build`

## 구현 메모 (2026-11-01)

지시서와 달라진 점이다.

- 팩 설치는 대기열 작업이 아니라 `PackManager`의 별도 태스크다. `jobs.project_id`는 필수인데 팩은 프로젝트에 속하지 않고, 수 분짜리 내려받기가 GPU 대기열을 막으면 안 된다. 진행률은 `pack_installs.stage`로 알린다.
- 파일 항목에 `revision`을 더해 커밋에 고정했다. 내려받기 주소는 `huggingface.co/<repo>/resolve/<revision>/<path>`로만 만든다.
- 모델 저장소에 LICENSE 파일이 없고 README는 문서 수정만으로 해시가 바뀐다. 라이선스 원문은 Apache 공식 텍스트를 쓰고, 라이선스 주소 허용 호스트에 `www.apache.org`를 더했다.
- 모델은 팩 폴더의 일반 폴더(`models/`)에 받아 경로로 로드한다. `from_pretrained`가 오프라인에서 허브 구조 없이 동작하는 것을 확인했다. `hf/`는 전역 캐시를 건드리지 않게 하는 `HF_HOME`이고 비어 있다.
- 시험 환경처럼 `torch`와 `torchaudio`가 둘 다 cu130이어야 해서 둘 다 지우고 다시 설치한다.
- 낭독 재작업 메모는 `narration_note`로 그림의 `note`와 분리했다. 낭독 후보는 메타 키 `narration_page_id`로 찾는다. `page_id`를 쓰면 그림 후보에 섞인다.
- 쪽의 본문을 바꾸면 낭독이 `draft`로 돌아간다. 그림은 유지된다.
- 사이드카는 백엔드의 자식 프로세스다. 표준 입력이 닫히면 끝나므로 백엔드가 죽어도 모델이 GPU에 남지 않는다. 작업 실패나 취소 때도 프로세스를 끝낸다. 진행 중인 생성을 멈출 방법이 없기 때문이다.
- 사이드카 포트는 `AIAS_TTS_PORT`(기본 8766), 낭독 작업 제한은 `AIAS_NARRATION_TIMEOUT`(기본 300초)이다.
- `VERIFIED_COMFYUI`를 `cli.py`에서 `comfy/preflight.py`로 옮겼다. `doctor`도 쓴다.
- `doctor`에서 NVIDIA GPU, uv, ffmpeg가 없으면 `fail`이다. 16GB VRAM은 실제 값이 16384MiB보다 조금 작아서 기준을 15500MiB로, 32GB RAM은 31GB로 잡았다.
- 첫 수동 검수에서 드러난 문제를 반복하지 않도록 낭독에도 일괄 채택을 넣었다. 책 머리를 그림과 낭독 두 줄로 나눴다.
- 일괄 채택과 팩 삭제는 두 번 눌러야 실행된다.
- 실제 책 낭독 측정(2026-11-01): 12쪽 1,807자, 음성 310초를 596초에 생성했다. 쪽당 약 50초, 실제 길이의 1.9배, VRAM 최대 4.59GB. 시험 때 대본보다 글이 길어 음성이 1.8배로 늘었다.
- 실제 설치 측정(2026-11-01, 동의 절차를 건너뛰고 설치 단계만 호출, 임시 폴더): 내려받기 94초, 패키지와 torch 36초, 합계 129초(uv 캐시가 있는 PC). 새 환경에서 첫 서버 시작 49초, 3.28초 낭독 생성 5.6초, VRAM 최대 3.99GB. 팩 폴더 7.62GB. 삭제 후 팩 폴더가 사라졌고 전역 Hugging Face 캐시와 ComfyUI 모델은 파일 수와 크기가 그대로였다.

---

### ✅ Checkpoint: Phase 2 완료 확인

**구현 확인:**
- [x] 동의 없이 설치 API를 부르면 거절된다.
- [x] MCP로는 동의와 설치가, CLI로는 동의가 불가능하다.
- [x] 동의 없이 `pack install`을 실행하면 exit 3과 갤러리 URL이 나온다.
- [x] `doctor --json`과 `setup`을 반복 실행해도 결과가 같고 내려받는 파일이 없다.
- [x] 다운로드 중단 후 다시 설치하면 이어받고, 체크섬이 틀리면 실패한다.
- [x] 음성 작업과 이미지 작업을 섞어 넣어도 GPU 작업은 하나씩 돌고 메모리가 전환된다.

**실행 확인:**
- [x] `uv run pytest`, `uv run ruff check .`, `npm run lint`, `npm run build`
- [x] GPU 종단검증 `uv run pytest -m gpu tests/gpu/test_audiobook.py`: 이미지, 낭독 2쪽, 이미지, MP3 순서. CLI로 재설치한 실제 팩으로 77초에 통과했다.

**수동 확인:**
- [x] 임시 `AIAS_DATA_DIR`에서 갤러리로 음성 팩을 동의하고, CLI로 설치, 삭제한다. 삭제 후 전역 캐시와 ComfyUI가 그대로다. 임시 폴더가 아니라 실제 데이터에서 사용자가 동의한 뒤 `pack remove`, `pack install` 순서로 확인했다. 삭제 후 전역 Hugging Face 캐시와 ComfyUI 모델의 파일 수와 크기가 같았다. 삭제해도 동의 기록은 남아 재설치에 다시 동의할 필요가 없었다.
- [x] 사용자가 낭독을 듣고 쪽별로 채택, 재작업한 뒤 MP3를 내보낸다. 12쪽을 재작업 없이 모두 채택했다. MP3는 322.88초로 `page_starts`의 끝과 일치하고, 라이선스 경고는 없다. 사람이 남긴 낭독 재작업 메모의 왕복은 자동 테스트로만 확인했다.

**이 체크포인트를 통과하면 사용자에게 확인 요청 후 Phase 3으로 진행.**
실패하면 실패 항목을 보고하고, 원인을 함께 파악해 수정한 뒤 다시 검증한다.
