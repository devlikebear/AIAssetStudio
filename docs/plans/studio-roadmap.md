# Studio — 개발 로드맵

_이 문서는 AIAssetStudio를 작품 제작 도구 Studio로 확장하는 계획의 **총괄본**이다. Claude Code는 이 로드맵을 먼저 읽고 각 페이즈 작업지시서로 이동한다. 페이즈를 넘어갈 때는 반드시 사용자 확인을 받는다._

_작성일: 2026-11-01_
_예상 전체 소요: 약 100시간 (1인 + Claude Code 기준)_
_페이즈 수: 4개_

## Overview

지금의 AIAssetStudio는 게임 에셋 한 장, 곡 하나를 만든다. Studio는 여기에 **작품 한 권 단위의 제작 공정**을 더한다. 소설을 쪽으로 나누고, 인물·장소·소품 시트로 일관성을 잡고, 그림과 음성과 영상을 만들고, 쪽 단위로 고르고 다시 만들어, PDF·오디오북·영상으로 내보낸다.

시험 제작([기록](./notes/studio-spike-2026-11-01.md))에서 16GB 노트북으로 세 공정이 끝까지 돌아가는 것을 확인했다. 병목은 모델 성능이 아니라 각색, 장소·소품 관리, 쪽 단위 재작업이었다. Studio는 이 재작업 흐름을 제품으로 만든다.

주 사용 방식은 지금과 같다. 에이전트(Claude Code, tars)가 MCP로 요청하고 사람은 웹 갤러리에서 보고 고른다. 에이전트는 Studio가 아닌 linetta MCP에서 원작을 읽어 쪽 대본을 Studio에 넣는다. **Studio는 linetta를 직접 부르지 않는다.**

모델과 실행 환경은 **기능 팩**으로 나눈다. 사람이 갤러리에서 라이선스를 확인해 동의하면 내려받고, 그때 기능이 켜진다.

Studio는 CLI와 백그라운드 로컬 웹서버로 실행한다. 설치와 설정은 결정적인 Studio CLI가 하고, tars 스킬이 대화로 그 CLI를 호출해 사용자를 안내한다. 같은 CLI를 Claude Code나 사람이 직접 써도 결과가 같아야 한다. 여기에 더해 Tauri 데스크톱 셸을 둔다(2026-11-07 사용자 결정으로 "데스크톱 앱은 만들지 않는다"를 번복): 셸은 같은 백엔드를 띄우고 같은 갤러리를 창으로 보여줄 뿐, 공정 로직은 갖지 않는다. [`studio-desktop-shell.md`](./studio-desktop-shell.md)

## 결정 사항 (2026-11-01)

| 결정 | 이유 |
|---|---|
| tars, linetta 코드를 바꾸지 않는다 | linetta 비대화와 tars 범위 확대를 피한다. tars는 플러그인으로만 연결한다 |
| 첫 지원 환경은 Windows + NVIDIA | tars의 크로스플랫폼은 Studio를 선택 사항으로 두어 지킨다. 다른 OS는 네트워크 MCP로 GPU PC의 Studio를 쓴다 |
| 공정은 일직선, 쪽별 작업은 대기열 | 시험 공정에 그래프가 필요 없었다. 노드 편집기는 만들지 않는다 |
| 라이선스 동의는 사람만 갤러리에서 | 에이전트가 사람 대신 약관에 동의할 수 없다. 채팅 답변을 동의로 처리하지 않는다. MCP에는 조회만 둔다 |
| 설치 로직은 Studio CLI에 둔다 | `doctor`, `setup`, `pack`이 일을 하고 에이전트는 호출과 안내만 한다. 동의 기록이 없으면 CLI 설치도 거절된다 |
| ~~데스크톱 앱은 만들지 않는다~~ → Tauri 셸을 만든다 (2026-11-07 번복) | 사용자 결정. 갤러리와 백엔드를 그대로 쓰는 얇은 셸만 만들고 공정 로직은 넣지 않는다 |
| 공개 이름은 Studio, 코드 이름은 유지 | 저장소와 패키지 이름 변경은 위험만 크고 기능 가치가 없다. Later로 미룬다 |

## 완료 조건 (전체)

- [ ] 에이전트가 원작 12화를 읽어 쪽 대본과 시트를 Studio에 넣고, 갤러리에서 쪽별로 고르고 재작업 요청을 남긴 뒤, 글자가 선택되는 PDF를 내보낸다.
- [ ] 쪽마다 근거 원문(화, `content_version`)이 기록되고, 원작이 바뀐 쪽을 찾아낼 수 있다.
- [ ] 음성 기능 팩을 갤러리에서 동의 후 설치하면 오디오북 공정이 켜지고, 낭독 MP3를 내보낸다.
- [ ] 영상 기능 팩을 설치하면 쪽별 클립을 만들고, 클립·앞부분·원본 그림 확대를 쪽마다 골라 낭독과 자막이 있는 영상을 내보낸다.
- [ ] 동의하지 않은 팩은 설치되지 않고, 결과물마다 사용 모델과 라이선스가 기록되며, 연구 전용 모델이 쓰인 결과물을 내보낼 때 경고가 나온다.
- [ ] tars 플러그인과 포커스 템플릿으로 그림책 한 권을 완주한다. tars와 linetta 저장소에는 변경이 없다.
- [ ] Studio가 없는 Windows GPU PC에서 tars에게 설치를 요청하면, 점검, 설치, 갤러리 동의, 음성 팩 설치까지 대화로 끝난다.

## 기술 스택 / 환경

