# AIAssetStudio

로컬 모델(ComfyUI)로 인디게임용 스프라이트·아이콘·BGM을 만드는 에셋 스튜디오. Windows 전용이다(아래 "준비").
Claude Code가 MCP 도구로 생성을 요청하고, 사람은 웹 갤러리에서 후보를 보고 고른다.
스프라이트 애니메이션만은 클라우드(sprite-gen + codex)로 만들고, 프로젝트마다 켜야 쓴다(아래 "애니메이션").

계획은 `docs/plans/aiassetstudio-roadmap.md`, 애니메이션은 `docs/plans/aiassetstudio-animation-roadmap.md`

## 구조

- **백엔드** (`127.0.0.1:8765`): ComfyUI 호출, 작업 대기열(GPU 작업은 한 번에 하나), 후처리, 저장을 모두 맡는다.
- **MCP 서버**와 **웹 갤러리**는 백엔드 HTTP API만 부른다.
- 데이터: `data/studio.db`, `data/projects/<프로젝트>/assets/<id>/` (이미지: `raw`·`processed`·`preview.png`,
  곡: `raw.flac`, `loop.wav`·`loop.ogg` 또는 `full.wav`·`full.ogg`,
  애니메이션: `row.png`·`animation.json`·`preview.png`·`preview.gif`·`base.png`·`frames/000~009.png`와
  sprite-gen 작업 폴더 `run/`), 로그는 `data/logs/`

## 준비

- **Windows 11**에서 만들고 확인했다(NVIDIA GPU 16GB VRAM, RAM 32GB). ComfyUI 자동 실행(WMI, `.venv\Scripts\python.exe`),
  작업 중단(`taskkill`), sprite-gen 경로가 Windows 기준이라 다른 OS에서는 그대로 돌지 않는다.
- ComfyUI 0.37.0과 아래 "모델과 라이선스"의 모델. 이 저장소 옆 폴더(`..\ComfyUI`)에 있으면 그대로 찾고, 다른 곳이면
  `AIAS_COMFY_DIR`에 경로를 준다. 자동 실행은 ComfyUI의 `.venv\Scripts\python.exe`를 쓴다. 포터블 판처럼 Python이
  다른 곳에 있으면 `AIAS_COMFY_PYTHON`에 그 `python.exe`를 준다(포터블 판: `AIAS_COMFY_DIR`는 `...\ComfyUI_windows_portable\ComfyUI`,
  `AIAS_COMFY_PYTHON`은 `...\ComfyUI_windows_portable\python_embeded\python.exe`).
