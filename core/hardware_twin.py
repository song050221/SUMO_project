"""실물 시연 보드(RC카 + 보행자 LED)의 상황을 SUMO 신양초 사거리에 그대로 그린다.

연동은 차량 → SUMO 한 방향이다(2026-09-26 하드웨어 팀 결정, 팀원 저장소
invuc02/capstone-sumo-bridge의 INTERFACE.md). 주행 판단(보행자 앞 정지, 후진, B 우회)은
전부 차량 호스트가 하고, 차량 호스트가 UDP 9002로 보내는 traffic_state를 받아 SUMO는
**그리기만 한다** - 그래서 여기서 만든 차량(ID가 HW_PREFIX로 시작)은 중앙 경로 재계산,
사고 대응 명령, 선제 우회, 견인 대상에서 모두 빠진다(각 모듈이 is_hardware_twin()으로 거름).

보드 위 주행이 끝나면(도착, 또는 사거리를 지난 뒤 인식이 끊김) 그 차를 지우지 않고 같은 자리·같은
그림의 일반 SUMO 차량(ID가 RELEASED_PREFIX로 시작)으로 넘겨 무작위 목적지까지 계속 달리게 한다
(2026-09-30 사용자 요청 - "시뮬레이션의 일부라는 느낌으로"). 이 차는 is_hardware_twin()에 걸리지 않으므로
중앙 경로 재계산·사고 대응·선제 우회·견인을 다른 차와 똑같이 받는다.

보드와 사거리는 크기·모양이 달라서 좌표를 그대로 옮기지 않는다. 차 위치를 보드 위 주행선
(configs/hardware_twin.json의 board_paths)에 투영해 "몇 m 진행했나"를 구하고, 기준점
(anchors: 출발, 사거리 입구, 보행자 LED 선, 도착)끼리 짝지어 SUMO 경로 위 거리로 선형
보간한다 - 그래야 실물 차가 LED 앞에서 서면 SUMO 차도 사거리의 보행자 지점 앞에서 선다.

보행자 LED가 잡히면 cctv_detector.set_hardware_pedestrian_present(True)로 기존 사고 흐름을
켜서(주변 일반 차량은 지금처럼 중앙 알고리즘이 반응) 파란 원으로 보행자 위치를 그린다.
"""

import json
import math
import os
import random
import socket
import threading
import time

import traci

HW_PREFIX = "hwtwin_"
HW_VTYPE = "hwtwin"
RELEASED_PREFIX = "rc_"   # 보드에서 나와 일반 차량이 된 실물 차 - 중앙 제어를 받는다
RELEASE_MIN_ROUTE_M = 1500.0  # 넘긴 뒤 목적지까지 최소 이 정도는 달리게(너무 금방 사라지지 않게)
RELEASE_DEST_TRIES = 40
ROLE_TYPES = ("lead", "follow", "diverted")
PEDESTRIAN_POI = "hwtwin_pedestrian"
CROSSWALK_PREFIX = "hwtwin_crosswalk_"
DEFAULT_CONFIG_PATH = "configs/hardware_twin.json"


def is_hardware_twin(veh_id):
    """실물 차량을 따라 그리는 SUMO 차량인지. 자동 제어 모듈들이 이걸로 거른다."""
    return veh_id.startswith(HW_PREFIX)


def load_config(path=DEFAULT_CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 기하 (TraCI 없이 테스트 가능)

def polyline_length(poly):
    return sum(math.dist(a, b) for a, b in zip(poly, poly[1:]))


def project_to_polyline(poly, pt):
    """pt에서 가장 가까운 poly 위 점까지의 호 길이(시작점 기준)."""
    best_d2, best_s, acc = None, 0.0, 0.0
    for (ax, ay), (bx, by) in zip(poly, poly[1:]):
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((pt[0] - ax) * dx + (pt[1] - ay) * dy) / seg2))
        px, py = ax + t * dx, ay + t * dy
        d2 = (pt[0] - px) ** 2 + (pt[1] - py) ** 2
        if best_d2 is None or d2 < best_d2:
            best_d2, best_s = d2, acc + t * math.sqrt(seg2)
        acc += math.sqrt(seg2)
    return best_s


