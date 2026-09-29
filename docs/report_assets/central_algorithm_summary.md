# 중앙 제어 알고리즘 — 핵심 메커니즘

## 1. 위험 판단 우선순위 (`decision_policy.py`)

CCTV(또는 하드웨어의 YOLO 카메라)가 감지한 위험을 받아 **STOP > REROUTE > SLOW** 순으로
차량마다 명령을 하나씩 배정한다.

```python
STOP_ELIGIBLE_TYPES = {"pedestrian_detected", "obstacle_detected", "accident_detected"}

def decide_actions(alerts):
    commands, assigned = [], set()
    for alert in alerts:
        if alert["type"] in STOP_ELIGIBLE_TYPES:
            assign(alert["vehicles_in_hazard_edge"], "stop", assigned, commands)      # 위험 위 즉시 정지
        assign(alert["vehicles_reroutable"], "reroute", assigned, commands)           # 아직 안 지남 → 우회
        assign(alert["vehicles_nearby"], "decelerate", assigned, commands)            # 근처 → 예방 감속
    return commands
```
*(`assign()`은 설명을 위해 반복되는 배정 로직을 한 줄로 압축한 것 — 실제 코드는
`core/decision_policy.py`에 있는 대로 각 분기가 풀어져 있음)*

**핵심 설계**: 이 함수는 TraCI를 호출하지 않는다. 그래서 SUMO 시뮬레이션과 실차
하드웨어(SUMO 미설치 PC)가 감지 방식은 서로 달라도 "위험에 어떻게 반응할지"는 완전히
같은 코드를 공유한다.

## 2. 감지 → 판단 → 실행

```
CCTV 감지(cctv_detector.py) → decide_actions() → 차량 제어(vehicle_controller.py)
```

REROUTE는 위험 edge의 통행시간을 인위적으로 키운 뒤 SUMO 라우터에게 다시 최단경로를
계산시키는 표준 incident-avoidance 방식이다(대체 경로를 직접 탐색하지 않아 네트워크
어디서든 그대로 동작).

## 3. 상시 최적화 (SUMO 전용 확장)

돌발 상황이 없어도 항상 도는 계층 — 하드웨어 시연에는 아직 미적용.

| 모듈 | 하는 일 |
|---|---|
| `central_server.py` | 출발 시 + 주행 중 60초마다 실시간 조건으로 경로 재계산 |
| `signal_controller.py` | 교차로 대기열을 방향별로 비교해 신호 시간을 수요 비례로 배분 |
| `predictive_reroute.py` | 혼잡 예상 지점을 미리 계산, 여유 있는 차량만 선제 우회 |
