# Studio Phase 4: tars 플러그인과 셋업 — 작업지시서

_Claude Code가 위에서부터 차례로 하되, 체크포인트에서 사용자 확인을 받는다._

_작성일: 2026-11-01_
_속한 로드맵: [`studio-roadmap.md`](./studio-roadmap.md)_
_예상 소요: 약 16시간_

## 페이즈 목표

tars 저장소를 고치지 않고, 플러그인과 포커스 템플릿 파일만으로 tars에서 그림책 공정을 돌린다. tars는 linetta MCP로 원작을 읽고 Studio MCP로 생성을 요청한다. 다른 OS의 tars는 네트워크 MCP로 GPU PC의 Studio를 쓴다.

또 Studio가 없는 Windows GPU PC에서 tars가 대화로 설치를 안내한다. 설치는 Studio CLI가 하고 스킬은 호출과 설명만 한다. 데스크톱 앱은 만들지 않는다.

## tars 쪽 전제 (2026-11-01, v0.67.0)

- 플러그인은 스킬과 MCP 서버만 묶는다. 화면을 추가할 수 없다.
- MCP 호출은 전체 15초 제한이다(`internal/mcp/client.go`).
- MCP 결과의 이미지가 버려진다. tars 에이전트는 미리보기를 볼 수 없다.
- 플러그인은 `supported_os`로 막으면 스킬까지 로드되지 않는다. 그래서 OS 조건을 두지 않고 MCP 연결은 사용자 설정으로 둔다. stdio 명령은 `extensions.mcp.command_allowlist`를 따른다.
- 포커스 템플릿은 `<workspace>/focus-templates/*.yaml`에서 읽는다. 텍스트만 담고 명령은 담지 못한다. 단계 종류는 `plan, build, review, pr, pr_review, merge`다.
- 검증 명령 하나의 제한은 15분이다.
- Skill Hub는 동결 상태다. 배포는 폴더 복사로 한다.

## 전제 조건

- [ ] Phase 2 체크포인트 통과. `doctor`, `setup`, `pack`이 필요하다. Phase 3은 없어도 진행할 수 있다
- [ ] tars에 linetta MCP가 연결돼 있다

## 포함 기능

1. MCP 대기 시간 상한
2. 책 상태 확인 CLI
3. 플러그인과 스킬
4. 포커스 템플릿
5. 원격 MCP
6. 설치 패키지
7. tars 설치 스킬

## 이 페이즈에서 하지 않는 것

- tars 코드 변경, Hub 등록, 포커스 카드의 미디어 표시
- 원격 PC의 설치와 팩 동의. 설치와 동의는 GPU PC에서 한다
- 데스크톱 앱, 재부팅 후 자동 실행, 자동 업데이트
- PyPI 배포. 처음에는 GitHub Release 파일을 쓴다

## 작업 체크리스트

### 작업 그룹 A: tars 제약 맞추기

- [ ] **T4.A.1** — MCP 대기 상한
  - 파일: `config.py`, `mcp_bridge/tools.py`, `mcp_bridge/server.py`, `tests/test_mcp_tools.py`
  - 내용: `Settings.mcp_max_wait: int = 60`(`AIAS_MCP_MAX_WAIT`). 모든 `wait_seconds`를 이 값으로 자른다. 플러그인은 10으로 준다. 응답에 "still running; call again"을 유지한다. 도구 호출은 어떤 경우에도 `wait_seconds + 2`초 안에 끝나야 한다.
  - 검증: `uv run pytest tests/test_mcp_tools.py`

- [ ] **T4.A.2** — `book-status` 명령
  - 파일: `src/aiassetstudio/cli.py`, `tests/test_cli.py`
  - 내용: `aiassetstudio book-status <book> --require pages-approved|narration-approved|clips-approved|exported`. 조건을 만족하면 exit 0, 아니면 exit 1과 남은 쪽 목록 및 재작업 메모를 출력한다. GPU PC의 tars에서 `export` 단계의 검증 명령으로 쓴다. 대기하지 않고 즉시 끝낸다. 작업이 아직 끝나지 않았으면 메시지로 구분한다.
  - 원격 tars에는 이 명령이 없다. 원격 계획은 검증 명령을 비우고 MCP `get_book` 결과로 판단한다.
  - 검증: `uv run pytest tests/test_cli.py`

### 작업 그룹 B: 플러그인

