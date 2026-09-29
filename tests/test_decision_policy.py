"""decision_policy.decide_actions() 단위 테스트. TraCI/SUMO 없이 실행 가능하다."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from decision_policy import decide_actions


def test_no_alerts_produces_no_commands():
    assert decide_actions([]) == []


def test_pedestrian_on_hazard_edge_gets_stop():
    alerts = [{
        "type": "pedestrian_detected", "edge": "E1",
        "vehicles_in_hazard_edge": ["v1"], "vehicles_nearby": [], "vehicles_reroutable": [],
    }]
    commands = decide_actions(alerts)
    assert len(commands) == 1
    assert commands[0]["veh_id"] == "v1"
    assert commands[0]["action"] == "stop"
    assert commands[0]["target_speed"] == 0.0


def test_congestion_never_produces_stop():
    alerts = [{
        "type": "congestion_detected", "edge": "E1",
        "vehicles_in_hazard_edge": ["v1"], "vehicles_nearby": [], "vehicles_reroutable": [],
    }]
    commands = decide_actions(alerts)
    assert len(commands) == 1
    assert commands[0]["veh_id"] == "v1"
    assert commands[0]["action"] == "decelerate"


def test_reroutable_vehicle_gets_reroute_not_slow():
    alerts = [{
        "type": "pedestrian_detected", "edge": "E1",
        "vehicles_in_hazard_edge": [], "vehicles_nearby": [], "vehicles_reroutable": ["v1"],
    }]
    commands = decide_actions(alerts)
    assert len(commands) == 1
    assert commands[0]["action"] == "reroute"
    assert commands[0]["avoid_edge"] == "E1"


def test_each_vehicle_gets_at_most_one_command():
    alerts = [
        {"type": "pedestrian_detected", "edge": "E1",
         "vehicles_in_hazard_edge": ["v1"], "vehicles_nearby": ["v1"], "vehicles_reroutable": ["v1"]},
    ]
    commands = decide_actions(alerts)
    assert len(commands) == 1
    assert commands[0]["action"] == "stop"


def test_stop_takes_priority_over_reroute_and_slow():
    alerts = [{
        "type": "pedestrian_detected", "edge": "E1",
        "vehicles_in_hazard_edge": ["v1"], "vehicles_nearby": ["v2"], "vehicles_reroutable": ["v3"],
    }]
    by_vehicle = {c["veh_id"]: c["action"] for c in decide_actions(alerts)}
    assert by_vehicle == {"v1": "stop", "v2": "decelerate", "v3": "reroute"}


if __name__ == "__main__":
    import sys

    failures = 0
    module = sys.modules[__name__]
    for name in dir(module):
        if name.startswith("test_"):
            try:
                getattr(module, name)()
                print(f"PASS {name}")
            except AssertionError as exc:
                failures += 1
                print(f"FAIL {name}: {exc}")
    if failures:
        raise SystemExit(f"{failures} test(s) failed")
    print("all tests passed")
