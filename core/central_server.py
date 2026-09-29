import traci

from decision_policy import decide_actions
from hardware_twin import is_hardware_twin


class CentralServer:
    """GPS/목적지 기반 1차 최적화(initial_optimization)와 CCTV 돌발 정보 수신 시
    재계산(handle_cctv_alert)을 분리해 제공한다. vehicle_controller.py는 이 클래스가
    반환한 명령을 그대로 실행만 하는 얇은 레이어여야 한다.
    """

    # s, 이미 주행 중인 차량도 이 주기로 실시간 정체를 반영해 경로를 다시 계산한다.
    # CCTV 알림(handle_cctv_alert)은 9개 구역 안에서 벌어지는 돌발상황에만 반응하므로,
    # 그 밖의 도로에서 서서히 쌓이는 정체는 감지하지 못한 채 방치된다 - 차량이 출발할
    # 때 한 번만 최적화하고 끝나던 이전 방식(REOPTIMIZE_INTERVAL 도입 전)의 사각지대였다.
    # traci.edge.getTraveltime()은 (adaptTraveltime로 강제 지정하지 않는 한) 그 edge의
    # 실측 현재 평균 속도를 반영하므로, rerouteTraveltime()을 그냥 주기적으로 다시
    # 불러주는 것만으로 네트워크 전역의 실시간 정체를 우회하게 만들 수 있다.
    REOPTIMIZE_INTERVAL = 60.0

    def __init__(self, record_changes=False):
        self.vehicle_routes = {}  # veh_id -> 마지막으로 재계산한 시각(s)
        # 대시보드용: 이번 호출에서 경로가 실제로 바뀐 차 [(veh_id, 바뀌기 전 남은 경로)].
        # 재계산 앞뒤로 경로를 한 번씩 더 읽어야 해서 측정 때는 끈다(record_changes=False).
        self.record_changes = record_changes
        self.route_changes = []
        self.arrived_count = 0
        self._known_arrived = set()

    def initial_optimization(self):
        """GPS/목적지 데이터 기반 경로 최적화 - 출발 시 1회 + 이후 주기적 재계산.

        중앙 서버가 현재 네트워크 통행시간(travel time)을 기준으로 경로를
        재계산한다(traci.vehicle.rerouteTraveltime). baseline(분산형)은 duarouter가
        미리 계산해 둔 정적 경로를 그대로 쓰지만, treatment(중앙집중형)는 실시간
        조건을 반영해 반복적으로 재계산한다는 점이 핵심 차이다.
        REOPTIMIZE_INTERVAL이 지나지 않은 차량은 건너뛰어 매 스텝 불필요한
        재계산(차량마다 네트워크 전역 최단경로 탐색이라 비용이 작지 않음)을 막는다.
        """
        now = traci.simulation.getTime()
        self.route_changes = []
        for veh_id in traci.vehicle.getIDList():
            if is_hardware_twin(veh_id):
                continue  # 실물 차량의 경로는 차량 호스트가 정한다
            last_time = self.vehicle_routes.get(veh_id)
            if last_time is not None and now - last_time < self.REOPTIMIZE_INTERVAL:
                continue
            if self.record_changes:
                old_rest = traci.vehicle.getRoute(veh_id)[traci.vehicle.getRouteIndex(veh_id):]
            traci.vehicle.rerouteTraveltime(veh_id)
            self.vehicle_routes[veh_id] = now
            if self.record_changes and last_time is not None:  # 출발 직후 첫 계산은 "변경"으로 치지 않는다
                new_rest = traci.vehicle.getRoute(veh_id)[traci.vehicle.getRouteIndex(veh_id):]
                if tuple(new_rest) != tuple(old_rest):
                    self.route_changes.append((veh_id, list(old_rest)))

    def handle_cctv_alert(self, alerts):
        """cctv_detector.py의 알림(차량 이상상황 + 보행자 감지) 수신 시 재계산.

        보행자 행동 모델 A안(기본 gap-acceptance 유지) 기준: 아이가 스스로는 안전하게
        기다리더라도, 비중앙집중 환경에서는 인간 운전자가 횡단 낌새를 놓칠 수 있다.
        CCTV가 횡단 의도를 사전 감지하면 인근 차량을 예방적으로 감속시켜, 실제
        위험 상황(급정거/충돌)이 발생하기 전에 개입하는 것이 이 시스템의 핵심 가치다.

        판단 로직 자체(decide_actions)는 TraCI를 직접 호출하지 않는다 — SUMO
        시뮬레이션(cctv_detector.py)과 실제 하드웨어 시연(카메라 기반 감지) 양쪽에서
        동일한 정책을 재사용하기 위함이다. 어떤 차량이 위험 edge 위/구역 내/우회
        가능에 해당하는지 분류하는 일은 alert를 만드는 쪽(cctv_detector.py)의 몫이다.
        """
        return decide_actions(alerts)

    def update_throughput(self):
        """traci.simulation.getArrivedIDList() 누적으로 처리량(throughput) 집계.

        매 시뮬레이션 스텝마다 호출해야 누락 없이 누적된다.
        """
        for veh_id in traci.simulation.getArrivedIDList():
            if veh_id not in self._known_arrived:
                self._known_arrived.add(veh_id)
                self.arrived_count += 1
        return self.arrived_count
