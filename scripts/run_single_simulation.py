import argparse
import csv
import os
import random
import subprocess
import sys

# core/의 공용 로직을 flat import로 그대로 쓸 수 있도록 경로에 추가한다
# (core/scripts/tests로 나뉘기 전 import 문을 그대로 유지하기 위함).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

import sumolib
import traci

from cctv_detector import poll_all_zones
from central_server import CentralServer
from vehicle_controller import execute_commands
from signal_controller import SignalController
from predictive_reroute import PredictiveRerouter
from stuck_vehicle_remover import StuckVehicleRemover

NET_FILE = "network/gwangjin.net.xml"
SIM_END = 3600
EMERGENCY_BRAKE_THRESHOLD = -4.5
# seed별로 생성되는 routes/collisions 파일은 20개 x 여러 종류라 용량이 크고 개수가 많다 -
# 루트 폴더를 어지럽히지 않도록 전용 폴더에 모아 둔다. 집계 결과 CSV도 같은 이유로
# 여기에 둔다(대시보드의 /api/comparison도 이 경로를 그대로 읽음, dashboard_server.py 참고).
EXPERIMENT_DATA_DIR = "experiment_data"
RESULTS_FILE = os.path.join(EXPERIMENT_DATA_DIR, "results.csv")


def _seed_path(filename):
    os.makedirs(EXPERIMENT_DATA_DIR, exist_ok=True)
    return os.path.join(EXPERIMENT_DATA_DIR, filename)


def ensure_demand(seed):
    """seed별 차량 demand(routes)를 생성해 캐시한다.

    baseline/treatment 비교쌍은 같은 seed에서 동일 demand를 공유해야 하므로,
    이미 생성된 파일이 있으면 재사용한다. trips.xml은 routes.xml로 변환되고 나면
    다시 쓰이지 않는 중간 산출물이라, 생성 직후 지워서 불필요한 파일이 안 남게 한다.
    """
    trips_file = _seed_path(f"trips_seed{seed}.xml")
    routes_file = _seed_path(f"routes_seed{seed}.xml")
    if not os.path.exists(routes_file):
        sumo_home = os.environ["SUMO_HOME"]
        # randomTrips.py는 기본값(--validate)으로 생성한 trip이 실제로 라우팅되는지 자체
        # duarouter 패스로 거른다. 이때 검증용 route 출력을 --route-file로 지정하면
        # (seed별로 다른 파일명을 줘서 동시 실행 충돌을 피하려던 시도, 2026-09-07)
        # 왜인지 randomTrips.py의 재시도 로직이 훨씬 일찍 포기해서 4800대 요청에
        # 250대 안팎만 만들고 끝나버린다(실측 확인 - --route-file 없이 기본 파일명
        # "routes.rou.xml"을 쓰면 4800대 정상 생성됨). 그래서 --route-file은 쓰지 않고,
        # 대신 seed를 병렬로 여러 개 돌릴 땐 반드시 이 demand 생성 단계만 먼저 순차로
        # 끝내둔다(caller 쪽 책임 - ensure_demand는 캐시가 있으면 재생성을 건너뛰므로,
        # 미리 순차 생성해두면 병렬 시뮬레이션 단계에서 이 함수가 아예 호출되지 않는다).
        subprocess.run(
            # -p 0.5(7200대): 대시보드 network/routes.xml과 같은 조건 - 실험 조건이 데모와 다르면
            # 비교 의미가 없음. 2026-08-10에 충돌이 늘어 0.75(4800대)로 낮췄다가, 2026-09-29 도로망
            # 재빌드로 충돌·견인이 크게 줄어 사용자 요청으로 다시 0.5로 올림.
            ["python", f"{sumo_home}/tools/randomTrips.py",
             "-n", NET_FILE, "-o", trips_file, "-p", "0.5", "-e", str(SIM_END), "--seed", str(seed)],
            check=True,
        )
        subprocess.run(
            ["duarouter", "-n", NET_FILE, "-t", trips_file, "-o", routes_file,
             "--seed", str(seed), "--alternatives-output", "NUL"],
            check=True,
        )
        os.remove(trips_file)
    return routes_file


