# Phase 4: BGM — 작업지시서

_이 페이즈의 목표를 달성하기 위한 구체적 작업 목록. Claude Code가 위에서부터 순서대로 실행하되, 체크포인트에서 사용자 확인을 받는다._

_작성일: 2026-09-24_
_속한 로드맵: [`aiassetstudio-roadmap.md`](./aiassetstudio-roadmap.md)_
_예상 소요: 약 12시간_

## 페이즈 목표

브리프(분위기·악기·BPM·길이)로 연주곡 후보를 ACE-Step 1.5로 만들고, 끝부분 무음을 자르고 마디 경계에 맞춘 반복용 WAV·OGG로 정리한다. 보컬 곡은 YuE2로 옵션 생성한다. 이미지 모델과 음악 모델을 바꿀 때는 ComfyUI 메모리를 비운다. 갤러리에서 반복 재생으로 들어보고 고른다. 이 페이즈가 끝나면 MVP 기능 다섯 개가 모두 동작한다.

## 전제 조건

- [x] Phase 2 완료 및 사용자 승인 (Phase 3과는 독립)
- [x] ACE-Step 1.5 모델 4개와 YuE2 모델이 설치돼 있다 (로드맵 "설치된 모델" 표. 2026-09-24 설치·검증) — `aiassetstudio check`: ace ok, yue2 ok
- [x] ffmpeg가 PATH에 있다 (2026-09-24 기준 ffmpeg 9.0, libvorbis 포함 빌드)
- [x] 보컬 비율 측정용으로 ai-toolkit 가상환경(`<ai-toolkit 가상환경>`, torchaudio·librosa 포함)이 있다. 앱 의존성에는 넣지 않는다.

## 포함 기능

1. BGM 생성 — 연주곡(ACE-Step, 기본), 보컬 곡(YuE2, 옵션), 후보 여러 곡
2. 오디오 후처리 — 끝부분 무음 자르기, 조용한 인트로 건너뛰기, 마디 경계 반복 구간, 이음새 크로스페이드, 음량 정규화, WAV·OGG
3. 모델 전환 규칙 — 계열이 바뀌면 `/free`
4. MCP `generate_bgm`, 갤러리 오디오 카드

## 이 페이즈에서 하지 않는 것

- 효과음 → Out of Scope (설치된 모델로 불가)
- 악보(ABC) 편집 UI → Out of Scope
- 음악 품질 자동 평가 → 사람이 듣고 고른다

## 작업 체크리스트

### 작업 그룹 A: 그래프와 사전 점검

- [x] **T4.A.1** — 음악 API 그래프
  - 파일: `src/aiassetstudio/comfy/graphs.py`, `tests/test_graphs.py`
  - 내용:
    - `def ace_music(tags: str, lyrics: str, bpm: int, seconds: float, keyscale: str, seed: int, prefix: str, language: str = "unknown") -> dict` — `spikes/acestep_bgm_test.py`의 `graph()`를 옮긴다. 노드: `UNETLoader`(`acestep_v1.5_turbo.safetensors`) → `ModelSamplingAuraFlow`(shift 3.0), `DualCLIPLoader`(`qwen_0.6b_ace15`, `qwen_4b_ace15`, type `ace`), `VAELoader`(`ace_1.5_vae`), `TextEncodeAceStepAudio1.5`(timesignature `"4"`, generate_audio_codes True, cfg_scale 2.0, temperature 0.85, top_p 0.9, top_k 0, min_p 0), `ConditioningZeroOut`, `EmptyAceStep1.5LatentAudio`, `KSampler`(8스텝, cfg 1.0, euler, simple), `VAEDecodeAudio`, `SaveAudio`. 출력 노드 id `ACE_OUTPUT_NODE = "19"`.
    - `def yue2_song(style: str, lyrics: str, seed: int, max_duration: float, prefix: str) -> dict` — `<ComfyUI 경로>\user\yue2_tools\yue2_run.py`의 ABC 모드 그래프를 옮긴다. 노드: `CheckpointLoaderSimple`(`yue2_3b_int8_convrot.safetensors`) → `YuE2GenerateABC`(mode full) → `YuE2GenerateMusic`(abc 연결) → `ConditioningZeroOut`, `EmptyYuE2LatentAudio`(seconds는 `YuE2GenerateMusic` 출력 1), `KSampler`(32스텝, cfg 1.0, dpm_2, sgm_uniform), `VAEDecodeAudio`, `SaveAudio`. 출력 노드 id `YUE2_OUTPUT_NODE = "10"`. 샘플링 인자는 원본 스크립트 값을 그대로 쓴다.
    - `filename_prefix`는 `f"aiassetstudio/{prefix}"`
  - 검증: `uv run pytest tests/test_graphs.py -k "ace or yue2"` — 링크 무결성, 인자 반영

