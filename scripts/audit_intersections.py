"""네트워크의 모든 사거리(교차로)를 국내 횡단보도·정지선 규칙에 비춰 점검한다.

근거(2026-09-28 조사, docs/HANDOFF_PROMPT.md X번):
- 도로교통법 시행규칙 제11조: 횡단보도는 육교·지하도·다른 횡단보도로부터 200m(집산·국지도로 100m)
  이내에 설치하지 않음(보호구역 등 예외).
- 같은 규칙 별표 6 노면표시 532: 보행자 통행이 빈번한 곳에 설치, 교차로에서는 대각선 가능, 중간에 보행섬을
  두고 설치 가능. 폭 4m 이상(경찰청 교통노면표시 업무편람).
- 정지선(별표 6 노면표시 530): 경찰청 업무편람 - 횡단보도로부터 3m 이상 전방 권장, 최소 2m ~ 최대 10m.
- 교차로 횡단보도는 교차로 모서리(각 방향 입구) 가까이 둔다.

"사거리"는 20m 미만(같은 신호가 아니면 10m 미만) 차도로 이어진 갈림 교차점(신호·우선·우측우선 등)들의 묶음으로 보고, 바깥으로 나가는 차도를
방향(35도 이내)별로 묶어 3갈래 이상인 것만 대상으로 한다(쪼개진 사거리도 하나로 본다 - netconvert가 OSM의
사거리 하나를 노드 여러 개로 쪼갠 경우가 많음).

점검 항목(코드):
  CENTER     사거리 안쪽 연결 도로(양 끝이 같은 사거리의 교차점) 위 횡단보도 - 모서리 설치·간격 규칙 위반
  DUPLICATE  같은 갈래 입구에 10m 이내로 겹친 횡단보도 - 간격 규칙 위반
  NO_CROSS   신호 사거리에서 보도가 있는 갈래에 횡단보도가 없음
  NARROW     폭 4m 미만 횡단보도
  PED_NO_GREEN 신호 제어 횡단보도인데 보행 초록이 한 번도 없음
  CONFLICT_G 충돌하는 두 흐름(차량-차량, 차량-보행)이 한 단계에서 동시에 우선 초록(G)
  STOPLINE   신호 사거리 진입 차선의 정지 위치가 횡단보도에서 2m 미만(SUMO 기본은 0m)

    python scripts/audit_intersections.py NET OUT_JSON
"""

import json
import math
import os
import re
import sys
from collections import defaultdict

import sumolib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tls_conflicts_traci import find_conflicts  # noqa: E402

JUNCTION_TYPES = {"traffic_light", "traffic_light_unregulated", "traffic_light_right_on_red", "priority",
                  "priority_stop", "right_before_left", "left_before_right", "allway_stop", "zipper", "unregulated"}
CONNECTOR_M = 20.0
CONNECTOR_OTHER_M = 10.0
ARM_WALK_M = 30.0
ARM_TOL = 35.0
DUP_M = 10.0
MIN_WIDTH = 4.0
MIN_STOP_OFFSET = 2.0


