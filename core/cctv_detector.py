"""차량 통행량이 많은 대표 교차로 8~10곳을 독립적인 CCTV 구역으로 관리한다.

구역 목록은 find_cctv_zones.py가 연결도(방법 A) + baseline 실측 통행량(방법 B)으로
데이터 기반 선정해 cctv_zones.json에 저장한 결과를 그대로 읽어 쓴다. 감으로 고른
지점이 없다는 것을 코드로도 보장하기 위함이다.

alert 생성 시 위험 edge를 기준으로 차량을 세 버킷으로 분류해 decision_policy.py가
STOP/REROUTE/SLOW를 구분해 판단할 수 있게 한다:
  - vehicles_in_hazard_edge: 위험 edge 위에 있는 차량 (즉시 위험)
  - vehicles_nearby: 위험 edge의 상류(가까운) edge에 있는 차량 (구역 내 감속)
  - vehicles_reroutable: 더 상류에 있으면서 남은 경로에 hazard edge가 포함된 차량 (우회 가능)
"""

import json
import random

import sumolib
import traci

NET_FILE = "network/gwangjin.net.xml"
NEARBY_HOPS = 2    # hazard edge로부터 이 hop 이내 = 감속 대상
REROUTE_HOPS = 5   # 감속 대상보다 더 상류, 이 hop 이내 = 우회 판단 대상

# 자동 사고: 30초마다 도로망 전체에서 "지금 도로 위 차들의 남은 경로에 가장 많이 들어 있는 도로"(앞으로 가장
# 많은 차가 지나갈 도로)에 사고를 낸다 - 사고 영향이 가장 크게 드러나는 곳. CCTV 구역 밖 사고도 도로망 전역 감지
# (detect_road_accidents)로 똑같이 정지/감속/우회 판단을 받는다. 지속시간 = 간격이라 새 사고가 나면 이전 사고가
# 풀린다(2026-09-29 사용자 요청 - 예전엔 20초 간격·45초 지속, 그 전엔 CCTV 9곳 안에서만 확률로 발생).
RANDOM_ACCIDENT_INTERVAL = 30.0  # s
RANDOM_ACCIDENT_MIN_EDGE_M = 20.0  # 이보다 짧은 도로(사거리 안 연결 토막 등)는 사고 위치로 안 고른다
RECENT_ACCIDENT_EXCLUDE = 5  # 최근 사고 이만큼의 도로는 다시 안 고른다 - 안 그러면 같은 간선도로에만 계속 난다
ACCIDENT_DURATION = 30.0  # s, 사고가 도로를 막는/서행시키는 지속 시간

with open("network/cctv_zones.json", encoding="utf-8") as f:
    _RAW_ZONES = json.load(f)

CCTV_ZONES = {
    zone_id: {"edges": info["edges"], "name": info["name"]}
    for zone_id, info in _RAW_ZONES.items()
}

# 데이터 기반으로 자동 선정된 CCTV 9곳과 달리, 하드웨어 시연 보드와 직접 연동되는
# 특정 교차로를 수동으로 등록해 둔 것 - 그래서 별도 파일/딕셔너리로 분리한다("CCTV
# 구역 9곳"이라는 기존 표현과 개수를 안 건드리기 위함). 대시보드에는 CCTV 그리드와
# 별개의 섹션으로 표시되지만, 감지·판단 로직(poll_all_zones, zone_status,
# trigger_accident)은 CCTV 구역과 완전히 동일하게 재사용한다.
with open("network/school_zones.json", encoding="utf-8") as f:
    _RAW_SCHOOL_ZONES = json.load(f)

SCHOOL_ZONES = {
    zone_id: {"edges": info["edges"], "name": info["name"]}
    for zone_id, info in _RAW_SCHOOL_ZONES.items()
}

# zone_status/trigger_accident 등 "어떤 zone_id든 상관없이" 동작해야 하는 함수들이
# 참조하는 통합 뷰. 어린이보호구역의 사고는 하드웨어 보행자 감지로 만들어지므로
# 무작위 자동 사고(update_accidents) 대상에서는 뺀다.
ALL_ZONES = {**CCTV_ZONES, **SCHOOL_ZONES}

_NET = sumolib.net.readNet(NET_FILE)
_UPSTREAM_CACHE = {}


