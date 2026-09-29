> **2026-09-28: 이 문서가 설명하는 `scripts/live_demo_controller.py`와 `configs/live_demo_config.json`은 삭제됨.**
> 하드웨어 팀이 연동을 차량 → SUMO 한 방향으로 정해서(판단은 차량이 함) SUMO가 판단을 보낼 일이 없어졌다.
> 지금의 실물 연동은 `core/hardware_twin.py`(신양초 사거리에 그리기만 함) - `docs/HANDOFF_PROMPT.md` R번 참고.
> 이 문서는 기록용으로만 남긴다.

# 하드웨어 팀 좌표 실측 요청 — 해결됨 (2026-09-26)

2026-09-09에 하드웨어 팀에 요청했던 세 가지는 차량 쪽 저장소
`invuc02/capstone-sumo-bridge` 가 생기면서 모두 해결됐다.

| 요청했던 것 | 어떻게 해결됐나 |
| --- | --- |
| `configs/demo_routes.json` 경로 좌표 | 필요 없어짐. 차량이 경로를 이름(`lead_C_to_A`, `divert_to_B_x710` 등)으로 관리하고, SUMO는 재경로를 그 이름으로만 지시한다. 파일은 삭제함 |
| `configs/live_demo_config.json` 의 `danger_zone` | 차량 쪽 `INTERFACE.md` 의 보드 좌표(원점 남서쪽 모서리, x 0~1.34m, y 0~0.91m)로 보드 전체 `[0, 0, 1.34, 0.91]` 를 넣음 |
| `camera_homography.json` | 차량 쪽에서 기준 마커 4개로 변환해 `coordinate_space: "world"` (미터) 로 보내고 있다 |

지금 기준 문서:

- 주고받는 메시지 규격: `capstone-sumo-bridge/INTERFACE.md` (traffic_state, decisions 둘 다)
- SUMO 쪽 구현 요약과 설정값 설명: `docs/SUMO_LIVE_DEMO_HANDOFF.md` 3~5절
- 하드웨어 없이 확인: `capstone-sumo-bridge` 의 `replay.py` 를 띄운 상태에서
  `python scripts/live_demo_controller.py` 를 실행하면 샘플 여섯 장면에 대한 판단이 9001로 나간다
