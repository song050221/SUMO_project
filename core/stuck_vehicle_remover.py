"""장시간 정지 상태(충돌·그리드락으로 완전히 낀) 차량을 견인차처럼 제거한다.

배경: `--collision.action warn`은 충돌해도 차량을 지우거나 순간이동시키지 않는다.
실측해보니(2026-08-10) 충돌에 연루된 일부 차량이 "거의 300초(=SUMO 기본
time-to-teleport) 대기 → 잠깐 풀림 → 거의 300초 다시 대기"를 계속 반복하며 사실상
영구히 그 자리를 맴돈다 - SUMO의 자체 teleport가 매번 "구해주긴" 하는데 곧바로 다시
같은 자리에 갇히는 패턴이었다. 실제 도로라면 견인차가 와서 치우는데, 시뮬레이션엔
그게 없어서 이게 정체가 절대 안 풀리던 숨은 원인 중 하나였다.

`traci.vehicle.getWaitingTime()`(마지막으로 0.1m/s 넘게 움직인 뒤로 연속 정지한 시간,
움직이면 리셋됨)이 STUCK_THRESHOLD_S를 넘는 차량을 "견인 완료"로 보고 제거한다.
신호 대기(보통 한 주기 90초 이내)와는 확실히 구분되는 값으로 잡았다.
"""

import traci

from hardware_twin import is_hardware_twin

CHECK_INTERVAL = 20.0       # s, 이 주기로 전체 차량을 점검한다 (매 스텝 다 보면 비용이 큼)
STUCK_THRESHOLD_S = 180.0   # s, 이만큼 연속으로 멈춰 있으면 "꼈다"고 보고 견인 제거


class StuckVehicleRemover:
    """모든 차량을 대상으로 장시간 정지 여부를 점검해 제거한다."""

    def __init__(self):
        self._last_check = -CHECK_INTERVAL
        self.total_removed = 0
        self.last_removed = []  # 가장 최근 점검에서 제거된 차량 id 목록 (대시보드 표시용)

    def step(self, now):
        self.last_removed = []
        if now - self._last_check < CHECK_INTERVAL:
            return
        self._last_check = now

        for veh_id in list(traci.vehicle.getIDList()):
            if is_hardware_twin(veh_id):
                continue  # 실물이 서 있으면 SUMO 차도 서 있어야 한다 - 견인하지 않음
            try:
                waiting = traci.vehicle.getWaitingTime(veh_id)
            except traci.exceptions.TraCIException:
                continue
            if waiting < STUCK_THRESHOLD_S:
                continue
            try:
                traci.vehicle.remove(veh_id)
            except traci.exceptions.TraCIException:
                continue
            self.total_removed += 1
            self.last_removed.append(veh_id)