def ensure_pedestrian_demand(seed):
    """차량 seed와 별도(+1)로 고정한 seed로 도시 전역 무작위 보행자 demand를 생성한다.

    --pedestrians로 네트워크 전역 임의 위치에서 발생시킨다 (특정 지점 지정 안 함).
    """
    pedestrian_seed = seed + 1
    trips_file = _seed_path(f"pedestrian_trips_seed{seed}.xml")
    routes_file = _seed_path(f"pedestrian_routes_seed{seed}.xml")
    if not os.path.exists(routes_file):
        sumo_home = os.environ["SUMO_HOME"]
        subprocess.run(
            ["python", f"{sumo_home}/tools/randomTrips.py",
             "-n", NET_FILE, "-o", trips_file, "--pedestrians", "--max-distance", "300",
             # -p 4(시간당 약 900명): 2026-09-29 사용자 요청으로 8(약 450명)에서 2배로
             "-p", "4", "-e", str(SIM_END), "--seed", str(pedestrian_seed)],
            check=True,
        )
        subprocess.run(
            ["duarouter", "-n", NET_FILE, "-t", trips_file, "-o", routes_file,
             "--seed", str(pedestrian_seed), "--alternatives-output", "NUL"],
            check=True,
        )
        os.remove(trips_file)
    return routes_file


