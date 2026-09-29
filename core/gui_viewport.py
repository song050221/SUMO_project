"""sumo-gui의 시각 품질(scheme)과 시작 시 확대 위치(viewport)를 설정하는 파일을 만든다.

SUMO의 gui-settings-file viewport는 zoom을 "전체 네트워크가 화면에 꽉 찼을 때 100%"
기준 퍼센트로 받는다. 구역 중심 좌표(cctv_zones.json)를 기준으로, 원하는 실제 폭(미터)이
화면에 꽉 차도록 zoom 값을 역산한다.

scheme은 SUMO GUI가 자체적으로 내보낸 실제 파일(예: $SUMO_HOME/tools/game/A10KW/osm.view.xml)의
스키마를 참고해, 배경색·차량/보행자 디테일과 크기만 최소한으로 덮어쓴다 — 알 수 없는 속성값을
넣어 렌더링이 깨지는 위험을 피하기 위해 나머지는 SUMO 기본값을 그대로 둔다.
"""

import json

# gwangjin.net.xml의 실측 경계 (sumolib.net.readNet(...).getBoundary()).
# net.xml을 다시 빌드하면 find_cctv_zones.py 실행 시 함께 갱신할 것.
NETWORK_BOUNDARY = (0.0, -0.89, 13739.84, 11472.29)

# 배경(폴리곤이 없는 빈 땅) 색 - OpenStreetMap 기본 지도(Carto)의 땅 색. 실제 물/녹지/주거지는
# gwangjin_styled.poly.xml의 폴리곤이 각자의 색(물=파랑, 숲=초록 등)으로 덮어 그린다
# (scripts/build_styled_polys.py, 같은 화풍). 2026-09-28 시연 품질 개선 전에는 "222,226,214".
BACKGROUND_COLOR = "242,239,233"
# 도로/보도/교차로 색 - 기본값(새까만 도로, 짙은 회색 보도)은 지도가 아니라 도면처럼 보여서
# 아스팔트 회색과 밝은 보도로 바꾼다.
ROAD_COLOR = "78,80,86"
SIDEWALK_COLOR = "214,210,202"
# 차량은 network/assets의 위에서 본 차 이미지(raster)로, 보행자는 사람 이미지로 그린다.
# 이미지가 없는 차종(vehicle_style.xml을 안 불러온 경우)은 SUMO가 단순 도형으로 대신 그린다.
VEHICLE_QUALITY = 3      # 0 삼각형, 1 상자, 2 단순 도형, 3 raster 이미지
VEHICLE_EXAGGERATION = 1.3
PERSON_QUALITY = 3
PERSON_EXAGGERATION = 4.0  # 실제 크기(폭 0.48m)로는 110m 확대 화면에서도 안 보여서 키운다 - 그림만 커지고 충돌 판정 크기는 그대로

# 보행자 색(초록) - pedestrian_style.xml의 vType color와 같은 값. GUI의 person 색상
# 모드가 어떤 것이든(uniform/given type color 등) 초록으로 뜨도록 이중으로 강제한다.
PEDESTRIAN_COLOR = "30,180,60"
# 사고 마커(빨간 원) 색 - traci.poi.add()로 찍는 원과 맞춘다.
ACCIDENT_COLOR = (220, 20, 20, 255)

# CCTV 9곳 + 어린이보호구역을 합쳐서 찾는다 - 카메라 포커스(zone_bounds)는 어느 쪽
# zone_id가 와도 동작해야 한다.
DEFAULT_ZONE_FILES = ("network/cctv_zones.json", "network/school_zones.json")

# 건국대학교 서울캠퍼스 실좌표(37.5419N, 127.0764E)를 net.xml의 UTM 투영으로 변환한
# 지도 로컬 좌표 - sumolib.net.Net.convertLonLat2XY()로 계산함(2026-08-10). 시뮬레이션
# 시작 화면 기본 위치로 쓴다. CCTV/어린이보호구역처럼 별도 zones.json에 등록된 "구역"이
# 아니라 그냥 고정 지도 랜드마크라 여기 상수로만 둔다.
# 2026-09-29: OSM 캠퍼스 경계(way 26281749 "건국대학교 서울캠퍼스", 약 990x700m)의 중심으로 옮김 - 예전 값
# (6899.05, 3397.94)은 캠퍼스 서쪽으로 90m쯤 치우쳐 있었다. 시작 화면 폭은 KONKUK_UNIV_VIEW_WIDTH_M.
KONKUK_UNIV_COORD = (6985.5, 3385.6)
KONKUK_UNIV_VIEW_WIDTH_M = 1150  # 캠퍼스 전체가 화면에 꽉 차게(캠퍼스 폭 990m + 여백)

_ZONE_CACHE = {}


def _load_zones(zones_files=DEFAULT_ZONE_FILES):
    if isinstance(zones_files, str):
        zones_files = (zones_files,)
    if zones_files not in _ZONE_CACHE:
        merged = {}
        for path in zones_files:
            with open(path, encoding="utf-8") as f:
                merged.update(json.load(f))
        _ZONE_CACHE[zones_files] = merged
    return _ZONE_CACHE[zones_files]


