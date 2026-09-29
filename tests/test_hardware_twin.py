"""hardware_twin의 순수 함수(좌표 투영/보간, 경로·역할 판별) 테스트. SUMO 없이 돈다."""

import json
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from hardware_twin import (  # noqa: E402
    is_hardware_twin, piecewise_map, point_at, polyline_length, project_to_polyline,
    pedestrian_hazards, route_kind, vehicle_role,
)

CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs", "hardware_twin.json")


def test_projection_on_straight_line():
    poly = [(0.0, 0.0), (10.0, 0.0)]
    assert project_to_polyline(poly, (3.0, 2.0)) == 3.0
    assert project_to_polyline(poly, (-5.0, 0.0)) == 0.0
    assert project_to_polyline(poly, (50.0, 1.0)) == 10.0


def test_projection_on_bent_line_counts_arc_length():
    poly = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]
    assert math.isclose(project_to_polyline(poly, (11.0, 4.0)), 14.0)
    assert polyline_length(poly) == 20.0


def test_point_at_gives_sumo_angle():
    # SUMO 각도: 북쪽 0도, 시계방향 - 동쪽으로 가면 90, 북쪽으로 가면 0
    x, y, a = point_at([(0.0, 0.0), (10.0, 0.0)], 4.0)
    assert (x, y) == (4.0, 0.0) and math.isclose(a, 90.0)
    x, y, a = point_at([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)], 15.0)
    assert (x, y) == (10.0, 5.0) and math.isclose(a, 0.0)
    x, y, _ = point_at([(0.0, 0.0), (10.0, 0.0)], 99.0)
    assert (x, y) == (10.0, 0.0)


def test_piecewise_map_interpolates_and_clamps():
    pairs = [(0.0, 50.0), (1.0, 120.0), (2.0, 130.0)]
    assert piecewise_map(pairs, -1.0) == 50.0
    assert piecewise_map(pairs, 0.5) == 85.0
    assert piecewise_map(pairs, 1.5) == 125.0
    assert piecewise_map(pairs, 9.0) == 130.0


def test_route_kind_from_destination_and_divert():
    assert route_kind({"route_id": "lead_C_to_A+entry", "destination_zone": "A_stop"}) == "A"
    assert route_kind({"route_id": "follow_C_to_A+plan", "destination_zone": "A_stop"}) == "A"
    # 후행이 막혀 B로 우회하면 route_id가 divert_to_B_x710 등으로 바뀐다(INTERFACE.md)
    assert route_kind({"route_id": "divert_to_B_x710", "destination_zone": "B_stop_710"}) == "B_divert"
    assert route_kind({"route_id": "lead_C_to_D", "destination_zone": None}) == "D"
    assert route_kind({"route_id": "", "destination_zone": ""}) is None


def test_role_comes_from_route_id_not_car_number():
    assert vehicle_role({"vehicle_id": "car_3", "route_id": "lead_C_to_A+entry"}) == "lead"
    assert vehicle_role({"vehicle_id": "car_2", "route_id": "follow_C_to_A"}) == "follow"
    assert vehicle_role({"vehicle_id": "car_2", "route_id": "divert_to_B_x680"}) == "follow"
    assert vehicle_role({"vehicle_id": "car_1", "route_id": None}) == "unknown"


def test_only_person_hazards_count_as_pedestrian():
    msg = {"hazards": [{"hazard_type": "person", "x": 0.3, "y": 0.4},
                       {"hazard_type": "obstacle", "x": 0.5, "y": 0.5}]}
    assert len(pedestrian_hazards(msg)) == 1
    assert pedestrian_hazards({}) == []


def test_hardware_twin_prefix():
    assert is_hardware_twin("hwtwin_car_2")
    assert not is_hardware_twin("1234")


def test_config_anchor_points_lie_on_board_paths():
    """기준점이 해당 주행선에서 멀리 떨어져 있으면 보간이 엉뚱해진다 - 5cm 이내인지 확인."""
    cfg = json.load(open(CONFIG, encoding="utf-8"))
    for kind, path in cfg["board_paths"].items():
        if kind.startswith("_"):
            continue
        anchors = cfg["anchors"][kind]
        for board_pt, _ in anchors:
            s = project_to_polyline(path, board_pt)
            x, y, _ = point_at(path, s)
            assert math.dist((x, y), board_pt) < 0.05, (kind, board_pt)
        # 기준점은 주행선을 따라 순서대로 놓여 있어야 한다
        ss = [project_to_polyline(path, p) for p, _ in anchors]
        assert ss == sorted(ss), kind