def point_at(poly, s):
    """poly 위 호 길이 s의 점과 SUMO 각도(북쪽 0도, 시계방향)."""
    s = max(0.0, s)
    acc = 0.0
    for (ax, ay), (bx, by) in zip(poly, poly[1:]):
        seg = math.dist((ax, ay), (bx, by))
        if seg > 0 and (acc + seg >= s or (bx, by) == tuple(poly[-1])):
            t = min(1.0, (s - acc) / seg)
            angle = math.degrees(math.atan2(bx - ax, by - ay)) % 360
            return ax + t * (bx - ax), ay + t * (by - ay), angle
        acc += seg
    (ax, ay), (bx, by) = poly[-2], poly[-1]
    return bx, by, math.degrees(math.atan2(bx - ax, by - ay)) % 360


def piecewise_map(pairs, s):
    """[(보드 거리, SUMO 거리), ...](보드 거리 오름차순)로 s를 선형 보간. 양 끝은 고정."""
    if s <= pairs[0][0]:
        return pairs[0][1]
    for (s0, d0), (s1, d1) in zip(pairs, pairs[1:]):
        if s <= s1:
            return d0 if s1 == s0 else d0 + (s - s0) / (s1 - s0) * (d1 - d0)
    return pairs[-1][1]


def route_kind(vehicle):
    """traffic_state 차량 항목에서 어느 갈래로 가는지: 'A' | 'B' | 'D' | 'B_divert' | None.

    우회는 route_id가 divert_to_B로 시작하는 것으로 알 수 있다(INTERFACE.md). 그 밖에는
    destination_zone(A_stop, B_stop_710 ...)의 첫 글자, 없으면 route_id의 '_to_X'를 본다.
    """
    route_id = (vehicle.get("route_id") or "").split("+")[0]
    if route_id.startswith("divert_to_B"):
        return "B_divert"
    dest = (vehicle.get("destination_zone") or "")[:1].upper()
    if dest in ("A", "B", "D"):
        return dest
    marker = route_id.rsplit("_to_", 1)
    if len(marker) == 2 and marker[1][:1].upper() in ("A", "B", "D"):
        return marker[1][:1].upper()
    return None


def vehicle_role(vehicle):
    """선행/후행은 차 번호가 아니라 route_id로 정해진다(INTERFACE.md)."""
    route_id = vehicle.get("route_id") or ""
    if route_id.startswith("lead"):
        return "lead"
    if route_id.startswith("follow") or route_id.startswith("divert"):
        return "follow"
    return "unknown"


def pedestrian_hazards(message):
    return [h for h in message.get("hazards", []) if h.get("hazard_type") == "person"]


# ---------------------------------------------------------------- UDP 수신

class UdpReceiver:
    """traffic_state를 백그라운드 스레드에서 받아 가장 최근 것만 들고 있는다.
    TraCI는 시뮬레이션 스레드에서만 부를 수 있어서, 여기서는 받기만 한다."""

    def __init__(self, host, port):
        self._lock = threading.Lock()
        self._latest = None
        self._received_at = None
        self.message_count = 0
        self.error = None
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind((host, port))
        self._sock.settimeout(0.5)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hardware-twin-udp", daemon=True)
        self._thread.start()

    def _run(self):
        while not self._stop.is_set():
            try:
                data, _ = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError as exc:
                self.error = str(exc)
                return
            try:
                message = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if message.get("type") != "traffic_state":
                continue
            with self._lock:
                self._latest = message
                self._received_at = time.monotonic()
                self.message_count += 1

    def latest(self):
        with self._lock:
            return self._latest, self._received_at

    def close(self):
        self._stop.set()
        self._sock.close()


# ---------------------------------------------------------------- SUMO에 그리기

