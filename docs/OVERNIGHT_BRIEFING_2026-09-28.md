# 밤사이 작업 브리핑 (2026-09-28 ~)

> **2026-09-29 파일 정리 후 참고**: 이 문서가 가리키는 캡처 이미지·백업 폴더는 삭제됐다(되돌리기 불가, HANDOFF AB번). 내용은 기록용으로만 남긴다.

## 일어나서 먼저 볼 것 (요약)

1. **전후 비교 그림**: `docs/report_assets/overnight_2026-09-28/` 의 3장.
2. **직접 확인하기** (2분):
   - `start_dashboard.bat` 실행 → 브라우저 대시보드가 뜨면 sumo-gui 창이 새 화면(회색 도로, 차 이미지, 나무)으로 뜸.
   - 새 터미널에서 `python scripts/fake_hardware_sender.py --loop` → 신양초 카드에 "실물 연동: 연결됨", sumo-gui 카메라가
     신양초로 이동, 주황(선행)·하늘색(후행) 차가 C에서 들어와 LED 보행자 앞 정지 → 후행 후진·B 우회 → 도착 반복.
3. **마음에 안 들면**: 각 단계의 "되돌리기" 참고. 전부 되돌리려면 `experiment_data/backup_overnight_2026-09-28/step0_original/`.

| 단계 | 내용 | 상태 |
|---|---|---|
| 1 | 실물 보드(traffic_state) → 신양초 사거리 자동 반영 | 완료, 가짜 송신기로 SUMO·대시보드까지 확인 |
| 2 | 시연 화면 품질(차·도로·건물·물·녹지·보행자) | 완료, 캡처로 확인, 속도 저하 없음(스텝당 6~7ms 동일) |
| 3 | 실물 연결 중 실제 시간 속도 + 연결 시 카메라 자동 이동 | 완료(카메라 이동은 화면으로 직접 확인 못 함) |

**결정이 필요한 것** (2026-09-28 오후 처리)
- ~~`scripts/live_demo_controller.py` 지울지~~ → **삭제함**(+ `tests/test_live_demo_controller.py`, `tests/test_udp_integration.py`,
  `configs/live_demo_config.json`). `core/decision_policy.py`는 중앙 서버가 쓰므로 남김(주석만 고침).
- D 경로(보드 C→D): 팀원이 만드는 중. 올라오면 `configs/hardware_twin.json`의 D 좌표를 맞춰야 함(추정값으로 넣어 둠).
- ~~백업 폴더 정리~~ → **삭제함**: 예전 net 백업 5개(before_E, before_tlsjoin, before_yellow, before_junctionjoin,
  before_round3, 약 690MB). `experiment_data` 741MB → 53MB. 이 브리핑의 백업(`backup_overnight_2026-09-28`, 4.9MB)은
  어젯밤 변경을 되돌릴 유일한 수단이라 남김. 단, `step0_original` 등 안에 옛 `live_demo_controller.py` 사본이 들어 있으니
  "전부 되돌리기"를 하면 그 파일들도 다시 살아남.

**팀원 저장소**: 밤새 여러 번 확인 - 06:01 기준 새 커밋·브랜치·PR 댓글 없음(마지막 커밋 cc489eb, 9/27 02:04).

요청: ① 팀원(하드웨어) 요청 반영 - 실물 보드 상황을 SUMO 신양초 사거리에 자동으로 그리기
(SUMO는 판단 없이 그리기만), ② 시연용으로 SUMO 화면 요소(건물·차량·보행자·강·풀 등)
품질 올리기, ③ 팀원 저장소 수시 확인.

## 되돌리는 법 (공통)

작업 시작 전 상태 전체를 `experiment_data/backup_overnight_2026-09-28/step0_original/`에
복사해 둠(core, scripts, dashboard, configs, tests, viewsettings.xml, start_dashboard.bat,
network의 gwangjin.poly.xml / pedestrian_style.xml / gwangjin.sumocfg / school_zones.json).
네트워크(gwangjin.net.xml)는 이 작업에서 건드리지 않음.

- **전부 되돌리기**: 위 폴더 안의 것들을 원래 자리로 덮어쓰기
  (`network/`에 속한 4개 파일은 `network/`로).
- **단계별로 되돌리기**: 아래 각 단계에 적힌 파일만 그 단계 백업에서 복사.

---

## 1단계. 실물 하드웨어 → 신양초 사거리 자동 반영 (완료)

**무엇이 바뀌나**: 대시보드(`start_dashboard.bat`)를 켜면 UDP 9002로 차량 호스트의
`traffic_state`를 받아 SUMO 신양초 사거리에 실물 상황을 그대로 그린다. 버튼을 누를 필요 없음.
SUMO는 판단하지 않는다(팀원 결정: 차량 → SUMO 한 방향).