- [ ] **T4.B.1** — 플러그인 패키지
  - 파일: `integrations/tars/studio/tars.plugin.json`, `integrations/tars/studio/skills/studio-book/SKILL.md`, `integrations/tars/README.md`
  - 내용:
    - 매니페스트: `schema_version: 2`, `id: studio`, `skills: ["skills"]`. `supported_os`와 `supported_arch`는 **넣지 않는다.** 넣으면 Mac과 Linux의 tars에서 스킬까지 사라져 원격 사용이 막힌다.
    - 매니페스트의 `mcp_servers`는 비운다. 연결은 사용자가 `extensions.mcp.servers`에 적는다: GPU PC는 stdio, 다른 PC는 `streamable_http`. README에 두 예시를 넣고, 로컬 예시에는 `AIAS_MCP_MAX_WAIT=10`을 넣는다.
    - `requires_plugin: studio`, `recommended_tools`를 스킬에 적는다.
    - 스킬 내용: linetta에서 읽는 순서, 쪽 대본 규칙(원문에 없는 내용 금지, `source_refs` 기록), 시트 작성, 생성, 갤러리 링크를 사용자에게 알리기, `get_book`으로 재작업 메모 읽기, 라이선스 경고 전달. 프롬프트 규칙은 `INSTRUCTIONS`와 중복하지 않고 참조만 한다.
    - README: 플러그인 폴더 복사, MCP 서버 설정, stdio면 `command_allowlist` 설정.
  - 검증: Windows와 다른 OS의 tars 모두에서 플러그인 진단에 오류 없음, `mcp.aiassetstudio.studio_status` 호출 성공

- [ ] **T4.B.2** — 포커스 템플릿
  - 파일: `integrations/tars/focus-templates/picturebook.yaml`, `tests/test_tars_template.py`
  - 내용:
    - 단계: `plan`(범위와 쪽 수), `adapt`(build, 쪽 대본과 근거), `sheets`(build, 시트), `render`(build, 생성), `choose`(build, 검증 명령이 사람의 채택을 기다림), `export`(build, PDF).
    - `choose`의 지시문은 갤러리 링크를 알리고 `<focus-report>`의 `decisions`로 "채택을 마쳤나요"를 묻게 한다. 결정 카드는 답을 받을 때까지 루프를 멈춘다(tars `docs/decisions/focus-mode.md` §4).
    - 답을 받으면 에이전트가 MCP `get_book`으로 승인 상태를 본다. 원격에서도 동작해야 하므로 CLI에 의존하지 않는다. 재작업 메모가 있으면 처리한 뒤 다시 묻고, 전부 승인됐을 때만 `tasks_done`을 보고한다.
    - `choose`에는 검증 명령을 넣지 않는다. 검증 실패는 수정 턴을 불러 빌드 한도 3회를 사람이 고르는 동안 다 쓰기 때문이다. 검증 명령이 없는 단계는 보고가 `tasks_done`이면 끝난다.
    - 목표 모드는 결정 카드에 스스로 답하므로 이 템플릿에 맞지 않는다.
    - **목표 모드에서는 쓰지 말라고** 문서에 적는다.
    - 12단계, 4000바이트 제한과 `<focus-` 금지를 파이썬 테스트로 확인한다.
  - 검증: `uv run pytest tests/test_tars_template.py`, tars `GET /v1/focus/templates`의 `diagnostics`가 비어 있음

### 작업 그룹 C: 원격

- [ ] **T4.C.1** — 네트워크 MCP
  - 파일: `src/aiassetstudio/cli.py`, `mcp_bridge/server.py`, `tests/test_cli.py`
  - 내용:
    - `aiassetstudio mcp --http --host <주소> --port 8767`. Streamable HTTP.
    - 비루프백 주소는 `AIAS_MCP_TOKEN` 없이는 시작을 거절한다(`is_loopback`). 요청은 Bearer 검사를 통과해야 한다.
    - HTTP 백엔드와 갤러리는 그대로 루프백이다. 원격 사용자에게 갤러리가 필요하면 Tailscale Serve로 노출하는 방법만 문서로 안내한다.
    - tars 설정 예: `transport: streamable_http`, `auth_mode: bearer`, `auth_token_env`.
  - 검증: `uv run pytest tests/test_cli.py`

### 작업 그룹 D: 설치 패키지와 셋업 스킬

저장소 없이 설치하려면 경로부터 고쳐야 한다. 지금은 `data_dir`, `comfy_dir`, `sprite_gen`, `GALLERY_DIST`가 모두 저장소 위치를 기준으로 잡히고, `web/dist`는 git에 없다.

- [ ] **T4.D.1** — 설치 모드 경로
  - 파일: `config.py`, `api/app.py`, `tests/test_config.py`
  - 내용:
    - 저장소 실행을 감지한다(`REPO_ROOT / "pyproject.toml"`이 있으면 개발 모드). 개발 모드의 기본값은 지금과 같아야 한다.
    - 설치 모드의 `data_dir` 기본값은 `%LOCALAPPDATA%\Studio`, `comfy_dir`은 설치된 팩이나 `AIAS_COMFY_DIR`이다.
    - 갤러리는 패키지 안의 `aiassetstudio/gallery/`를 먼저 찾고, 개발 모드에서는 `web/dist`를 쓴다.
    - `AIAS_*` 환경 변수는 어느 모드에서나 우선한다.
  - 검증: `uv run pytest tests/test_config.py`

