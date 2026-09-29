"""실시간 모니터링 대시보드 + baseline/treatment 비교 결과 대시보드를 제공하는 Flask 앱.

central_server.py + cctv_detector.py(9개 구역)가 개입하는 treatment 시뮬레이션을
백그라운드 스레드에서 직접 돌리면서, 매 스텝 poll_all_zones() 결과를 WebSocket으로
브라우저에 푸시한다. 비교 결과 대시보드는 experiment_data/results.csv를 읽어 정적으로 렌더링한다.
"""

import os
import sys
import time

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "core"))

import sumolib
import traci
from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO

from analysis import compute_comparison
from cctv_detector import (
    CCTV_ZONES, SCHOOL_ZONES, ALL_ZONES, poll_all_zones, zone_status,
    get_active_accident_edges, get_active_accidents, edge_midpoint, trigger_accident,
    route_shape, spawn_hardware_vehicle, set_hardware_pedestrian_present,
    edge_point_near_start, HARDWARE_PEDESTRIAN_EDGE, HARDWARE_PEDESTRIAN_OFFSET_M, road_name,
)
from hardware_twin import HardwareTwin, UdpReceiver, is_hardware_twin, load_config as load_hardware_twin_config
from gui_viewport import (write_zone_viewport, zone_bounds, point_bounds, ACCIDENT_COLOR, KONKUK_UNIV_COORD,
                          KONKUK_UNIV_VIEW_WIDTH_M)
from central_server import CentralServer
from vehicle_controller import execute_commands, eta_waiting_at, last_reroute_outcomes, edge_traveltime
from signal_controller import SignalController
from predictive_reroute import PredictiveRerouter
from stuck_vehicle_remover import StuckVehicleRemover

NET_FILE = "network/gwangjin.net.xml"
ROUTES_FILE = "network/routes.xml,network/pedestrian_routes.xml"
# 시연용 배경(OSM 지도 화풍으로 다시 칠한 건물·녹지·물 + 나무) + 차량/보행자 그림(차종 묶음, 사람 이미지).
# 둘 다 scripts/build_styled_polys.py, scripts/build_visual_assets.py로 다시 만들 수 있다. 예전 조합은
# "network/gwangjin.poly.xml,network/pedestrian_style.xml"(vehicle_style.xml이 보행자 색 재정의도 포함).
POLY_FILE = "network/gwangjin_styled.poly.xml,network/vehicle_style.xml"
SIM_END = 3600
EMERGENCY_BRAKE_THRESHOLD = -4.5
STEP_DELAY = 0.05  # 스텝 사이 최소 지연(초) - 웹 소켓 등 다른 작업에 양보할 틈
# 재생 배속: 1.0이면 시뮬레이션 1초(1스텝)를 실제 1초에 맞춘다(차 속도가 현실과 같아 보임). 스텝 계산 시간을 빼고
# 남은 만큼만 기다리므로 고정 딜레이보다 정확하다. 빨리 보고 싶으면 DASHBOARD_SPEED=5 처럼 준다(0 이하면 최대 속도).
# 2026-09-29 전에는 고정 0.05초 지연이라 계산 속도에 따라 실제의 3~10배로 흘렀다.
PLAYBACK_SPEED = float(os.environ.get("DASHBOARD_SPEED", "1.0"))
MAX_RECENT_ALERTS = 5

app = Flask(
    __name__,
    template_folder=os.path.join(_PROJECT_ROOT, "dashboard", "templates"),
    static_folder=os.path.join(_PROJECT_ROOT, "dashboard", "static"),
)
app.config["SECRET_KEY"] = "sumo-dashboard"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

summary = {
    "collision_count": 0,
    "emergency_brake_count": 0,
    "vehicle_count": 0,
    "person_count": 0,
    "accident_count": 0,
    "elapsed_step": 0,
    "sim_end": SIM_END,
    "running": False,
}
recent_alerts = []
_sim_started = False

# 카메라 포커스 요청. Flask 요청 스레드가 쓰고, simulation_loop 스레드가 읽어서 처리한다.
# kind: "zone" | "vehicle" | "person" | "accident", id: 그 종류의 식별자.
_pending_focus = None
# 구역 포커스 시 화면에 보일 실제 폭(m) - 사고 추적 화면과 같은 200m(2026-09-30 사용자 요청, 전엔 250)
_FOCUS_VIEW_WIDTH_M = 200
_POINT_FOCUS_WIDTH_M = 80    # 차량/보행자 등 개별 대상 포커스 시 화면 폭(m) - 구역보다 좁게 확대
# 사고는 주변 도로 상황(막히는 곳·우회하는 차)까지 보이게 넓게 - 80m는 사고 지점만 너무 클로즈업됐다(2026-09-29)
_ACCIDENT_FOCUS_WIDTH_M = 200  # 450 → 300 → 200, 사용자 요청으로 단계적으로 확대
ACCIDENT_MARKER_M = 10  # 사고 표시(빨간 원) 지름(m)
# 어린이보호구역도 사고 추적 화면과 같은 200m로 맞춘다(2026-09-30 사용자 요청, 전엔 사거리만 꽉 차게 110m).
_SCHOOL_ZONE_FOCUS_VIEW_WIDTH_M = 200

# "사고 생성" 버튼 요청. 포커스와 같은 이유로 simulation_loop 스레드에서만 처리한다.
_pending_accident_zone = None

# 어린이보호구역 하드웨어 연동(아직 실물 하드웨어가 없어 대시보드 버튼으로 시뮬레이션).
# 포커스/사고 생성과 같은 이유로 simulation_loop 스레드에서만 처리한다.
_pending_hardware_vehicle_spawn = False   # True면 다음 스텝에 차량 하나 생성
_pending_hardware_pedestrian_state = None  # None=변경 없음, True/False=그 상태로 설정

