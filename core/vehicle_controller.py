import os

import traci

from hardware_twin import is_hardware_twin

# adaptTraveltime()으로 건 페널티가 findRoute/rerouteTraveltime의 경로 재계산에
# 실제로 반영되려면 (begin, end) 구간이 충분히 길어야 한다 - 실측 결과 2~10초는
# SUMO 라우터가 무시하고 원래 경로를 그대로 반환했고, 20초부터 안정적으로 회피
# 경로를 찾았다(2026-08-10 확인). decide_actions가 명령에 담아 보내는 duration(SLOW
# 감속 지속시간 등 다른 의미)과는 별개로, "우회 계산 한 번을 성립시키는 데 필요한
# 최소 페널티 유지시간"이라 명령의 duration과 무관하게 이 값을 쓴다.
REROUTE_PENALTY_WINDOW = 30.0  # s

# "사고가 풀릴 때까지 기다리는 게 더 빠르면 원래 경로 유지" 판단 켜기/끄기 - 효과 비교 측정용(SUMO_KEEP_ROUTE=0이면 끔)
KEEP_ROUTE_IF_WAITING_FASTER = os.environ.get("SUMO_KEEP_ROUTE", "1") != "0"

# 우회 결과 기록 - 대시보드가 사고 추적 목록에 "우회했는지/원래 경로를 유지했는지"와 두 예상 도착을 보여준다.
# execute_commands()가 부를 때마다 새로 채운다: veh_id -> {"rerouted", "eta_wait", "eta_detour", "avoid_edge"}
last_reroute_outcomes = {}
# 예상 도착 계산 때 도로 하나의 통행시간 상한(s). 차가 멈춰 선 도로는 SUMO 추정 통행시간이 길이/거의 0 속도라
# 수만 초로 튄다(2026-09-29 실측 35,920초) - 그 값 하나로 비교·표시가 망가지지 않게 자른다.
MAX_EDGE_TRAVELTIME = 300.0
# 같은 사고에 대해 "원래 경로 유지"로 판단한 차 - 매 스텝 같은 차를 다시 계산하지 않게(사고가 끝날 때까지)
_kept_until = {}  # (veh_id, avoid_edge) -> 사고가 풀리는 시각


def execute_commands(commands):
    """central_server.py가 반환한 명령 dict를 traci 호출로 변환·실행만 한다.

    판단 로직은 일절 포함하지 않는다 — central_server.py의 출력을 그대로 실행하는
    얇은 레이어로 유지해야 "GPS 기반 1차 최적화 + CCTV 재계산"이라는 핵심 주장이
    코드상으로도 분리되어 드러난다. (예외: 우회는 실제로 경로를 계산해 봐야 득실을 알 수 있어서,
    "사고가 풀릴 때까지 기다리는 게 더 빠르면 원래 경로 유지" 비교만 여기서 한다 - _reroute_around.)
    """
    last_reroute_outcomes.clear()
    live_ids = set(traci.vehicle.getIDList())
    now = traci.simulation.getTime()
    for key, until in list(_kept_until.items()):
        if now >= until or key[0] not in live_ids:
            del _kept_until[key]
    for cmd in commands:
        veh_id = cmd["veh_id"]
        if veh_id not in live_ids or is_hardware_twin(veh_id):
            continue  # 실물 차량을 따라 그리는 차는 차량 호스트가 판단한다 - SUMO가 명령하지 않음
        action = cmd["action"]
        if action == "decelerate":
            traci.vehicle.slowDown(veh_id, cmd["target_speed"], duration=cmd.get("duration", 2.0))
        elif action == "stop":
            traci.vehicle.slowDown(veh_id, cmd.get("target_speed", 0.0), duration=cmd.get("duration", 2.0))
        elif action == "reroute":
            if (veh_id, cmd["avoid_edge"]) in _kept_until:
                continue  # 이미 "기다리는 게 빠름"으로 판단한 차 - 사고가 풀릴 때까지 다시 계산 안 함
            _reroute_around(veh_id, cmd["avoid_edge"], cmd.get("hazard_until"))