- [x] **T4.A.2** — 사전 점검에 음악 계열 추가
  - 파일: `src/aiassetstudio/comfy/preflight.py`, `tests/test_preflight.py`
  - 내용:
    - `"ace"`: 노드 `UNETLoader`, `DualCLIPLoader`, `VAELoader`, `ModelSamplingAuraFlow`, `TextEncodeAceStepAudio1.5`, `ConditioningZeroOut`, `EmptyAceStep1.5LatentAudio`, `KSampler`, `VAEDecodeAudio`, `SaveAudio` / 모델 `diffusion_models/acestep_v1.5_turbo.safetensors`, `text_encoders/qwen_0.6b_ace15.safetensors`, `text_encoders/qwen_4b_ace15.safetensors`, `vae/ace_1.5_vae.safetensors`
    - `"yue2"`: 노드 `CheckpointLoaderSimple`, `YuE2GenerateABC`, `YuE2GenerateMusic`, `ConditioningZeroOut`, `EmptyYuE2LatentAudio`, `KSampler`, `VAEDecodeAudio`, `SaveAudio` / 모델 `checkpoints/yue2_3b_int8_convrot.safetensors`
  - 검증: `uv run pytest tests/test_preflight.py`, `uv run aiassetstudio check`에 `ace: ok`, `yue2: ok`

### 작업 그룹 B: 오디오 후처리

2026-09-24 테스트에서 확인한 것: ACE-Step 4곡 모두 요청한 90초보다 일찍 끝나 마지막 3~6초 이상이 무음이었다. 가사 칸에 `[Instrumental]`만 넣은 전투곡은 처음 약 4초가 -24dB 안팎으로 조용했고, 인트로 없는 구간 태그를 넣은 곡은 첫 소절부터 제 음량이었다.

- [x] **T4.B.1** — 불러오기와 무음 처리
  - 파일: `src/aiassetstudio/post/audio.py`, `tests/test_post_audio.py`
  - 내용:
    - 의존성 추가: `uv add soundfile`
    - `load_audio(path) -> tuple[np.ndarray, int]` — 항상 `(frames, channels)` float32
    - `window_db(y, sr, win_s=0.05) -> np.ndarray` — 창별 RMS(dB)
    - `trim_trailing_silence(y, sr, rel_db=-40.0) -> np.ndarray` — 곡 전체 창 dB의 중앙값보다 40dB 이상 작은 창이 끝까지 이어지는 구간을 잘라낸다
    - `leading_quiet_bars(y, sr, bar_s, rel_db=-12.0, max_bars=4) -> int` — 처음부터 중앙값보다 12dB 이상 작은 마디 수(최대 4)
  - 검증: `uv run pytest tests/test_post_audio.py -k "trim or quiet"` — 합성 신호(100 BPM 클릭 + 톤 20초 + 무음 4초)에서 무음 제거, 조용한 앞 1마디 감지