# 차량 선택 시 그려주는 경로선. 이름이 고정된 폴리곤 하나만 유지한다(항상 최근에
# 선택한 차량 하나의 경로만 보여줌). 포커스 처리와 같은 스레드 제약으로
# simulation_loop에서만 그리고/지운다.
ROUTE_LINE_ID = "route_line"
ROUTE_LINE_COLOR = (74, 158, 255, 255)  # 대시보드 포커스 강조색(파랑)과 통일
_route_vehicle_id = None  # 현재 경로선이 표시 중인 차량 (없으면 None)
_pending_route_clear = False  # 상세 패널을 닫을 때 등 명시적으로 경로선을 지워야 할 때

# 사고 추적 모드(상단 빨간 카드) - 켜 있는 동안 새 사고가 날 때마다 sumo-gui 카메라를 그 사고로 옮기고,
# 사고 때문에 경로를 바꾼 차량을 목록으로 보여준다. 목록 창을 닫으면 꺼진다(2026-09-29 사용자 요청).
_tracking = False
_tracking_since_step = 0
_pending_tracking_start = False  # 켜는 순간 가장 최근 사고로 카메라를 한 번 옮긴다(simulation_loop에서 처리)
_known_accidents = set()          # 지난 스텝까지 본 활성 사고 - 새로 생긴 사고를 찾는 용도
_latest_accident = None           # 가장 최근에 생긴 사고 edge
accident_reroutes = []            # 사고 때문에 정지·감속·우회한 차량 기록, 최신이 앞
_accident_reroute_seen = set()    # (사고 edge, 차량, 조치) - 같은 사고로 같은 차·같은 조치를 두 번 올리지 않게
MAX_ACCIDENT_REROUTES = 300

# 구역 상세 창의 "적용 알고리즘" 칸 - 차마다 마지막으로 받은 경로 변경(실시간 재계산·선제 우회).
# 사고 대응은 accident_reroutes, 신호 조정은 SignalController.recent_adjust에서 따로 찾는다.
vehicle_control = {}  # veh_id -> {"time", "action", "algorithm", "detail", "old_eta", "new_eta"}
CONTROL_SHOW_S = 60.0          # 경로 변경을 "지금 적용 중"으로 보여 주는 시간(실시간 재계산 주기와 같음)
SIGNAL_SHOW_S = 30.0           # 신호 조정을 보여 주는 시간
SIGNAL_NEAR_M = 120.0          # 다음 신호까지 이 거리 안이면 그 신호 조정의 영향을 받는 차로 본다

# 차량별 "방금 경로 최적화됨" 상태. simulation_loop만 쓰고 읽는다.
_recent_optimizations = {}  # veh_id -> {"old_eta", "new_eta", "until", "orig_color"}
OPTIMIZATION_BADGE_DURATION = 15.0  # s, 최적화 배지를 유지하는 시간
REROUTE_HIGHLIGHT_COLOR = (255, 60, 220, 255)  # 경로 재배치 강조색(마젠타) - 사고(빨강)/보행자(초록)와 구분

# 월드 전체 차량/보행자/사고 목록(ETA 재계산 포함)은 비용이 커서 매 스텝이 아니라
# 이 스텝 수마다만 다시 계산한다. 프론트엔드 폴링 주기(1.5s ≈ 30 스텝)보다 훨씬
# 촘촘하므로 화면상 체감 지연은 없다.
_WORLD_SNAPSHOT_INTERVAL = 10

# 구역별/월드 전체 상세정보 - simulation_loop가 매 스텝 갱신하고 /api/zone·/api/world가
# 그대로 읽는다. TraCI는 simulation_loop 스레드에서만 부를 수 있어서(zone-focus와 동일한
# 이유), Flask 요청 시점에 직접 조회하지 않고 미리 계산해 둔다.
zone_vehicle_details = {zid: [] for zid in ALL_ZONES}
# 구역 상세 창은 카메라가 보여 주는 200m 화면 안의 차를 모두 보여 준다 - CCTV 구역 도로(8~10개, 수십 m)만
# 세면 차가 0~1대뿐이라 창이 거의 비었다(2026-09-30). 시작할 때 화면 안 도로를 한 번 구해 둔다.
_zone_view_edges = {}
world_vehicles = []
world_persons = []
world_accidents = []


_alert_last_step = {}  # (종류, 구역, 도로) -> 마지막으로 목록에 올린 스텝
ALERT_REPEAT_STEPS = 60  # 같은 알림(예: 30초 동안 이어지는 같은 사고)은 이 스텝 안에 다시 올리지 않는다


def _record_alerts(alerts, step):
    # 감지는 매 스텝 같은 사고를 다시 보고한다 - 그대로 쌓으면 목록 5칸이 한 사고로 도배돼 새 사고가
    # 어디서 났는지 안 보였다(2026-09-29). 같은 알림은 ALERT_REPEAT_STEPS 안에 한 번만 올린다.
    for alert in alerts:
        key = (alert["type"], alert.get("zone"), alert.get("edge"))
        if step - _alert_last_step.get(key, -ALERT_REPEAT_STEPS) < ALERT_REPEAT_STEPS:
            continue
        _alert_last_step[key] = step
        recent_alerts.insert(0, {
            "zone": alert.get("zone"),
            # 구역 밖 도로 사고는 alert에 도로 이름이 들어 있다(cctv_detector.detect_road_accidents)
            "zone_name": alert.get("zone_name") or ALL_ZONES.get(alert.get("zone"), {}).get("name", ""),
            "edge": alert.get("edge"),
            "type": alert["type"],
            "step": step,
        })
    del recent_alerts[MAX_RECENT_ALERTS:]


