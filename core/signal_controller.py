"""교차로 신호를 중앙에서 실시간 대기열 기준으로 조정하는 모듈.

배경: 차량 대수를 늘렸더니 네트워크가 정체로 무너지는 문제가 있었다. 경로를 아무리
잘 분산해도(재계산 주기 단축, weights.random-factor) 개선되지 않았는데, 이는
"어느 길로 보낼지"가 아니라 교차로가 처리할 수 있는 차량 자체(용량)가 부족해서였다.
그래서 라우팅이 아니라 신호 운영 쪽에서 용량을 늘리는 접근으로 바꿨다.

v1은 "대기열이 있으면 무조건 조금 연장"이었다. v2는 "차량이 많은 쪽에 더 오래
배정"하도록 바꿨다 - 현재 초록불 방향의 대기열과, 다음 차례 방향의 대기열을
비교해서: 지금 방향이 더 급하면 대기열 크기에 비례해 더 오래 연장하고, 반대로
다음 방향이 훨씬 더 급하면 (최소 시간은 지킨 채) 지금 phase를 일찍 끊어 넘겨준다.
이게 실제 교통공학의 max-pressure 신호제어와 같은 방향이다 - "누가 더 급한가"를
양쪽 다 보고 상대적으로 배분한다.
"""

import traci

CHECK_INTERVAL = 5.0        # s, 이 주기로 각 교차로를 점검한다 (매 스텝 다 검사하면 비용이 큼)
QUEUE_THRESHOLD = 3         # 대기(halting) 차량 수가 이 이상이면 "처리할 차가 있다"고 판단
EXTENSION_BASE = 4.0        # s, 연장의 기본값
EXTENSION_PER_VEHICLE = 1.0  # s, 대기 차량 한 대당 추가로 얹어주는 연장 시간
MAX_EXTENSION = 20.0        # s, 한 번에 줄 수 있는 연장의 상한
CUTOFF_RATIO = 1.8          # 다음 방향 대기열이 지금 방향의 이 배수를 넘으면 일찍 끊는다
EARLY_CUTOFF_DURATION = 2.0  # s, 일찍 끊을 때 남겨두는 시간(바로 끊으면 급정거 유발)
# 2026-09-25에 "이 방향에 차도 사람도 없으면 minDur도 건너뛴다"를 시도했었음(간선도로-
# 골목 조합에서 minDur가 낭비된다고 보고) - 네트워크 전역 308개 신호 전부에 적용했더니
# 오히려 악화됨(만성 정체 7678→11029초). 빈 방향을 자주 끊을수록 신호가 더 자주
# 바뀌면서 매번 필요한 황색/클리어런스 전환 오버헤드가 늘어난 게 이득보다 컸던 것으로
# 보임. 이론상 맞아 보여도 실측에서 역효과였으므로 원복함 - minDur는 절대 안 건드리는
# 것으로 되돌아옴. 나중에 다시 시도한다면 전역 적용 말고 극단적 불균형 교차로 몇 곳에만
# 좁혀서 검증할 것.
# 2026-09-26에 게이팅(하류 edge가 꽉 차면 초록 연장 안 함, sumolib net으로 각 phase의
# 하류 edge를 미리 계산)을 시도했었음 - 5-seed로 검증하니 만성정체는 거의 그대로
# (9420→9224), 그리드락은 오히려 악화됨(876→1272, +45%, 5개 중 4개 seed에서 악화).
# 하류를 보호하려고 지금 방향 초록을 안 늘려주면 그 대기열이 지금 교차로에 쌓여서
# 오히려 이 교차로 자체가 그리드락에 빠지기 쉬워지는 부작용으로 보임 - 원복함.

# 2026-09-28에 "진입 lane이 15m 미만 edge면 상류 lane(최대 3단계)의 대기열도 센다"를
# 시도했었음 - netconvert가 쪼갠 사거리의 0m 진입 edge 때문에 대기열이 0으로 보여 phase가
# minDur 직후 끊기는 걸 (5036,6038) 사거리에서 확인했고, 신호 203개 중 151개가 이런 짧은
# 진입 lane을 가짐. 그런데 5-seed로 검증하니 전반적으로 악화(견인 117→123, 만성정체
# 2876→3277s, 그리드락 697→739s, 충돌 66→173 - 5개 중 1~2개 seed만 개선) - 원복함. 상류
# lane의 정지 차량엔 다른 방향으로 가는 차도 섞여 있어 대기열이 부풀려지고, 151개 신호가
# 동시에 초록을 더 오래 잡으면서 전체 교대가 느려진 것으로 보임.


