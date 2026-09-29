"""CCTV 구역 8~10곳을 데이터 기반으로 선정한다.

방법 A: sumolib로 각 교차로의 연결 edge 수(연결도)를 계산해 상위 후보군 추출.
방법 B: baseline 시뮬레이션 1회(seed 42 demand) 실행 후 후보 교차로에 연결된
        edge들의 실측 통행량을 집계해 최종 8~10곳을 확정한다.

결과는 cctv_zones.json에 저장하고, cctv_detector.py의 CCTV_ZONES가 이 파일을 읽어 쓴다.
"""

import json

import sumolib
import traci

NET_FILE = "network/gwangjin.net.xml"
ROUTES_FILE = "network/routes.xml"
CANDIDATE_COUNT = 30
FINAL_ZONE_COUNT = 9
SIM_END = 3600


def rank_by_connectivity(net):
    junctions = [j for j in net.getNodes() if j.getType() not in ("internal", "unregulated")]
    scored = []
    for j in junctions:
        edges = {e.getID() for e in j.getIncoming() + j.getOutgoing() if e.allows("passenger")}
        if not edges:
            continue
        scored.append((j, len(edges), edges))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def measure_edge_traffic(candidate_edges):
    traci.start([
        "sumo", "-n", NET_FILE, "-r", ROUTES_FILE,
        "--seed", "42", "--begin", "0", "--end", str(SIM_END),
    ])
    edge_traffic = {e: 0 for e in candidate_edges}
    step = 0
    while step < SIM_END:
        traci.simulationStep()
        for e in candidate_edges:
            edge_traffic[e] += traci.edge.getLastStepVehicleNumber(e)
        step += 1
    traci.close()
    return edge_traffic


def main():
    net = sumolib.net.readNet(NET_FILE)
    scored = rank_by_connectivity(net)

    print(f"방법 A: 연결도 상위 후보 교차로 {CANDIDATE_COUNT}곳")
    candidates = scored[:CANDIDATE_COUNT]
    for j, degree, edges in candidates:
        print(f"  {j.getID()}: 연결 edge {degree}개, 좌표 {j.getCoord()}")

    candidate_edges = set()
    for _, _, edges in candidates:
        candidate_edges |= edges

    print(f"\n방법 B: baseline(seed 42) 1회 실행하여 후보 edge {len(candidate_edges)}개 실측 통행량 집계 중...")
    edge_traffic = measure_edge_traffic(candidate_edges)

    junction_traffic = []
    for j, degree, edges in candidates:
        total = sum(edge_traffic[e] for e in edges)
        junction_traffic.append((j, degree, edges, total))
    junction_traffic.sort(key=lambda x: x[3], reverse=True)

    final = junction_traffic[:FINAL_ZONE_COUNT]

    print(f"\n최종 선정 CCTV 구역 {FINAL_ZONE_COUNT}곳 (연결도 상위 {CANDIDATE_COUNT}곳 중 실측 통행량 기준):")
    zones = {}
    for i, (j, degree, edges, total) in enumerate(final, start=1):
        zone_id = f"zone_{i}"
        zones[zone_id] = {
            "name": f"교차로 {i} ({j.getID()})",
            "junction_id": j.getID(),
            "coord": list(j.getCoord()),
            "degree": degree,
            "measured_traffic": total,
            "edges": sorted(edges),
        }
        print(f"  {zone_id}: junction={j.getID()}, 연결edge={degree}개, 누적통행량={total}")
        print(f"    edges={sorted(edges)}")

    with open("network/cctv_zones.json", "w", encoding="utf-8") as f:
        json.dump(zones, f, ensure_ascii=False, indent=2)
    print("\nnetwork/cctv_zones.json 저장 완료")


if __name__ == "__main__":
    main()