def run(seed, mode):
    # cctv_detector.py의 사고 발생(update_accidents)·하드웨어 목적지 선택은 Python
    # 표준 random 모듈을 쓰는데, 이건 SUMO의 --seed(차량 흐름/차선변경 등 SUMO 내부
    # 난수)와는 완전히 별개 상태라 여기서 직접 고정 안 하면 매 프로세스 실행마다
    # OS 엔트로피로 새로 시드된다 - "같은 seed인데 실행할 때마다 사고가 다르게 나는"
    # 재현 불가 문제였다(2026-09-10, 소거 실험 중 발견 - treatment를 두 번 따로 돌렸더니
    # 사고 시점/위치가 달라서 숫자가 안 맞았음). SUMO seed와 동일한 값으로 고정한다.
    random.seed(seed)
    routes_file = ensure_demand(seed)
    pedestrian_routes_file = ensure_pedestrian_demand(seed)
    collision_out = _seed_path(f"collisions_seed{seed}_{mode}.xml")

    cmd = [
        "sumo",
        "-n", NET_FILE,
        "-r", f"{routes_file},{pedestrian_routes_file}",
        "--begin", "0",
        "--end", str(SIM_END),
        "--seed", str(seed),
        "--collision.action", "warn",
        "--collision.check-junctions", "true",
        "--collision.mingap-factor", "0",
        "--intermodal-collision.action", "warn",
        "--collision-output", collision_out,
        # 캐시된 일부 seed의 보행자 경로에 간헐적으로 라우팅 불가능한 walk가 섞여있어
        # (seed 1에서 실측 확인: 특정 person이 walkingArea에서 도로로 못 건너감) 기본값이면
        # 시뮬레이션 전체가 그 자리에서 죽는다. 그 보행자 하나만 건너뛰고 계속 진행시킨다.
        "--ignore-route-errors", "true",
    ]
    # 신호 로직(actuated)은 netconvert 빌드 시점에 net.xml에 이미 반영되어 있어
    # baseline/treatment 모두 동일하게 적용된다. 두 조건의 유일한 차이는
    # central_server + vehicle_controller의 TraCI 개입 여부다.

    traci.start(cmd)

    server = CentralServer()
    # treatment에서만 개입하므로 baseline에서는 굳이 만들지 않는다(순수 분산형과 비교하는
    # 것이 이 실험의 목적이라 baseline에는 신호/예측 개입도 없어야 함).
    signals = SignalController() if mode == "treatment" else None
    predictor = PredictiveRerouter(sumolib.net.readNet(NET_FILE)) if mode == "treatment" else None
    # 견인차 제거는 "중앙 제어 알고리즘"이 아니라 현실 보정(충돌·그리드락으로 영구히
    # 낀 차량은 실제로는 견인차가 치운다)이라 baseline/treatment 둘 다 동일하게 적용한다
    # - 안 그러면 이것도 알고리즘 효과로 착각되어 비교가 왜곡된다.
    remover = StuckVehicleRemover()
    depart_time = {}
    travel_times = []
    arrived_ids = set()
    emergency_brakes = 0
    bottleneck_wait = 0.0

    step = 0
    while step < SIM_END:
        traci.simulationStep()

        for veh_id in traci.simulation.getDepartedIDList():
            depart_time[veh_id] = step
        for veh_id in traci.simulation.getArrivedIDList():
            if veh_id in depart_time:
                travel_times.append(step - depart_time[veh_id])
                arrived_ids.add(veh_id)

        now = traci.simulation.getTime()
        remover.step(now)

        # treatment만 central_server + vehicle_controller가 개입한다.
        # baseline은 분산형(개입 없음)이라 initial_optimization/handle_cctv_alert를 호출하지 않는다.
        if mode == "treatment":
            server.initial_optimization()
            alerts = poll_all_zones()
            commands = server.handle_cctv_alert(alerts)
            execute_commands(commands)
            signals.step(now)
            predictor.step(now)

        server.update_throughput()

        # 급제동 판정과 누적 대기시간 집계 둘 다 "현재 차량 전체"를 도는 동일한
        # 대상이라, getIDList()를 한 번만 불러 같은 루프에서 같이 처리한다(전에는
        # 스텝마다 이 목록을 두 번 요청했음 - 네트워크 전체 균일 수요에서는
        # CCTV 구역 몇 곳만으로 병목을 측정하면 대부분 0이 나오므로 대기시간도
        # 네트워크 전체 차량 기준으로 누적해야 의미 있는 값이 나온다).
        for veh_id in traci.vehicle.getIDList():
            if traci.vehicle.getAcceleration(veh_id) < EMERGENCY_BRAKE_THRESHOLD:
                emergency_brakes += 1
            bottleneck_wait += traci.vehicle.getWaitingTime(veh_id)

        step += 1

    traci.close()

    collision_count = 0
    if os.path.exists(collision_out):
        with open(collision_out, encoding="utf-8") as f:
            collision_count = f.read().count("<collision ")

    avg_travel_time = sum(travel_times) / len(travel_times) if travel_times else 0.0

    # 총 시스템 통행시간(TSTT) - "평균 통행시간"은 도착한 차량만 집계해서, treatment가
    # 처리량을 늘리면(원래 못 갔을 차량까지 도착 처리) 그 차량들이 평균을 오히려
    # 끌어올리는 착시가 생긴다(2026-08-10 seed4 실측에서 확인). TSTT는 도착 여부와
    # 무관하게 "차량이 도로 위에 머문 시간 전부"를 더해서 이 편향을 없앤다 - 아직
    # 도착 못 한 채 시뮬레이션이 끝난 차량은 SIM_END까지 걸린 시간을 그대로 더한다.
    tstt = sum(travel_times)
    for veh_id, dtime in depart_time.items():
        if veh_id not in arrived_ids:
            tstt += SIM_END - dtime

    row = {
        "seed": seed,
        "mode": mode,
        "avg_travel_time": avg_travel_time,
        "total_system_travel_time": tstt,
        "total_wait_time": bottleneck_wait,
        "collision_count": collision_count,
        "emergency_brake_count": emergency_brakes,
        "throughput": server.arrived_count,
        "towed_count": remover.total_removed,
    }

    write_header = not os.path.exists(RESULTS_FILE)
    with open(RESULTS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(row.keys()))
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    return row


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--mode", choices=["baseline", "treatment"], required=True)
    args = parser.parse_args()
    result = run(args.seed, args.mode)
    print(result)