- [x] **T4.B.2** — 반복 구간 만들기
  - 파일: `src/aiassetstudio/post/audio.py`, `tests/test_post_audio.py`
  - 내용:
    - `@dataclass class LoopResult`: `audio`, `start_s`, `end_s`, `bars`, `seam_ratio`
    - `make_loop(y, sr, bpm, beats_per_bar=4, crossfade_ms=30.0, min_bars=4) -> LoopResult`
      1. `bar_s = 60 / bpm * beats_per_bar`
      2. 시작점 = 조용한 앞 마디 수 × `bar_s`
      3. 길이 = (남은 길이 − 크로스페이드 길이)에 들어가는 **온전한 마디 수** × `bar_s`. `min_bars`보다 적으면 `ValueError`
      4. 구간 `seg = y[start : start + L]`, 뒤꼬리 `tail = y[start + L : start + L + xf]`
      5. `seg[:xf] = seg[:xf] * ramp + tail * (1 - ramp)` (`ramp`는 0→1). 반복될 때 `seg`의 마지막 샘플 다음에 오는 `seg[0]`이 원래 곡의 바로 다음 샘플(`tail[0]`)과 같아져서 이음새가 이어진다.
    - `seam_ratio(loop) -> float` — `max|loop[0] − loop[-1]|` ÷ `|diff(loop)|`의 99번째 백분위수. 1 이하면 이음새의 급변이 곡 안의 평범한 샘플 변화보다 크지 않다는 뜻이다.
    - 음악적으로 자연스럽게 이어지는지는 보장하지 않는다. 딸깍 소리를 없애는 것까지가 목표다.
  - 검증: `uv run pytest tests/test_post_audio.py -k loop`
    - 길이가 마디 배수(±1 샘플)
    - 끝에서 위상이 끊기는 합성 사인파에서 크로스페이드 전 `seam_ratio > 5`, 후 `≤ 1`
    - 마디가 모자라면 `ValueError`

- [x] **T4.B.2a** — (조건부) 템포 보정 — 조건이 생겨서 했다: 96 BPM 요청 곡이 98.01·95.01 BPM으로 나왔다 (아래 구현 메모)
  - 전제: `make_loop`는 ACE-Step이 요청한 BPM을 지킨다고 가정한다. 90초 곡에서 템포가 0.6%만 어긋나도 끝에서 약 0.5초가 밀려 박자 중간에서 잘린다.
  - 2026-09-24 실측(librosa 박자 추적 + 박자 시각 직선 맞춤): 구간 태그를 쓴 전투곡은 **100.00 BPM**(요청 100, 박자 오차 2.9ms)으로 정확했다. 나머지 3곡은 타악기가 약해 박자 추적 오차가 86~143ms로 커서 템포를 판정할 수 없었다(맞춤값 93.9~100.3).
  - 할 일: T4.E.2 GPU 테스트와 청취 확인에서 이음새가 박자에서 어긋나면 그때 한다. `detect_tempo(y, sr, requested_bpm) -> float | None` — 박자 시각을 직선으로 맞춰 오차가 20ms 이하일 때만 맞춤 BPM을 돌려주고, 아니면 None(요청 BPM 사용). librosa 의존성은 이 작업을 할 때만 추가한다.
  - 검증: 박자가 뚜렷한 합성 신호에서 알려진 BPM ±0.1 추정, 박자가 흐린 신호에서 None

- [x] **T4.B.3** — 정규화와 인코딩
  - 파일: `src/aiassetstudio/post/audio.py`, `src/aiassetstudio/config.py`, `tests/test_post_audio.py`
  - 내용:
    - `normalize_peak(y, peak_dbfs=-1.0)`
    - `write_wav(path, y, sr)` — soundfile, PCM_16
    - `encode_ogg(wav_path, ogg_path, ffmpeg: str, quality: int = 6)` — `ffmpeg -y -loglevel error -i <wav> -c:a libvorbis -q:a 6 <ogg>`. 실패하면 stderr를 담은 예외
    - 설정 `ffmpeg`(`AIAS_FFMPEG`, 기본 `"ffmpeg"`) 추가
    - WAV는 이음새 없이 반복되고, OGG는 용량이 작지만 엔진에 따라 반복 지점에 아주 짧은 틈이 생길 수 있다. 둘 다 만들고, README에 "완벽한 반복은 WAV"라고 적는다.
  - 검증: `uv run pytest tests/test_post_audio.py -k encode` (ffmpeg가 없으면 skip)

### 작업 그룹 C: 작업과 대기열

- [x] **T4.C.1** — 모델 계열 전환 규칙
  - 파일: `src/aiassetstudio/jobs/queue.py`, `tests/test_queue.py`
  - 내용: 다음 작업의 `family`가 `current_family`와 다르고 모델이 올라가 있으면, 실행 전에 `comfy.free()`를 부르고 작업 `timings.free_before = true`를 기록한다. 같은 계열 우선 선택(Phase 1)은 그대로 둔다. 이미지 모델(텍스트 인코더 9.4GB + 본체 7.3GB)과 ACE-Step(텍스트 인코더 8.4GB + 본체 4.8GB)을 동시에 올리면 32GB RAM이 넘친다.
  - 검증: `uv run pytest tests/test_queue.py -k family` — image → bgm 순서에서 `free` 1회, 같은 계열 연속이면 0회

