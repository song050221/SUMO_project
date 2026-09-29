"""그리드락(2방향 이상 동시 정지)·만성 정체(한 방향이라도 오래 심하게 막힘)를
실측하는 진단 스크립트. 신호/알고리즘을 바꾼 뒤 "실제로 나아졌는가"를 확인할 때 쓴다.

2026-09-25~26 세션에서 이 계측 없이(또는 seed 고정 없이) "이전/이후"를 비교했다가
잘못된 결론을 낸 적이 여러 번 있었다 - 반드시 이 스크립트로, 여러 seed에 대해
평균을 내서 비교할 것 (`docs/HANDOFF_PROMPT.md`의 "알아두면 좋은 함정들" 참고).

사용법: python scripts/measure_congestion.py --seeds 1 2 3 4 5
(experiment_data/routes_seed{N}.xml, pedestrian_routes_seed{N}.xml이 미리 있어야 함 -
run_single_simulation.py의 ensure_demand()로 생성)
"""

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

import sumolib
import traci

from cctv_detector import poll_all_zones, reset_accidents
from central_server import CentralServer
from vehicle_controller import execute_commands
from signal_controller import SignalController
from predictive_reroute import PredictiveRerouter
from stuck_vehicle_remover import StuckVehicleRemover

NET_FILE = "network/gwangjin.net.xml"
RUN_SECONDS = 3600
SEVERE_SPEED = 2.0          # m/s, 이 이하면 "심하게 막힘"
SUSTAIN_THRESHOLD = 120.0   # s, 이만큼 연속으로 심하게 막혀야 "만성 정체"로 침
DEADLOCK_HALT_THRESHOLD = 60.0  # s, 이만큼 연속 정지해야 "그리드락 후보" 방향으로 침
CHECK_INTERVAL = 10.0
PROGRESS_EVERY = 300  # 스텝, 진행 상황 출력 주기


def measure(seed, net, net_file=NET_FILE, route_dir="experiment_data"):
    random.seed(seed)  # cctv_detector의 사고 발생은 SUMO --seed와 무관한 별개 난수 상태
    reset_accidents()  # seed 여러 개를 한 프로세스에서 돌리므로 앞 seed의 사고·다음 사고 시각이 남지 않게

    edge_to_node = {e.getID(): e.getToNode().getID() for e in net.getEdges()}
    edge_bad_since = {}
    chronic_events = []
    junction_deadlock_since = {}
    deadlock_events = []

    collisions = 0
    arrived = 0

    traci.start([
        "sumo", "-n", net_file,
        "-r", f"{route_dir}/routes_seed{seed}.xml,{route_dir}/pedestrian_routes_seed{seed}.xml",
        "--begin", "0", "--end", str(RUN_SECONDS), "--seed", str(seed),
        "--collision.action", "warn", "--collision.check-junctions", "true",
        "--collision.mingap-factor", "0", "--intermodal-collision.action", "warn",
        "--ignore-route-errors", "true", "--no-step-log", "true",
    ])

    server = CentralServer()
    signals = SignalController()
    predictor = PredictiveRerouter(net)
    remover = StuckVehicleRemover()

    last_check = -CHECK_INTERVAL
    step = 0
    while step < RUN_SECONDS:
        traci.simulationStep()
        collisions += len(traci.simulation.getCollisions())
        arrived += traci.simulation.getArrivedNumber()
        now = traci.simulation.getTime()
        remover.step(now)
        server.initial_optimization()
        alerts = poll_all_zones()
        commands = server.handle_cctv_alert(alerts)
        execute_commands(commands)
        signals.step(now)
        predictor.step(now)
        server.update_throughput()

        if now - last_check >= CHECK_INTERVAL:
            last_check = now

            active_edges = set()
            for veh_id in traci.vehicle.getIDList():
                e = traci.vehicle.getRoadID(veh_id)
                if e and not e.startswith(":"):
                    active_edges.add(e)

            currently_bad = set()
            # 집합은 실행마다 도는 순서가 달라진다 - 순서를 고정해 같은 seed면 같은 결과가 나오게(2026-09-28)
            for e in sorted(active_edges):
                speed = traci.edge.getLastStepMeanSpeed(e)
                n = traci.edge.getLastStepVehicleNumber(e)
                if n > 0 and speed < SEVERE_SPEED:
                    currently_bad.add(e)
                    edge_bad_since.setdefault(e, now)
            for e in list(edge_bad_since):
                if e not in currently_bad:
                    start = edge_bad_since.pop(e)
                    dur = now - start
                    if dur >= SUSTAIN_THRESHOLD:
                        chronic_events.append({"edge": e, "duration": dur})

            junction_edges_halted = {}
            for veh_id in traci.vehicle.getIDList():
                edge_id = traci.vehicle.getRoadID(veh_id)
                node_id = edge_to_node.get(edge_id)
                if node_id is None:
                    continue
                wt = traci.vehicle.getWaitingTime(veh_id)
                d = junction_edges_halted.setdefault(node_id, {})
                if wt > d.get(edge_id, 0.0):
                    d[edge_id] = wt
            for node_id, edges in sorted(junction_edges_halted.items()):
                if len(edges) < 2:
                    junction_deadlock_since.pop(node_id, None)
                    continue
                all_halted = all(wt >= DEADLOCK_HALT_THRESHOLD for wt in edges.values())
                if all_halted:
                    junction_deadlock_since.setdefault(node_id, now)
                else:
                    if node_id in junction_deadlock_since:
                        start = junction_deadlock_since.pop(node_id)
                        deadlock_events.append({"node": node_id, "duration": now - start})

        step += 1
        if step % PROGRESS_EVERY == 0:
            # 오래 걸리는 seed가 어디쯤인지 보이게(2026-09-29 - 수요를 늘린 뒤 seed 하나가 50분 넘게 걸렸는데
            # 진행 상황을 알 수 없었다)
            print(f"[seed {seed}] {step}/{RUN_SECONDS}s 차량 {traci.vehicle.getIDCount()} 견인 {remover.total_removed} "
                  f"도착 {arrived}", flush=True)

    for e, start in list(edge_bad_since.items()):
        dur = RUN_SECONDS - start
        if dur >= SUSTAIN_THRESHOLD:
            chronic_events.append({"edge": e, "duration": dur})
    for node_id, start in list(junction_deadlock_since.items()):
        deadlock_events.append({"node": node_id, "duration": RUN_SECONDS - start})

    traci.close()

    return {
        "seed": seed,
        "chronic_total_events": len(chronic_events),
        "chronic_total_seconds": sum(e["duration"] for e in chronic_events),
        "deadlock_total_events": len(deadlock_events),
        "deadlock_total_seconds": sum(e["duration"] for e in deadlock_events),
        "collisions": collisions,
        "tows": remover.total_removed,  # 견인(막힌 차 강제 제거) 횟수 - 막힘을 가장 직접 보여줌
        "arrived": arrived,
        # 어느 교차로/도로가 나빠졌는지 가리려고 위치별 합계도 남긴다(2026-09-28 추가) -
        # 사거리 여러 곳을 한 번에 고친 뒤 전체 합계만으로는 어느 곳 탓인지 알 수 없었음.
        "deadlock_by_node": _sum_by(deadlock_events, "node"),
        "chronic_by_edge": _sum_by(chronic_events, "edge"),
    }