def angle_gap(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def main():
    net_file, out = sys.argv[1], sys.argv[2]
    net = sumolib.net.readNet(net_file, withPrograms=True, withPedestrianConnections=True)
    conflicts = find_conflicts(net_file)

    # --- net.xml에서 횡단보도, 신호 링크(보행 링크인지), 정지 오프셋
    crossings = []                       # (node, crossing_edge_id, [crossed edges], width, 중심점)
    tl_links = defaultdict(dict)         # tl -> linkIndex -> 보행 링크 여부
    stop_offset = {}                     # lane id -> stopOffset
    edge_stop = {}                       # edge id -> stopOffset(도로 단위)
    cur_lane_edge = None
    cross_re = re.compile(r'<edge id=":(.+?)(_c\d+)" function="crossing" crossingEdges="([^"]*)"')
    conn_re = re.compile(r'<connection from="([^"]+)" [^>]*tl="([^"]+)" linkIndex="(\d+)"')
    last_cross = None
    with open(net_file, encoding="utf-8") as f:
        for line in f:
            s = line.lstrip()
            if s.startswith("<edge "):
                m = cross_re.search(s)
                last_cross = None
                em = re.match(r'<edge id="([^":][^"]*)"', s)
                cur_lane_edge = em.group(1) if em else None
                if m:
                    last_cross = [m.group(1), m.group(1) + m.group(2), m.group(3).split(), None, None]
                    crossings.append(last_cross)
            elif cur_lane_edge and s.startswith("<stopOffset "):
                v = re.search(r'value="([^"]+)"', s)
                if v:   # 도로 단위 정지 오프셋 - 그 도로의 모든 차선에 적용
                    edge_stop[cur_lane_edge] = float(v.group(1))
            elif last_cross is not None and s.startswith("<lane ") and last_cross[3] is None:
                w = re.search(r'width="([^"]+)"', s)
                last_cross[3] = float(w.group(1)) if w else 4.0
                sh = re.search(r'shape="([^"]+)"', s)
                if sh:   # 횡단보도 중심점 - 합친 노드는 횡단보도가 모두 같은 노드 좌표를 가져 노드 좌표로는 거리를 못 잰다
                    pts = [tuple(map(float, p.split(","))) for p in sh.group(1).split()]
                    last_cross[4] = (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
            elif s.startswith("<connection ") and ' tl="' in s:
                m = conn_re.search(s)
                if m:
                    frm, tl, idx = m.groups()
                    # 충돌 판정은 SUMO에 직접 묻는다(tls_conflicts_traci) - 여기선 보행 링크인지만 본다
                    tl_links[tl][int(idx)] = frm.startswith(":") and "_w" in frm
    for lane in [l for e in net.getEdges() for l in e.getLanes()]:
        so = lane._stopOffsets if hasattr(lane, "_stopOffsets") else None
        if so:
            stop_offset[lane.getID()] = max(so.values())

    # --- 사거리(교차점 묶음)
    jn = {n.getID(): n for n in net.getNodes() if n.getType() in JUNCTION_TYPES}
    parent = {k: k for k in jn}

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    # 차도로 이어진 이웃 교차점 수 - 2 이하면 도로가 그냥 이어지는 점(진입부 토막을 끊는 점)이지 갈림점이 아님
    nbrs = defaultdict(set)
    for e in net.getEdges():
        if e.getFunction() == "" and e.allows("passenger"):
            a, b = e.getFromNode().getID(), e.getToNode().getID()
            nbrs[a].add(b); nbrs[b].add(a)
    # 짧은 연결 도로라도 양 끝이 모두 갈림점일 때만 한 사거리로 묶는다. 진입부 토막(바깥 끝이 갈림점이 아님)을
    # 묶으면 그 위의 진입 횡단보도가 '한가운데'로 잘못 잡힌다(#23·#39에서 겪음)
    # 같은 신호가 제어하는 교차점끼리는 20m까지, 아니면(따로 떨어진 이웃 교차로일 수 있음) 10m까지만 묶는다 -
    # 20m로 다 묶으면 15m 간격의 T자 두세 개가 한 사거리가 되어 각 T자의 입구 횡단보도가 '한가운데'로 잡혔다
    tl_of = {}
    for t in net.getTrafficLights():
        for c in t.getConnections():
            tl_of[c[0].getEdge().getToNode().getID()] = t.getID()
    for e in net.getEdges():
        if e.getFunction() == "" and e.allows("passenger") and e.getLength() < CONNECTOR_M:
            a, b = e.getFromNode().getID(), e.getToNode().getID()
            same_tl = a in tl_of and tl_of.get(a) == tl_of.get(b)
            if not same_tl and e.getLength() >= CONNECTOR_OTHER_M:
                continue
            if a in jn and b in jn and len(nbrs[a]) >= 3 and len(nbrs[b]) >= 3:
                parent[find(a)] = find(b)
    clusters = defaultdict(set)
    for k in jn:
        clusters[find(k)].add(k)

    cross_by_node = defaultdict(list)
    for node, cid, edges, width, pos in crossings:
        cross_by_node[node].append((cid, edges, width, pos))

    results = []
    for nodes in clusters.values():
        # 바깥 갈래: 사거리 밖과 이어진 차도
        ext = []
        for n in nodes:
            node = net.getNode(n)
            for e in node.getIncoming():
                if e.allows("passenger") and e.getFromNode().getID() not in nodes:
                    s = e.getShape(); ext.append((math.degrees(math.atan2(s[-2][1] - s[-1][1], s[-2][0] - s[-1][0])) % 360, e.getID(), "in"))
            for e in node.getOutgoing():
                if e.allows("passenger") and e.getToNode().getID() not in nodes:
                    s = e.getShape(); ext.append((math.degrees(math.atan2(s[1][1] - s[0][1], s[1][0] - s[0][0])) % 360, e.getID(), "out"))
        arms = []
        for ang, eid, d in sorted(ext):
            for a in arms:
                if angle_gap(ang, a["ang"]) < ARM_TOL:
                    a["edges"].append(eid); break
            else:
                arms.append({"ang": ang, "edges": [eid]})
        if len(arms) < 3:
            continue
        xs = [net.getNode(n).getCoord() for n in nodes]
        cx, cy = sum(p[0] for p in xs) / len(xs), sum(p[1] for p in xs) / len(xs)
        tls = sorted({tl_of[n] for n in nodes if n in tl_of})
        issues = defaultdict(list)
        inner_edges = {e.getID() for n in nodes for e in net.getNode(n).getOutgoing()
                       if e.getToNode().getID() in nodes}
        # 갈래를 바깥으로 따라가며(갈림점이 아닌 점만 넘어서, 30m까지) 그 위 도로·교차점도 갈래에 넣는다 -
        # 진입 횡단보도가 사거리 바로 앞 토막 끝 점에 붙어 있는 경우가 많다
        arm_of_edge, arm_nodes = {}, defaultdict(set)
        for i, a in enumerate(arms):
            for eid in a["edges"]:
                e = net.getEdge(eid)
                inward = e.getToNode().getID() in nodes
                near = e.getToNode() if inward else e.getFromNode()
                far = e.getFromNode() if inward else e.getToNode()
                dist = e.getLength()
                arm_of_edge[eid] = i
                while far.getID() not in nodes and len(nbrs[far.getID()]) <= 2 and dist < ARM_WALK_M:
                    arm_nodes[i].add(far.getID())
                    cand = far.getIncoming() if inward else far.getOutgoing()
                    nxt = [x for x in cand if x.allows("passenger")
                           and (x.getFromNode() if inward else x.getToNode()).getID() != near.getID()]
                    if not nxt:
                        break
                    e = nxt[0]
                    arm_of_edge[e.getID()] = i
                    dist += e.getLength()
                    near, far = far, (e.getFromNode() if inward else e.getToNode())
        arm_cross = defaultdict(list)   # 갈래 -> [(crossing id, 교차점 좌표)]
        for n in sorted(nodes | set().union(*arm_nodes.values()) if arm_nodes else nodes):
            for cid, edges, width, pos in cross_by_node.get(n, []):
                car = [e for e in edges if net.hasEdge(e) and net.getEdge(e).allows("passenger")]
                if car and all(e in inner_edges for e in car):
                    issues["CENTER"].append(cid)
                if width is not None and width < MIN_WIDTH:
                    issues["NARROW"].append(f"{cid}({width}m)")
                arms_hit = {arm_of_edge[e] for e in car if e in arm_of_edge}
                for a in arms_hit:
                    arm_cross[a].append((cid, pos or net.getNode(n).getCoord(), set(car)))
        for a, lst in arm_cross.items():
            for i in range(len(lst)):
                for j in range(i + 1, len(lst)):
                    # 같은 차도를 두 번 건너는 것만 겹침 - 분리된 들어오는/나가는 차로를 따로 건너는 두 조각(가운데
                    # 보행섬)은 규칙상 허용이라 제외(2026-09-29, 기준 사거리 cluster_436538601…이 이렇게 되어 있음)
                    if lst[i][2] & lst[j][2] and math.dist(lst[i][1], lst[j][1]) < DUP_M:
                        issues["DUPLICATE"].append(f"{lst[i][0]}~{lst[j][0]}")
        if tls:
            for i, a in enumerate(arms):
                has_sidewalk = any(any(l.allows("pedestrian") and not l.allows("passenger") for l in net.getEdge(e).getLanes()) for e in a["edges"])
                if has_sidewalk and i not in arm_cross:
                    issues["NO_CROSS"].append(f"갈래{i}({int(a['ang'])}°:{','.join(a['edges'])})")
            for t in tls:
                logic = list(net.getTLS(t).getPrograms().values())[0]
                ph = logic.getPhases()
                links = tl_links.get(t, {})
                n_links = len(ph[0].state)
                for i in range(n_links):
                    info = links.get(i)
                    if info and all(p.state[i] in "rs" for p in ph):
                        issues["PED_NO_GREEN"].append(f"{t}:{i}")
                # 충돌 판정은 SUMO의 내부 차선 충돌 목록으로(tls_conflicts_traci.py) - net.xml 충돌표를
                # 직접 해석하던 방식은 오탐이 많았다(2026-09-28)
                for f in conflicts.get(t, []):
                    issues["CONFLICT_G"].append(f"{t}:단계{f['phase']}({f['duration']:.0f}s) {f['kind']} 링크{f['links'][0]}×{f['links'][1]}")
            # 정지선: 신호 사거리로 들어오는 차선 중 횡단보도가 있는 갈래의 정지 오프셋
            for i, a in enumerate(arms):
                if i not in arm_cross:
                    continue
                for e in a["edges"]:
                    ed = net.getEdge(e)
                    if ed.getToNode().getID() in nodes:
                        lanes = [l for l in ed.getLanes() if l.allows("passenger")]
                        if any(stop_offset.get(l.getID(), edge_stop.get(e, 0.0)) < MIN_STOP_OFFSET for l in lanes):
                            issues["STOPLINE"].append(e)
        lon, lat = net.convertXY2LonLat(cx, cy)
        results.append({"id": sorted(nodes)[0], "nodes": sorted(nodes), "x": round(cx, 1), "y": round(cy, 1),
                        "lat": round(lat, 6), "lon": round(lon, 6), "arms": len(arms), "signal": bool(tls),
                        "tls": tls, "issues": {k: v for k, v in issues.items()}})
    json.dump(results, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    tot = defaultdict(int)
    for r in results:
        for k in r["issues"]:
            tot[k] += 1
    print(f"사거리(3갈래 이상) {len(results)}곳, 신호 {sum(r['signal'] for r in results)}곳")
    for k in ("CENTER", "DUPLICATE", "NO_CROSS", "NARROW", "PED_NO_GREEN", "CONFLICT_G", "STOPLINE"):
        print(f"  {k:13s} 문제 있는 사거리 {tot[k]}곳")


if __name__ == "__main__":
    main()
