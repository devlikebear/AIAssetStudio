# 공식 Turbo로 Viggle 대체 시험 (T1.A.3, 2026-11-01)

스크립트: `spikes/studio/official_turbo.py`. 파일은 `Comfy-Org/Qwen-Image-2.1`의 `diffusion_models/qwen_image_2.1_turbo_int8_convrot.safetensors`(7,256,787,829바이트, sha256 `8144a0182964aa8403ad6dbc011db837304167d235161b9aabaa8532e967314c`). ComfyUI 0.37.0을 그대로 썼고 커스텀 노드는 쓰지 않았다. `QwenImage21Cache`, `ManualSigmas`, `er_sde`, `linear_quadratic`은 모두 기본 제공이다.

T1.A.2와 같은 프롬프트, 참조 3장, 시드, 1184×880으로 비교했다.

| 구성 | 그리기 | 판단 |
|---|---|---|
| Viggle Turbo 6스텝 | 약 20초 | 기준 |
| 공식 Turbo, `ManualSigmas` + euler, 8스텝 | 13.3~16.2초 | 인물, 장소, 화풍 동등 |
| 공식 Turbo, `linear_quadratic` + `er_sde`, 8스텝 | 13.3초 | 동등, 구도 변화가 조금 더 큼 |

- 시그마는 공개된 값 `1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0`을 썼다. 모델 카드는 일정이 체크포인트에 저장돼 있다고 하며, 값 자체는 제3자 문서 기준이다.
- 결과가 안정적이고 값이 고정된 `ManualSigmas` + euler를 쓴다.
- 작업 후 VRAM 여유 7.25GB, RAM 여유 약 9GB.
- 투명 출력도 된다. RGBA 프롬프트로 스프라이트 2종을 만들었고 배경이 깨끗했다. 픽셀아트와 참조 이미지 경로의 회귀 시험은 하지 않았다.

## 결정

규칙 1번을 택한다. 책의 그림은 공식 Turbo로 만든다(`qwen_book_page`, 계열 `qwen_turbo`). 라이선스는 여전히 Qwen Research로 연구·평가 목적이다. 달라지는 점은 라이선스 미확인 LoRA와 커스텀 노드가 빠진다는 것이다.

기존 스프라이트와 아이콘 경로는 그대로 둔다. 새 PC 설치에는 이 경로도 Turbo로 옮겨야 하므로 Phase 3에 넣는다.