def _upstream_edges(edge_id, hops):
    """edge_id로부터 hops 단계 이내의 상류(incoming) edge 집합을 반환한다."""
    cache_key = (edge_id, hops)
    if cache_key in _UPSTREAM_CACHE:
        return _UPSTREAM_CACHE[cache_key]

    visited = {edge_id}
    frontier = {edge_id}
    for _ in range(hops):
        nxt = set()
        for eid in frontier:
            try:
                edge = _NET.getEdge(eid)
            except KeyError:
                continue
            for pred in edge.getIncoming():
                pred_id = pred.getID()
                if pred_id not in visited:
                    visited.add(pred_id)
                    nxt.add(pred_id)
        frontier = nxt
        if not frontier:
            break
    visited.discard(edge_id)
    _UPSTREAM_CACHE[cache_key] = visited
    return visited


def _classify_vehicles(hazard_edge, nearby_hops=NEARBY_HOPS, reroute_hops=REROUTE_HOPS):
    """hazard_edge를 기준으로 인근 차량을 (구역 내 감속 대상, 우회 판단 대상)으로 나눈다."""
    nearby_ring = _upstream_edges(hazard_edge, nearby_hops)
    reroute_ring = _upstream_edges(hazard_edge, reroute_hops) - nearby_ring - {hazard_edge}

    # 집합(set)은 Python 실행마다 도는 순서가 달라진다(문자열 해시 무작위화) - 그 순서가 곧 명령·재경로
    # 순서가 되어 같은 seed여도 결과가 갈렸다(2026-09-28 확인). 항상 정렬해서 돈다.
    nearby_vehicles = []
    for edge in sorted(nearby_ring):
        nearby_vehicles.extend(traci.edge.getLastStepVehicleIDs(edge))

    reroutable_vehicles = []
    for edge in sorted(reroute_ring):
        for veh_id in traci.edge.getLastStepVehicleIDs(edge):
            route = traci.vehicle.getRoute(veh_id)
            route_index = traci.vehicle.getRouteIndex(veh_id)
            if hazard_edge in route[route_index:]:
                reroutable_vehicles.append(veh_id)

    return nearby_vehicles, reroutable_vehicles


_active_accidents = {}  # edge_id -> 종료 시각(s)
_next_random_accident = RANDOM_ACCIDENT_INTERVAL
_RANDOM_ACCIDENT_EDGES = None  # 사고 후보 도로(차도, 일정 길이 이상, 어린이보호구역 제외) - 첫 호출 때 계산


def _random_accident_edges():
    global _RANDOM_ACCIDENT_EDGES
    if _RANDOM_ACCIDENT_EDGES is None:
        school = {e for info in SCHOOL_ZONES.values() for e in info["edges"]}
        _RANDOM_ACCIDENT_EDGES = sorted(
            e.getID() for e in _NET.getEdges()
            if not e.getFunction() and e.allows("passenger") and e.getLength() >= RANDOM_ACCIDENT_MIN_EDGE_M
            and e.getID() not in school)
    return _RANDOM_ACCIDENT_EDGES


_recent_accident_edges = []  # 최근 자동 사고 도로(오래된 것부터)


def _busiest_upcoming_edge(exclude):
    """도로 위 모든 차의 남은 경로(지금 도로 포함)를 세어, 앞으로 가장 많은 차가 지나갈 사고 후보 도로."""
    allowed = set(_random_accident_edges())
    counts = {}
    for veh_id in traci.vehicle.getIDList():
        if veh_id.startswith("hwtwin_"):
            continue  # 실물 보드 차는 SUMO 경로를 안 따른다
        route = traci.vehicle.getRoute(veh_id)
        for e in route[traci.vehicle.getRouteIndex(veh_id):]:
            if e in allowed and e not in exclude:
                counts[e] = counts.get(e, 0) + 1
    if not counts:
        return None
    return max(sorted(counts), key=lambda e: counts[e])  # 동률이면 id 순 - 실행마다 같은 결과