| 실물(보드) | SUMO 신양초 사거리 |
|---|---|
| 차가 C에서 출발 | 남동 진입로 `-172058984`에 차 생성 (선행 주황 / 후행 하늘색) |
| 목적지 A / B / D | 북서 `-85960673#2` / 남서 `172058988#2`(C에서 좌회전) / 북동 `-172058988#0`(우회전) |
| 차가 움직이거나 섬 | 보드 위 진행 거리를 SUMO 경로 위 거리로 옮겨 같은 자리에 놓음 (LED 앞에서 서면 SUMO에서도 보행자 지점 앞에서 섬) |
| 후행이 `divert_to_B`로 우회 | SUMO 차 경로도 B로 바뀌고 색이 마젠타로 |
| 도착(`arrived`) | SUMO 차 제거 |
| 보행자 LED 인식 | 북서 진출로 10m 지점에 파란 원(LED 위치 따라 도로를 가로지름) + 기존 "보행자 사고" 흐름 켜짐(주변 일반 차량은 지금처럼 중앙 알고리즘이 반응) |
| 연결 상태 | 대시보드 신양초 카드에 "실물 연동: 연결됨/대기 중/끊김" + 차량별 "선행 car_2 · 정지 → A" |

- 보드 A/B/C/D ↔ 사거리 대응은 sumolib로 회전 방향을 계산해 확인(남서 +80° 좌회전 = B, 북동 -94° 우회전 = D).
- 실물 차량을 따라 그리는 SUMO 차(ID `hwtwin_…`)는 중앙 경로 재계산·사고 대응 명령·선제 우회·견인에서 모두 빠짐.
- D 경로는 팀원이 만드는 중이라 **추정값**. 확정되면 `configs/hardware_twin.json`의 `board_paths.D`,
  `anchors.D`만 고치면 됨(테스트가 기준점이 주행선 위에 있는지 검사함).
- 끄려면 `HARDWARE_TWIN=0` 환경변수, 포트 바꾸려면 `HARDWARE_TWIN_PORT`.

**하드웨어 없이 리허설**: 대시보드를 켠 뒤 다른 터미널에서
`python scripts/fake_hardware_sender.py` (선행·후행 C→A + 보행자 = 사고 시나리오).
`--lead A|B|D --follow A|B|D --no-pedestrian --loop`로 조합 변경. 팀원 저장소의 `replay.py`(실주행 6장면)도 그대로 붙음.

**확인한 것**: 광진구 net에 붙여 주 시나리오를 돌림 - 선행은 보행자 지점(10m) 바로 앞 8.0m에서
12~16초 정지 후 도착, 후행은 사거리 입구에서 막혀 후진 → B(`172058988#2`)로 우회 → 도착.
sumo-gui 캡처로 위치 확인. 테스트 27 → 36개 전부 통과.

**바뀐 파일**
- 새 파일: `core/hardware_twin.py`, `configs/hardware_twin.json`, `scripts/fake_hardware_sender.py`, `tests/test_hardware_twin.py`
- 수정: `scripts/dashboard_server.py`(수신 시작 + 매 스텝 반영 + 상태 전송),
  `dashboard/templates/index.html`·`dashboard/static/dashboard.js`·`dashboard.css`(신양초 카드 "실물 연동"),
  `core/vehicle_controller.py`·`central_server.py`·`predictive_reroute.py`·`stuck_vehicle_remover.py`(hwtwin 차량 제외 한두 줄씩)

**이 단계만 되돌리기**: `step0_original/`의 위 수정 파일들을 원위치로 복사하고 새 파일 4개 삭제.
(1단계 직후 상태 스냅샷: `experiment_data/backup_overnight_2026-09-28/step1_after_hardware_twin/`)

**그대로 둔 것**: 예전 "차량 감지 / 보행자 출현" 버튼(수동 흉내용)은 남겨 둠.
`scripts/live_demo_controller.py`(SUMO→차량 판단 전송)는 팀원 결정으로 시연에서 안 쓰이지만 지우지 않음 - 지울지는 결정 필요.

## 2단계. 시연용 SUMO 화면 품질 개선 (완료)

**비교 그림**: `docs/report_assets/overnight_2026-09-28/`
- `compare_konkuk.png` 건국대 일대(대시보드 시작 화면) 전/후 - 캡처 타이밍 탓에 두 장의 확대 배율이 조금 다름
- `compare_intersection.png` 큰 교차로 전/후 (마젠타 차 = 대시보드의 "경로 재배치" 강조가 이미지 차에도 보이는지 확인한 것)
- `hardware_twin_sinyang.png` 신양초 사거리에서 실물 연동 장면(주황 선행이 LED 보행자 앞 정지, 하늘색 후행은 사거리 입구)

| 요소 | 전 | 후 |
|---|---|---|
| 차량 | 전부 노란 단순 도형 | 위에서 본 차 이미지 25종(흰·검정·회색·은색이 대부분인 한국 도로 색 비율 + SUV + 택시) |
| 도로 | 새까만 선, 큰 교차로는 검은 덩어리 | 아스팔트 회색 + 밝은 보도, 차선 흰 선 |
| 건물 | 테두리 없는 연분홍 | 베이지 + 한 톤 어두운 테두리 |
| 토지이용 | 대학 진분홍, 주거지 회색 | OpenStreetMap 기본 지도 색(학교 연노랑, 상업 분홍, 주차장 회색 …) |
| 물 | 건대 일감호가 대학 부지에 가려 안 보였음 | 물을 대학·주거지 위에 그려 호수가 보임. 육지까지 덮던 57km짜리 가짜 물 면(`378066781`) 제거 - 한강은 다른 폴리곤으로 그대로 |
| 공원·숲 | 연두 면 | 연두 면 + 나무 9,000그루(나무 이미지) |
| 보행자 | 초록 점 5배 | 사람 이미지(초록 옷) 4배 |
| 실물 연동 | (없음) | 선행 주황 / 후행 하늘색 / 우회 마젠타 차 이미지, LED 보행자는 파란 빛 사람 이미지, 그 자리에 어린이보호구역 노란 횡단보도 |