def _sum_by(events, key):
    out = {}
    for e in events:
        out[e[key]] = out.get(e[key], 0.0) + e["duration"]
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    parser.add_argument("--out", default="experiment_data/congestion_measurement.json")
    parser.add_argument("--net", default=NET_FILE, help="비교용으로 백업 net.xml 등 다른 네트워크를 잴 때")
    parser.add_argument("--route-dir", default="experiment_data",
                        help="routes_seed{N}.xml이 있는 폴더 - 백업 net은 그 net에 맞는 백업 경로로 재야 함")
    args = parser.parse_args()

    net = sumolib.net.readNet(args.net)
    # cctv_detector는 import 시점에 network/gwangjin.net.xml을 읽어 상류 edge를 찾는다 -
    # 다른 net을 잴 때 그대로 두면 없는 edge를 조회하다 죽거나 상류 범위가 틀어진다.
    import cctv_detector
    cctv_detector._NET = net
    cctv_detector._UPSTREAM_CACHE.clear()
    # seed별 수요 파일이 없으면(저장소에는 용량 때문에 안 올림) 실험과 같은 조건으로 먼저 만든다 - 순차로(병렬 생성은 충돌)
    if args.route_dir == "experiment_data":
        from run_single_simulation import ensure_demand, ensure_pedestrian_demand
        for seed in args.seeds:
            ensure_demand(seed)
            ensure_pedestrian_demand(seed)

    results = []
    for seed in args.seeds:
        results.append(measure(seed, net, args.net, args.route_dir))
        # seed가 끝날 때마다 저장 - 중간에 멈춰도 끝난 seed 결과는 남게(2026-09-29)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"net": args.net, "per_seed": results, "partial": len(results) < len(args.seeds)},
                      f, ensure_ascii=False, indent=2)

    n = len(results)
    avg_chronic = sum(r["chronic_total_seconds"] for r in results) / n
    avg_deadlock = sum(r["deadlock_total_seconds"] for r in results) / n
    avg_collisions = sum(r["collisions"] for r in results) / n
    avg_tows = sum(r["tows"] for r in results) / n
    avg_arrived = sum(r["arrived"] for r in results) / n
    summary = {"net": args.net, "per_seed": results, "avg_chronic_seconds": avg_chronic,
               "avg_deadlock_seconds": avg_deadlock, "avg_collisions": avg_collisions,
               "avg_tows": avg_tows, "avg_arrived": avg_arrived}

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"평균 만성정체: {avg_chronic:.0f}s, 평균 그리드락: {avg_deadlock:.0f}s, "
          f"평균 충돌: {avg_collisions:.1f}건, 평균 견인: {avg_tows:.0f}대, 평균 도착: {avg_arrived:.0f}대 "
          f"({args.out}에 저장됨)")