def point_bounds(x, y, view_width_m=80):
    """임의의 (x, y) 좌표를 중심으로 (xmin, ymin, xmax, ymax) 사각형을 반환한다.

    traci.gui.setBoundary()에 그대로 넘길 수 있는 형태 — 차량/보행자/사고처럼 미리
    좌표를 알 수 없고 매번 현재 위치를 조회해야 하는 대상을 카메라로 옮길 때 쓴다.
    """
    half = view_width_m / 2
    return (x - half, y - half, x + half, y + half)


def zone_bounds(zone_id, view_width_m=250, zones_files=DEFAULT_ZONE_FILES):
    """구역 중심을 기준으로 (xmin, ymin, xmax, ymax) 사각형을 반환한다.

    traci.gui.setBoundary()에 그대로 넘길 수 있는 형태 — 실시간으로 sumo-gui 카메라를
    특정 구역으로 이동시킬 때(대시보드 클릭 등) 이 함수를 쓴다. CCTV 구역/어린이보호
    구역 zone_id 어느 쪽이든 동작한다.
    """
    zones = _load_zones(zones_files)
    if zone_id not in zones:
        raise ValueError(f"{zones_files}에 '{zone_id}'가 없습니다. 사용 가능: {list(zones)}")
    x, y = zones[zone_id]["coord"]
    return point_bounds(x, y, view_width_m)


def write_scheme(output_path="viewsettings.xml", zone_id="zone_1", view_width_m=250,
                  zones_files=DEFAULT_ZONE_FILES, coord=None):
    """시각 품질(scheme) + 특정 위치 확대(viewport)를 하나의 파일로 만든다.

    coord=(x, y)를 직접 주면 zone_id 조회 없이 그 좌표를 그대로 쓴다(건국대학교처럼
    zones.json에 등록 안 된 고정 랜드마크로 시작할 때). coord가 없고 zone_id가
    None/빈 문자열이면 viewport 없이 scheme만 만든다 (전체 네트워크 기본 보기).
    """
    viewport_xml = ""
    if coord is not None:
        x, y = coord
        min_x, min_y, max_x, max_y = NETWORK_BOUNDARY
        network_span = max(max_x - min_x, max_y - min_y)
        zoom = (network_span / view_width_m) * 100
        viewport_xml = f'    <viewport zoom="{zoom:.0f}" x="{x}" y="{y}" angle="0"/>\n'
    elif zone_id:
        zones = _load_zones(zones_files)
        if zone_id not in zones:
            raise ValueError(f"{zones_files}에 '{zone_id}'가 없습니다. 사용 가능: {list(zones)}")
        x, y = zones[zone_id]["coord"]

        min_x, min_y, max_x, max_y = NETWORK_BOUNDARY
        network_span = max(max_x - min_x, max_y - min_y)
        zoom = (network_span / view_width_m) * 100
        viewport_xml = f'    <viewport zoom="{zoom:.0f}" x="{x}" y="{y}" angle="0"/>\n'

    xml = (
        "<viewsettings>\n"
        '    <scheme name="gwangjin_demo">\n'
        f'        <background backgroundColor="{BACKGROUND_COLOR}" showGrid="0"/>\n'
        '        <edges laneEdgeMode="0" laneShowBorders="1" showLinkDecals="1" showRails="1" hideConnectors="1">\n'
        '            <colorScheme name="uniform">\n'
        f'                <entry color="{ROAD_COLOR}" name="road"/>\n'
        f'                <entry color="{SIDEWALK_COLOR}" name="sidewalk"/>\n'
        '                <entry color="192,66,44" name="bike lane"/>\n'
        '                <entry color="0,0,0,0" name="green verge"/>\n'
        '                <entry color="160,204,224" name="waterway"/>\n'
        '                <entry color="120,120,120" name="no passenger"/>\n'
        '                <entry color="red" name="closed"/>\n'
        '                <entry color="green" name="connector"/>\n'
        "            </colorScheme>\n"
        "        </edges>\n"
        '        <junctions junctionMode="0" drawCrossingsAndWalkingareas="1">\n'
        '            <colorScheme name="uniform">\n'
        f'                <entry color="{ROAD_COLOR}"/>\n'
        '                <entry color="160,204,224" name="waterway"/>\n'
        "            </colorScheme>\n"
        "        </junctions>\n"
        f'        <vehicles vehicleQuality="{VEHICLE_QUALITY}" vehicle_exaggeration="{VEHICLE_EXAGGERATION:.2f}" showBlinker="1"/>\n'
        f'        <persons personQuality="{PERSON_QUALITY}" person_exaggeration="{PERSON_EXAGGERATION:.2f}">\n'
        '            <colorScheme name="given person/type color">\n'
        f'                <entry color="{PEDESTRIAN_COLOR}"/>\n'
        "            </colorScheme>\n"
        '            <colorScheme name="uniform">\n'
        f'                <entry color="{PEDESTRIAN_COLOR}"/>\n'
        "            </colorScheme>\n"
        "        </persons>\n"
        "    </scheme>\n"
        f"{viewport_xml}"
        "</viewsettings>\n"
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(xml)
    return output_path


# 이전 이름과의 호환 - run_gui_preview.py/dashboard_server.py가 이 이름으로 호출한다.
write_zone_viewport = write_scheme