- [x] **T4.C.2** — BGM 실행기
  - 파일: `src/aiassetstudio/jobs/runners.py`, `tests/test_runners.py`, `tests/fakes.py`
  - 내용:
    - `run_bgm_job(ctx, job)`. `params`: `brief`, `bpm`(40~200), `seconds`(30~240, 기본 90), `loop`(기본 True), `vocal`(기본 False), `lyrics`(vocal이면 필수), `keyscale`(기본 `"A minor"`), `count`(1~4, 기본 2), `seed`
    - 연주곡(`family="ace"`):
      - `tags = f"{brief}, instrumental, no vocals, video game background music"`
      - `lyrics`: 반복용이면 인트로·아웃트로 없는 구간 태그 `"[Main Theme]\n\n[Variation]\n\n[Main Theme - full]"`, 아니면 `"[Instrumental]"` (ACE-Step 문서 `docs/en/Tutorial.md`의 연주곡 규칙)
      - `language="unknown"`
    - 보컬 곡(`family="yue2"`): `style = brief`, 사용자 가사 그대로, `max_duration = seconds`
    - 후보마다: 제출 → `wait(bgm_timeout)` → 출력 오디오(`outputs[<출력 노드>]["audio"][0]`) 받기 → `raw.flac` → 무음 자르기 → 반복용이면 `make_loop` → `loop.wav`, `loop.ogg` / 아니면 `full.wav`, `full.ogg`
    - `make_loop`가 `ValueError`면(마디 부족) 반복 없이 `full.*`로 저장하고 `meta.loop_error`를 남긴다.
    - `meta`: `tags` 또는 `style`, `lyrics`, `bpm`, `keyscale`, `requested_s`, `raw_s`, `trimmed_s`, `loop: {start_s, end_s, bars, seam_ratio}`, `vocal`, 모델 파일명, `comfy_prompt_id`, `timings`
    - `tests/fakes.py`의 `FakeComfy`가 `SaveAudio` 출력과 `/view`에서 합성 FLAC(톤 + 끝 무음)을 돌려주게 넓힌다.
  - 검증: `uv run pytest tests/test_runners.py -k bgm` — 연주곡 2곡에서 `loop.wav`·`loop.ogg`·`raw.flac`, 보컬 곡에 가사 없으면 422 또는 실패, 마디 부족 시 `full.*`

### 작업 그룹 D: API, MCP, 갤러리

- [x] **T4.D.1** — API
  - 파일: `src/aiassetstudio/api/app.py`, `src/aiassetstudio/api/schemas.py`, `tests/test_api.py`
  - 내용:
    - `POST /api/jobs/bgm` 본문은 T4.C.2의 `params`와 같다 → 202 + `{"job_id"}`
    - 파일 이름 `raw`, `loop_wav`, `loop_ogg`, `full_wav`, `full_ogg`를 알맞은 미디어 타입(`audio/flac`, `audio/wav`, `audio/ogg`)으로 준다
    - BGM 에셋 내보내기는 WAV와 OGG를 둘 다 복사한다
  - 검증: `uv run pytest tests/test_api.py -k bgm`

- [x] **T4.D.2** — MCP `generate_bgm`
  - 파일: `src/aiassetstudio/mcp_bridge/tools.py`, `src/aiassetstudio/mcp_bridge/server.py`, `tests/test_mcp_tools.py`
  - 내용:
    - `generate_bgm(project, brief, bpm, seconds=90, loop=True, vocal=False, lyrics=None, keyscale=None, count=2, seed=None)` → 작업 id와 "90초 곡 하나에 약 30~40초(ACE-Step), 보컬 곡은 몇 분"이라는 안내
    - BGM 작업의 `get_job` 결과는 텍스트만: 곡마다 길이, BPM, 마디 수, 반복 구간, 파일 경로, 갤러리 링크
    - 도구 설명에 "You cannot hear audio. After generating BGM, ask the user to listen in the gallery and pick one."을 넣는다
  - 검증: `uv run pytest tests/test_mcp_tools.py -k bgm`