def _compute_eta(veh_id, current_time):
    """남은 경로의 edge별 통행시간(traci.edge.getTraveltime, rerouteTraveltime과
    같은 지표)을 더해 예상 도착 시각을 추정한다. 물리적으로 정확한 값이 아니라
    "지금 조건이 유지된다면"이라는 근사치 - 대시보드 표시용이다."""
    route = traci.vehicle.getRoute(veh_id)
    idx = traci.vehicle.getRouteIndex(veh_id)
    remaining = route[idx:]
    total = sum(edge_traveltime(e) for e in remaining)  # 도로당 상한 - 멈춘 도로에서 수만 초로 튀는 것 방지
    return current_time + total


def _record_route_changes(changes, now, action, algorithm):
    """중앙 서버·선제 우회가 경로를 바꾼 차마다 바뀌기 전/후 예상 도착을 남긴다.
    같은 스텝에 여러 대가 바뀌므로 도로별 통행시간을 한 번씩만 읽는다."""
    tt = {}

    def rest_eta(edges):
        total = 0.0
        for e in edges:
            if e not in tt:
                tt[e] = edge_traveltime(e)
            total += tt[e]
        return now + total

    live = set(traci.vehicle.getIDList())
    for change in changes:
        vid, old_rest = change[0], change[1]
        if vid not in live:
            continue
        new_rest = traci.vehicle.getRoute(vid)[traci.vehicle.getRouteIndex(vid):]
        detail = f"새 도로 {sum(1 for e in new_rest if e not in set(old_rest))}개로 변경"
        if len(change) > 2:
            detail = f"{road_name(change[2])} 정체 예상 · " + detail
        vehicle_control[vid] = {"time": now, "action": action, "algorithm": algorithm, "detail": detail,
                                "old_eta": rest_eta(old_rest), "new_eta": rest_eta(new_rest)}


def _control_row(vid, edge, now, server, signals, accident_rows, active_acc, hardware_cars):
    """구역 상세 창 한 줄: 이 차가 지금 어떤 중앙 제어를 받고 있는지(사고 추적 창과 같은 모양).
    우선순위: 실물 차 > 사고 대응(정지·감속·우회·유지) > 선제 우회·실시간 재계산으로 경로 변경 > 신호 조정 > 평소."""
    base = {"vehicle_id": vid, "edge": edge, "road_name": "교차로 안" if edge.startswith(":") else road_name(edge),
            "hops_before": None, "detour_edges": None, "detail": None, "old_eta": None, "time": -1.0}
    if is_hardware_twin(vid):
        # 실물 차의 판단은 RC카 제어기(차량 호스트)가 traffic_state의 event로 보내 준다(팀원 저장소 INTERFACE.md)
        car = hardware_cars.get(vid, {})
        label = car.get("event_label") or "-"
        dest = (car.get("destination_zone") or "")[:1]
        detail = "RC카 제어기가 직접 판단" + (f" · 목적지 {dest}" if dest else "")
        return {**base, "action": "hardware", "algorithm": f"실물 · {label}", "detail": detail,
                "new_eta": None, "time": now + 1}
    acc = accident_rows.get(vid)
    if acc and acc["accident_edge"] in active_acc:
        return {**base, **{k: acc[k] for k in ("action", "algorithm", "hops_before", "detour_edges",
                                                "old_eta", "new_eta")},
                "detail": f"{acc['road_name']} 사고", "time": float(acc["step"])}
    ctl = vehicle_control.get(vid)
    if ctl and now - ctl["time"] <= CONTROL_SHOW_S:
        return {**base, **ctl}
    eta = _compute_eta(vid, now)
    nxt = traci.vehicle.getNextTLS(vid)
    if nxt:
        tls_id, _link, dist, _state = nxt[0]
        adj = signals.recent_adjust.get(tls_id)
        if dist <= SIGNAL_NEAR_M and adj and now - adj[0] <= SIGNAL_SHOW_S:
            t, kind, own_q, next_q, secs = adj
            detail = (f"대기 {own_q}대 방향 초록 {secs:.0f}s 연장" if kind == "extend"
                      else f"다음 방향 대기 {next_q}대 → {secs:.0f}s 뒤 전환")
            return {**base, "action": "signal", "algorithm": "신호 시간 배분",
                    "detail": f"앞 신호 {dist:.0f}m · {detail}", "new_eta": eta, "time": t}
    last = server.vehicle_routes.get(vid)
    since = f"{now - last:.0f}s 전 확인" if last is not None else "출발 대기"
    return {**base, "action": "normal", "algorithm": "실시간 경로 재계산",
            "detail": f"지금 경로가 최단 · {since}", "new_eta": eta}


def _vehicle_record(vid, edge, now):
    route = traci.vehicle.getRoute(vid)
    opt = _recent_optimizations.get(vid)
    return {
        "vehicle_id": vid,
        "edge": edge,
        "destination": route[-1] if route else None,
        "eta": _compute_eta(vid, now),
        "optimized": opt is not None,
        "old_eta": opt["old_eta"] if opt else None,
    }


def _compute_zone_view_edges(net):
    """구역마다 포커스 화면(중심에서 _FOCUS_VIEW_WIDTH_M/2 안)에 걸친 차도 edge 목록."""
    for zone_id in ALL_ZONES:
        xmin, ymin, xmax, ymax = zone_bounds(zone_id, _FOCUS_VIEW_WIDTH_M)
        cx, cy, half = (xmin + xmax) / 2, (ymin + ymax) / 2, (xmax - xmin) / 2
        edges = {e.getID() for e, _d in net.getNeighboringEdges(cx, cy, r=half)
                 if e.getFunction() != "internal" and (e.allows("passenger") or e.allows("custom1"))}
        _zone_view_edges[zone_id] = sorted(edges | set(ALL_ZONES[zone_id]["edges"]))