- **기존 스택 유지**: Python 3.13(uv), FastAPI, SQLite, MCP Python SDK v2(stdio), React 19 + Vite 갤러리, pytest(`httpx.MockTransport` 가짜 ComfyUI), `@pytest.mark.gpu` 분리, ruff, oxlint.
- **추가 의존**: `reportlab`(PDF, 실제 텍스트), dev에 `pypdf`(PDF 검증). ffmpeg는 기존처럼 외부 도구다.
- **기능 팩 런타임**: 엔진마다 별도 uv venv. Studio의 `.venv`에 torch를 넣지 않는다.
- **실행 환경**: Windows 11, NVIDIA GPU 16GB, RAM 32GB. 백엔드 `127.0.0.1:8765`, ComfyUI `127.0.0.1:8188`, 음성 사이드카 `127.0.0.1:8766`.
- **코드 컨벤션**: [`codebase-analysis.md`](./codebase-analysis.md)를 따른다. 실측 근거는 상수 주석에 적는다.

## 전체 구조

```
에이전트(Claude Code, tars) ── linetta MCP로 원작 읽기
   │
   ├─ CLI (doctor, setup, pack) ─┐
   └─ MCP (mcp_bridge) ──────────┤
웹 갤러리 ───────────────────────┼─ HTTP API ─ 백엔드 (FastAPI)
                                 │              ├ 책 저장소: books, pages, sheets, terms
                                 │              ├ 작업 대기열 (GPU 작업 하나씩)
                                 │              ├ 기능 팩 관리자: 목록, 동의, 설치
                                 │              └ 내보내기: PDF, MP3, MP4
                                 │
                                 ├─ ComfyUI (이미지, 영상)
                                 └─ 음성 사이드카 (TTS)
```

대기열의 "한 번에 GPU 작업 하나" 규칙은 사이드카에도 적용한다. 계열이 바뀌면 이전 엔진의 메모리를 비운다.

## 페이즈

| 페이즈 | 끝나면 되는 일 | 소요 | 지시서 |
|---|---|---|---|
| 1. 책과 그림책 | 설치된 모델로 그림책 한 권을 만들어 PDF로 내보낸다 | 약 30시간 | [`studio-phase-1-picturebook.md`](./studio-phase-1-picturebook.md) |
| 2. 기능 팩과 오디오북 | CLI로 환경을 점검하고, 음성 팩을 동의 후 설치해 오디오북을 만든다 | 약 32시간 | [`studio-phase-2-packs-audiobook.md`](./studio-phase-2-packs-audiobook.md) |
| 3. 움직이는 그림책 | 영상 팩을 설치해 낭독·자막 영상을 만든다. ComfyUI도 팩으로 설치한다 | 약 22시간 | [`studio-phase-3-motion-book.md`](./studio-phase-3-motion-book.md) |
| 4. tars 플러그인과 셋업 | tars에서 Studio를 설치하고 공정을 돌린다. 코드 변경 없이 연결한다 | 약 16시간 | [`studio-phase-4-tars-plugin.md`](./studio-phase-4-tars-plugin.md) |

페이즈 1은 음성 품질 결과와 상관없이 진행한다. 페이즈 2는 **사용자가 낭독을 들어본 결과**가 먼저다(T2.A.1).

## Out of Scope

구현 중에 "이것도 필요한가?" 싶으면 여기를 본다.

- **tars, linetta 코드 변경**: 포커스 `job` 단계, 미디어 승인 카드, MCP 제한 변경, linetta 이미지 가져오기 도구를 만들지 않는다.
- **노드 편집기**: 공정은 코드와 팩이 정의한다.
- **데스크톱 트레이, 설치 프로그램, 자동 업데이트**: 셸(`desktop/`)은 창 하나만 띄운다. 2026-11-07 번복으로 셸 자체는 만들지만, 그 이상은 배포가 필요해질 때 본다.
- **재부팅 후 자동 실행, Windows 서비스**: MCP와 CLI가 필요할 때 백엔드를 띄운다.
- **macOS, Linux, AMD GPU의 Studio**: 다른 OS는 원격 MCP로 쓴다.
- **갤러리에서 생성하기**: 기존 규칙 유지. 갤러리는 보기, 고르기, 재작업 요청, 내보내기, 팩 설치만 한다.
- **EPUB, 웹툰, 말풍선 레이아웃, 다중 영상 편집 타임라인**: PDF, MP3, MP4가 먼저다.
- **리네타웍스 자동 게시**: 파일을 내보내면 사람이 처리한다.
- **게이트 모델 자동 동의**: 사용자가 Hugging Face에서 직접 동의하고 본인 토큰을 넣는다.
- **MiniMax H3와 대한민국을 제외한 모델**: 목록에 넣지 않는다.
- **구독, 계정, 클라우드 렌더링**: 로컬 전용이다.

## Next (로드맵 이후 후보)

- 이미지 부분 재생성(프롬프트로 안 되는 작은 결함). 먼저 Qwen edit 경로를 시험한다.
- 공개 게시용 이미지 팩: Ming Image 0.1 Design(MIT), MOSS-Image(Apache 2.0), FLUX.3 Image Klein. ComfyUI 업데이트와 16GB 일관성 재시험이 필요하다.
- 영상에 ACE-Step 배경음악 깔기, MiniMax Music 3.
- Whisper 받아쓰기로 낭독 자동 점검.
- 음성 복제. 목소리 주인의 동의 기록이 전제다.
- 저장소와 패키지 이름을 Studio로 변경.
- Tauri 데스크톱 앱: 셸은 2026-11-07에 만들었다([`studio-desktop-shell.md`](./studio-desktop-shell.md)). 남은 것은 배포용 포장이다: Python 백엔드 포장(PyInstaller) 시험, 트레이, 알림, 업데이터.
