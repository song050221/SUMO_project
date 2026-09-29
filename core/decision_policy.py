"""TraCI 유무와 무관하게 재사용 가능한 위험 판단 정책.

CCTV/카메라가 감지한 위험(alert)을 받아 차량별 행동(stop/decelerate/reroute)을
결정한다. TraCI를 직접 호출하지 않는다 - 원래 SUMO 시뮬레이션(central_server.py)과
실차 시연(live_demo_controller.py) 양쪽에서 공유하려던 것인데, 2026-09-26 하드웨어 팀이
연동을 차량 → SUMO 한 방향으로 정해(판단은 차량이 함) live_demo_controller.py는 2026-09-28에
삭제됐다. 지금은 central_server.py만 쓴다. 어떤 차량이 "위험 지점 위/구역 내/우회 가능"에
해당하는지 분류하는 일(TraCI 좌표 계산이 필요한 부분)은 호출자(cctv_detector.py)의 몫이다.
"""

PREVENTIVE_SLOWDOWN_SPEED = 5.0       # m/s, SLOW 목표 속도
PREVENTIVE_SLOWDOWN_DURATION = 2.0    # s, SLOW/STOP/REROUTE 페널티 유지 시간
STOP_SPEED = 0.0

# 위험 edge 위 차량을 즉시 정지시켜야 하는 이벤트 종류. 정체(congestion_detected)는
# 멈출 이유가 없는 반면, 보행자·장애물·사고는 물리적으로 진로를 막고 있어 STOP 대상이다.
STOP_ELIGIBLE_TYPES = {"pedestrian_detected", "obstacle_detected", "accident_detected"}


def decide_actions(alerts):
    """alert 목록을 받아 차량별 명령 리스트를 만든다.

    각 alert는 다음 필드를 포함해야 한다:
      - type: "pedestrian_detected" | "congestion_detected" | "accident_detected" | "obstacle_detected"
      - edge: 위험이 감지된 edge (reroute 시 회피 대상)
      - vehicles_in_hazard_edge: 위험 지점 위에 있는 차량 (pedestrian_detected일 때만 즉시 정지)
      - vehicles_nearby: 위험 구역 내에서 감속해야 하는 차량
      - vehicles_reroutable: hazard edge를 아직 지나지 않아 우회가 유효한 차량

    한 차량에는 하나의 명령만 배정하며, STOP > REROUTE > SLOW 순으로 우선한다
    (즉시 정지가 필요한 차량은 우회를 계산할 여유가 없다고 본다).
    """
    commands = []
    assigned = set()

    for alert in alerts:
        reason = alert["type"]
        hazard_edge = alert.get("edge")
        on_hazard_edge = list(alert.get("vehicles_in_hazard_edge", []))
        nearby = list(alert.get("vehicles_nearby", []))
        reroutable = list(alert.get("vehicles_reroutable", []))

        if reason in STOP_ELIGIBLE_TYPES:
            for veh_id in on_hazard_edge:
                if veh_id in assigned:
                    continue
                commands.append({
                    "veh_id": veh_id,
                    "action": "stop",
                    "target_speed": STOP_SPEED,
                    "duration": PREVENTIVE_SLOWDOWN_DURATION,
                    "reason": reason,
                    "hazard_edge": hazard_edge,  # 어느 위험 때문인지 - 대시보드 사고 추적 목록용
                })
                assigned.add(veh_id)
        else:
            # 정체 등 STOP 대상이 아닌 이벤트는 hazard edge 위 차량도 감속 버킷으로 합류시킨다.
            nearby = on_hazard_edge + nearby

        for veh_id in reroutable:
            if veh_id in assigned:
                continue
            commands.append({
                "veh_id": veh_id,
                "action": "reroute",
                "avoid_edge": hazard_edge,
                "duration": PREVENTIVE_SLOWDOWN_DURATION,
                "reason": reason,
                "hazard_edge": hazard_edge,
                # 위험이 풀리는 시각(사고만 있음) - 있으면 실행 쪽이 "기다리는 게 더 빠르면 원래 경로 유지"를 판단
                "hazard_until": alert.get("hazard_until"),
            })
            assigned.add(veh_id)

        for veh_id in nearby:
            if veh_id in assigned:
                continue
            commands.append({
                "veh_id": veh_id,
                "action": "decelerate",
                "target_speed": PREVENTIVE_SLOWDOWN_SPEED,
                "duration": PREVENTIVE_SLOWDOWN_DURATION,
                "reason": reason,
                "hazard_edge": hazard_edge,
            })
            assigned.add(veh_id)

    return commands