def _update_zone_vehicle_details(current_time, server, signals):
    """구역별 차량 목록과 각 차가 받는 중앙 제어(적용 알고리즘·예상 도착 전→후)를 다시 계산해 둔다.
    최근에 제어를 받은 차가 위, 평소 주행 차는 아래."""
    now = current_time
    accident_rows = {}
    for r in reversed(accident_reroutes):  # 최신이 앞이라 거꾸로 돌면 차마다 가장 최근 기록이 남는다
        accident_rows[r["vehicle_id"]] = r
    active_acc = get_active_accidents()
    hardware_cars = {v["sumo_id"]: v for v in (summary.get("hardware") or {}).get("vehicles", [])}
    for zone_id, info in ALL_ZONES.items():
        records = []
        for edge in _zone_view_edges.get(zone_id) or info["edges"]:
            for vid in traci.edge.getLastStepVehicleIDs(edge):
                records.append(_control_row(vid, edge, now, server, signals, accident_rows, active_acc, hardware_cars))
        records.sort(key=lambda r: (-r["time"], r["vehicle_id"]))
        zone_vehicle_details[zone_id] = records


def _expire_optimizations(current_time):
    """만료된 "경로 재배치" 배지를 정리하고, GUI에서 강조색으로 바꿔둔 차량 색을
    원래대로 되돌린다. 전체 차량 수와 무관하게 가벼워서 매 스텝 실행한다."""
    now = current_time
    live_ids = None
    for vid in list(_recent_optimizations):
        if _recent_optimizations[vid]["until"] < now:
            entry = _recent_optimizations.pop(vid)
            if live_ids is None:
                live_ids = set(traci.vehicle.getIDList())
            if vid in live_ids:
                traci.vehicle.setColor(vid, entry["orig_color"])


def _update_world_snapshots(current_time):
    """월드 전체 차량/보행자/사고 목록을 다시 계산해 둔다 (요약바 클릭 시 보여줄 상세)."""
    global world_vehicles, world_persons, world_accidents
    now = current_time

    world_vehicles = [
        _vehicle_record(vid, traci.vehicle.getRoadID(vid), now)
        for vid in traci.vehicle.getIDList()
    ]
    world_persons = [
        {"person_id": pid, "edge": traci.person.getRoadID(pid)}
        for pid in traci.person.getIDList()
    ]
    world_accidents = [
        {"accident_id": edge, "edge": edge, "road_name": road_name(edge), "remaining_s": max(0.0, end_time - now)}
        for edge, end_time in get_active_accidents().items()
    ]


def _accident_marker_point(edge_id):
    """사고 마커/카메라 포커스에 쓸 좌표. 하드웨어 보행자 사고는 "도로 초입부(교차로
    쪽)"라는 의미가 중요해서 edge_midpoint() 대신 시작점 기준 함수를 쓴다 -
    edge_midpoint()는 점이 2개뿐인 직선 edge에서는 중간점이 아니라 끝점을 반환하는
    문제가 있어(정수 나눗셈), 이 edge에서 마커가 교차로 반대편 도로 맨 끝에 찍히는
    원인이었다."""
    if edge_id == HARDWARE_PEDESTRIAN_EDGE:
        return edge_point_near_start(edge_id, HARDWARE_PEDESTRIAN_OFFSET_M)
    return edge_midpoint(edge_id)


def _resolve_focus_bounds(focus):
    """포커스 요청(kind+id)을 현재 위치 기준 (xmin,ymin,xmax,ymax)로 변환한다.
    대상이 이미 사라졌으면(도착/사고 종료 등) None을 반환한다."""
    kind, target_id = focus["kind"], focus["id"]
    if kind == "zone":
        width = _SCHOOL_ZONE_FOCUS_VIEW_WIDTH_M if target_id in SCHOOL_ZONES else _FOCUS_VIEW_WIDTH_M
        return zone_bounds(target_id, width)
    if kind == "vehicle":
        if target_id not in traci.vehicle.getIDList():
            return None
        x, y = traci.vehicle.getPosition(target_id)
        return point_bounds(x, y, _POINT_FOCUS_WIDTH_M)
    if kind == "person":
        if target_id not in traci.person.getIDList():
            return None
        x, y = traci.person.getPosition(target_id)
        return point_bounds(x, y, _POINT_FOCUS_WIDTH_M)
    if kind == "accident":
        if target_id not in get_active_accident_edges():
            return None
        x, y = _accident_marker_point(target_id)
        return point_bounds(x, y, _ACCIDENT_FOCUS_WIDTH_M)
    return None


def _sync_accident_pois(rendered):
    """활성 사고 목록과 화면에 그려둔 POI 집합을 맞춘다 - 새로 난 사고는 빨간 원을
    추가하고, 끝난 사고는 지운다."""
    active = get_active_accident_edges()
    for edge in active - rendered:
        x, y = _accident_marker_point(edge)
        # 10m: 25m는 옆 도로까지 덮어 엉뚱한 도로에 사고가 난 것처럼 보였다(2026-09-29). 도로 폭 정도로.
        traci.poi.add(f"accident_{edge}", x, y, ACCIDENT_COLOR, layer=20, width=ACCIDENT_MARKER_M, height=ACCIDENT_MARKER_M)
        rendered.add(edge)
    for edge in rendered - active:
        traci.poi.remove(f"accident_{edge}")
        rendered.discard(edge)


