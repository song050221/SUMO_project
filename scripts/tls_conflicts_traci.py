"""신호의 한 단계에서 서로 충돌하는 두 흐름(차량·보행)이 동시에 우선 초록(G)인 곳을 SUMO에게 직접 물어 찾는다.

net.xml의 충돌표(request foes) 번호를 해석하는 방식은 여러 교차점을 묶은 신호와 횡단보도에서 번호가
어긋나 오판이 많았다(2026-09-28). 여기서는 TraCI로 각 신호 링크의 교차로 안 경로 조각(내부 차선)을
끝까지 따라가 모으고, SUMO가 계산한 내부 차선 충돌 목록(lane.getInternalFoes)에 상대 흐름의 조각이
하나라도 있으면 충돌로 본다. 보행 링크는 횡단보도 차선 자체가 경로다.

    python scripts/tls_conflicts_traci.py NET [OUT_JSON]
"""

import json
import sys

import traci


def internal_chain(via):
    """via 내부 차선에서 시작해 일반 차선에 닿을 때까지 이어지는 내부 차선 목록."""
    chain, lane, guard = [], via, 0
    while lane and lane.startswith(":") and guard < 6:
        chain.append(lane)
        nxt = [l[0] for l in traci.lane.getLinks(lane)]
        lane = nxt[0] if nxt else None
        guard += 1
    return chain


def find_conflicts(net_file):
    traci.start(["sumo", "-n", net_file, "--no-step-log", "true", "--no-warnings", "true"])
    result = {}
    foe_cache = {}

    def foes_of(lane):
        if lane not in foe_cache:
            foe_cache[lane] = set(traci.lane.getInternalFoes(lane))
        return foe_cache[lane]
    try:
        for tl in traci.trafficlight.getIDList():
            links = traci.trafficlight.getControlledLinks(tl)
            chains = {}
            for i, lk in enumerate(links):
                if not lk:
                    continue
                inl, outl, via = lk[0]
                if via:
                    chains[i] = (internal_chain(via), False, inl.rsplit("_", 1)[0], outl)
                elif outl.startswith(":") and "_c" in outl:        # 보행: walkingarea -> crossing
                    chains[i] = ([outl], True, inl, outl)
            logic = traci.trafficlight.getAllProgramLogics(tl)[0]
            found = []
            for k, ph in enumerate(logic.phases):
                G = [i for i in chains if ph.state[i] == "G"]
                for a in range(len(G)):
                    for b in range(a + 1, len(G)):
                        x, y = G[a], G[b]
                        cx, px, ex, ox = chains[x]
                        cy, py, ey, oy = chains[y]
                        if px and py:
                            continue   # 보행끼리는 충돌로 보지 않음
                        if ex == ey:
                            continue   # 같은 도로에서 나뉘어 가는 흐름 - 출발점이 겹칠 뿐 신호 충돌이 아님
                        if any(l2 in foes_of(l1) for l1 in cx for l2 in cy):
                            if px != py:
                                kind = "보행×차량"
                            elif ox == oy:
                                kind = "합류"      # 같은 차선으로 들어감(예: 우회전+직진) - 보통 한쪽이 양보(g)해야 함
                            else:
                                kind = "차량×차량"
                            found.append({"phase": k, "duration": ph.duration, "kind": kind, "links": [x, y]})
            if found:
                result[tl] = found
    finally:
        traci.close()
    return result


def main():
    res = find_conflicts(sys.argv[1])
    for tl, lst in res.items():
        kinds = {}
        for f in lst:
            kinds[f["kind"]] = kinds.get(f["kind"], 0) + 1
        print(f"{tl[:50]}  {kinds}  예: 단계{lst[0]['phase']}({lst[0]['duration']:.0f}s) 링크{lst[0]['links']}")
    print("충돌 있는 신호", len(res))
    if len(sys.argv) > 2:
        json.dump(res, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
