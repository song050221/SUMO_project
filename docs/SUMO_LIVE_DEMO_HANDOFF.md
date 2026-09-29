> **2026-09-28: 이 문서가 설명하는 `scripts/live_demo_controller.py`와 `configs/live_demo_config.json`은 삭제됨.**
> 하드웨어 팀이 연동을 차량 → SUMO 한 방향으로 정해서(판단은 차량이 함) SUMO가 판단을 보낼 일이 없어졌다.
> 지금의 실물 연동은 `core/hardware_twin.py`(신양초 사거리에 그리기만 함) - `docs/HANDOFF_PROMPT.md` R번 참고.
> 이 문서는 기록용으로만 남긴다.

# SUMO 담당자 인계 문서 — 실차 시연 연동

`SUMO_YOLO_하드웨어_호환성_및_담당자별_작업분담.docx` 2-1절(SUMO 담당자가 해야 할 일)의
산출물을 정리한 문서. YOLO/하드웨어 담당자가 자신의 파일을 만들 때 참고할 고정 계약이다.

## 1. hazards / traffic_state 스키마 (YOLO·비전 담당자가 채워야 하는 입력)

`live_demo_controller.py`가 9002 포트에서 받는 `traffic_state` JSON:

```json
{
  "coordinate_space": "world",
  "vehicles": [
    {"vehicle_id": "car_1", "visible": true, "x": 1.2, "y": 0.8}
  ],
  "hazards": [
    {
      "hazard_id": "h-42",
      "class_name": "person",
      "hazard_type": "person",
      "confidence": 0.87,
      "active": true,
      "x": 1.4,
      "y": 0.9,
      "bbox": [100, 120, 40, 60]
    }
  ]
}
```

**필수 필드**
- `coordinate_space`: `"world"` 또는 `"image"`. `live_demo_config.json`의 값과 다르면 그
  프레임 전체를 무시한다(좌표 단위 혼용 방지).
- `vehicles[].vehicle_id`: 중복 불가. 없거나 중복이면 프레임 전체를 거부한다
  (`validate_traffic_state`).
- `hazards[].x`, `y`: 숫자(NaN/Inf 불가)가 아니면 그 hazard만 조용히 제외하고 나머지는
  정상 처리한다. 문자열이 와도 어댑터가 죽지 않는다(`_is_valid_point`로 검증).
- `hazards[].active`: `false`면 무시.

## 2. class_name / hazard_type → SUMO 이벤트 매핑

`live_demo_controller.py`의 `HAZARD_TYPE_EVENT_MAP`:

| class_name / hazard_type | SUMO 이벤트 | 차량 반응 |
|---|---|---|
| `person`, `pedestrian` | `pedestrian_detected` | 위험 지점 위 차량 STOP, 주변 차량 SLOW |
| `hazard_led_candidate` | `pedestrian_detected` | (현재 vision 기본 출력과의 하위 호환) |
| `obstacle`, `vehicle_stall` | `obstacle_detected` | 위험 지점 위 차량 STOP, 주변 차량 SLOW |
| 그 외/미지정 | `pedestrian_detected` (기본값) | 보수적으로 최우선 이벤트로 처리 |

YOLO 쪽에서 새 클래스를 추가하면 `live_demo_controller.py`의 `HAZARD_TYPE_EVENT_MAP`과 이
표를 함께 갱신할 것. `congestion_detected`(SUMO 배치 시뮬레이션 전용, 정체 감지)는 STOP을
발생시키지 않고 SLOW만 발생시킨다 — 하드웨어 시연에서는 쓰이지 않는다.

## 3. decisions 스키마 (SUMO → 차량, 9001 포트로 송신)

**2026-09-26부터 기준 문서는 차량 쪽 저장소 `invuc02/capstone-sumo-bridge`의
`INTERFACE.md` "decisions 메시지" 절이다.** 이 절은 요약이다.

```json
{
  "type": "decisions",
  "timestamp_ms": 1790347817958,
  "decisions": [
    {"vehicle_id": "car_2", "action": "STOP", "decision_id": "car_2-stop-12",
     "ttl_ms": 500, "reason": "pedestrian_detected", "target_speed_mps": 0.0},
    {"vehicle_id": "car_3", "action": "REROUTE", "decision_id": "car_3-reroute-13",
     "ttl_ms": 500, "reason": "pedestrian_detected", "route_id": "divert_to_B_x710"}
  ]
}
```