class HardwareTwin:
    """매 시뮬레이션 스텝 step(now)을 불러 실물 상황을 SUMO에 반영한다."""

    def __init__(self, config, receiver):
        self.cfg = config
        self.receiver = receiver
        self._lane_idx = config["vehicle_lane_index"]
        self._routes = {}      # kind -> {"edges", "poly", "pairs", "edge_start"}
        self._cars = {}        # 차량 호스트 vehicle_id -> 상태 dict
        self._ped_present = False
        self._ped_last_seen = None
        self._ped_poi = False
        self._last_message = None
        self._ready = False
        self._role_types = None
        self._released = {}    # 넘긴 SUMO id -> 차량 호스트 vehicle_id
        self._release_seq = 0
        self._rng = random.Random()  # 전역 random(사고 발생 seed)을 건드리지 않게 따로 둔다
        self._dest_edges = None

    # --- 준비: SUMO 경로 모양과 기준점 거리 계산 (TraCI 연결 뒤 한 번)
    def _setup(self):
        types = set(traci.vehicletype.getIDList())
        # network/vehicle_style.xml을 불러왔으면 역할별 차 이미지 차종(hwtwin_lead 등)을 쓴다.
        # TraCI로는 imgFile을 못 바꿔서, 없으면 기본 차종을 복사해 색만 바꾸는 방식으로 대신한다.
        if all(f"hwtwin_{r}" in types for r in ROLE_TYPES):
            self._role_types = {r: f"hwtwin_{r}" for r in ROLE_TYPES}
        else:
            self._role_types = None
            if HW_VTYPE not in types:
                base = "DEFAULT_VEHTYPE" if "DEFAULT_VEHTYPE" in types else sorted(types)[0]
                traci.vehicletype.copy(base, HW_VTYPE)
                traci.vehicletype.setShapeClass(HW_VTYPE, "passenger/sedan")
                traci.vehicletype.setLength(HW_VTYPE, 4.6)
                traci.vehicletype.setWidth(HW_VTYPE, 1.9)
                # 신양초 사거리 차도는 custom1만 다닐 수 있다(network/sinyang_closed.edg.xml)
                traci.vehicletype.setVehicleClass(HW_VTYPE, "custom1")
        for kind, zone in (("A", "A"), ("B", "B"), ("D", "D"), ("B_divert", "B")):
            self._routes[kind] = self._build_route(kind, zone)
        self._draw_crosswalk()
        self._ready = True

    def _crossing_frame(self):
        """보행자 지점의 중심 좌표, 진행 방향(SUMO 각도), 차선 폭."""
        p = self.cfg["pedestrian"]
        r = self._routes["A"]
        cx, cy, angle = point_at(r["poly"], r["edge_start"][p["edge"]] + p["offset"])
        width = traci.lane.getWidth(f"{p['edge']}_{self._lane_idx}")
        return cx, cy, angle, width

    def _draw_crosswalk(self):
        """실물 보드 A 도로의 횡단보도처럼 LED 보행자가 건너는 자리에 줄무늬를 그린다."""
        cw = self.cfg["pedestrian"].get("crosswalk")
        if not cw:
            return
        cx, cy, angle, width = self._crossing_frame()
        h = math.radians(angle)
        fwd = (math.sin(h), math.cos(h))
        left = (-math.cos(h), math.sin(h))
        pitch = cw["stripe_m"] + cw["gap_m"]
        n = max(3, int((width + cw["gap_m"]) / pitch))
        start = -(n * pitch - cw["gap_m"]) / 2
        existing = set(traci.polygon.getIDList())
        for i in range(n):
            a = start + i * pitch
            b = a + cw["stripe_m"]
            d = cw["depth_m"] / 2
            pts = [(cx + left[0] * lat + fwd[0] * lon, cy + left[1] * lat + fwd[1] * lon)
                   for lat, lon in ((a, -d), (b, -d), (b, d), (a, d))]
            # sumo-gui는 시계 방향으로 찍힌 채운 다각형을 안 그린다(2026-09-29, 도로 방향이 바뀌며 줄무늬가 사라졌던 원인)
            area = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(pts, pts[1:] + pts[:1]))
            if area < 0:
                pts.reverse()
            pid = f"{CROSSWALK_PREFIX}{i}"
            if pid not in existing:
                # layer 3: 2026-09-29 재빌드한 도로망에선 0.2~2로는 도로 밑에 묻혔다(3 이상이어야 보임)
                traci.polygon.add(pid, pts, tuple(cw["color"]), fill=True, polygonType="hardware crosswalk", layer=3)

    def _build_route(self, kind, zone):
        edges = self.cfg["routes"][zone]
        poly, edge_start = [], {}
        acc = 0.0
        for edge in edges:
            shape = [tuple(p) for p in traci.lane.getShape(f"{edge}_{self._lane_idx}")]
            if poly:
                acc += math.dist(poly[-1], shape[0])  # 사거리 안(내부 차선)은 직선으로 잇는다
            edge_start[edge] = acc
            if poly and math.dist(poly[-1], shape[0]) < 1e-6:
                shape = shape[1:]
            poly.extend(shape if poly else shape)
            acc = polyline_length(poly)
        board = self.cfg["board_paths"][kind]
        first_len = edge_start[edges[1]] if len(edges) > 1 else acc
        first_lane_len = traci.lane.getLength(f"{edges[0]}_{self._lane_idx}")
        junction_d = min(first_len, first_lane_len)
        pairs = []
        for board_pt, sumo_ref in self.cfg["anchors"].get(kind, self.cfg["anchors"][zone]):
            s_b = project_to_polyline(board, board_pt)
            if sumo_ref == "start":
                d = max(0.0, junction_d - self.cfg["approach_m"])
            elif sumo_ref == "junction":
                d = junction_d
            else:
                d = edge_start[sumo_ref["edge"]] + sumo_ref["offset"]
            pairs.append((s_b, d))
        pairs.sort()
        return {"edges": edges, "poly": poly, "pairs": pairs, "edge_start": edge_start,
                "board": board}

    def _sumo_pose(self, kind, x, y):
        r = self._routes[kind]
        s_b = project_to_polyline(r["board"], (x, y))
        d = piecewise_map(r["pairs"], s_b)
        px, py, angle = point_at(r["poly"], d)
        return px, py, angle, d

    # --- 매 스텝
    def step(self, now):
        if not self._ready:
            self._setup()
        message, _ = self.receiver.latest()
        wall = time.monotonic()
        live = set(traci.vehicle.getIDList())
        if message is not None and message is not self._last_message:
            self._last_message = message
            self._apply_vehicles(message, wall, live)
            self._apply_pedestrian(message, wall, now)
        elif self._ped_present and self._ped_last_seen is not None \
                and wall - self._ped_last_seen > self.cfg["pedestrian_clear_after_s"]:
            self._set_pedestrian(False, now)  # 메시지가 끊겨도 보행자가 영원히 남지 않게
        self._hold_positions(live)
        self._forget_stale(wall, live)

    def _apply_vehicles(self, message, wall, live):
        for v in message.get("vehicles", []):
            hid = v.get("vehicle_id")
            if not hid:
                continue
            car = self._cars.setdefault(hid, {"sumo_id": f"{HW_PREFIX}{hid}", "kind": None,
                                               "pose": None, "arrived": False})
            car["last_seen"] = wall
            car["info"] = v
            sumo_id = car["sumo_id"]
            if v.get("arrived"):
                if not car["arrived"]:
                    self._release(hid, car, live)
                    car["arrived"] = True
                    car["pose"] = None
                    car["kind"] = None  # 다음 판에 같은 갈래로 다시 나타나도 새로 만들게
                continue
            car["arrived"] = False
            car.pop("released_as", None)  # 새 판 시작 - 지난 판에 넘긴 차는 SUMO에서 따로 계속 달린다
            kind = route_kind(v)
            if kind is None or not v.get("visible") or v.get("x") is None:
                continue  # 마커를 놓치면 마지막 위치에 그대로 둔다
            if car["kind"] != kind:
                self._change_route(car, kind, live)
            px, py, angle, _ = self._sumo_pose(kind, v["x"], v["y"])
            car["pose"] = (px, py, angle)
            self._color(car, v, kind, live)

    def _change_route(self, car, kind, live):
        sumo_id = car["sumo_id"]
        edges = self._routes[kind]["edges"]
        if sumo_id in live and car["kind"] is not None:
            current = traci.vehicle.getRoadID(sumo_id)
            if current in edges:
                try:
                    traci.vehicle.setRoute(sumo_id, edges[edges.index(current):])
                    car["kind"] = kind
                    return
                except traci.exceptions.TraCIException:
                    pass
            self._remove(sumo_id, live)
        route_id = f"{sumo_id}_route_{kind}"
        if route_id not in traci.route.getIDList():
            traci.route.add(route_id, edges)
        start_d = self._routes[kind]["pairs"][0][1]
        type_id = self._role_types[self._look(car, kind)] if self._role_types else HW_VTYPE
        traci.vehicle.add(sumo_id, route_id, typeID=type_id, depart="now",
                          departLane=str(self._lane_idx), departPos=f"{start_d:.1f}", departSpeed="0")
        try:
            traci.vehicle.setSpeedMode(sumo_id, 0)
            traci.vehicle.setLaneChangeMode(sumo_id, 0)
        except traci.exceptions.TraCIException:
            pass
        car["kind"] = kind

    @staticmethod
    def _look(car, kind):
        """그림 역할: 우회 중이면 diverted, 아니면 선행/후행(모르면 후행 모양)."""
        if kind == "B_divert":
            return "diverted"
        role = vehicle_role(car.get("info", {}))
        return role if role in ("lead", "follow") else "follow"

    def _color(self, car, v, kind, live):
        look = self._look(car, kind)
        if car.get("look") == look or car["sumo_id"] not in traci.vehicle.getIDList():
            return
        if self._role_types:
            traci.vehicle.setType(car["sumo_id"], self._role_types[look])
        else:
            colors = self.cfg["colors"]
            color = colors["diverted"] if kind == "B_divert" else colors[vehicle_role(v)]
            traci.vehicle.setColor(car["sumo_id"], tuple(color))
        car["look"] = look

    def _hold_positions(self, live):
        """moveToXY는 한 스텝만 유효하다 - 매 스텝 마지막 목표 위치에 다시 놓아
        SUMO가 차를 제멋대로 몰고 가지 않게 한다(실물이 서 있으면 SUMO 차도 서 있음)."""
        live = set(traci.vehicle.getIDList())
        for car in self._cars.values():
            if car["pose"] is None or car["sumo_id"] not in live:
                continue
            x, y, angle = car["pose"]
            try:
                traci.vehicle.setSpeed(car["sumo_id"], 0)
                traci.vehicle.moveToXY(car["sumo_id"], "", self._lane_idx, x, y, angle, keepRoute=1)
            except traci.exceptions.TraCIException:
                pass

    def _forget_stale(self, wall, live):
        for hid, car in list(self._cars.items()):
            if wall - car.get("last_seen", wall) > self.cfg["forget_after_s"]:
                # 사거리를 이미 지났으면 보드 밖으로 나간 것으로 보고 일반 차량으로 넘긴다. 진입로에서 끊겼으면 지운다.
                if not car["arrived"] and not self._release(hid, car, live, require_past_junction=True):
                    self._remove(car["sumo_id"], live)
                del self._cars[hid]
        gone = [s for s in self._released if s not in live]
        if gone:
            pending = set(traci.simulation.getPendingVehicles())  # 방금 넣어 아직 도로에 안 올라간 차는 남긴다
            for sumo_id in gone:
                if sumo_id not in pending:
                    del self._released[sumo_id]  # 목적지 도착·견인 등으로 사라진 차

    # --- 보드에서 나온 차를 일반 SUMO 차량으로 넘기기
    def _release(self, hid, car, live, require_past_junction=False):
        """보드 차(HW_PREFIX)를 지우고 같은 자리에 같은 그림의 일반 차량(RELEASED_PREFIX)을 넣는다.
        넘겼으면 새 SUMO id, 못 넘겼으면(차가 없음, 사거리 전, 갈 곳 없음) None - 보드 차는 어느 쪽이든 지운다."""
        sumo_id = car["sumo_id"]
        if sumo_id not in live and sumo_id not in traci.vehicle.getIDList():
            return None
        try:
            edge = traci.vehicle.getRoadID(sumo_id)
            pos = traci.vehicle.getLanePosition(sumo_id)
            type_id = traci.vehicle.getTypeID(sumo_id)
        except traci.exceptions.TraCIException:
            return None
        route_edges = self._routes[car["kind"]]["edges"] if car.get("kind") in self._routes else []
        if edge.startswith(":") or edge not in route_edges:
            # 사거리 안(내부 차선)에는 차를 넣을 수 없다 - 나가는 도로 시작점에서 이어 간다
            edge, pos = (route_edges[-1], 0.0) if route_edges else (edge, pos)
        if require_past_junction and route_edges and edge == route_edges[0]:
            return None
        self._remove(sumo_id, live)
        car["pose"] = None
        route = self._release_route(edge, type_id)
        if route is None:
            return None
        self._release_seq += 1
        new_id = f"{RELEASED_PREFIX}{hid}_{self._release_seq}"
        traci.route.add(f"{new_id}_route", route)
        pos = min(pos, max(0.0, traci.lane.getLength(f"{edge}_{self._lane_idx}") - 1.0))
        traci.vehicle.add(new_id, f"{new_id}_route", typeID=type_id, depart="now",
                          departLane=str(self._lane_idx), departPos=f"{pos:.1f}", departSpeed="0")
        self._released[new_id] = hid
        car["released_as"] = new_id
        return new_id

    def _release_route(self, from_edge, type_id):
        """from_edge에서 RELEASE_MIN_ROUTE_M 이상 떨어진 무작위 목적지까지의 경로(없으면 None)."""
        if self._dest_edges is None:
            self._dest_edges = [e for e in traci.edge.getIDList() if not e.startswith(":")]
        best = None
        for _ in range(RELEASE_DEST_TRIES):
            dest = self._rng.choice(self._dest_edges)
            try:
                r = traci.simulation.findRoute(from_edge, dest, vType=type_id)
            except traci.exceptions.TraCIException:
                continue
            if not r.edges:
                continue
            if r.length >= RELEASE_MIN_ROUTE_M:
                return list(r.edges)
            if best is None or r.length > best[0]:
                best = (r.length, list(r.edges))
        return best[1] if best else None

    def _remove(self, sumo_id, live):
        if sumo_id in live or sumo_id in traci.vehicle.getIDList():
            try:
                traci.vehicle.remove(sumo_id)
            except traci.exceptions.TraCIException:
                pass

    # --- 보행자 LED
    def _apply_pedestrian(self, message, wall, now):
        peds = pedestrian_hazards(message)
        if peds:
            self._ped_last_seen = wall
            if not self._ped_present:
                self._set_pedestrian(True, now)
            self._draw_pedestrian(peds[0])
        elif self._ped_present and wall - (self._ped_last_seen or wall) > self.cfg["pedestrian_clear_after_s"]:
            self._set_pedestrian(False, now)

    def _set_pedestrian(self, present, now):
        # cctv_detector는 import하는 순간 광진구 net 전체를 읽으므로 쓸 때만 불러온다(테스트가 가볍게).
        from cctv_detector import set_hardware_pedestrian_present
        self._ped_present = present
        set_hardware_pedestrian_present(present, now)
        if not present and self._ped_poi:
            try:
                traci.poi.remove(PEDESTRIAN_POI)
            except traci.exceptions.TraCIException:
                pass
            self._ped_poi = False

    def _pedestrian_xy(self, hazard_y):
        p = self.cfg["pedestrian"]
        r = self._routes["A"]
        d = r["edge_start"][p["edge"]] + p["offset"]
        cx, cy, angle = point_at(r["poly"], d)
        frac = (hazard_y - p["road_y_min"]) / (p["road_y_max"] - p["road_y_min"])
        frac = max(-0.4, min(1.4, frac))
        # 보드의 y는 D쪽(작음)에서 B쪽(큼)으로 커지고, C→A 진행 방향 기준 D는 오른쪽, B는 왼쪽이다.
        lateral_left = (frac - 0.5) * p["road_width_m"]
        heading = math.radians(angle)
        left = (-math.cos(heading), math.sin(heading))  # SUMO 각도(북 0, 시계방향) 기준 왼쪽 단위벡터
        return cx + left[0] * lateral_left, cy + left[1] * lateral_left

    def _draw_pedestrian(self, hazard):
        x, y = self._pedestrian_xy(hazard.get("y", 0.5))
        color = tuple(self.cfg["colors"]["pedestrian"])
        if not self._ped_poi:
            p = self.cfg["pedestrian"]
            image = os.path.abspath(p["image"]) if p.get("image") and os.path.exists(p["image"]) else ""
            size = p.get("image_size_m", 2.5) if image else 2.5
            # LED는 D쪽에서 B쪽으로, 즉 C→A 진행 방향의 오른쪽에서 왼쪽으로 건넌다
            _, _, road_angle, _ = self._crossing_frame()
            traci.poi.add(PEDESTRIAN_POI, x, y, color, poiType="hardware pedestrian", layer=30,
                          imgFile=image, width=size, height=size, angle=(road_angle - 90) % 360)
            self._ped_poi = True
        else:
            traci.poi.setPosition(PEDESTRIAN_POI, x, y)

    # --- 대시보드 표시용
    def status(self):
        message, received_at = self.receiver.latest()
        age = None if received_at is None else time.monotonic() - received_at
        cars = []
        for hid, car in sorted(self._cars.items()):
            v = car.get("info", {})
            cars.append({
                "vehicle_id": hid,
                "sumo_id": car["sumo_id"],
                "role": vehicle_role(v),
                "command": v.get("command"),
                "route_id": v.get("route_id"),
                "destination_zone": v.get("destination_zone"),
                "visible": bool(v.get("visible")),
                "arrived": car["arrived"],
                "released_as": car.get("released_as"),
            })
        return {
            "connected": age is not None and age <= self.cfg["stale_after_s"],
            "last_message_age_s": None if age is None else round(age, 1),
            "message_count": self.receiver.message_count,
            "scenario_state": (message or {}).get("scenario_state"),
            "pedestrian": self._ped_present,
            "vehicles": cars,
            "released": sorted(self._released),  # 보드에서 나와 일반 차량으로 달리는 중인 SUMO id
            "error": self.receiver.error,
        }