def _clear_route_line():
    """표시 중이던 경로선을 지운다. 아무것도 안 그려져 있으면 조용히 넘어간다."""
    global _route_vehicle_id
    if _route_vehicle_id is None:
        return
    try:
        traci.polygon.remove(ROUTE_LINE_ID)
    except traci.exceptions.TraCIException:
        pass
    _route_vehicle_id = None


def _draw_route_line(veh_id):
    """선택된 차량의 남은 경로를 선으로 그린다. 항상 하나만 유지되도록 먼저 지운다."""
    global _route_vehicle_id
    shape = route_shape(veh_id)
    _clear_route_line()
    if len(shape) < 2:
        return
    traci.polygon.add(ROUTE_LINE_ID, shape, ROUTE_LINE_COLOR, fill=False, layer=25, lineWidth=1)
    _route_vehicle_id = veh_id


def _start_hardware_twin():
    """실물 보드(차량 호스트) traffic_state 수신을 시작한다. HARDWARE_TWIN=0이면 끈다.
    포트가 이미 쓰이는 중이면(다른 수신기가 떠 있음) 대시보드는 그대로 돌고 연동만 빠진다."""
    if os.environ.get("HARDWARE_TWIN") == "0":
        summary["hardware"] = {"enabled": False}
        return None
    cfg = load_hardware_twin_config()
    port = int(os.environ.get("HARDWARE_TWIN_PORT", cfg["udp_port"]))
    try:
        receiver = UdpReceiver(cfg["udp_host"], port)
    except OSError as exc:
        print(f"[dashboard] 실물 연동 수신 포트 {port}를 열 수 없음({exc}) - 연동 없이 진행")
        summary["hardware"] = {"enabled": False, "error": str(exc)}
        return None
    print(f"[dashboard] 실물 연동 수신 대기: UDP {cfg['udp_host']}:{port}")
    return HardwareTwin(cfg, receiver)