- [uv](https://docs.astral.sh/uv/), Node 22 (갤러리 빌드용)
- ffmpeg (libvorbis 포함, BGM의 OGG용). PATH에 없으면 `AIAS_FFMPEG`에 경로를 준다.
- 애니메이션을 쓸 때만: sprite-gen과 codex CLI(아래 "애니메이션")

```
uv sync
npm --prefix web install
npm --prefix web run build
```

## 모델과 라이선스

이 저장소의 코드는 MIT 라이선스다([`LICENSE`](LICENSE)). 모델은 들어 있지 않고, 모델과 그 결과물에는 각 모델의 라이선스가
적용된다. 코드의 MIT 라이선스는 모델이나 결과물에 적용되지 않는다. 아래는 2026-09 기준 요약이므로, 쓰기 전에 원문을 확인한다.

| 용도 | 모델 | 파일 (ComfyUI `models/` 아래) | 라이선스 |
|---|---|---|---|
| 스프라이트·아이콘 | [Qwen-Image-2.1](https://huggingface.co/Qwen/Qwen-Image-2.1) | `diffusion_models/qwen_image_2.1_int8_convrot.safetensors`, `text_encoders/qwen3vl_8b_int8_convrot.safetensors`, `vae/qwen_image_2.1_vae_bf16.safetensors` | Qwen Research License (연구·평가용, 비상업) |
| 이미지 6스텝 가속 | [Viggle Turbo](https://huggingface.co/Viggle/Qwen-Image-2.1-viggle-turbo) | `loras/Qwen-Image-2.1-viggle-turbo-v0.2.1-6step-lora-r128.safetensors` + 커스텀 노드 `ViggleTurboLora`·`ViggleTurboSigmas` | Qwen Research License |
| 연주곡 | [ACE-Step 1.5](https://huggingface.co/ACE-Step/Ace-Step1.5) | `diffusion_models/acestep_v1.5_turbo.safetensors`, `text_encoders/qwen_0.6b_ace15.safetensors`, `text_encoders/qwen_4b_ace15.safetensors`, `vae/ace_1.5_vae.safetensors` | MIT |
| 보컬 곡 | [YuE2](https://github.com/multimodal-art-projection/YuE) | `checkpoints/yue2_3b_int8_convrot.safetensors` | CC BY-NC 4.0 + 창작자 허용(개인·창작자는 결과물로 수익을 낼 수 있고, 회사는 상업 라이선스가 필요) |

- **판매할 게임의 이미지**: Qwen-Image-2.1과 Viggle Turbo는 비상업 라이선스다. 판매용 게임의 에셋을 만들려면 상업
  라이선스를 따로 받거나 이미지 모델을 바꿔야 한다.
- **애니메이션**: [sprite-gen](https://github.com/aldegad/sprite-gen)(Apache-2.0)이 OpenAI의 codex CLI로 만든다. 보내는
  그림과 결과물에는 OpenAI 이용 약관이 적용된다.
- 빠진 노드와 모델 파일은 `uv run aiassetstudio check`가 이름으로 알려 준다.

## 실행과 점검

```
uv run aiassetstudio check        # ComfyUI와 필요한 노드·모델 점검 (빠진 것은 이름으로 표시)
uv run aiassetstudio serve        # 백엔드 + 갤러리: http://127.0.0.1:8765/  (API 문서: /docs)
```

ComfyUI는 따로 켜 두지 않아도 된다. 생성 요청이 들어왔을 때 꺼져 있으면 백엔드가 창 없이 띄운다
(최대 2분, 로그 `data/logs/comfyui.log`). 백엔드도 MCP 도구를 처음 부를 때 꺼져 있으면 MCP 서버가 띄운다
(로그 `data/logs/backend.log`). 둘 다 Claude Code 세션 밖에서 띄우므로(Windows에서는 WMI로 띄운다,
`src/aiassetstudio/detach.py`) 띄운 세션을 닫아도 계속 돈다.

### 보안

- 백엔드 API에는 로그인이 없다. 기본값대로 `127.0.0.1`에서만 받게 둔다. API는 받은 경로의 이미지를 읽고
  (`reference_image`), 받은 폴더에 파일을 쓴다(`export_dir`, `dest_dir`). `AIAS_HOST=0.0.0.0` 등으로 다른 기기에
  열면 그 네트워크의 누구나 같은 일을 할 수 있다. 이때 백엔드는 시작하면서 경고를 남긴다.
- 자기 호스트 이름(`127.0.0.1`, `localhost`, 설정한 주소)으로 온 요청만 받는다. 웹 페이지가 자기 도메인을
  127.0.0.1로 돌려 이 API를 부르는 공격(DNS 리바인딩)을 막기 위해서다.
- 네트워크 경로(`\\서버\공유`)는 받지 않는다. 열기만 해도 Windows가 그 서버에 접속해 로그인을 시도하기 때문이다.
  네트워크 폴더로 내보내려면 드라이브 문자로 연결해서 쓴다.
- 그림을 밖으로 보내는 기능은 애니메이션뿐이고, 프로젝트에서 켠 경우에만 보낸다(아래 "애니메이션").

## Claude Code에 등록 (MCP)

사용자 범위로 한 번 등록하면 모든 프로젝트 폴더의 Claude Code 세션에서 쓸 수 있다. `<이 저장소 경로>`는 이 폴더의
절대 경로다(공백이 있으면 따옴표로 감싼다). 프로젝트가 없을 때 갤러리가 경로를 채운 명령을 보여 준다.

```
claude mcp add --transport stdio aiassetstudio --scope user -- uv --directory <이 저장소 경로> run python -m aiassetstudio mcp
claude mcp list
```

이미 열려 있는 세션은 새로 열어야 도구가 보인다. 도구: `studio_status`, `list_projects`, `get_project`,
`create_project`, `update_project`, `generate_image`, `generate_bgm`, `generate_animation`, `get_job`,
`list_assets`, `set_asset_status`, `export_asset`, `cancel_job`.

요청 예시 (게임 폴더에서 연 Claude Code 세션):

- "에셋 스튜디오에 lastlight 프로젝트 만들어줘. 어두운 판타지 화풍, 내보내기 폴더는 C:\...\Assets\Art"
- "그 화풍으로 그림자 적 스프라이트 4장 뽑아서 보여줘"
- "2번 골라서 enemy_shadow 이름으로 내보내줘"
- "lastlight 프로젝트를 32×32, 12색 픽셀아트로 바꾸고 참고 이미지는 C:\...\keeper.png로 해줘"
- "demo 프로젝트에 아늑한 마을 BGM 2곡, 96 BPM, 90초로 만들어줘" → 갤러리에서 들어 보고 고른다
- "lastlight 프로젝트에 애니메이션 클라우드 켜줘" → "그림자 적 `<id>`로 애니메이션 만들어줘"
  → "shadow_anim 이름으로 내보내줘"

코드를 새로 받은 뒤에는 떠 있는 백엔드를 한 번 끄고(아래 "끄기", 다음 도구 호출 때 새 코드로 다시 뜬다)
Claude Code 세션도 새로 열어야 바뀐 도구 인자가 보인다.

### 픽셀아트 프로젝트와 참고 이미지

- 픽셀아트 규격(`pixel_art`, `logical_width`·`logical_height`, `max_colors`, 선택 `palette`)이 있으면 후처리본이
  그 캔버스 크기, 최대 색 수(팔레트가 있으면 팔레트 색만), 알파 0/255를 지킨다. 스프라이트는 발을 캔버스
  아래쪽 여백 1칸 위에 맞추고, 아이콘은 가운데에 둔다. 갤러리는 논리 크기 그림을 정수배로 키워 보여준다.
- 참고 이미지가 있으면 스프라이트는 참고 이미지의 대상이 선 줄에 선다. 예를 들어 LAST LIGHT keeper는
  32줄 중 28번째 줄에 서므로 아래 3줄을 비운다. 비우는 줄은 최소 1줄, 최대 캔버스의 1/4이고,
  `meta.postprocess.pixelate.ground`에 남는다.
- 모델이 고른 칸(블록) 격자로 그렸으면 그 칸 하나를 픽셀 하나로 되살리고, 캔버스(여백 1칸 제외)에 들어가는
  가장 큰 정수배로만 키운다. 1배일 수 있으므로 캔버스를 다 채우지 않을 수 있다. 격자가 고르지 않거나 칸 수가
  캔버스보다 많으면 예전처럼 늘려 맞춘다. 어느 쪽인지는 갤러리 상세의 "규격"과 MCP `get_job`에 나온다
  (`meta.pixel.fit`).
- `icon_size`는 모든 프로젝트에 쓴다. 아이콘을 그 크기의 정사각형으로 줄인다(픽셀아트는 없으면 `logical_width`).
- 참고 이미지(`reference_image`, PNG/JPEG 절대 경로)는 스튜디오 데이터 폴더로 복사되고 원본은 읽기만 한다.
  스프라이트에만 쓰고 아이콘은 무시한다. 결과는 참고 이미지의 자세와 비율을 따라가는 경향이 있다
  (검증 기록: `docs/plans/notes/ref-rgba-validation.md`).

### BGM

- 연주곡은 ACE-Step 1.5로 만든다(90초 곡에 20~40초). 반복용(기본)은 끝의 무음을 자르고, 조용한 앞 마디를
  최대 4마디 건너뛴 뒤, 온전한 4/4 마디 수만큼 잘라 30ms 크로스페이드로 이음새를 잇고, -1 dBFS로 맞춘다.
  마디가 4개보다 모자라면 반복 없이 전체 곡(`full.*`)을 남긴다.
- 파일은 WAV와 OGG를 함께 만들고 내보내기도 둘 다 복사한다. **완벽한 반복은 WAV**다. OGG는 용량이 작지만
  엔진에 따라 반복 지점에 아주 짧은 틈이 생길 수 있다.
- 보컬 곡은 `vocal=true`와 가사로 YuE2가 만든다. 곡 하나에 몇 분이 걸린다.
- Claude는 소리를 들을 수 없다. 갤러리에서 반복 재생하고 "이음새 듣기"(끝나기 3초 전부터 재생)로 들어 본 뒤 고른다.
- 이미지 작업과 음악 작업이 번갈아 오면 ComfyUI 메모리를 비우고 모델을 바꾼다(16GB VRAM·32GB RAM에 둘 다 안 들어간다).
- 보컬이 섞였는지는 `scripts/vocal_check.py`로 잰다(torch·torchaudio·librosa가 있는 Python으로 실행, 아래 "스모크 테스트와 개발").

### 애니메이션 (클라우드)

픽셀아트 프로젝트의 스프라이트 하나로 적 애니메이션 한 줄(대기 4 + 이동 6 = 10프레임)을 만든다. 규격은
LAST LIGHT 규약이다: 프로젝트 칸 크기(32×32), 참고 이미지의 발 줄(keeper는 28번째 줄), 대기 0.18초·이동 0.1초.

- **이 스튜디오에서 유일하게 클라우드를 쓰는 기능이다.** [sprite-gen](https://github.com/aldegad/sprite-gen)
  (Apache-2.0)이 codex CLI(ChatGPT 구독의 이미지 생성)를 부른다. OpenAI로 가는 것은 기본 스프라이트(1024px로
  키운 것), sprite-gen의 배치 가이드, 프롬프트다. 에셋 `meta.cloud`에 남는다.
- 프로젝트마다 켜야 한다(`animation_cloud`, 기본 꺼짐): MCP `update_project(animation_cloud=true)`. 꺼진
  프로젝트는 API·실행기·MCP 모두 거부하고 아무것도 보내지 않는다.
- 후보 하나에 1~3분 걸린다(한 줄 60~90초, 두 줄을 동시에). 그동안 GPU 작업은 대기열에서 기다린다. 애니메이션
  작업은 ComfyUI를 쓰지 않고, 시작할 때 올라가 있던 GPU 모델을 비워 공유 GPU를 돌려준다.
- codex는 기본 그림보다 촘촘한 격자로 크게 그린다. 그래서 원본 줄을 두 배 칸으로 다시 추출하고, 줄마다 높이를
  기본 그림에 맞춰 줄인다(1px 윤곽과 눈을 살리는 kCentroid 방식). 색은 기본 그림의 색으로 맞추고(고정
  팔레트가 있으면 그 색), 모든 프레임을 발 줄에 세운다. 대기 프레임이 기본 그림과 폭 ±2칸·높이 ±1칸을
  벗어나면 "크기 다름"으로 표시한다(`meta.fit`, 시험 기록 `docs/plans/notes/animation-trial.md`).
- 내보내기(`export_asset(asset_id, name="shadow_anim")`)는 게임 형식 그대로다: `shadow_anim.png`(10칸 한 줄),
  `shadow_anim/000.png`~`009.png`, `shadow_anim.json`(프레임 크기, `idle` 0~3·`walk` 4~9 태그와 시간).
  이름이 하나라도 있으면 셋 다 `_2`를 붙인다.
- 갤러리: 애니메이션 카드는 대기에 이어 이동을 게임 시간대로 반복 재생한다(정수배 확대). 카드 아래 "codex"
  표시가 있고, 크기가 기본 그림과 다르면 "크기 다름"이 붙는다. 상세의 "재생"에서 전체·대기·이동을 따로
  재생하고 멈추며, "프레임"에서 000~009를 대기·이동으로 나눠 나란히 본다. "발 줄"로 발이 서는 줄 아래에 선을
  긋는다. 종류 필터에 "애니메이션"이 있고, 프로젝트 정보에 클라우드 설정과 지금 만들 수 있는지가 보인다.
  갤러리에서는 설정을 바꾸지 않는다(MCP `update_project`).

준비(한 번). 이 저장소 옆 폴더에 받으면 그대로 찾는다:

```
cd ..
git clone --depth 1 https://github.com/aldegad/sprite-gen
cd sprite-gen
uv venv
uv pip install -e .
```

- codex CLI는 Codex 앱에 든 것을 쓴다(`%LOCALAPPDATA%\OpenAI\Codex\bin\<hash>\codex.exe`, 가장 최근 것을
  찾는다). PATH의 옛 독립 설치본(0.147)은 새 `~/.codex/config.toml`을 못 읽고 바로 끝난다. 다른 codex를 쓰려면
  `AIAS_CODEX_DIR`에 그 폴더를 준다. sprite-gen이 다른 곳에 있으면 `AIAS_SPRITE_GEN`에 `sprite-gen.exe` 경로를 준다.
- codex에 ChatGPT로 로그인해 둔다(`codex login`, Plus 이상). `studio_status`가
  "animation (sprite-gen + codex, cloud): ready" 또는 준비되지 않은 이유를 보인다.

## 끄기

- 직접 띄운 백엔드: 그 터미널에서 Ctrl+C
- 자동으로 뜬 백엔드·ComfyUI는 창이 없다. PowerShell에서:

```
Get-CimInstance Win32_Process | Where-Object CommandLine -Match 'aiassetstudio serve' | ForEach-Object { Stop-Process -Id $_.ProcessId }
Get-CimInstance Win32_Process | Where-Object CommandLine -Match 'ComfyUI\\main.py|main.py --port 8188' | ForEach-Object { Stop-Process -Id $_.ProcessId }
```

ComfyUI는 다른 프로그램이나 세션도 쓰고 있을 수 있으니, 끄기 전에 다른 작업이 없는지 확인한다.

## 스모크 테스트와 개발

```
uv run python scripts/smoke_image.py          # 켜진 백엔드로 스프라이트 2장 (투명 테두리 확인)
uv run python scripts/smoke_mcp.py --generate # MCP 서버를 stdio로 띄워 생성·미리보기·내보내기 한 바퀴
uv run python scripts/smoke_mcp.py --pixel C:\...\ref.png  # 픽셀아트+참고 이미지 프로젝트: 스프라이트 4장, 아이콘 1장, 내보내기 확인
uv run python scripts/smoke_mcp.py --bgm --vocal  # 마을 BGM 2곡(반복 WAV·OGG)과 한국어 보컬 곡 1곡, 내보내기 확인
uv run python scripts/smoke_mcp.py --animation C:\...\keeper.png  # 스프라이트 1장과 그 애니메이션(codex, 클라우드), 게임 형식 확인
uv run python scripts/animation_trial.py      # 애니메이션 축척 시험 (codex, 클라우드; 결과는 임시 폴더)
<torch·torchaudio·librosa가 있는 python.exe> scripts\vocal_check.py <곡 파일들>  # 보컬 비율 (Demucs)
uv run pytest                                 # 가짜 ComfyUI·가짜 sprite-gen으로 도는 테스트 (codex는 부르지 않는다)
uv run pytest -m gpu                          # 실제 ComfyUI·GPU 테스트 (ComfyUI가 바쁘면 건너뜀)
uv run ruff check . ; uv run ruff format --check .
npm --prefix web run dev                      # 갤러리 개발 서버 (/api는 8765로 프록시)
```

설정은 환경 변수 `AIAS_HOST`, `AIAS_PORT`, `AIAS_DATA_DIR`, `AIAS_COMFY_URL`, `AIAS_COMFY_DIR`, `AIAS_COMFY_PYTHON`,
`AIAS_IDLE_FREE_SECONDS`, `AIAS_IMAGE_TIMEOUT`, `AIAS_BGM_TIMEOUT`, `AIAS_FFMPEG`, `AIAS_SPRITE_GEN`,
`AIAS_CODEX_DIR`, `AIAS_ANIMATION_TIMEOUT`으로 바꾼다 (`src/aiassetstudio/config.py`).

클라우드를 부르는 스모크(`--animation`, `animation_trial.py`)는 시험 스프라이트를 OpenAI로 보낸다. 사용자
`data/` 대신 `AIAS_PORT=8766`과 임시 `AIAS_DATA_DIR`로 돌린다.

## 문제 해결

- **`uv sync`·`uv add`가 `aiassetstudio.exe`를 지울 수 없다며 실패**: `uv run aiassetstudio serve`로 띄운 백엔드가
  그 파일을 잡고 있다. 백엔드를 끄고 다시 하거나, 백엔드를 `uv run python -m aiassetstudio serve`로 띄운다
  (MCP 서버와 자동 실행되는 백엔드는 처음부터 `python -m`을 쓴다).
- **Claude Code 세션을 닫으면 백엔드나 ComfyUI가 같이 꺼진다**: 세션 안의 프로세스는 세션의 Windows 작업(Job)에
  묶여 함께 끝난다. 앱은 WMI(`Win32_Process.Create`)로 띄워 여기서 빠져나온다. WMI가 막혀 있으면 직접 띄우고
  `data/logs/mcp.log`(백엔드)나 `backend.log`(ComfyUI)에 "could not start ... through WMI" 경고를 남기는데,
  이때는 세션과 함께 꺼진다. 직접 `uv run aiassetstudio serve`로 띄운 백엔드도 그 터미널과 함께 꺼진다.
- **생성이 오래 걸리다 시간 초과**: `data/logs/`와 ComfyUI 로그(`http://127.0.0.1:8188/internal/logs/raw`)를 본다.
  다른 세션이 GPU를 쓰는 중이면 느려진다.
- **애니메이션이 "sprite-gen gen-set failed"로 실패**: 이유가 작업 오류에 붙는다. codex 로그인이 풀렸으면
  `codex login`을 다시 한다. 행마다의 codex 로그는 에셋 폴더의 `run/gen/reports/gen-set/`에 있다.

## 라이선스

코드는 [MIT](LICENSE)다. 모델과 그 결과물에는 각 모델의 라이선스가 적용된다(위 "모델과 라이선스").
