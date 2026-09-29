"""각 차량의 남은 경로를 미리 살펴, 앞으로 혼잡해질 것으로 예상되는 edge를
아직 우회 여유가 있는 차량에 한해 선제적으로 재계산시킨다.

cctv_detector.py의 congestion_detected는 "이미 느려진" 상황에만, 그것도 9개
CCTV 구역 안에서만 반응한다. 여기서는 그 밖의 도로까지 포함해서 "앞으로 이 edge에
도착 예정인 차량 수가 그 edge가 처리 가능한 양보다 많다"를 미리 계산하고, 아직
다른 길을 고를 시간 여유(lead time)가 있는 차량만 먼저 우회시킨다. 이미 그
edge 근처까지 와버린 차량은 건드리지 않는다 - 그 시점엔 대안 경로도 같이 막혀
있을 가능성이 높아 실익이 적다(이전에 확인한 "경로 분산이 안 먹히는" 문제와 같은
이유). 미리 손을 쓸수록 실제로 흩어질 여지가 남아있다는 것이 핵심 전제다.
"""

import traci

from hardware_twin import is_hardware_twin

PREDICT_INTERVAL = 60.0          # s, 예측 재계산 주기 (차량이 많을 때 한 번에 몇 초씩 걸려서 너무 잦으면 시뮬레이션이 버벅임)
PREDICT_HORIZON = 90.0           # s, 이 시간 이내 도착 예정인 edge까지만 내다본다
MAX_EDGES_PER_VEHICLE = 25       # 안전장치: 정체로 통행시간이 늘어져도 한 차량당 이만큼만 본다
MIN_LEAD_TIME = 45.0             # s, 이 정도 이상 여유가 있어야 "아직 우회 가능"으로 보고 개입
SATURATION_FLOW_PER_LANE = 0.4   # veh/s/lane, 차선 하나가 처리 가능한 대략적 처리율(=1440veh/h)
REROUTE_PENALTY = 1e5            # s, 예측 우회 대상 edge에 거는 통행시간 페널티
# 2026-09-10에 이 고정값 대신 edge 실측 통행시간의 배수로 바꿔봤음(대안 경로가 진짜
# 이득일 때만 우회하도록) - seed 1~3 소거 실험 결과가 seed마다 뒤섞여 나와서(어떤
# seed는 TSTT·대기시간 둘 다 개선, 어떤 seed는 둘 다 악화) 일관된 개선이라고 볼 근거가
# 없었다. 근거 없는 튜닝값을 갖고 가는 것보다 낫다고 판단해 원래 고정값으로 되돌림.
# (원래 값 자체도 완벽하진 않다 - 같은 실험에서 TSTT는 항상 소폭 악화, 대기시간은
# 항상 개선되는 트레이드오프가 3개 seed 전부에서 일관되게 나왔음. 나중에 다시 튜닝을
# 시도한다면 고정 배수 하나가 아니라 seed를 훨씬 더 많이 돌려서 검증할 것.)
REROUTE_DURATION = PREDICT_INTERVAL  # s, 페널티 유지 시간 - 다음 예측 주기까지만 유효
# 차량이 많을 때 rerouteTraveltime() 자체가 차량당 ~10ms(네트워크 전역 최단경로 탐색)라
# 대상이 너무 많으면 한 사이클에 몇 초씩 걸려 시뮬레이션이 버벅인다. 우선순위(여유
# 시간이 적어 더 급한 차량)대로 이 개수만큼만 실제로 재계산하고 나머지는 다음
# 사이클로 넘긴다 - 매 사이클 도는 주기적 스캔이라 놓친 차량도 곧 다시 잡힌다.
MAX_REROUTES_PER_CYCLE = 120
# 같은 사이클에 선정된 차량들은 전부 "같은 edge가 방금 페널티를 먹은" 동일한 가중치
# 그래프를 보고 각자 최단경로를 계산한다 - 그러니 서로 다른 차량인데도 거의 전부
# 같은 대안 edge 하나로 몰리는 현상이 실측됨(2026-09-23 확인 - 한 사이클에 73대 중
# 71대가 edge 하나로 몰림). 몰려서 새 병목을 만들면 "우회로 정체를 없앤다"는 목적
# 자체가 무너진다. 그래서 한 사이클 안에서 순차적으로 배정하면서, 이미 많이 몰린
# 대안 edge에는 그 차량만 보는 개인별 페널티(traci.vehicle.setAdaptedTraveltime)를
# 추가로 걸어 재계산시켜 다른 대안을 찾게 한다(전역 페널티가 아니라 이 차량만).
MAX_DETOUR_SHARE_PER_LANE = 15  # 한 사이클에 대안 edge 하나가 새로 받을 수 있는 차선당 최대 차량 수