- [x] **T4.D.3** — 갤러리 오디오 카드
  - 파일: `web/src/components/AudioCard.tsx`, `web/src/components/JobGroup.tsx`, `web/src/components/DetailModal.tsx`
  - 내용:
    - `<audio controls loop>`로 `loop_ogg`(없으면 `full_ogg`)를 재생한다. 원본(`raw`)으로 바꿔 듣기.
    - "이음새 듣기" 버튼: 끝나기 3초 전으로 이동해 재생한다. 반복 지점을 바로 들어볼 수 있게 하려는 것이다.
    - BPM, 마디 수, 길이, 보컬 여부를 보여준다. 고르기·버리기·내보내기는 이미지 카드와 같다.
  - 검증: `npm --prefix web run build`

### 작업 그룹 E: 검증 도구와 실측

- [x] **T4.E.1** — 보컬 비율 측정 스크립트
  - 파일: `scripts/vocal_check.py`
  - 내용:
    - `<ComfyUI 경로>\user\yue2_tools\vocal_energy.py`를 옮기되, 분리한 음원 파일을 스크립트 옆이 아니라 `--out-dir`(기본: 임시 폴더)에 쓰게 바꾼다.
    - GPU를 쓰므로 시작할 때 ComfyUI `/free`를 표준 라이브러리 `urllib`로 직접 부른다(`--no-free`로 끌 수 있게). ComfyUI가 모델을 잡은 채로 Demucs를 돌리면 앞선 세션들처럼 메모리가 넘쳐 멈춘다. PowerShell에서 JSON 따옴표를 다루는 번거로움도 피한다.
    - 실행은 ai-toolkit 가상환경으로 한다: `<ai-toolkit 가상환경>\Scripts\python.exe scripts\vocal_check.py <곡 파일들>`
  - 검증: 2026-09-24 ACE-Step 테스트 곡(`<ComfyUI 경로>\output\aiassetstudio_test\ace_*.flac`)에서 보컬 비율 0~0.9%가 다시 나온다

- [x] **T4.E.2** — 실제 GPU 테스트
  - 파일: `tests/gpu/test_bgm_e2e.py`
  - 내용: `@pytest.mark.gpu`. 60초 연주곡 1곡(반복용)을 요청하고, `loop.wav` 길이가 마디 배수(±1 샘플)인지, `seam_ratio ≤ 1`인지 확인한다. 이어서 이미지 1장 → BGM 1곡 순서로 요청해 BGM 작업 `timings.free_before`가 true인지 확인한다.
  - 검증: `uv run pytest -m gpu -k bgm`

---

## ✅ Phase 4 Checkpoint

**구현 확인:**
- [x] 모든 작업 체크박스 완료
- [x] 연주곡이 반복용 WAV·OGG로 나오고, 마디 부족 같은 예외는 `full.*`로 대체된다
- [x] 보컬 곡 옵션이 동작한다
- [x] 이미지 ↔ 음악 계열이 바뀔 때 메모리를 비운다

**자동 검증:**
- [x] 전체 테스트: `uv run pytest`
- [x] 린트: `uv run ruff check .` 와 `uv run ruff format --check .`
- [x] 갤러리 빌드: `npm --prefix web run build`
- [x] GPU 테스트: `uv run pytest -m gpu -k bgm` (64초)