def update_accidents(current_time):
    """만료된 사고를 정리하고, RANDOM_ACCIDENT_INTERVAL초마다 앞으로 가장 많은 차가 지나갈 도로에 새 사고를 낸다.
    poll_all_zones()가 매 스텝 자동으로 호출한다."""
    global _next_random_accident
    for eid, end_time in list(_active_accidents.items()):
        if current_time >= end_time:
            del _active_accidents[eid]

    if current_time < _next_random_accident:
        return
    _next_random_accident = current_time + RANDOM_ACCIDENT_INTERVAL
    edge = _busiest_upcoming_edge(set(_active_accidents) | set(_recent_accident_edges))
    if edge:
        _active_accidents[edge] = current_time + ACCIDENT_DURATION
        _recent_accident_edges.append(edge)
        del _recent_accident_edges[:-RECENT_ACCIDENT_EXCLUDE]


def reset_accidents():
    """새 시뮬레이션을 시작할 때(한 프로세스에서 seed 여러 개를 연달아 돌리는 측정 등) 사고 상태를 비운다."""
    global _next_random_accident
    _active_accidents.clear()
    _recent_accident_edges.clear()
    _next_random_accident = RANDOM_ACCIDENT_INTERVAL


def road_name(edge_id):
    """사고 위치를 사람이 알아볼 수 있게 - 도로 이름(OSM), 없으면 edge id."""
    try:
        return _NET.getEdge(edge_id).getName() or edge_id
    except KeyError:
        return edge_id


def detect_road_accidents():
    """CCTV·어린이보호구역 밖 도로의 사고 - 도로망 전역 감지(V2N 차량 신고)로 보고 구역 사고와 같은 alert를 만든다."""
    zone_edges = {e for info in ALL_ZONES.values() for e in info["edges"]}
    alerts = []
    for edge in sorted(_active_accidents):
        if edge in zone_edges:
            continue
        nearby_vehicles, reroutable_vehicles = _classify_vehicles(edge)
        alerts.append({
            "zone": "road",
            "zone_name": road_name(edge),
            "edge": edge,
            "type": "accident_detected",
            "hazard_until": _active_accidents[edge],  # 사고가 풀리는 시각 - 우회 vs 대기 비교용
            "vehicles_in_hazard_edge": list(traci.edge.getLastStepVehicleIDs(edge)),
            "vehicles_nearby": nearby_vehicles,
            "vehicles_reroutable": reroutable_vehicles,
        })
    return alerts


def get_active_accident_edges():
    """현재 활성 사고가 있는 edge 집합. GUI에서 표시 마커(POI) 동기화용."""
    return set(_active_accidents)


def get_active_accidents():
    """현재 활성 사고를 {edge_id: 종료 시각(s)} 형태로 반환한다. 대시보드에서
    남은 시간을 보여줄 때 쓴다."""
    return dict(_active_accidents)


def trigger_accident(zone_id, current_time):
    """구역 내 아직 사고가 없는 edge 하나를 골라 강제로 사고를 생성한다.

    UI의 "사고 생성" 버튼 등 수동 트리거용 - update_accidents()의 자동 발생과
    같은 상태(_active_accidents)를 공유해서, 이후 감지·시각화·판단 로직이 자동 발생
    사고와 완전히 동일하게 처리한다. 구역 내 모든 edge에 이미 사고가 있으면 아무 일도
    안 하고 None을 반환한다. CCTV 구역뿐 아니라 어린이보호구역 등 ALL_ZONES에 속한
    어떤 zone_id로도 호출 가능하다 - 하드웨어 보행자 감지를 사고로 표현할 때도 이
    함수를 그대로 재사용할 수 있게 하기 위함."""
    edges = ALL_ZONES[zone_id]["edges"]
    candidates = [e for e in edges if e not in _active_accidents]
    if not candidates:
        return None
    edge = random.choice(candidates)
    _active_accidents[edge] = current_time + ACCIDENT_DURATION
    return edge


# 신양초 어린이보호구역 하드웨어 연동 지점. school_zones.json의 arms와 일치한다.
HARDWARE_PEDESTRIAN_EDGE = "-85960673#2"  # LED 보행자가 나타나는 위치(NW 진출로 초입부)
HARDWARE_SPAWN_EDGE = "-172058984"        # 카메라가 차량을 인식하면 여기서 SUMO 차량을 만든다(SE 진입로, 일방통행 시작점)
# 하드웨어 신호(LED on/off)로 지속시간이 결정되는 사고라 고정 시간(ACCIDENT_DURATION)을
# 안 쓴다. float('inf')는 JSON 직렬화가 안 돼서(JS의 JSON.parse가 리터럴 Infinity를
# 못 읽음) 대신 충분히 큰 유한값을 쓴다.
HARDWARE_ACCIDENT_SENTINEL_DURATION = 999999.0

