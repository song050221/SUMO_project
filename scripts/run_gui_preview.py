"""발표용 SUMO-GUI 미리보기. sumo-gui 창을 띄워 실제 화면에 재생될 모습을 그대로 보여준다.

--mode treatment: central_server.py + cctv_detector.py(9개 구역) + vehicle_controller.py가
개입하는 중앙집중형 시나리오 (심사위원에게 보여줄 핵심 장면).
--mode baseline: TraCI 개입 없는 분산형 시나리오 (비교용).
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

import traci

from cctv_detector import (
    poll_all_zones, get_active_accident_edges, edge_midpoint,
    edge_point_near_start, HARDWARE_PEDESTRIAN_EDGE,
)
from central_server import CentralServer
from gui_viewport import write_zone_viewport, ACCIDENT_COLOR
from vehicle_controller import execute_commands
from stuck_vehicle_remover import StuckVehicleRemover

NET_FILE = "network/gwangjin.net.xml"
ROUTES_FILE = "network/routes.xml,network/pedestrian_routes.xml"
# 시연용 배경(OSM 지도 화풍으로 다시 칠한 건물·녹지·물 + 나무) + 차량/보행자 그림(차종 묶음, 사람 이미지).
# 둘 다 scripts/build_styled_polys.py, scripts/build_visual_assets.py로 다시 만들 수 있다. 예전 조합은
# "network/gwangjin.poly.xml,network/pedestrian_style.xml"(vehicle_style.xml이 보행자 색 재정의도 포함).
POLY_FILE = "network/gwangjin_styled.poly.xml,network/vehicle_style.xml"
SIM_END = 3600


def run(mode, speed, seed, zone, view_width_m):
    cmd = [
        "sumo-gui",
        "-n", NET_FILE,
        "-r", ROUTES_FILE,
        "-a", POLY_FILE,
        "--begin", "0",
        "--end", str(SIM_END),
        "--seed", str(seed),
        "--collision.action", "warn",
        "--collision.check-junctions", "true",
        "--collision.mingap-factor", "0",
        "--intermodal-collision.action", "warn",
        "--start",              # 창이 뜨자마자 자동 재생 (발표 중 버튼 조작 불필요)
    ]
    viewport_path = write_zone_viewport(zone_id=zone or None, view_width_m=view_width_m)
    cmd += ["--gui-settings-file", viewport_path]
    traci.start(cmd)
    server = CentralServer()
    remover = StuckVehicleRemover()
    rendered_accident_pois = set()

    step = 0
    while step < SIM_END:
        step_started = time.monotonic()
        traci.simulationStep()

        remover.step(traci.simulation.getTime())

        if mode == "treatment":
            server.initial_optimization()
            alerts = poll_all_zones()
            commands = server.handle_cctv_alert(alerts)
            execute_commands(commands)

            active = get_active_accident_edges()
            for edge in active - rendered_accident_pois:
                # dashboard_server.py의 _accident_marker_point()와 같은 이유: 하드웨어
                # 보행자 사고는 도로 초입부(교차로 쪽)에 찍어야 한다.
                x, y = edge_point_near_start(edge, 10.0) if edge == HARDWARE_PEDESTRIAN_EDGE else edge_midpoint(edge)
                traci.poi.add(f"accident_{edge}", x, y, ACCIDENT_COLOR, layer=20, width=10, height=10)
                rendered_accident_pois.add(edge)
            for edge in rendered_accident_pois - active:
                traci.poi.remove(f"accident_{edge}")
                rendered_accident_pois.discard(edge)

        step += 1
        # 재생 속도: speed=1이면 시뮬레이션 1초를 실제 1초에 맞춘다(차 속도가 현실과 같아 보임). 계산 시간을 빼고
        # 남은 만큼만 기다리므로 고정 --delay보다 정확하다(dashboard_server.py와 같은 방식, 2026-09-29).
        if speed > 0:
            wait = traci.simulation.getDeltaT() / speed - (time.monotonic() - step_started)
            if wait > 0:
                time.sleep(wait)

    traci.close()


def parse_args():
    parser = argparse.ArgumentParser(description="발표용 SUMO-GUI 미리보기")
    parser.add_argument("--mode", choices=["baseline", "treatment"], default="treatment")
    parser.add_argument("--speed", type=float, default=1.0,
                        help="재생 배속 - 1이면 실제 시간(기본), 5면 5배속, 0이면 최대 속도")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--zone", default="zone_1",
                         help="시작 시 확대해서 보여줄 CCTV 구역 (cctv_zones.json 기준, 빈 문자열이면 전체 네트워크)")
    parser.add_argument("--view-width-m", type=int, default=250,
                         help="확대했을 때 화면에 보일 실제 폭(미터), 작을수록 더 확대됨")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args.mode, args.speed, args.seed, args.zone, args.view_width_m)