- **주행 동작은 안 바뀜**: 차종 묶음(`DEFAULT_VEHTYPE` 재정의)에는 그림·색만 있고 길이·가속 등 물리 값은
  SUMO 기본값 그대로(길이 5.0, 폭 1.8, 가속 2.6, 감속 4.5 확인). 실험 스크립트(`measure_congestion.py` 등)는
  이 파일을 안 불러오므로 측정 결과와 무관. 대시보드는 차종 추첨에 난수를 쓰므로 같은 seed여도 예전과 차 배치가 조금 다를 수 있음.
- 인터넷에서 받은 이미지 없음 - 전부 PIL로 직접 그림(`scripts/build_visual_assets.py`).
- 알아둘 점: sumo-gui는 차 이미지에 차 색을 곱해 그림 → 이미지 차종의 색은 흰색으로 둠. 그래서 검은 차는
  마젠타 강조를 받아도 검게 보이고 강조 고리로만 구분됨.
- 캡처 도중 이미지 파일을 다시 만들면 sumo-gui가 꺼질 수 있음(실제로 한 번 겪음) - 시연 중엔 스크립트를 돌리지 말 것.

**바뀐 파일**
- 새 파일: `scripts/build_visual_assets.py` → `network/assets/`(PNG 30개) + `network/vehicle_style.xml`,
  `scripts/build_styled_polys.py` → `network/gwangjin_styled.poly.xml`
- 수정: `core/gui_viewport.py`(배경·도로·교차로 색, 차량/보행자 raster 이미지, 배율),
  `scripts/dashboard_server.py`·`scripts/run_gui_preview.py`의 `POLY_FILE`
  (`network/gwangjin.poly.xml,network/pedestrian_style.xml` → `network/gwangjin_styled.poly.xml,network/vehicle_style.xml`),
  `core/hardware_twin.py`·`configs/hardware_twin.json`(역할별 차 이미지, LED 보행자 이미지, 노란 횡단보도)
- 원본 `network/gwangjin.poly.xml`, `network/pedestrian_style.xml`은 그대로 둠.

**이 단계만 되돌리기**: `step1_after_hardware_twin/`의 `core/gui_viewport.py`, `core/hardware_twin.py`,
`configs/hardware_twin.json`, `scripts/dashboard_server.py`, `scripts/run_gui_preview.py`를 원위치로 복사
(새 파일들은 남아 있어도 아무도 안 불러옴). 2단계 직후 스냅샷: `step2_after_visual_quality/`.
**일부만 되돌리기**: 예전 배경만 원하면 `POLY_FILE`에서 `gwangjin_styled.poly.xml`을 `gwangjin.poly.xml`로,
예전 차 모양(단순 도형)만 원하면 `core/gui_viewport.py`의 `VEHICLE_QUALITY = 2`.

## 3단계. 시연 흐름 다듬기 (완료)

1. **실물 연결 중엔 실제 시간 속도로**: 대시보드 시뮬레이션은 평소 실제 시간의 약 6배로 흐름(측정: 8초에 49스텝).
   실물 차는 실제 시간대로 움직여서 주변 차만 휙휙 지나가 보이던 것을, 연결된 동안은 1스텝 = 실제 1초로 맞춤
   (측정: 연결 후 10초에 10스텝). 연결이 끊기면 원래 속도로 돌아감.
2. **처음 연결되면 카메라를 신양초로**: 실물 메시지가 처음 잡히는 순간(끊겼다 다시 잡힐 때 포함) sumo-gui 카메라를
   신양초 사거리로 한 번 옮김. **sumo-gui 화면으로 직접 확인은 못 함**(화면 제어 권한 필요) - 코드는 기존 카드 클릭
   포커스와 같은 경로(`_pending_focus`)를 씀.
- 둘 다 `configs/hardware_twin.json`의 `realtime_when_connected`, `auto_focus_on_connect`를 `false`로 하면 꺼짐.
- 대시보드 + 가짜 송신기(`--loop`)로 확인: 신양초 카드가 "연결됨", 차량 줄이 정지→전진→도착, 후행 "전진 · 우회 → B",
  사고(보행자) 표시 켜짐/꺼짐, 다음 판 다시 시작까지 정상. 서버 오류 없음.

**바뀐 파일**: `scripts/dashboard_server.py`, `configs/hardware_twin.json`.
**되돌리기**: `step2_after_visual_quality/`의 두 파일을 원위치로. 3단계 직후 스냅샷: `step3_after_demo_pacing/`.
