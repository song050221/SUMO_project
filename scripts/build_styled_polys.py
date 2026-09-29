"""시연용으로 지도 배경(건물·토지이용·물·녹지) 색을 다시 칠한 폴리곤 파일을 만든다.

network/gwangjin.poly.xml(polyconvert 기본 색: 연분홍 건물, 회색 주거지, 진분홍 대학 부지)은
그대로 두고 network/gwangjin_styled.poly.xml을 새로 만든다. 대시보드가 이 파일을 쓴다.

- 색은 OpenStreetMap 기본 지도(Carto) 화풍을 따른다 - 사람들이 "지도"로 익숙하게 읽는 색.
- 건물은 채움 위에 한 톤 어두운 테두리를 따로 그려(채움 없는 폴리곤) 윤곽이 보이게 한다.
- 물 폴리곤 중 광진구 net보다 몇 배 큰 것(OSM 한강 multipolygon의 일부 way만 닫혀서 생긴
  수십 km짜리 가짜 면)과, net 경계 밖에 완전히 떨어진 것은 뺀다.
- 공원·숲·녹지 안에는 나무 이미지(POI)를 흩뿌려 녹지가 녹지처럼 보이게 한다
  (network/assets/tree_*.png, scripts/build_visual_assets.py로 생성).

    python scripts/build_styled_polys.py
"""

import math
import os
import random
import re
import xml.sax.saxutils as su

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "network", "gwangjin.poly.xml")
DST = os.path.join(ROOT, "network", "gwangjin_styled.poly.xml")
NET_BOUNDARY = (0.0, -0.89, 13739.84, 11472.29)  # gui_viewport.NETWORK_BOUNDARY와 같은 값
MAX_SPAN_M = 15000.0      # 이보다 큰 폴리곤은 잘못 닫힌 가짜 면으로 본다(net 대각선 ~17.9km)
TREE_SPACING_M = 14.0     # 녹지 안 나무 간격(대략)
MAX_TREES = 9000

# type -> (채움 색, layer). layer가 클수록 위에 그려진다(도로는 0).
STYLE = {
    "residential": ((224, 223, 223), -6),
    "landuse":     ((236, 234, 222), -6),
    "commercial":  ((242, 218, 217), -6),
    "industrial":  ((235, 219, 232), -6),
    "military":    ((243, 227, 221), -6),
    "farm":        ((238, 240, 213), -6),
    "university":  ((255, 255, 229), -6),
    "college":     ((255, 255, 229), -6),
    "school":      ((255, 255, 229), -6),
    "research_institute": ((255, 255, 229), -6),
    "clinic":      ((255, 250, 235), -6),
    "amenity":     ((240, 236, 226), -5),
    "tourism":     ((236, 240, 222), -5),
    "historic":    ((236, 228, 212), -5),
    "shop":        ((255, 214, 209), -5),
    "man_made":    ((230, 230, 230), -5),
    "leisure":     ((200, 236, 180), -5),
    "sport":       ((170, 224, 203), -4),
    "natural":     ((173, 209, 158), -5),
    "forest":      ((173, 209, 158), -5),
    "parking":     ((238, 238, 238), -4),
    "water":       ((160, 204, 224), -3),
    "building":    ((217, 208, 201), -1),
}
BUILDING_OUTLINE = (178, 164, 152)
GREEN_TYPES = {"leisure", "forest", "natural"}
POLY_RE = re.compile(r'<poly id="([^"]+)" type="([^"]+)" color="([^"]+)" fill="(\d)" layer="([^"]+)" shape="([^"]+)"(.*?)/>')


def _bbox(pts):
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _area(pts):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2


def _inside(pt, pts):
    x, y = pt
    inside = False
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _rgb(c):
    return ",".join(str(v) for v in c)


def main():
    rng = random.Random(7)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           "<!-- scripts/build_styled_polys.py가 network/gwangjin.poly.xml에서 만든 시연용 배경. 직접 고치지 말고 스크립트를 고칠 것. -->",
           "<additional>"]
    dropped, kept, outlines, trees = [], 0, 0, 0
    nx0, ny0, nx1, ny1 = NET_BOUNDARY
    greens = []
    for line in open(SRC, encoding="utf-8"):
        m = POLY_RE.search(line)
        if not m:
            continue
        pid, ptype, _color, fill, _layer, shape, rest = m.groups()
        pts = [tuple(map(float, p.split(","))) for p in shape.split()]
        x0, y0, x1, y1 = _bbox(pts)
        if max(x1 - x0, y1 - y0) > MAX_SPAN_M or x1 < nx0 or x0 > nx1 or y1 < ny0 or y0 > ny1:
            dropped.append((pid, ptype, round(x1 - x0), round(y1 - y0)))
            continue
        color, layer = STYLE.get(ptype, ((236, 234, 222), -5))
        out.append(f'    <poly id="{su.escape(pid)}" type="{ptype}" color="{_rgb(color)}" fill="{fill}" '
                   f'layer="{layer:.2f}" shape="{shape}"{rest}/>')
        kept += 1
        if ptype == "building" and fill == "1":
            out.append(f'    <poly id="{su.escape(pid)}_outline" type="building_outline" color="{_rgb(BUILDING_OUTLINE)}" '
                       f'fill="0" lineWidth="0.35" layer="{layer + 0.5:.2f}" shape="{shape}"/>')
            outlines += 1
        if ptype in GREEN_TYPES and fill == "1" and _area(pts) > 150:
            greens.append(pts)
    # 녹지 안에 나무 흩뿌리기 - 격자에 약간의 흔들림을 줘서 자연스럽게. 후보를 전부 모은 뒤
    # MAX_TREES만큼 고르게 뽑는다(앞쪽 녹지에만 몰리지 않게).
    candidates = []
    for pts in greens:
        x0, y0, x1, y1 = _bbox(pts)
        row = 0
        y = y0 + TREE_SPACING_M / 2
        while y < y1:
            x = x0 + TREE_SPACING_M / 2 + (TREE_SPACING_M / 2 if row % 2 else 0)
            while x < x1:
                px, py = x + rng.uniform(-4, 4), y + rng.uniform(-4, 4)
                if _inside((px, py), pts):
                    candidates.append((px, py))
                x += TREE_SPACING_M
            y += TREE_SPACING_M * math.sqrt(3) / 2
            row += 1
    if len(candidates) > MAX_TREES:
        candidates = rng.sample(candidates, MAX_TREES)
    for px, py in candidates:
        size = rng.uniform(7.0, 11.0)
        out.append(f'    <poi id="tree_{trees}" type="tree" color="255,255,255" layer="-0.50" '
                   f'x="{px:.2f}" y="{py:.2f}" imgFile="assets/tree_{rng.randrange(4)}.png" '
                   f'width="{size:.1f}" height="{size:.1f}" angle="{rng.uniform(0, 360):.0f}"/>')
        trees += 1
    out.append("</additional>")
    with open(DST, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    print(f"폴리곤 {kept}개(건물 테두리 {outlines}개 추가), 나무 {trees}그루, 제외 {len(dropped)}개 -> {DST}")
    for d in dropped[:10]:
        print("  제외:", d)


if __name__ == "__main__":
    main()