HARDWARE_DEST_HOPS = 8  # HARDWARE_PEDESTRIAN_EDGE 하류 몇 hop까지를 목적지 후보로 볼지

_hardware_vehicle_seq = 0
_HARDWARE_DEST_CANDIDATES = None  # 첫 호출 때 한 번만 findRoute로 검증해서 캐싱


def _downstream_edges(edge_id, hops):
    """edge_id로부터 hops 단계 이내의 하류(outgoing) 차량 edge 집합을 반환한다.
    _upstream_edges()와 반대 방향 버전."""
    visited = {edge_id}
    frontier = {edge_id}
    for _ in range(hops):
        nxt = set()
        for eid in frontier:
            try:
                edge = _NET.getEdge(eid)
            except KeyError:
                continue
            for succ in edge.getOutgoing():
                succ_id = succ.getID()
                if succ_id not in visited and succ.allows("passenger"):
                    visited.add(succ_id)
                    nxt.add(succ_id)
        frontier = nxt
        if not frontier:
            break
    visited.discard(edge_id)
    return visited


def _hardware_dest_candidates():
    """HARDWARE_SPAWN_EDGE에서 출발해 HARDWARE_PEDESTRIAN_EDGE를 반드시 지나가는
    목적지 edge 후보 목록을 만든다(첫 호출 때만 계산해 캐싱).

    완전 무작위 목적지로는 사거리에서 갈 수 있는 여러 방향 중 하나일 뿐이라, "차량
    감지 시뮬레이션"으로 만든 차량이 정작 보행자 사고 지점(HARDWARE_PEDESTRIAN_EDGE)을
    지나갈 확률이 낮았다 - 그래서 경로 최적화(재배치)를 볼 기회 자체가 거의 없었다.
    HARDWARE_PEDESTRIAN_EDGE보다 하류에 있는 edge만 후보로 추리고, 실제로 그 경로가
    이 edge를 지나는지 traci.simulation.findRoute()로 검증해서 확실한 것만 남긴다.
    """
    global _HARDWARE_DEST_CANDIDATES
    if _HARDWARE_DEST_CANDIDATES is None:
        candidates = []
        for edge_id in sorted(_downstream_edges(HARDWARE_PEDESTRIAN_EDGE, HARDWARE_DEST_HOPS)):
            route = traci.simulation.findRoute(HARDWARE_SPAWN_EDGE, edge_id)
            if HARDWARE_PEDESTRIAN_EDGE in route.edges:
                candidates.append(edge_id)
        _HARDWARE_DEST_CANDIDATES = candidates or [HARDWARE_PEDESTRIAN_EDGE]
    return _HARDWARE_DEST_CANDIDATES


def set_hardware_pedestrian_present(present, current_time):
    """하드웨어 LED 보행자 감지 신호를 반영한다.

    present=True면 HARDWARE_PEDESTRIAN_EDGE에 사고 상태를 만들어서(보행자가 사라질
    때까지 지속) 이후 감지·시각화·판단 로직이 일반 사고와 완전히 동일하게 처리하게
    한다(_active_accidents 공유). present=False면 그 자리의 사고를 즉시 해제한다.
    자동 사고(update_accidents)와 달리 고정 시간이 아니라 외부 신호로
    지속시간이 결정된다는 점이 다르다.
    """
    if present:
        _active_accidents[HARDWARE_PEDESTRIAN_EDGE] = current_time + HARDWARE_ACCIDENT_SENTINEL_DURATION
    else:
        _active_accidents.pop(HARDWARE_PEDESTRIAN_EDGE, None)