**수동 확인:**
- [x] Claude Code 세션에서 "demo 프로젝트에 아늑한 마을 BGM 2곡, 96 BPM, 90초로 만들어줘" → `generate_bgm` → 갤러리 링크 (MCP 클라이언트로 대신 확인: `smoke_mcp.py --bgm --vocal`, 임시 데이터)
- [ ] 갤러리에서 두 곡을 반복 재생하고 "이음새 듣기"로 반복 지점에서 딸깍 소리가 나지 않는지 확인 — **사람 귀가 필요하다.** 기능(반복 재생, 이음새 듣기가 끝 3초 전으로 이동해 이어 재생)은 브라우저로 확인했고, 수치로는 이음새 비율 0.0008~0.23(1 이하)이다
- [ ] `scripts/vocal_check.py`로 두 곡의 보컬 비율이 2% 미만인지 확인 — 첫 실행 0.0%·0.0%. 템포 보정 뒤 다시 만든 두 곡은 2.8%·0.8%. 2.8%의 보컬 트랙은 D5·A4 두 음을 떠는 순음(플루트로 보임)이라 노래와 다르지만, 기준 2%는 넘으므로 사람이 들어 확인할 것
- [x] 한국어 가사로 보컬 곡 1곡(YuE2) 생성 → 갤러리에서 재생 (46초 곡, 보컬 54.3%, 갤러리에서 재생됨)
- [x] 고른 곡을 내보내면 WAV와 OGG가 함께 복사된다

**완료 처리:**
1. 위 항목이 모두 통과하면 Claude Code는 사용자에게 완료한 작업, 자동 검증 결과, 청취 확인이 필요한 항목을 보고한다.
2. 사용자가 "Phase 4 완료"라고 승인하면 커밋하고, 로드맵의 **최종 완료 체크리스트**(LAST LIGHT 실전 테스트 포함)로 간다.
3. 체크포인트가 실패하면 실패 항목을 보고하고, 원인을 분석해 수정한 뒤 다시 검증한다.


## 구현 메모 (2026-09-25)

계획과 다르게 하거나 더한 것:
- **끝 무음 기준을 곡의 큰 소리 수준(창 dB의 90백분위)으로 바꿨다.** 계획은 중앙값 − 40dB였다. `[Instrumental]` 전투 테스트곡은 앞 8마디가 −40dB 근처라 중앙값이 −26.5dB로 내려가서, −65dB 끝 무음이 기준보다 1.5dB 높아 잘리지 않았다. 조용한 앞 마디 판정은 계획대로 중앙값 기준(최대 4마디)이다.
- **T4.B.2a 템포 보정을 했다.** 종단검증에서 96 BPM으로 요청한 마을 곡이 98.01 BPM(박자 오차 8ms)으로 나왔다. 96 BPM 32마디로 자르면 반복 지점이 박자에서 약 2.6박 어긋난다. `detect_tempo`는 librosa 박자 추적(요청 템포 근처, tightness 400)과 직선 맞춤을 쓴다. 박자 오차 rms가 20ms 이하이고 요청과 10% 안일 때만 그 템포로 마디를 자르고, 아니면 요청 템포를 쓴다. 다시 만든 곡은 95.01 BPM으로 검출돼 그 템포 32마디로 잘렸다(ai-toolkit의 별도 librosa로 95.00 BPM 확인). 타악기가 약한 곡은 오차가 94ms라 요청 템포를 썼다. 계획대로 librosa 의존성은 이때 더했다(numba 포함). 첫 호출은 numba 컴파일에 약 11초가 걸리고 이후 곡당 0.35초다. `meta.tempo {requested, detected}`, `meta.loop.bpm`(반올림하지 않은 실제 자른 템포)을 남긴다.
- **YuE2 스타일에 템포를 붙인다**(`"{brief}, {bpm} BPM"`). YuE2에는 템포 입력이 없고, 원본 스크립트도 스타일 문장에 BPM을 넣었다.
- **OGG 인코딩이 실패해도 WAV는 남긴다**(`meta.ogg_error`). 곡 하나에 GPU로 30초 이상 들었기 때문이다. ffmpeg는 `CREATE_NO_WINDOW`로 띄운다. 창 없이 도는 백엔드에서 콘솔 창이 뜨지 않게 하려는 것이다. 설정은 `AIAS_FFMPEG`다.
- **내보내기는 WAV·OGG에 같은 이름을 쓴다.** 둘 중 하나만 이름이 겹쳐도 둘 다 `_2`가 된다(`unique_stem`).
- 파일은 알맞은 미디어 타입(`audio/flac`, `audio/wav`, `audio/ogg`)으로 준다. Windows의 mimetypes는 `.flac`을 모를 수 있다.
- 계열 전환 `free`는 ComfyUI가 켜진 뒤, 실행기 제한 시간 밖에서 한다. `timings.free_before`는 실행기가 자기 timings를 쓴 뒤 대기열이 합친다(실행기가 덮어쓰지 않게). `/free`가 실패해도 작업은 계속한다.
- 갤러리: 곡 카드는 두 칸 너비의 재생기다(반복본/원본 전환, "이음새 듣기"). 상세에는 템포(검출값과 요청값), 마디·반복 구간·이음새 비율, 길이 흐름, 태그(보컬 곡은 스타일과 가사)를 보여준다. 종류 필터에 BGM을 더했다. BGM 작업의 제목·종류가 "(설명 없음)"·"bgm"으로 나오던 것을 확인하고 고쳤다.
- MCP `get_job`은 곡마다 반복 구간·마디·템포(요청과 다르면 둘 다)·파일 링크를 글로 주고, "들을 수 없으니 사용자에게 갤러리에서 듣고 고르게 하라"는 문장을 붙인다.