def simulation_loop():
    global _pending_focus, _pending_accident_zone, _pending_route_clear
    global _pending_hardware_vehicle_spawn, _pending_hardware_pedestrian_state
    global _latest_accident, _pending_tracking_start
    summary["running"] = True
    # sumo-gui로 띄운다 — 웹 대시보드와 별개의 시뮬레이션을 headless로 돌리면 겉보기엔
    # 같아 보여도 실제로는 시드/타이밍이 다른 별개 상황이 된다. sumo-gui 창과 이 웹
    # 페이지가 정확히 같은 TraCI 세션·같은 시뮬레이션 스텝을 보도록 하나로 합친다.
    sumo_binary = "sumo" if os.environ.get("DASHBOARD_HEADLESS") == "1" else "sumo-gui"
    cmd = [
        sumo_binary, "-n", NET_FILE, "-r", ROUTES_FILE, "-a", POLY_FILE,
        "--begin", "0", "--end", str(SIM_END), "--seed", "42",
        "--collision.action", "warn",
        "--collision.check-junctions", "true",
        "--collision.mingap-factor", "0",
        "--intermodal-collision.action", "warn",
    ]
    if sumo_binary == "sumo-gui":
        cmd.append("--start")  # 창이 뜨자마자 자동 재생 - 발표 중 버튼 조작 불필요
        # 기본값은 건국대학교(캠퍼스 랜드마크)에서 시작한다 - DASHBOARD_FOCUS_ZONE을
        # 지정하면(예: "zone_1") 그 구역으로 대신 시작할 수 있다(기존 동작 유지).
        focus_zone = os.environ.get("DASHBOARD_FOCUS_ZONE")
        if focus_zone:
            viewport_path = write_zone_viewport(zone_id=focus_zone)
        else:
            viewport_path = write_zone_viewport(coord=KONKUK_UNIV_COORD, view_width_m=KONKUK_UNIV_VIEW_WIDTH_M)
        cmd += ["--gui-settings-file", viewport_path]
    traci.start(cmd)
    server = CentralServer(record_changes=True)
    signals = SignalController()
    net = sumolib.net.readNet(NET_FILE)
    predictor = PredictiveRerouter(net, record_changes=True)
    _compute_zone_view_edges(net)
    remover = StuckVehicleRemover()
    rendered_accident_pois = set()
    hardware_twin = _start_hardware_twin()
    hardware_was_connected = False

    step = 0
    while step < SIM_END:
        step_started = time.monotonic()
        traci.simulationStep()

        colliding = traci.simulation.getCollidingVehiclesIDList()
        summary["collision_count"] += len(colliding)

        for veh_id in traci.vehicle.getIDList():
            if traci.vehicle.getAcceleration(veh_id) < EMERGENCY_BRAKE_THRESHOLD:
                summary["emergency_brake_count"] += 1

        if _pending_accident_zone:
            edge = trigger_accident(_pending_accident_zone, traci.simulation.getTime())
            if edge:
                print(f"[dashboard] 수동 사고 생성: zone={_pending_accident_zone} edge={edge}")
            else:
                print(f"[dashboard] 수동 사고 생성 실패(모든 edge가 이미 사고 중): zone={_pending_accident_zone}")
            _pending_accident_zone = None

        if _pending_route_clear:
            _clear_route_line()
            _pending_route_clear = False

        if _pending_hardware_vehicle_spawn:
            veh_id = spawn_hardware_vehicle(traci.simulation.getTime())
            if veh_id:
                print(f"[dashboard] 하드웨어 차량 감지 → SUMO 차량 생성: {veh_id}")
            else:
                print("[dashboard] 하드웨어 차량 생성 실패(목적지 경로를 못 찾음)")
            _pending_hardware_vehicle_spawn = False

        if _pending_hardware_pedestrian_state is not None:
            set_hardware_pedestrian_present(_pending_hardware_pedestrian_state, traci.simulation.getTime())
            print(f"[dashboard] 하드웨어 보행자 상태 변경: present={_pending_hardware_pedestrian_state}")
            _pending_hardware_pedestrian_state = None

        if hardware_twin is not None:
            try:
                hardware_twin.step(traci.simulation.getTime())
            except traci.exceptions.TraCIException as exc:
                print(f"[dashboard] 실물 연동 반영 실패: {exc}")
            summary["hardware"] = hardware_twin.status()
            # 실물 차의 판단(보행자 앞 정지, 우회 준비, 후진, 우회)을 알림 목록에 올린다
            focus_zone = hardware_twin.cfg.get("focus_zone", "school_zone_1")
            for text in hardware_twin.pop_event_alerts():
                recent_alerts.insert(0, {
                    "zone": focus_zone, "zone_name": ALL_ZONES.get(focus_zone, {}).get("name", ""),
                    "edge": None, "type": "hardware_event", "text": text, "step": step,
                })
                del recent_alerts[MAX_RECENT_ALERTS:]
            connected = summary["hardware"]["connected"]
            if connected and not hardware_was_connected and hardware_twin.cfg.get("auto_focus_on_connect"):
                # 실물이 처음 연결되면 카메라를 신양초 사거리로 한 번 옮긴다(시연 중 다른 곳을 보고 있을 수 있음)
                _pending_focus = {"kind": "zone", "id": hardware_twin.cfg.get("focus_zone", "school_zone_1")}
            hardware_was_connected = connected

        server.initial_optimization()
        if server.route_changes:
            _record_route_changes(server.route_changes, traci.simulation.getTime(), "central", "실시간 경로 재계산")
            server.route_changes = []
        alerts = poll_all_zones()
        commands = server.handle_cctv_alert(alerts)

        now = traci.simulation.getTime()
        remover.step(now)
        vehicle_ids = set(traci.vehicle.getIDList())
        if _route_vehicle_id is not None and _route_vehicle_id not in vehicle_ids:
            _clear_route_line()  # 경로선을 보여주던 차량이 도착/소멸 - 자동으로 지움
        summary["vehicle_count"] = len(vehicle_ids)
        summary["person_count"] = traci.person.getIDCount()
        summary["accident_count"] = len(get_active_accident_edges())
        reroute_targets = {cmd["veh_id"] for cmd in commands if cmd["action"] == "reroute"} & vehicle_ids
        eta_before_map = {vid: _compute_eta(vid, now) for vid in reroute_targets}
        # 어느 사고 때문에 우회 대상이 됐는지 - 사고 추적 목록용
        accident_of = {cmd["veh_id"]: cmd.get("avoid_edge") for cmd in commands
                       if cmd["action"] == "reroute" and cmd.get("reason") == "accident_detected"}
        # 우회 전 경로 - 사고까지 몇 도로 남았을 때 잡혔는지, 우회로 새로 쓰는 도로가 몇 개인지 보여주려고
        route_before = {vid: (traci.vehicle.getRoute(vid), traci.vehicle.getRouteIndex(vid))
                        for vid in accident_of if vid in vehicle_ids}
        accident_end = get_active_accidents()
        # 사고로 정지·감속 명령을 받은 차도 사고 추적 목록에 올린다(경로는 그대로라 도착 예상은 사고 해제 대기 기준)
        for cmd in commands:
            if cmd.get("reason") != "accident_detected" or cmd["action"] not in ("stop", "decelerate"):
                continue
            vid, acc_edge = cmd["veh_id"], cmd.get("hazard_edge")
            key = (acc_edge, vid, cmd["action"])
            if not acc_edge or vid not in vehicle_ids or key in _accident_reroute_seen:
                continue
            _accident_reroute_seen.add(key)
            rest = traci.vehicle.getRoute(vid)[traci.vehicle.getRouteIndex(vid):]
            eta_wait = eta_waiting_at(vid, acc_edge, accident_end.get(acc_edge), now)
            accident_reroutes.insert(0, {
                "vehicle_id": vid, "accident_edge": acc_edge, "road_name": road_name(acc_edge),
                "step": step, "old_eta": None,
                "new_eta": eta_wait if eta_wait is not None else _compute_eta(vid, now),
                "action": cmd["action"],
                "algorithm": "정지" if cmd["action"] == "stop" else f"감속 ({cmd['target_speed']:.0f}m/s)",
                "hops_before": rest.index(acc_edge) if acc_edge in rest else None,
                "detour_edges": None,
            })

        execute_commands(commands)

        # 우회 대상이던 차: 실제로 우회했는지, "기다리는 게 빠름"으로 원래 경로를 유지했는지(vehicle_controller가 판단)
        for vid, outcome in last_reroute_outcomes.items():
            rerouted = outcome["rerouted"]
            new_eta = outcome["eta_detour"] if rerouted else (outcome["eta_wait"] or _compute_eta(vid, now))
            if rerouted:
                _recent_optimizations[vid] = {
                    "old_eta": eta_before_map.get(vid, new_eta),
                    "new_eta": new_eta,
                    "until": now + OPTIMIZATION_BADGE_DURATION,
                    "orig_color": traci.vehicle.getColor(vid),
                }
            acc_edge = accident_of.get(vid)
            action = "reroute" if rerouted else "keep"
            if acc_edge and (acc_edge, vid, action) not in _accident_reroute_seen:
                _accident_reroute_seen.add((acc_edge, vid, action))
                old_route, old_idx = route_before.get(vid, ((), 0))
                old_rest = list(old_route[old_idx:])
                hops = old_rest.index(acc_edge) if acc_edge in old_rest else None
                new_rest = traci.vehicle.getRoute(vid)[traci.vehicle.getRouteIndex(vid):]
                detour = sum(1 for e in new_rest if e not in set(old_rest))
                accident_reroutes.insert(0, {
                    "vehicle_id": vid, "accident_edge": acc_edge, "road_name": road_name(acc_edge),
                    # 전 = 원래 경로로 가서 사고가 풀릴 때까지 기다렸을 때, 후 = 우회 경로(유지한 차는 찾았던 우회 경로)
                    "step": step, "old_eta": outcome["eta_wait"] if outcome["eta_wait"] is not None else eta_before_map.get(vid),
                    "new_eta": outcome["eta_detour"],
                    "action": action,
                    "algorithm": "사고 회피 재탐색" if rerouted else "원래 경로 유지",
                    "hops_before": hops, "detour_edges": detour if rerouted else None,
                })
            if not rerouted:
                continue
            traci.vehicle.setColor(vid, REROUTE_HIGHLIGHT_COLOR)
            if sumo_binary == "sumo-gui":
                # sumo-gui 화면에 잠깐 링을 띄워서 "지금 이 차가 재배치됐다"를
                # 대시보드를 열지 않아도 한눈에 보이게 한다.
                traci.vehicle.highlight(vid, REROUTE_HIGHLIGHT_COLOR, -1, 255, 2.5, 0)
        del accident_reroutes[MAX_ACCIDENT_REROUTES:]

        _expire_optimizations(now)
        server.update_throughput()
        signals.step(now)
        predictor.step(now)
        if predictor.route_changes:
            _record_route_changes(predictor.route_changes, now, "predict", "정체 예측 선제 우회")
            predictor.route_changes = []
        for vid in [v for v in vehicle_control if v not in vehicle_ids]:
            del vehicle_control[vid]
        _update_zone_vehicle_details(now, server, signals)
        if step % _WORLD_SNAPSHOT_INTERVAL == 0:
            _update_world_snapshots(now)

        if sumo_binary == "sumo-gui":
            _sync_accident_pois(rendered_accident_pois)

        summary["elapsed_step"] = step
        if alerts:
            _record_alerts(alerts, step)

        # 새로 생긴 사고 찾기 - 사고 추적 모드면 카메라를 그 사고로
        active_accidents = get_active_accident_edges()
        new_accidents = sorted(active_accidents - _known_accidents)
        _known_accidents.clear()
        _known_accidents.update(active_accidents)
        if new_accidents:
            _latest_accident = new_accidents[-1]
        if _tracking and (new_accidents or _pending_tracking_start):
            if _latest_accident in active_accidents:
                _pending_focus = {"kind": "accident", "id": _latest_accident}
            _pending_tracking_start = False
        summary["tracking"] = _tracking

        if _pending_focus and sumo_binary == "sumo-gui":
            try:
                bounds = _resolve_focus_bounds(_pending_focus)
                if bounds is not None:
                    traci.gui.setBoundary(traci.gui.DEFAULT_VIEW, *bounds)
                # 차량을 선택했을 때만 경로선을 그린다 - 구역/보행자/사고를 선택하면
                # 이전에 그려둔 경로선은 지워서 화면에 안 맞는 선이 남지 않게 한다.
                if _pending_focus["kind"] == "vehicle" and bounds is not None:
                    _draw_route_line(_pending_focus["id"])
                else:
                    _clear_route_line()
            except (KeyError, traci.exceptions.TraCIException) as exc:
                print(f"[dashboard] 카메라 이동 실패({_pending_focus}): {exc}")
            _pending_focus = None

        zones_payload = [zone_status(zid) for zid in ALL_ZONES]
        socketio.emit("zone_update", {
            "zones": zones_payload,
            "summary": dict(summary),
            "recent_alerts": recent_alerts,
        })

        step += 1
        speed = PLAYBACK_SPEED
        if (hardware_twin is not None and hardware_was_connected
                and hardware_twin.cfg.get("realtime_when_connected")):
            # 실물 연결 중에는 배속 설정과 상관없이 실제 시간 - 실물 차와 주변 차의 속도감을 같게
            speed = 1.0
        delay = STEP_DELAY
        if speed > 0:
            delay = max(STEP_DELAY, traci.simulation.getDeltaT() / speed - (time.monotonic() - step_started))
        socketio.sleep(delay)

    traci.close()
    summary["running"] = False
    socketio.emit("simulation_ended", {})