- [ ] **T4.D.2** — 릴리스 패키지
  - 파일: `pyproject.toml`, `scripts/build_release.ps1`, `README.md`, `.gitignore`
  - 내용:
    - `npm run build` 결과를 `src/aiassetstudio/gallery/`로 복사하고 wheel을 만든다. 복사본은 git에 넣지 않는다.
    - 설치 명령은 `uv tool install --python 3.13 <release wheel URL>`이다.
    - 릴리스에 플러그인 묶음 `studio-tars-plugin.zip`도 올린다. Studio가 없는 PC의 시작점이다. 사용자가 이것을 `<workspace>/plugins/`에 풀면 `/studio-setup`을 쓸 수 있다. 스킬의 release URL은 묶음을 만들 때 해당 버전으로 고정한다.
    - README에 설치, `doctor`, `setup`, 제거 방법을 적는다. 설치가 ComfyUI나 모델을 내려받지 않는다는 점도 적는다.
    - 공개 전에 현재 `LICENSE`와 의존성 라이선스를 확인한다.
  - 검증: 깨끗한 임시 uv 도구 폴더에 설치하고 Node 없이 `aiassetstudio setup` 후 갤러리가 열림

- [ ] **T4.D.3** — tars 설치 스킬
  - 파일: `integrations/tars/studio/skills/studio-setup/SKILL.md`, `integrations/tars/README.md`
  - 내용:
    - frontmatter: `user-invocable: true`, `slash: /studio-setup`, `recommended_tools: [bash]`, `requires_plugin: studio`. Studio가 아직 없을 수 있으므로 `requires_bins`는 넣지 않는다.
    - 순서
      1. `aiassetstudio doctor --json`을 실행한다. 명령이 없으면 설치 방법을 설명하고 사용자가 허락하면 release wheel을 설치한다.
      2. `fail` 항목을 쉬운 말로 설명한다. 드라이버, Python, 시스템 설정은 직접 바꾸지 않고 사용자에게 안내한다.
      3. `aiassetstudio setup`을 실행한다.
      4. 원하는 기능을 묻고 `pack list --json`의 크기와 라이선스 요약을 보여준다.
      5. 갤러리 팩 URL을 주고 **사용자가 직접 동의**하게 한다. 동의를 대신하거나 채팅 답변을 동의로 처리하지 않는다.
      6. `pack install <id>`를 실행하고 짧게 `pack status`를 확인해 완료를 알린다.
      7. `aiassetstudio doctor`로 마무리한다.
    - 스킬에서 금지: 목록에 없는 명령 임의 실행, `--force`류 우회, 기존 ComfyUI 업데이트, 토큰을 채팅이나 파일에 쓰기.
    - 목표 모드와 자동 승인 모드로 실행하지 말라고 적는다. 시스템을 바꾸는 작업이기 때문이다.
    - Windows가 아니면 로컬 설치를 시작하지 않고 원격 연결 안내로 넘어간다.
    - 스킬은 짧게 유지하고 판단은 CLI 출력에 맡긴다.
  - 검증: 빠진 항목이 있는 환경에서 수동 실행. 긴 작업이 tars 15초 호출 제한에 걸리지 않음

- [ ] **T4.D.4** — 없는 환경에서 설치 시험 (수동)
  - 파일: `docs/plans/notes/studio-setup-trial.md`
  - 내용: 새 Windows 사용자 계정이나 Windows Sandbox처럼 Studio와 ComfyUI가 없는 환경에서 tars로 `/studio-setup`을 실행한다. Sandbox에서 GPU를 쓸 수 없으면 `doctor`와 설치까지만 보고 팩 실행은 실제 PC에서 본다. 막힌 지점과 시간을 기록한다.
  - 결정 규칙: 사용자가 터미널 지식 없이 끝내지 못하는 단계가 남으면 CLI 메시지를 먼저 고친다. 그래도 안 되면 Tauri를 다시 검토한다.
  - 검증: 기록 문서 작성, 사용자와 결과 합의

---

### ✅ Checkpoint: Phase 4 완료 확인

**구현 확인:**
- [ ] tars, linetta 저장소에 변경이 없다.
- [ ] 15초 안에 끝나지 않는 MCP 호출이 없다.
- [ ] 토큰 없이 비루프백으로 시작할 수 없다.

**실행 확인:**
- [ ] `uv run pytest`, `uv run ruff check .`

**수동 확인:**
- [ ] tars 포커스에서 `picturebook` 템플릿으로 8쪽 이상 책을 완주한다. 갤러리에서 고른 뒤 PDF가 나온다.
- [ ] 재작업 메모가 다음 턴에 처리된다.
- [ ] Tailscale로 연결한 다른 PC의 tars에서 `studio_status`와 쪽 생성이 동작한다.
- [ ] Studio가 없는 환경에서 `/studio-setup`으로 점검, 설치, 갤러리 동의, 음성 팩 설치까지 끝낸다.
- [ ] 스킬이 동의를 대신하지 못하고, 동의 전 설치는 CLI에서 거절된다.

**이 체크포인트를 통과하면 로드맵 완료를 사용자에게 보고한다.**
실패하면 실패 항목을 보고하고, 원인을 함께 파악해 수정한 뒤 다시 검증한다.