- **마커가 보이는 차량마다 매 주기 판단이 하나씩 들어간다.** 위험이 없으면 `FOLLOW_PATH`.
  마커를 놓친 차(`visible: false`)에는 보내지 않는다 — `ttl_ms`가 지나면 차량은 자체
  판단으로 돌아간다(정지 아님).
- **경로 좌표(`path`)는 보내지 않는다.** 차량이 경로를 이름으로 관리하고 궤적도 직접
  맡는다. 재경로는 차량 쪽 경로 이름(`route_id`)으로만 지시한다.
- `target_speed_mps`는 `SLOW`/`STOP`에만, `route_id`는 `REROUTE`에만 있다.
- `action` 우선순위는 STOP > REROUTE > SLOW (`decision_policy.py`, 한 차량에 하나만 배정).
  차량은 자기 로컬 판단과 SUMO 판단 중 더 보수적인 쪽을 따른다.
- 예전(2026-08) 형식은 `path`/`coordinate_space`를 실어 보냈고 `configs/demo_routes.json`에서
  경로 좌표를 읽었다. 차량 쪽이 이름 기반 경로를 갖게 되면서 폐기했다(파일도 삭제).

## 4. 우회(REROUTE) 판단 규칙 — 실물 보드 전용

`live_demo_controller._can_reroute()`. 보행자는 A 도로(x=0.30)에 선다. 다음을 모두
만족하는 차에 `reroute_route_id`(기본 `divert_to_B_x710`)로 우회를 지시한다.

- 목적지(`destination_zone`)가 A 쪽(`reroute_destination_prefix`, 기본 `"A"`)
- 위험물이 차 앞(서쪽, x가 더 작음)에 있음
- 차가 아직 B 도로 동쪽(`x >= reroute_min_x`, 기본 0.90)이라 B로 꺾을 수 있음
- 이미 우회 경로(`route_id`가 `divert_`로 시작)가 아님
- 즉시 정지 반경 안이 아님 (그 안이면 STOP이 우선)

`reroute_route_id`가 설정에 없으면 REROUTE는 나가지 않는다. 차량 쪽 샘플
`samples/02_pedestrian_stop.json` 상황에서 선행 STOP, 후행 REROUTE가 나오는 것을 확인했다.

## 5. live_demo_config.json — 좌표계 / danger zone / proximity / 우회 기준

`configs/live_demo_config.json` (실물 보드 기준, 2026-09-26):

```json
{
  "coordinate_space": "world",
  "danger_zone": [0.0, 0.0, 1.34, 0.91],
  "proximity_world": 0.4,
  "proximity_px": 150.0,
  "stop_proximity_ratio": 0.4,
  "hazard_hold_ms": 2000,
  "decision_ttl_ms": 500,
  "reroute_route_id": "divert_to_B_x710",
  "reroute_min_x": 0.90,
  "reroute_destination_prefix": "A"
}
```

- 좌표는 보드 남서쪽 모서리 원점의 미터 단위다(9/25 보드 변경 후 x 0~1.34, y 0~0.91).
- `danger_zone`은 보드 전체다. 보드 위 보행자는 전부 관련이 있고, 어느 차가 반응할지는
  proximity가 정한다. 예전 값 `[0,0,0,0]`은 자리표시였고, 이 때문에 보행자에 전혀
  반응하지 않았다.
- `coordinate_space`가 `"world"`면 `proximity_world`(미터)를, `"image"`면
  `proximity_px`(픽셀)를 쓴다. 단위를 섞어 쓰면 즉시 로더가 예외를 던진다(fail-fast).
- `stop_proximity_ratio`: `proximity_* × 이 값`이 STOP 반경, 나머지가 SLOW 반경이다
  (0.4 → 보행자 0.16m 이내 STOP, 0.4m 이내 SLOW).
- `hazard_hold_ms`와 `decision_ttl_ms`는 서로 다른 개념이다 — 아래 6번 참고.