def spawn_hardware_vehicle(current_time):
    """하드웨어 카메라가 차량을 인식했을 때 SUMO에도 같은 시점에 차량을 추가한다.

    출발 지점은 HARDWARE_SPAWN_EDGE(일방통행 시작점) 고정, 목적지는
    _hardware_dest_candidates()가 검증해 둔 후보(HARDWARE_PEDESTRIAN_EDGE를 반드시
    지나가는 경로) 중에서 무작위로 고른다 - 그래야 나중에 "보행자 출현"을 눌렀을 때
    이 차량이 실제로 그 사고를 만나 경로 재배치를 보여줄 수 있다. 목적지까지 경로를
    못 찾으면(고립된 edge 등) None을 반환한다 - 호출자가 실패를 알 수 있게.
    """
    global _hardware_vehicle_seq

    dest_edge = random.choice(_hardware_dest_candidates())
    route = traci.simulation.findRoute(HARDWARE_SPAWN_EDGE, dest_edge)
    if not route.edges:
        return None

    _hardware_vehicle_seq += 1
    veh_id = f"hw_{_hardware_vehicle_seq}"
    route_id = f"hw_route_{veh_id}"
    traci.route.add(route_id, route.edges)
    traci.vehicle.add(veh_id, route_id, depart="now")
    return veh_id