@app.route("/")
def index():
    return render_template(
        "index.html",
        zones=list(CCTV_ZONES.items()),
        school_zones=list(SCHOOL_ZONES.items()),
    )


@app.route("/comparison")
def comparison():
    return render_template("comparison.html")


@app.route("/api/comparison")
def api_comparison():
    if not os.path.exists("experiment_data/results.csv"):
        return jsonify({"error": "experiment_data/results.csv not found"}), 404
    return jsonify(compute_comparison())


@app.route("/api/zone/<zone_id>/vehicles")
def api_zone_vehicles(zone_id):
    """구역 상세 패널용: 그 구역 도로 위의 차량 목록(목적지/ETA/최적화 배지).

    simulation_loop가 매 스텝 미리 계산해 둔 zone_vehicle_details를 그대로 읽기만
    한다 - TraCI 호출은 여기서 하지 않는다(스레드 제약, /api/focus와 동일한 이유).
    """
    if zone_id not in ALL_ZONES:
        return jsonify({"error": f"unknown zone: {zone_id}"}), 404
    zone_edges = set(ALL_ZONES[zone_id]["edges"])
    accidents = [{"edge": e, "road_name": road_name(e), "remaining_s": max(0.0, end - summary["elapsed_step"])}
                 for e, end in get_active_accidents().items() if e in zone_edges]
    return jsonify({
        "zone_id": zone_id,
        "zone_name": ALL_ZONES[zone_id]["name"],
        "school_zone": zone_id in SCHOOL_ZONES,
        "hardware": summary.get("hardware") if zone_id in SCHOOL_ZONES else None,
        "accidents": accidents,
        "vehicles": zone_vehicle_details.get(zone_id, []),
    })