## 6. 위험 감지 → SLOW 해제 타임라인 (hold vs TTL)

```
t=0.0s   카메라가 위험을 감지 → decide_actions()가 SLOW/STOP 판단, hold_state[veh]=0.0 기록
t=0.1s   카메라가 잠깐 놓침(프레임 끊김) → 이번 판단에는 위험이 없지만
         (now - hold_state[veh]) = 0.1s < hazard_hold_ms(2.0s) → 계속 SLOW 유지
t=0.5s   카메라가 다시 위험 감지 → hold_state[veh]=0.5로 갱신, 계속 SLOW
t=2.5s   마지막 감지(0.5s) 이후 2.0s 경과 → hold 종료, FOLLOW_PATH로 복귀
```

각 판단 패킷의 `ttl_ms`(기본 500ms)는 통신 유효시간일 뿐이다 — vision 쪽이 그 시간 안에
다음 판단을 못 받으면 정지하는 것과 별개로, SUMO 쪽 SLOW/STOP "의도"는 `hazard_hold_ms`
동안 유지된다. 500ms마다 최신 판단이 오더라도 그 판단의 reason이 `hazard_hold`(감지가
끊겼지만 hold 중)인지 원래 이벤트 타입인지로 구분할 수 있다.

## 7. 차량 ID 정책

`live_demo_controller.py`는 `traffic_state["vehicles"][].vehicle_id`를 그대로
`decisions[].vehicle_id`로 돌려준다 — SUMO 내부 숫자 ID와의 매핑이 필요 없다. 실차
시연에서는 카메라가 이미 `car_1`/`car_2`/`car_3` 같은 문자열 ID로 차량을 식별하기
때문이다. **`vehicle_id_map.json`은 만들지 않는다** — SUMO 배치 시뮬레이션(TraCI 숫자
ID)과 실차 ID를 직접 연결해야 하는 상황이 생기기 전까지는 불필요하다.

## 8. 네트워크 구성 (동일 PC / 서로 다른 PC)

- **같은 PC에서 실행**: 기본값(`127.0.0.1`) 그대로 사용.
  ```
  python live_demo_controller.py
  ```
- **다른 PC에서 실행** (예: 비전 프로그램은 카메라가 연결된 노트북, SUMO 어댑터는 다른 PC):
  ```
  python live_demo_controller.py --state-host 0.0.0.0 --decision-host <상대 PC의 LAN IP>
  ```
  수신은 `0.0.0.0`으로 모든 인터페이스에 바인드하고, 송신은 상대 PC의 실제 LAN IP를
  지정한다. Windows 방화벽에서 UDP 9001/9002(또는 커스텀 포트)를 허용해야 한다.

## 9. 테스트 실행 명령

```
python test_decision_policy.py        # STOP/REROUTE/SLOW 우선순위 판단 로직 (TraCI 불필요)
python test_live_demo_controller.py   # FOLLOW_PATH 기본 발행, hold, 좌표계 검증, 이벤트 매핑
python test_udp_integration.py        # 실제 UDP 9002->9001 왕복 (어댑터를 서브프로세스로 실행)
```

세 파일 모두 pytest 없이 `python <파일명>`으로 바로 실행 가능하다. 마지막 통합 테스트
결과: 정상 상태(FOLLOW_PATH), 위험 상태(STOP), 깨진 JSON, 비정상 좌표(문자열/NaN)를 모두
검증 — 잘못된 payload 이후에도 어댑터가 살아남아 다음 정상 payload에 응답하는 것까지
확인됨(2026-07-29 기준 전체 통과).

## 범위 밖 (다른 담당자 몫)

- `vision/vehicle_fleet.json`, `vision/camera_homography.json`, 차량별 PWM/조향 보정,
  `firmware/include/secrets.h` — 하드웨어/임베디드 담당자
- `vision/yolo/yolo_detector.py`, YOLO 데이터셋/학습/`best.pt` — YOLO 담당자
- `vision/central_fleet_controller.py`의 `VehicleRoute` 순환 처리, SLOW 시 경로 적재 —
  하드웨어/YOLO 담당자 코드베이스(비전 쪽)