class PredictiveRerouter:
    """예상 혼잡 edge를 찾아 아직 여유 있는 차량만 선제 우회시킨다."""

    def __init__(self, net, record_changes=False):
        self._net = net
        # 대시보드용: 마지막 예측 주기에 경로가 실제로 바뀐 차 [(veh_id, 바뀌기 전 남은 경로, 넘칠 것으로 본 도로)]
        self.record_changes = record_changes
        self.route_changes = []
        self._last_check = -PREDICT_INTERVAL
        self._lane_count_cache = {}

    def _lane_count(self, edge_id):
        cached = self._lane_count_cache.get(edge_id)
        if cached is None:
            try:
                cached = self._net.getEdge(edge_id).getLaneNumber()
            except KeyError:
                cached = 1
            self._lane_count_cache[edge_id] = cached
        return cached

    def step(self, now):
        if now - self._last_check < PREDICT_INTERVAL:
            return
        self._last_check = now
        self._predict_and_reroute(now)

    def _predict_and_reroute(self, now):
        self.route_changes = []
        tt_cache = {}

        def travel_time(edge_id):
            tt = tt_cache.get(edge_id)
            if tt is None:
                tt = traci.edge.getTraveltime(edge_id)
                tt_cache[edge_id] = tt
            return tt

        live_ids = traci.vehicle.getIDList()

        # edge -> [(veh_id, lead_time), ...] - PREDICT_HORIZON 안에 도착 예정인 차량들
        projected = {}
        for veh_id in live_ids:
            if is_hardware_twin(veh_id):
                continue  # 실물 차량의 경로는 차량 호스트가 정한다
            route = traci.vehicle.getRoute(veh_id)
            idx = traci.vehicle.getRouteIndex(veh_id)
            t = 0.0
            for edge_id in route[idx + 1: idx + 1 + MAX_EDGES_PER_VEHICLE]:
                if t > PREDICT_HORIZON:
                    break
                projected.setdefault(edge_id, []).append((veh_id, t))
                t += travel_time(edge_id)

        # (edge_id, veh_id, lead_time) 후보를 전부 모은 뒤, 여유가 적어 더 급한
        # 차량부터 우선 처리한다 - 한 사이클에 너무 많이 재계산하면(차량당 ~10ms짜리
        # 네트워크 전역 탐색) 시뮬레이션이 버벅이므로 MAX_REROUTES_PER_CYCLE로 자른다.
        candidates = []
        overloaded_edges = set()
        for edge_id, arrivals in projected.items():
            capacity = self._lane_count(edge_id) * SATURATION_FLOW_PER_LANE * PREDICT_HORIZON
            if len(arrivals) <= capacity:
                continue
            overloaded_edges.add(edge_id)
            for veh_id, lead in arrivals:
                if lead >= MIN_LEAD_TIME:
                    candidates.append((lead, edge_id, veh_id))

        if not candidates:
            return

        candidates.sort(key=lambda c: c[0])
        selected = []
        seen_vehicles = set()
        for lead, edge_id, veh_id in candidates:
            if veh_id in seen_vehicles:
                continue  # 같은 차량이 여러 혼잡 예상 edge에 겹쳐 걸린 경우 한 번만 재계산
            seen_vehicles.add(veh_id)
            selected.append((lead, edge_id, veh_id))
            if len(selected) >= MAX_REROUTES_PER_CYCLE:
                break

        # 혼잡이 예상되는 edge에 페널티를 걸어두면, 그 뒤 rerouteTraveltime()이 자연히
        # 이 edge를 피해서 계산한다 - vehicle_controller._reroute_around()와 같은
        # SUMO 표준 incident-avoidance 기법을 "예측"에 적용한 것뿐이다.
        for edge_id in overloaded_edges:
            traci.edge.adaptTraveltime(edge_id, REROUTE_PENALTY, begin=now, end=now + REROUTE_DURATION)

        live_ids_set = set(live_ids)
        detour_share = {}  # edge_id -> 이번 사이클에 이미 그 edge로 새로 배정된 차량 수
        for _lead, edge_id, veh_id in selected:
            if veh_id not in live_ids_set:
                continue
            try:
                old_route = traci.vehicle.getRoute(veh_id)
                old_idx = traci.vehicle.getRouteIndex(veh_id)
            except traci.exceptions.TraCIException:
                continue
            old_remaining = set(old_route[old_idx:])

            traci.vehicle.rerouteTraveltime(veh_id)

            try:
                new_route = traci.vehicle.getRoute(veh_id)
                new_idx = traci.vehicle.getRouteIndex(veh_id)
            except traci.exceptions.TraCIException:
                continue
            new_detour = [e for e in new_route[new_idx:] if e not in old_remaining]

            crowded = [e for e in new_detour
                       if detour_share.get(e, 0) >= self._lane_count(e) * MAX_DETOUR_SHARE_PER_LANE]
            if crowded:
                # 이미 몰린 대안 edge만 이 차량 개인 기준으로 추가 회피시켜서 다시 계산 -
                # 전역 페널티를 건드리지 않으므로 다른 차량들의 계산에는 영향 없다.
                for e in crowded:
                    traci.vehicle.setAdaptedTraveltime(veh_id, e, REROUTE_PENALTY, now, now + REROUTE_DURATION)
                traci.vehicle.rerouteTraveltime(veh_id)
                try:
                    new_route = traci.vehicle.getRoute(veh_id)
                    new_idx = traci.vehicle.getRouteIndex(veh_id)
                    new_detour = [e for e in new_route[new_idx:] if e not in old_remaining]
                except traci.exceptions.TraCIException:
                    pass

            for e in new_detour:
                detour_share[e] = detour_share.get(e, 0) + 1
            if self.record_changes and new_detour:
                self.route_changes.append((veh_id, old_route[old_idx:], edge_id))