class SignalController:
    """모든 신호 교차로를 대상으로 대기열 비교 기반 초록불 배분을 수행한다."""

    def __init__(self):
        tls_ids = list(traci.trafficlight.getIDList())
        self._logics = {}
        self._green_lanes = {}   # tid -> {phase_idx: set(lane_id)} (초록이 있는 phase만)
        self._green_order = {}   # tid -> [phase_idx, ...] (초록 phase만 순서대로, cyclic)

        for tid in tls_ids:
            logics = traci.trafficlight.getAllProgramLogics(tid)
            if not logics:
                continue
            logic = logics[0]
            lanes = traci.trafficlight.getControlledLanes(tid)

            green_lanes = {}
            green_order = []
            for i, phase in enumerate(logic.phases):
                state = phase.state
                if "y" in state or "Y" in state:
                    continue  # 전이(황색) phase는 제어 대상에서 뺀다
                # 보행자 횡단(walkingarea) lane은 ":"로 시작한다 - 차량 대기열 비교에
                # 넣으면 안 된다. 넣으면 "초록불 유지 + 보행자 신호만 끈 짧은 부속
                # phase"(예: minDur=maxDur=5s짜리 클리어런스 phase)가 차량 lane
                # 집합은 똑같은데도 별개의 "다음 방향"으로 오인식된다(2026-09-23
                # 확인 - 436832681 교차로에서 이 버그로 반대 방향과 비교해야 할
                # _next_green_phase()가 자기 자신의 부속 phase와 비교하게 되어
                # "반대 방향이 급하면 일찍 끊기" 로직이 죽어있었고, 신호 편향으로
                # 그 교차로의 그리드락이 10배 가까이 악화됨).
                lane_set = {lane for lane, s in zip(lanes, state)
                            if s in ("G", "g") and not lane.startswith(":")}
                if not lane_set:
                    continue  # 전부 빨강이거나(전 방향 대기) 보행자 lane만 초록인 phase도 뺀다
                # 차량 lane 집합이 방금 추가한 방향과 완전히 같으면(보행자 클리어런스
                # 부속 phase) 새 방향이 아니라 같은 방향의 변형이므로 건너뛴다 - 그래야
                # green_order가 "실제 교대되는 방향" 순서를 정확히 반영한다.
                if green_order and green_lanes[green_order[-1]] == lane_set:
                    continue
                green_lanes[i] = lane_set
                green_order.append(i)

            if len(green_order) < 2:
                continue  # 비교할 "다음 방향"이 없으면 이 컨트롤러가 할 일이 없다

            self._logics[tid] = logic
            self._green_lanes[tid] = green_lanes
            self._green_order[tid] = green_order

        self._last_check = -CHECK_INTERVAL
        self._phase_seen = {}  # tid -> (phase_idx, 그 phase가 시작된 시각)

    def step(self, now):
        """CHECK_INTERVAL마다 모든 교차로를 점검한다. 그 사이 호출은 조용히 무시한다."""
        if now - self._last_check < CHECK_INTERVAL:
            return
        self._last_check = now
        for tid in self._logics:
            self._adjust(tid, now)

    def _queue(self, lanes):
        return sum(traci.lane.getLastStepHaltingNumber(lane) for lane in lanes)

    def _next_green_phase(self, tid, phase_idx):
        order = self._green_order[tid]
        pos = order.index(phase_idx) if phase_idx in order else None
        if pos is None:
            return None
        return order[(pos + 1) % len(order)]

    def _adjust(self, tid, now):
        phase_idx = traci.trafficlight.getPhase(tid)
        if phase_idx not in self._green_lanes[tid]:
            return  # 지금 황색/전방향 대기 중 - 손대지 않는다

        seen = self._phase_seen.get(tid)
        if seen is None or seen[0] != phase_idx:
            self._phase_seen[tid] = (phase_idx, now)
            return  # 이번 phase가 막 시작됨 - 판단 근거(경과 시간)가 아직 없다

        _, phase_start = seen
        elapsed = now - phase_start
        phase = self._logics[tid].phases[phase_idx]

        if elapsed < phase.minDur:
            return  # 최소 보장 시간은 절대 건드리지 않는다

        own_queue = self._queue(self._green_lanes[tid][phase_idx])
        next_idx = self._next_green_phase(tid, phase_idx)
        next_queue = self._queue(self._green_lanes[tid][next_idx]) if next_idx is not None else 0
        remaining = traci.trafficlight.getNextSwitch(tid) - now

        if next_queue > own_queue * CUTOFF_RATIO and remaining > EARLY_CUTOFF_DURATION:
            # 다음 방향이 훨씬 더 급함 - 최소 시간은 이미 채웠으니 곧 넘겨준다
            traci.trafficlight.setPhaseDuration(tid, EARLY_CUTOFF_DURATION)
            return

        if own_queue < QUEUE_THRESHOLD or elapsed >= phase.maxDur:
            return  # 지금 방향에 처리할 차가 얼마 없거나, 이미 최대 길이 - 반대 방향을 굶기지 않는다

        # 대기열이 클수록 더 오래 배정한다 - "차량이 많은 도로에 신호를 오래 배정"
        extension = min(EXTENSION_BASE + own_queue * EXTENSION_PER_VEHICLE, MAX_EXTENSION,
                         phase.maxDur - elapsed)
        if remaining < extension:
            traci.trafficlight.setPhaseDuration(tid, extension)