def edge_traveltime(edge_id):
    return min(traci.edge.getTraveltime(edge_id), MAX_EDGE_TRAVELTIME)


def eta_waiting_at(veh_id, hazard_edge, hazard_until, current_time):
    """원래 경로 그대로 위험 도로까지 가서, 위험이 풀릴 때까지 멈춰 기다린 뒤 나머지를 가면 도착하는 예상 시각.
    위험 도로 자체는 멈춘 차 때문에 실측 통행시간이 부풀어 있어 제한속도 기준 통행시간을 쓴다.
    (대시보드 사고 추적 목록의 "전" 값과 같은 계산.) 위험 도로가 남은 경로에 없으면 None."""
    route = traci.vehicle.getRoute(veh_id)
    rest = route[traci.vehicle.getRouteIndex(veh_id):]
    if hazard_edge not in rest or hazard_until is None:
        return None
    k = rest.index(hazard_edge)
    t_reach = current_time + sum(edge_traveltime(e) for e in rest[:k])
    lane = f"{hazard_edge}_{traci.edge.getLaneNumber(hazard_edge) - 1}"  # _0은 보도일 수 있어 가장 안쪽 차선
    free_flow = traci.lane.getLength(lane) / max(traci.lane.getMaxSpeed(lane), 0.1)
    t_after = sum(edge_traveltime(e) for e in rest[k + 1:])
    return max(t_reach, hazard_until) + free_flow + t_after


def eta_on_current_route(veh_id, current_time):
    route = traci.vehicle.getRoute(veh_id)
    return current_time + sum(edge_traveltime(e) for e in route[traci.vehicle.getRouteIndex(veh_id):])


def _reroute_around(veh_id, avoid_edge, hazard_until=None):
    """avoid_edge를 일시적으로 통행시간이 매우 큰 것처럼 취급해 SUMO의 표준
    incident-avoidance 기법(효율 페널티 + rerouteTraveltime)으로 우회 경로를 계산한다.
    수동으로 대체 경로를 탐색하지 않고 SUMO 라우팅 엔진에 맡기는 것이, 네트워크
    전역 어디서든 동작하고 유지보수가 쉬운 표준 방식이다.

    hazard_until(위험이 풀리는 시각)을 알면, 찾은 우회 경로의 예상 도착이 "원래 경로로 가서 풀릴 때까지
    기다리는 것"보다 빠르지 않을 때 원래 경로로 되돌린다(2026-09-29 - 30초짜리 사고에 간선도로에서
    골목으로 빠져 90초씩 늦어지는 차가 있었다).
    """
    now = traci.simulation.getTime()
    old_rest = None
    eta_wait = None
    if hazard_until is not None:
        route = traci.vehicle.getRoute(veh_id)
        old_rest = list(route[traci.vehicle.getRouteIndex(veh_id):])
        eta_wait = eta_waiting_at(veh_id, avoid_edge, hazard_until, now)
    traci.edge.adaptTraveltime(avoid_edge, 1e6, begin=now, end=now + REROUTE_PENALTY_WINDOW)
    traci.vehicle.rerouteTraveltime(veh_id)
    eta_detour = eta_on_current_route(veh_id, now)
    rerouted = True
    if KEEP_ROUTE_IF_WAITING_FASTER and eta_wait is not None and eta_detour >= eta_wait and old_rest:
        try:
            traci.vehicle.setRoute(veh_id, old_rest)  # 기다리는 게 빠르거나 같음 - 원래 경로 유지
            rerouted = False
            _kept_until[(veh_id, avoid_edge)] = hazard_until
        except traci.exceptions.TraCIException:
            pass  # 이미 다음 도로로 넘어가는 중 등 - 우회 경로를 그대로 둔다
    last_reroute_outcomes[veh_id] = {"rerouted": rerouted, "eta_wait": eta_wait, "eta_detour": eta_detour,
                                     "avoid_edge": avoid_edge}