실측 (2026-09-25):
- GPU 테스트(`-m gpu -k bgm`, 64초): 60초 전투곡은 20초 안팎에 생성됐다. 100.003 BPM으로 검출돼 23마디 루프가 됐고, 이음새 비율은 0.005였다. 이미지 → 음악 순서에서 `free_before`가 기록됐다.
- 종단검증(`AIAS_PORT=8766`, 임시 데이터로 `smoke_mcp.py --bgm --vocal`): 90초 마을 곡 2곡 × 3회가 곡당 25~29초에 생성됐고, 후처리는 1.4~5.2초였다. 루프는 32~35마디, 이음새 비율은 0.0008~0.23이다. 내보내기는 WAV·OGG 한 쌍이고 길이는 마디 배수(±1샘플)다. 한국어 가사 YuE2 곡은 46.2초 곡이 20초에 나왔다(계열 전환 free 포함).
- 보컬 비율(`vocal_check.py`): 2026-09-24 테스트곡에서 0~0.9%를 다시 냈다. 마을 곡은 0.0%, 0.0%, 2.8%, 0.8%, 한국어 발라드는 54.3%다. 2.8% 곡의 보컬 트랙은 D5·A4를 흔들림 없이 내는 순음(평탄도 0.0000)이었다. 발라드 목소리(약 300Hz, 숨소리, 넓은 음정 변화)와 달라 플루트가 보컬 트랙으로 새어 든 것으로 보인다.

남은 것(사람 확인 필요):
- 반복 지점의 딸깍 소리와 음악적 자연스러움은 들어 봐야 안다.
- 2.8% 곡이 정말 노래가 섞이지 않았는지 들어 볼 것.

---

## 참고 자료

- 로드맵: [`aiassetstudio-roadmap.md`](./aiassetstudio-roadmap.md)
- ACE-Step 실측 스크립트: `spikes/acestep_bgm_test.py` (4곡, 90초 곡당 32~36초, 보컬 비율 0~0.9%)
- YuE2 그래프 원본: `<ComfyUI 경로>\user\yue2_tools\yue2_run.py`
- ACE-Step 1.5 연주곡 규칙: https://github.com/ace-step/ACE-Step-1.5 의 `docs/en/Tutorial.md`, `docs/en/INFERENCE.md` (가사 칸 `[Instrumental]`, 언어 `unknown`)
- ACE-Step 노드 코드: `<ComfyUI 경로>\comfy_extras\nodes_ace.py`, YuE2 노드: `comfy_extras\nodes_yue2.py`

## 메모 / 주의

- Whisper로 보컬 여부를 판정하지 않는다. 음악에서 "Thank you", "you" 같은 문장을 지어내는 오인식이 흔하다(2026-09-24 확인). 보컬 판정은 HDemucs 보컬 비율로 한다.
- YuE2 보컬 곡은 첫 로딩 포함 수 분이 걸린다(73초 곡에 204초). `bgm_timeout` 600초 안에 들어오지만, 긴 곡을 요청하면 늘려야 할 수 있다.
- ACE-Step과 YuE2의 결과에는 기존 곡과 닮은 부분이 있을 수 있다. 라이선스가 그 권리 문제까지 보장하지는 않는다.

---
_다음: 로드맵의 최종 완료 체크리스트 (LAST LIGHT 실전 테스트) → [`aiassetstudio-roadmap.md`](./aiassetstudio-roadmap.md)_