@app.route("/api/world/vehicles")
def api_world_vehicles():
    """요약바의 "현재 차량 수" 클릭용: 월드 전체 차량 목록(목적지/ETA/최적화 배지)."""
    return jsonify({"vehicles": world_vehicles})


@app.route("/api/world/persons")
def api_world_persons():
    """요약바의 "현재 보행자 수" 클릭용: 월드 전체 보행자 목록(현재 위치)."""
    return jsonify({"persons": world_persons})


@app.route("/api/world/accidents")
def api_world_accidents():
    """요약바의 "현재 사고 수" 클릭용: 월드 전체 활성 사고 목록(위치/남은 시간)."""
    return jsonify({"accidents": world_accidents})


@app.route("/api/focus/<kind>/<target_id>", methods=["POST"])
def api_focus(kind, target_id):
    """카드/목록 항목을 클릭하면 sumo-gui 카메라를 그 대상으로 옮긴다.

    kind: zone(구역, 고정 좌표) | vehicle | person | accident(매 순간 현재 위치 조회 필요).
    simulation_loop가 도는 스레드에서만 TraCI를 호출해야 하므로, 여기서는 요청을
    표시만 해두고 다음 시뮬레이션 스텝에서 simulation_loop가 실제로 이동시킨다.
    """
    global _pending_focus
    if kind not in ("zone", "vehicle", "person", "accident"):
        return jsonify({"error": f"unknown kind: {kind}"}), 400
    if kind == "zone" and target_id not in ALL_ZONES:
        return jsonify({"error": f"unknown zone: {target_id}"}), 404
    _pending_focus = {"kind": kind, "id": target_id}
    return jsonify({"ok": True, "kind": kind, "id": target_id})


@app.route("/api/tracking/start", methods=["POST"])
def api_tracking_start():
    """사고 추적 모드 켜기 - 바로 가장 최근 사고로 카메라를 옮기고, 이후 새 사고마다 따라간다."""
    global _tracking, _tracking_since_step, _pending_tracking_start
    _tracking = True
    _tracking_since_step = summary["elapsed_step"]
    _pending_tracking_start = True
    return jsonify({"ok": True})


@app.route("/api/tracking/stop", methods=["POST"])
def api_tracking_stop():
    """목록 창을 닫으면 호출 - 사고 추적 모드 끄기."""
    global _tracking
    _tracking = False
    return jsonify({"ok": True})


@app.route("/api/tracking")
def api_tracking():
    """사고 추적 창 내용: 지금 따라가는 사고 + 그 사고 때문에 경로를 바꾼 차량(최신이 위).
    새 사고로 추적 대상이 바뀌면 이전 사고의 차량은 목록에서 빠진다(사용자 요청)."""
    accident = None
    acc = get_active_accidents()
    if _latest_accident in acc:
        accident = {"edge": _latest_accident, "road_name": road_name(_latest_accident),
                    "remaining_s": max(0.0, acc[_latest_accident] - summary["elapsed_step"])}
    vehicles = [r for r in accident_reroutes
                if r["step"] >= _tracking_since_step and r["accident_edge"] == _latest_accident]
    return jsonify({"active": _tracking, "accident": accident, "vehicles": vehicles})


@app.route("/api/zone/<zone_id>/trigger_accident", methods=["POST"])
def api_trigger_accident(zone_id):
    """구역 상세 패널의 "사고 생성" 버튼용 - 그 구역 도로 중 하나에 강제로 사고를 낸다.

    실제로 _active_accidents에 넣는 작업은 TraCI 조회(traci.simulation.getTime())가
    필요해서 simulation_loop 스레드에서 해야 한다 - 여기서는 요청만 표시해 둔다.
    """
    global _pending_accident_zone
    if zone_id not in ALL_ZONES:
        return jsonify({"error": f"unknown zone: {zone_id}"}), 404
    _pending_accident_zone = zone_id
    return jsonify({"ok": True, "zone_id": zone_id})


@app.route("/api/route/clear", methods=["POST"])
def api_route_clear():
    """상세 패널을 닫을 때 등, 표시 중이던 차량 경로선을 명시적으로 지운다."""
    global _pending_route_clear
    _pending_route_clear = True
    return jsonify({"ok": True})


@app.route("/api/school_zone/vehicle_detected", methods=["POST"])
def api_school_zone_vehicle_detected():
    """어린이보호구역 상세 패널의 "차량 감지 시뮬레이션" 버튼용 - 실제 하드웨어
    카메라가 아직 없어 대시보드에서 대신 신호를 보낸다. 일방통행 시작점에 무작위
    목적지를 가진 차량을 하나 생성한다."""
    global _pending_hardware_vehicle_spawn
    _pending_hardware_vehicle_spawn = True
    return jsonify({"ok": True})


@app.route("/api/school_zone/pedestrian", methods=["POST"])
def api_school_zone_pedestrian():
    """어린이보호구역 상세 패널의 보행자 출현/통과완료 버튼용. body의 {"present": true|false}로
    상태를 지정한다 - 실제 하드웨어 LED 신호가 연결되면 이 엔드포인트를 그대로 호출하면 된다."""
    global _pending_hardware_pedestrian_state
    body = request.get_json(silent=True) or {}
    present = bool(body.get("present"))
    _pending_hardware_pedestrian_state = present
    return jsonify({"ok": True, "present": present})


@socketio.on("connect")
def handle_connect():
    global _sim_started
    if not _sim_started:
        _sim_started = True
        socketio.start_background_task(simulation_loop)


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)