def edge_midpoint(edge_id):
    """edge 형상의 중간점 좌표. 사고 마커를 놓을 위치로 쓴다."""
    shape = _NET.getEdge(edge_id).getShape()
    return shape[len(shape) // 2]


def _point_along_shape(shape, distance_m):
    """shape(좌표 리스트)를 따라 시작점에서 distance_m만큼 간 지점을 선형보간한다.
    distance_m이 전체 길이보다 크면 끝점을 반환한다."""
    remaining = distance_m
    for i in range(len(shape) - 1):
        x1, y1 = shape[i]
        x2, y2 = shape[i + 1]
        seg_len = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
        if remaining <= seg_len:
            t = remaining / seg_len if seg_len else 0
            return (x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)
        remaining -= seg_len
    return shape[-1]


def edge_point_near_start(edge_id, distance_m=10.0):
    """edge 시작점(도로 초입부)에서 distance_m만큼 안쪽 지점의 좌표를 반환한다.

    edge_midpoint()는 `shape[len(shape)//2]`로 계산하는데, 점이 2개뿐인(직선) edge는
    이게 중간점이 아니라 끝점이 나온다(정수 나눗셈이라 1이 나와서 사실상 끝점을 고르는
    꼴) - 신양초 하드웨어 보행자 사고가 도로 맨 끝(교차로에서 먼 쪽)에 찍히던 원인이
    이거였다. 하드웨어 보행자는 "교차로 쪽 초입부"라는 의미가 중요해서 시작점 기준으로
    거리를 재는 이 함수를 별도로 쓴다.
    """
    shape = _NET.getEdge(edge_id).getShape()
    return _point_along_shape(shape, distance_m)


def route_shape(veh_id):
    """차량의 남은 경로(현재 위치 이후)를 지도 좌표 폴리라인으로 반환한다.
    대시보드에서 차량을 선택했을 때 경로를 선으로 그려주는 용도."""
    route = traci.vehicle.getRoute(veh_id)
    idx = traci.vehicle.getRouteIndex(veh_id)
    points = []
    for edge_id in route[idx:]:
        try:
            edge = _NET.getEdge(edge_id)
        except KeyError:
            continue
        points.extend(edge.getShape())
    return points


def detect_accidents(zone_id, zone_edges):
    """활성 사고가 있는 edge에 대해 alert를 만든다 (보행자/장애물과 동일하게 즉시 정지 대상)."""
    alerts = []
    for edge in zone_edges:
        if edge not in _active_accidents:
            continue
        vehicles_in_hazard_edge = list(traci.edge.getLastStepVehicleIDs(edge))
        if edge == HARDWARE_PEDESTRIAN_EDGE:
            # 하드웨어 스폰 지점(HARDWARE_SPAWN_EDGE)이 사고 지점에서 1~2 hop밖에
            # 안 떨어져 있어(2026-09-29 재빌드 후 1 hop - 사거리 안 0.2m 연결 도로가 없어짐) 기본 NEARBY_HOPS로는 항상
            # "감속 대상"에만 걸리고 "우회 대상"엔 못 들어간다. 이 지점만
            # nearby_hops=0으로 좁혀 감속 구간을 없애고 바로 우회 판단을 받게 한다.
            nearby_vehicles, reroutable_vehicles = _classify_vehicles(edge, nearby_hops=0)
        else:
            nearby_vehicles, reroutable_vehicles = _classify_vehicles(edge)
        alerts.append({
            "zone": zone_id,
            "edge": edge,
            "type": "accident_detected",
            "hazard_until": _active_accidents[edge],  # 사고가 풀리는 시각 - 우회 vs 대기 비교용
            "vehicles_in_hazard_edge": vehicles_in_hazard_edge,
            "vehicles_nearby": nearby_vehicles,
            "vehicles_reroutable": reroutable_vehicles,
        })
    return alerts


def detect_pedestrian_in_zone(zone_id, zone_edges):
    """보행자가 특정 구역에 진입했는지 감지 (횡단 의도 감지에 사용)"""
    alerts = []
    for edge in zone_edges:
        persons = traci.edge.getLastStepPersonIDs(edge)
        if not persons:
            continue
        vehicles_in_hazard_edge = list(traci.edge.getLastStepVehicleIDs(edge))
        nearby_vehicles, reroutable_vehicles = _classify_vehicles(edge)
        alerts.append({
            "zone": zone_id,
            "edge": edge,
            "persons": persons,
            "type": "pedestrian_detected",
            "vehicles_in_hazard_edge": vehicles_in_hazard_edge,
            "vehicles_nearby": nearby_vehicles,
            "vehicles_reroutable": reroutable_vehicles,
        })
    return alerts


def detect_traffic_anomaly(zone_id, zone_edges, speed_threshold=2.0):
    """구간 평균 속도 급락 감지 (차량 데이터 기반 이상 상황)"""
    alerts = []
    for edge in zone_edges:
        mean_speed = traci.edge.getLastStepMeanSpeed(edge)
        vehicle_count = traci.edge.getLastStepVehicleNumber(edge)
        if vehicle_count == 0 or mean_speed >= speed_threshold:
            continue
        vehicles_in_hazard_edge = list(traci.edge.getLastStepVehicleIDs(edge))
        nearby_vehicles, reroutable_vehicles = _classify_vehicles(edge)
        alerts.append({
            "zone": zone_id,
            "edge": edge,
            "mean_speed": mean_speed,
            "type": "congestion_detected",
            "vehicles_in_hazard_edge": vehicles_in_hazard_edge,
            "vehicles_nearby": nearby_vehicles,
            "vehicles_reroutable": reroutable_vehicles,
        })
    return alerts


def poll_all_zones():
    """모든 구역(CCTV 9곳 + 어린이보호구역)을 한 스텝마다 순회 조사.

    자동 사고(update_accidents)는 30초마다 도로망 전체에서 나고(어린이보호구역 제외 - 거기 사고는
    하드웨어 보행자 감지로 만든다), 구역 밖 사고는 detect_road_accidents()가 따로 감지한다.
    구역 감지(보행자/정체/활성 사고)는 ALL_ZONES 전체를 돈다 - 어린이
    보호구역에서 사고가 생기면(수동이든 나중의 하드웨어 연동이든) 다른 구역과 완전히
    동일하게 decision_policy가 STOP/REROUTE/SLOW를 판단하게 하기 위함.
    """
    update_accidents(traci.simulation.getTime())
    all_alerts = []
    for zone_id, info in ALL_ZONES.items():
        all_alerts += detect_pedestrian_in_zone(zone_id, info["edges"])
        all_alerts += detect_traffic_anomaly(zone_id, info["edges"])
        all_alerts += detect_accidents(zone_id, info["edges"])
    all_alerts += detect_road_accidents()
    return all_alerts


def zone_status(zone_id):
    """대시보드용: 구역의 현재 차량 수/평균 속도/보행자·사고 유무를 반환.
    CCTV 구역과 어린이보호구역 모두 이 함수 하나로 처리한다(ALL_ZONES 기준)."""
    edges = ALL_ZONES[zone_id]["edges"]
    counts = {e: traci.edge.getLastStepVehicleNumber(e) for e in edges}
    vehicle_count = sum(counts.values())
    speeds = [traci.edge.getLastStepMeanSpeed(e) for e in edges if counts[e] > 0]
    mean_speed = sum(speeds) / len(speeds) if speeds else 0.0
    pedestrian_present = any(traci.edge.getLastStepPersonIDs(e) for e in edges)
    accident_present = any(e in _active_accidents for e in edges)
    return {
        "zone_id": zone_id,
        "name": ALL_ZONES[zone_id]["name"],
        "vehicle_count": vehicle_count,
        "mean_speed": mean_speed,
        "pedestrian_present": pedestrian_present,
        "accident_present": accident_present,
    }
