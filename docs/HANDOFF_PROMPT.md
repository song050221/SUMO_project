# 세션 인계 프롬프트 (다른 기기/AI가 이어서 진행할 때 붙여넣기)

너는 이 프로젝트를 처음 보는 새 AI 세션이다. 아래는 지금까지 진행된 작업 요약이니, 처음부터
다시 하지 말고 이어서 진행해라. **2026-07-29 세션에서 대규모 재설계 + 하드웨어 연동
리팩터링이 있었다** — 이전에 이 문서를 읽은 적이 있다면 반드시 다시 읽을 것.

## 프로젝트 개요

건국대 전기전자공학부 캡스톤 "CCTV 연계형 사고 유발 상황 대응 및 자율주행 중앙 제어 교통
최적화 시스템: V2N 통합 제어 시뮬레이션 및 하드웨어 구현" 중 SUMO 시뮬레이션 파트. 작업
폴더는 **`C:\SUMO_project`** (2026-08-03에 `C:\SUMO_project\SUMO_project` 중복 폴더 구조를
없애고 이 경로 하나로 합쳤다 — 이 문서를 예전에 읽었다면 경로가 바뀐 것 주의). OneDrive 등
클라우드 동기화 폴더 절대 금지 — 파일이 예측 불가능하게 생성/삭제되는 문제가 있었음.

### 폴더 구조 (2026-09-28 갱신 — 루트에는 `start_dashboard.bat` 하나만 남기고 전부 폴더 안으로 정리함)

```
C:\SUMO_project\
├── core\                    (여러 스크립트가 공유하는 로직 - 직접 실행 안 함)
│   ├── cctv_detector.py
│   ├── central_server.py
│   ├── decision_policy.py
│   ├── vehicle_controller.py
│   ├── signal_controller.py       (J번 참고 — 신호 연장/조기전환)
│   ├── predictive_reroute.py      (J번 참고 — 선제적 우회)
│   ├── stuck_vehicle_remover.py   (L번 참고 — 장시간 정지 차량 견인 제거)
│   ├── analysis.py
│   ├── gui_viewport.py            (R번 참고 — 시연용 화면 설정)
│   └── hardware_twin.py           (R번 참고 — 실물 보드 → 신양초 사거리 반영)
├── scripts\                 (터미널에서 직접 실행하는 진입점)
│   ├── run_single_simulation.py
│   ├── run_experiments.py
│   ├── run_gui_preview.py
│   ├── dashboard_server.py
│   ├── measure_congestion.py      (O·Q번 참고 — 정체/그리드락/견인/충돌 계측)
│   ├── fake_hardware_sender.py    (R번 참고 — 하드웨어 없이 시연 리허설)
│   ├── build_visual_assets.py     (R번 참고 — 차·사람·나무 이미지 + vehicle_style.xml)
│   ├── build_styled_polys.py      (R번 참고 — gwangjin_styled.poly.xml)
│   └── find_cctv_zones.py
├── tests\
│   ├── test_decision_policy.py
│   └── test_hardware_twin.py
├── start_dashboard.bat      (원클릭 실행, 바탕화면 바로가기가 이걸 가리킴 — 루트에 있는 유일한 파일)
├── network\                 (광진구 도로망+수요: gwangjin.net.xml/.sumocfg/.poly.xml,
│                              routes.xml, pedestrian_routes.xml, pedestrian_style.xml,
│                              export.osm/export_buildings.osm(재빌드용 원본 지도),
│                              cctv_zones.json, school_zones.json)
├── configs\                 (hardware_twin.json — 실물 보드 ↔ 신양초 사거리 대응, R번 참고)
├── docs\                    (이 문서, SUMO_LIVE_DEMO_HANDOFF.md,
│                              HARDWARE_CALIBRATION_REQUEST.md, report_assets\,
│                              예선 신청서·최종보고서 PDF 2종)
├── experiment_data\          (seed별 routes/collisions + 실험 결과 results.csv/results_v2.csv/results_v3.csv
│                              - 용량 큰 것들 모아둠, 2026-09-09부터 결과 CSV도 여기로 통합)
│                              + junctionjoin_measure_2026-09-27(Q번 원자료), backup_overnight_2026-09-28(R번 백업)
│                              - 2026-09-28에 예전 net 백업 5개(~690MB) 삭제함
├── dashboard\                (Flask 템플릿/static)
└── .claude\                  (launch.json)
```
**`demo_board/`(우드락 실물 시연용 별도 소형 네트워크)는 2026-08-09에 삭제됨** — K번 참고,
`network/school_zones.json`(광진구 실도로망 안의 실제 교차로) 방식으로 대체됨.
**2026-09-09에 폴더 최적화 한 번 더 함**: 안 쓰는 `network/trips.xml`·`pedestrian_trips.xml`·
`collisions.xml`, 캐시(`__pycache__`/`.pytest_cache`), 초창기 스모크 테스트
`scripts/traci_test.py`, 낡은 `results_final_tow.csv` 삭제. `results.csv`/`results_v2.csv`와
예선 PDF 2종은 루트 → 각각 `experiment_data/`·`docs/`로 이동(**루트엔 `start_dashboard.bat`만
남기기로 함** — 코드에서 `"results.csv"`를 참조하던 곳(`core/analysis.py`,
`scripts/dashboard_server.py`, `scripts/run_single_simulation.py`)도 전부
`experiment_data/results.csv` 기준으로 같이 갱신함, 안 그러면 대시보드 비교 페이지가 깨짐.

### 폴더별 역할 (헷갈리기 쉬운 2개 — network/dashboard)

- **`network/`** — 발표 핵심 시나리오(baseline vs treatment 40회 실험)가 실제로 도는
  **광진구 실도로망 무대**. `gwangjin.net.xml`(약 117MB, 도로망 자체 — J번에서 구조적 병목
  교차로 92곳에 신호를 새로 추가해 재빌드함, 신호 295개), `routes.xml`/`trips.xml`
  (차량 수요, J번에서 밀도 2배로 재생성), `pedestrian_routes.xml`/`pedestrian_trips.xml`
  (보행자 수요), `gwangjin.poly.xml`(한강·공원 등 배경 그림, 로직엔 영향 없음),
  `cctv_zones.json`(데이터 기반 선정 CCTV 9곳), `gwangjin.sumocfg`(위 전부를 묶는 설정),
  `export.osm`/`export_buildings.osm`(원본 지도
  데이터, 재빌드할 때만 필요).
- **`dashboard/`** — 파이썬 코드 없이 **HTML/CSS/JS 웹 화면 파일만** 있는 폴더.
  `scripts/dashboard_server.py`가 이 안의 `templates/*.html`을 렌더링하고
  `static/*.js`·`*.css`로 꾸며서 브라우저에 띄운다. `index.html`=실시간 CCTV 구역
  모니터링, `comparison.html`=baseline vs treatment 통계 비교 화면. 이 폴더 자체는 "그림"일
  뿐이고, 데이터를 채워 살아있게 만드는 로직은 `scripts/dashboard_server.py`에 있다.
- **`demo_board/`(삭제됨, 2026-08-09)** — 원래 `network/`(광진구 전체)와 완전히 무관한
  독립 미니 네트워크였다(가로 100m×세로 40m 축소판 사거리 + `traci.vehicle.moveToXY()`로
  카메라가 인식한 RC카 좌표를 실시간 반영). **실제 하드웨어 보드가 구체적으로 제작되면서
  이 축소판 미니 네트워크 방식 자체를 버리고, 광진구 실도로망 안에서 그 보드와 대응되는
  진짜 교차로를 찾아 연동하는 방식(K번, `network/school_zones.json`)으로 완전히
  대체됐다.** 어떤 코드도 이 폴더를 더 이상 참조하지 않는 것을 grep으로 확인 후 삭제함.

**반드시 알아야 할 것 — 파이썬 import 우회 방법**: `core/`·`scripts/`·`tests/`로 나뉘면서
파이썬이 서로 다른 폴더의 모듈을 못 찾는 문제가 생긴다. 그래서 `scripts/`와 `tests/`의
일부 파일(교차 import가 있는 것만: `run_single_simulation.py`, `dashboard_server.py`,
`run_gui_preview.py`, `live_demo_controller.py`, `test_decision_policy.py`,
`test_live_demo_controller.py`) 맨 위에 다음과 같은 부트스트랩을 추가해뒀다:
```python
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))
```
이 덕분에 `from cctv_detector import ...`처럼 **기존 import 문은 하나도 안 바뀌었다** —
`core/`가 통째로 sys.path에 들어가서 flat import가 그대로 통한다. **새 스크립트를
`scripts/`나 `tests/`에 추가할 때 core/의 모듈을 가져다 쓴다면 이 부트스트랩을 잊지 말고
넣을 것.**

**주의사항 모음**:
- 파일 경로 상수(`NET_FILE`, `DEFAULT_CONFIG_PATH`, `EXPERIMENT_DATA_DIR` 등)는 전부 실행
  시점의 **현재 작업 폴더(cwd) 기준** 상대경로다 — 그래서 스크립트는 항상 프로젝트 루트
  (`C:\SUMO_project`)에서 `python scripts/run_single_simulation.py`처럼 실행해야 한다.
  `cd scripts && python run_single_simulation.py`처럼 폴더 안에 들어가서 실행하면 경로가
  다 깨진다.
- `gwangjin.sumocfg` 내부의 `net-file`/`route-files`/`additional-files` 값은 파일명만
  있는데, SUMO가 sumocfg **자기 파일이 있는 폴더(network/) 기준**으로 상대경로를 풀기
  때문에 문제없다(실제 검증함) — 헷갈려서 여기에 `network/`를 또 붙이지 말 것.
- `dashboard_server.py`의 Flask `template_folder`/`static_folder`는 스크립트 자기 위치가
  아니라 **프로젝트 루트 기준 절대경로**로 명시적으로 계산해서 넘긴다(Flask 기본값은
  스크립트가 있는 폴더 기준이라 `scripts/dashboard/templates`를 찾으려다 실패했었음 —
  이미 고쳐져 있음, 다시 건드리지 말 것).
- `run_experiments.py`(scripts/ 안)가 `run_single_simulation.py`를 서브프로세스로 부를 때
  `"scripts/run_single_simulation.py"`로 경로를 명시한다 — 프로젝트 루트에서 실행한다는
  전제.
- `.claude/launch.json`, `start_dashboard.bat`도 전부 `scripts/dashboard_server.py`를
  가리키도록 갱신됨.

## 2026-07-29 세션에서 바뀐 것 (중요 — 이전 문서 내용을 대체함)

### A. 핵심 설계 변경: 보행자/CCTV를 "특정 지점" → "도시 전역" 방식으로 전면 전환

과거에는 동자초등학교 정문 사거리 한 곳에 보행자를 수동 스폰하고, CCTV 구역도 그 지점
위주로 하드코딩했다. **이 접근을 폐기했다.**

- **보행자**: `pedestrian_injector.py`(동자초 단일 지점 스폰) 삭제. 대신
  `randomTrips.py --pedestrians --max-distance 300 -p 8 -e 3600 --seed 43`으로 네트워크
  전역 임의 위치·임의 시점에서 보행자가 발생하도록 변경. `pedestrian_routes.xml`을
  `gwangjin.sumocfg`의 `route-files`에 추가.
- **CCTV 구역**: `find_cctv_zones.py` 신설 — 방법 A(sumolib로 교차로 연결도 계산) + 방법
  B(baseline 1회 실행 후 edge별 실측 통행량 집계)로 **9곳을 데이터 기반 선정**, 결과를
  `cctv_zones.json`에 저장. `cctv_detector.py`는 이 파일을 읽어 `CCTV_ZONES`를 구성한다
  (감으로 고른 지점 없음 — 발표에서 선정 근거로 그대로 제시 가능).
- **대시보드 2종 신설** (기존에 전혀 없었음):
  - 실시간 모니터링: `dashboard_server.py` + `dashboard/templates/index.html` — 9개 구역
    카드 그리드(차량수/평균속도/보행자감지/최근 alert), 누적 충돌·급제동, Flask-SocketIO로
    실시간 푸시. 브라우저로 직접 켜서 동작 확인 완료.
  - baseline/treatment 비교: `dashboard/templates/comparison.html` + `/api/comparison` —
    막대그래프+오차범위, boxplot(직접 구현, 외부 플러그인 미사용), p-값 배지. `analysis.py`에
    `compute_comparison()` 추가.
- `run_single_simulation.py` 재작성: 새 보행자/CCTV 시나리오 반영.

### B. 하드웨어(RC카+YOLO) 연동 리팩터링

팀원이 `SUMO_YOLO_하드웨어_호환성_및_담당자별_작업분담.docx` 검토 문서를 보내와, 그 안의
**SUMO 담당자 몫(2-1절) + 관련 Part 1 문제점**을 전부 반영했다. 상세 스키마·매핑표·타임라인은
**`SUMO_LIVE_DEMO_HANDOFF.md`에 정리해 뒀으니 그 문서를 먼저 읽을 것** (이 문서는 요약만 함).

- `decision_policy.py` 신설: TraCI 비의존 공통 판단 로직. STOP(즉시 위험) > REROUTE(우회
  가능) > SLOW(구역 내 감속) 우선순위로 한 차량에 하나의 명령만 배정. `central_server.py`와
  `live_demo_controller.py`가 공유.
- `central_server.py`: `initial_optimization()`이 이제 신규 차량마다 1회
  `traci.vehicle.rerouteTraveltime()`으로 실제 재계산함 (전에는 기존 경로를 읽어 저장만
  했음 — "GPS 기반 1차 최적화"라는 핵심 주장이 코드상 실종돼 있었음). `handle_cctv_alert()`는
  `decision_policy.decide_actions()`에 위임.
- `cctv_detector.py`: hazard edge 기준 sumolib 상류(upstream) hop 탐색으로
  "즉시위험(hazard edge 위)/구역내감속(가까운 상류)/우회가능(더 먼 상류 + 남은 경로에
  hazard edge 포함)" 3버킷으로 차량을 분류.
- `vehicle_controller.py`: STOP 실행 추가(`slowDown(0.0)`), REROUTE를 SUMO 표준
  incident-avoidance 기법(`traci.edge.adaptTraveltime` 페널티 + `rerouteTraveltime`)으로
  실제 구현(전에는 분기만 있고 central_server가 명령을 만들지 않아 죽은 코드였음).
- `live_demo_controller.py` 전면 재작성:
  - 매 주기 **모든 차량**에 판단 발행(위험 없으면 `FOLLOW_PATH`) — 전에는 위험 없으면
    아무 판단도 안 보내서 팀원 쪽 안전 정책 때문에 차량이 계속 정지 상태였음.
  - hazard_type/class_name → SUMO 이벤트 매핑(`pedestrian_detected`/`obstacle_detected`).
  - 마지막 감지 후 `hazard_hold_ms`(기본 2초) 동안 SLOW 유지 — `ttl_ms`(통신 유효시간)와
    별개 개념으로 분리.
  - `coordinate_space`(world/image) 불일치 시 프레임 거부, image/world proximity 분리.
  - 좌표가 문자열/NaN/Inf여도 해당 항목만 로그 후 제외(전체 프레임은 안 버림), `run()`
    루프에 try/except 안전망 — 잘못된 payload 하나로 어댑터 전체가 죽지 않음.
  - `central_server.py` 대신 `decision_policy.py`만 import — SUMO 없는 하드웨어 전용 PC에서
    import 단계부터 실패하던 문제 해결.
- `demo_routes.json`, `live_demo_config.json` 신설 — **스키마만 완성, 실측값은 placeholder**.
  danger_zone 좌표, proximity, 차량별 경로 좌표는 하드웨어 담당자가 카메라/도로판 실측 후
  채워야 함.
- 테스트 3종 신설, 전체 통과: `test_decision_policy.py`, `test_live_demo_controller.py`(17개
  케이스), `test_udp_integration.py`(어댑터를 서브프로세스로 띄워 실제 UDP 9002→9001 왕복 +
  손상된 payload 복구까지 검증).
- **범위 밖으로 명시적으로 제외한 것** (다른 담당자 코드베이스): `vehicle_fleet.json`,
  `camera_homography.json`, 차량별 PWM/조향 보정, `firmware/secrets.h`(하드웨어 담당),
  YOLO detector/데이터셋/`best.pt`(YOLO 담당), `vision/central_fleet_controller.py`의 순환
  경로 처리(비전 쪽 코드).

### C. 폴더 정리 (여러 차례, 최신순)

- 1차: `__pycache__`, `results_old_bottleneck_bug.csv.bak`(옛 버그 백업), 모든
  `*.alt.xml`(duarouter 부산물, 코드에서 참조 안 함), `find_walking_edges.py`(동자초
  단일지점 설계 전용 도구, 용도 소멸), 옛 동자초 설계로 생성됐던 stale
  `collisions_seed{2..20}_*.xml`(2026-07-21 생성분) 삭제.
- 2차: `__pycache__`(재생성분), `collisions.xml`(seed 없는 일회성 테스트 잔여물),
  `pedestrian_routes_seed*.alt.xml`(보행자 duarouter 부산물), `routes.rou.xml`
  (`randomTrips.py --persons`가 내부적으로 duarouter를 호출해 라우팅 검증할 때 생기는
  부산물 — 매 seed마다 같은 파일명으로 덮어써지며 아무 코드도 안 읽음), `viewsettings.xml`
  (`gui_viewport.py`가 실행할 때마다 새로 만드는 캐시 파일) 삭제.
- `trips_seed*.xml`/`routes_seed*.xml`(차량 demand, seed 1~20)은 로직이 안 바뀌어 그대로
  재사용. `export.osm`(도로망 원본), `export_polygons.osm`(D번 지리 폴리곤 원본)은 재빌드
  시 필요한 소스라 의도적으로 보존.

### D. 발표 미리보기 도구 신설 + 시각 품질 개선

발표 당일 심사위원 앞에서 sumo-gui로 보여줄 화면을 미리 점검하고 다듬었다.

- `run_gui_preview.py` 신설: `sumo-gui`를 TraCI로 띄워 central_server/cctv_detector/
  vehicle_controller가 개입하는 treatment 시나리오를 화면으로 볼 수 있게 함
  (`--mode baseline`으로 비교도 가능). `--start`로 자동 재생.
- **`dashboard_server.py`와 `sumo-gui`가 원래 서로 다른 시뮬레이션이었던 문제 수정**:
  `dashboard_server.py`의 `simulation_loop()`이 headless `sumo` 대신 `sumo-gui`를 띄우도록
  바꿔서, 웹 대시보드를 열면 **같은 TraCI 세션의 sumo-gui 창도 함께 뜨고 완전히 동기화**된다
  (전에는 웹 페이지와 GUI 창이 서로 다른 seed/타이밍으로 따로 돌았음 — `DASHBOARD_HEADLESS=1`
  환경변수로 예전처럼 headless만 쓰게 되돌릴 수 있음).
- `gui_viewport.py` 신설: `cctv_zones.json`의 좌표를 기준으로 sumo-gui가 **특정 CCTV
  구역(기본 zone_1)을 확대한 상태로 시작**하도록 `viewsettings.xml`을 매번 생성
  (`--gui-settings-file`로 전달). `DASHBOARD_FOCUS_ZONE` 환경변수로 대시보드가 보여줄 구역
  변경 가능.
- **지리적 배경 추가**: 기존 Overpass 쿼리는 도로(`way["highway"]`)만 가져와서 물/녹지가
  전혀 없었음. Overpass API에 물(`natural=water`)/하천(`waterway`)/토지이용(`landuse`)/
  공원(`leisure`) 쿼리를 추가로 날려 `export_polygons.osm`(115개 물, 413개 landuse 등)을
  받고, `polyconvert`로 `gwangjin.poly.xml`(745개 폴리곤)을 생성. `gwangjin.sumocfg`/
  `run_gui_preview.py`/`dashboard_server.py` 전부 `--additional-files`로 로드.
- **보행자 시인성 문제 수정**: SUMO 기본 보행자 크기(폭 약 0.2m)가 화면에서 사실상 안 보여서,
  `pedestrian_style.xml`을 만들어 SUMO의 예약 타입 id `DEFAULT_PEDTYPE`을 재선언(폭/길이
  1.2m, 빨간색)했다 — TraCI로 실측 확인 결과 **width/length 재정의는 확실히 적용됨**, color
  재정의는 적용 여부가 불확실(TraCI로 조회 시 그대로 노란색으로 나왔음 — 실제 GUI 렌더링에서
  반영되는지는 미확인, 사용자에게 재확인 요청한 상태). `gui_viewport.py`의
  `person_exaggeration`도 2.5배로 설정해 크기를 이중으로 보강.
- `start_dashboard.bat` + 바탕화면 바로가기("SUMO 발표 시작") 신설: 더블클릭 한 번으로
  `dashboard_server.py` 실행 + 4초 후 브라우저 자동으로 `localhost:5000` 열기까지 처리.
  **주의**: 이미 터미널에서 `dashboard_server.py`가 켜져 있는 상태로 이 바로가기를 실행하면
  포트 5000 충돌로 실패함 — 기존 걸 먼저 끄고 실행해야 함.
- **보행자가 횡단보도 건너자마자 사라지는 현상**: 사용자가 문의해서 TraCI로 사라진 보행자
  50명을 전수 추적함. **전부 `traci.simulation.getArrivedPersonIDList()`로 확인된 정상
  도착(arrival)** — 버그 아님. `randomTrips.py --max-distance 300`으로 출발-목적지 거리를
  짧게 제한해서, 횡단보도 건너자마자 목적지에 도착하는 경우가 흔한 것뿐. 사용자가 "일단 이대로
  두자"고 결정함 — **바꾸지 말 것** (바꾸려면 `--max-distance`를 늘리고 seed 42/43 보행자
  데이터를 재생성해야 하며, 이미 진행 중인 배치 실험과 시나리오가 달라짐을 먼저 고지할 것).

### E. 우드락 실물 시연 보드 — 별도 소형 네트워크 신설 (2026-08-01~08-03)

팀원이 우드락으로 만든 모의 사거리에 RC카 3대를 놓고, 보행자 역할 LED를 카메라가 인식하면
중앙 알고리즘이 차량을 조율하는 실물 시연을 준비 중이다. 이걸 발표 모니터에 SUMO로 실시간
띄우기 위한 **완전히 별도의 소형 네트워크**를 만들었다 — `gwangjin.net.xml`(광진구 전체)과는
무관하다.

- **`demo_board/` 폴더 신설**: `demo_board.nod.xml`/`demo_board.edg.xml`/`demo_board.con.xml`
  로 직접 작성한 사거리 (가로 100m x 세로 40m, 가로가 더 긴 직사각형). netconvert로
  `demo_board.net.xml` 빌드.
- **일방통행·편도 1차선·직진형**(사용자가 실제 참고 지도의 화살표를 보고 확정): 서→동(`W2C`→
  `C2E`), 남→북(`S2C`→`C2N`) 두 직선만 있고 회전 연결은 아예 없음(`demo_board.con.xml`에
  명시된 조합 외에는 생성 안 됨 — sumolib로 검증 완료).
- **겪은 함정**: netconvert가 기본적으로 좌표를 자동 정규화(shift)해서, nod.xml에 지정한
  좌표(중심 0,0)와 실제 net.xml 내부 좌표가 달라지는 문제가 있었다. `--offset.disable-
  normalization true`로 재빌드해서 해결 — 이 네트워크를 다시 빌드할 일이 있으면 이 옵션을
  반드시 유지할 것.
- **`live_position_sync.py` 신설**: 카메라가 인식한 RC카 실좌표(UDP, `live_demo_controller.py`
  와 동일 traffic_state 스키마)를 받아 `traci.vehicle.moveToXY(vehID, "", -1, x, y,
  keepRoute=0)`로 SUMO 차량 위치에 매 프레임 그대로 반영한다. 판단 로직(STOP/SLOW)과는 무관 —
  오직 "발표 모니터에 실차 위치를 그대로 보여주는" 시각화 전용. `board_calibration.json`에
  카메라 좌표→SUMO 좌표 변환(scale/offset)을 두었으나 **아직 placeholder**(실제 보드/카메라
  설치 후 캘리브레이션 필요). 헤드리스로 가짜 좌표 주입 테스트해서 W2C→C2E 경계를 정확히
  넘어가는 것까지 확인함.
- **대시보드 구역 카드 클릭 → sumo-gui 카메라 이동 기능 추가**: `traci.gui.setBoundary()`로
  구현. Flask 요청 스레드와 TraCI를 쥔 `simulation_loop` 스레드가 달라서, 클릭 시
  `/api/focus/<zone_id>`가 `_pending_focus_zone` 전역변수에 표시만 해두고, 다음 시뮬레이션
  스텝에서 `simulation_loop`가 실제로 카메라를 이동시키는 구조(TraCI는 한 스레드에서만 호출
  가능). 브라우저로 클릭→200 OK 응답까지 실제 검증함(headless 모드로, sumo-gui 렌더링 자체는
  미확인).
- **폴더 재정리**: seed별 산출물(`routes_seed*.xml`, `pedestrian_routes_seed*.xml`,
  `collisions_seed*_*.xml`, 49개 파일)을 전용 폴더 `experiment_data/`로 이동. `trips_seed*.xml`/
  `pedestrian_trips_seed*.xml`(routes로 변환되면 다시 안 쓰이는 중간 산출물)은 전부 삭제하고,
  `run_single_simulation.py`가 **생성 직후 자동으로 지우도록** 수정해서 앞으로도 안 쌓이게 함.
  **`run_single_simulation.py`의 `NET_FILE`/`RESULTS_FILE`은 그대로 루트 기준이고,
  seed 관련 파일만 `EXPERIMENT_DATA_DIR = "experiment_data"` 하위로 감** — 다른 스크립트가
  이 경로를 참조하는 곳은 없었음(grep으로 확인).
- **duarouter 부산물 완전 차단**: `--alternatives-output NUL`을 추가해서 `.alt.xml` 파일이
  아예 안 생기게 함 (전에는 매번 수동으로 지워야 했음).
- **주의**: `routes.rou.xml`(randomTrips.py가 내부 검증용으로 만드는, 우리 코드가 안 만드는
  부산물)은 여전히 매번 루트에 재생성됨 — randomTrips.py 내부 동작이라 억제 방법을 못 찾음,
  그냥 무시하거나 가끔 지울 것.

### F. 폴더 재정리 (core/scripts/tests) + 지도 시각 밀도 대폭 강화 (2026-08-03)

- **파이썬 파일도 `core/`(공용 로직 6개) / `scripts/`(실행 진입점 7개) / `tests/`(테스트
  3개)로 분리**. 서로 다른 폴더 간 import가 안 되는 문제는 `scripts/`·`tests/`의 교차
  import가 있는 파일 맨 위에 `sys.path.insert(0, .../"core")` 부트스트랩 2줄을 추가해서
  해결 — 기존 `from cctv_detector import ...` 같은 import 문은 하나도 안 바꿈. 새 스크립트
  추가 시 이 부트스트랩 잊지 말 것(위 폴더 구조 섹션에 코드 있음).
- **`network/gwangjin.poly.xml` 지도 밀도 대폭 강화**: 기존엔 물/녹지/주거지 등 745개
  폴리곤뿐이라 지도가 휑했음. Overpass에 `building`/`amenity`/`shop`/`sport`/`tourism` 등을
  추가로 질의해서 `export_buildings.osm`(10.9MB, 건물 11,329개 포함)을 새로 받고
  polyconvert로 재생성 → **13,354개 폴리곤**(건물이 대부분)으로 늘어남. 헤드리스로 전체
  스택(net+routes+poly+pedestrian_style) 로드 검증 완료. 예전 `export_polygons.osm`(물/녹지
  전용, 이제 이 새 파일의 부분집합)은 삭제함 — `export_buildings.osm`이 현재 poly.xml의
  유일한 원본 소스.
- 색상은 SUMO 기본 typemap(`$SUMO_HOME/data/typemap/osmPolyconvert.typ.xml`) 그대로 씀 —
  건물은 연한 분홍빛 흰색(1.0,.90,.90), layer=-1이라 녹지/수역(layer -3~-4)보다 위, 도로
  (layer 0)보다는 아래에 깔림. 색을 더 손보고 싶으면 이 typemap을 복사해서 값만 바꾼 커스텀
  typemap을 만들어 `--type-file`에 넘기면 됨(아직 안 함).
- 실제 sumo-gui 화면에서 어떻게 보이는지는 **아직 사용자 확인 못 받음** — 다음 세션에서
  체크할 것.

### G. 사고 발생 + 대시보드 드릴다운(목적지·ETA·최적화 배지) — "중앙 제어가 실제로
    작동하는지 확인이 안 된다"는 사용자 피드백에 대한 응답 (2026-08-03)

사용자가 지적한 두 가지 문제: (1) 중앙 제어 알고리즘이 실제로 뭔가 하고 있는지 눈으로
확인할 방법이 없었다, (2) 흔히 생각하는 "사고로 인한 정체"가 구현돼 있지 않았다(기존
`congestion_detected`는 속도 임계값 기반일 뿐 사고 개념이 없었음). 두 기능으로 대응:

- **사고(accident) 메커니즘 신설** (`core/cctv_detector.py`): CCTV 9개 구역 내에서
  통행량이 많은 edge일수록 높은 확률로 랜덤 사고 발생(`update_accidents()`,
  `ACCIDENT_BASE_PROB_PER_VEHICLE`/`ACCIDENT_MAX_PROB`로 조정 가능), 45초간 지속
  (`ACCIDENT_DURATION`) 후 자동 해제. `accident_detected` alert 타입 신설,
  `decision_policy.py`의 `STOP_ELIGIBLE_TYPES`에 추가해 그 edge 위 차량은 STOP,
  상류 차량은 SLOW/REROUTE 판단을 받도록 연결했다.
- **시각 표시**: 사고 위치에 `traci.poi.add()`로 **빨간 원** 마커(`dashboard_server.py`/
  `run_gui_preview.py`의 루프에서 매 스텝 `get_active_accident_edges()`와 화면에 그려둔
  POI 집합을 비교해 동기화, 사고가 끝나면 자동으로 지움). **보행자 색은 빨강→초록
  (30,180,60)으로 변경** — 사고 마커와 헷갈리지 않도록. `network/pedestrian_style.xml`
  (vType color)과 `core/gui_viewport.py`의 GUI colorScheme 양쪽에 넣어 이중으로 강제함.
- **차량 ETA 계산**: `traci.edge.getTraveltime()`(rerouteTraveltime이 실제로 쓰는 지표와
  동일)을 남은 경로 edge마다 더해서 예상 도착 시각을 추정한다(`dashboard_server.py`의
  `_compute_eta()`) — 물리적으로 정확한 값이 아니라 "지금 조건이 유지된다면"이라는 근사치.
- **경로 최적화 이력 추적**: `decision_policy`가 "reroute" 명령을 낸 차량에 한해 실행
  전/후 ETA를 비교해 `_recent_optimizations`에 15초간(`OPTIMIZATION_BADGE_DURATION`)
  기록해 둔다. 이 차량이 어느 CCTV 구역 도로 위에 있든(꼭 사고가 난 그 구역이 아니어도)
  그 15초 동안은 "최적화됨" 배지가 뜬다.
  **알아둘 것**: `vehicles_reroutable`은 hazard edge로부터 상류 2~5 hop 범위에서 찾는데
  (`cctv_detector.NEARBY_HOPS`/`REROUTE_HOPS`), 이 범위가 CCTV 구역의 공식 edge 목록보다
  넓다. 그래서 방금 리라우트된 차량이 그 순간 정확히 그 구역 도로 위에 없을 수도 있다 —
  버그 아니라 설계상 특성. 실측으로는 150스텝 동안 사고 확률을 강제로 높여도 reroute가
  4번밖에 안 나올 만큼 발생 조건이 좁으니, 발표 중 배지가 잘 안 뜨면 당황하지 말고 좀 더
  지켜볼 것(또는 `cctv_detector.ACCIDENT_MAX_PROB` 등을 일시적으로 올려서 시연).
- **`/api/zone/<zone_id>/vehicles` API + 상세 패널 UI**: 구역 카드를 클릭하면(기존
  카메라 이동 기능과 동시에) 그 도로 위 차량 목록을 모달로 보여준다 — 차량ID/목적지
  edge/예상도착시간, 최적화됐으면 **빨간 "경로 최적화" 배지 + 초록색 새 ETA**. 패널이
  열려있는 동안 1.5초 간격으로 폴링(`dashboard/static/dashboard.js`), 닫으면 폴링도 멈춤
  (브라우저에서 직접 검증함 - fetch 가로채서 호출 횟수 실측). TraCI는 `simulation_loop`
  스레드에서만 부를 수 있어서, 이 API는 매 스텝 미리 계산해 둔 `zone_vehicle_details`
  전역 dict를 읽기만 한다(`/api/focus`와 같은 패턴).
- 전 과정 실측 검증: 사고 발생→POI 표시→STOP 판단, ETA 계산, reroute 전/후 ETA 비교,
  API 응답, UI 폴링 시작/종료까지 전부 확인함. **실제 sumo-gui 화면에서 어떻게 보이는지는
  아직 사용자 확인 못 받음**(headless로만 검증) — 다음 세션에서 체크할 것.

### H. 요약바 개편 + 포커스 메커니즘 완전 일반화 (2026-08-03)

G번 UI를 사용자가 써보고 요청한 후속 개선. 두 가지: (1) 상단 요약바 재구성, (2) 차량/
보행자/사고 각각을 "월드 전체 목록으로 보고, 개별 항목 클릭 시 그 위치로 카메라 이동".

- **요약바**: "누적 충돌"/"누적 급제동"/"상태(연결 상태)" 카드를 없애고
  **현재 차량 수 → 현재 보행자 수 → 현재 사고 수 → 경과 시간** 순서로 재구성
  (`dashboard/templates/index.html`). 충돌/급제동 집계 로직 자체는 `summary` dict에 남아있음
  (화면에만 안 보임 - 나중에 다시 쓸 수도 있어서 지우진 않음).
- **카메라 포커스 메커니즘을 완전히 일반화**: 기존 `_pending_focus_zone`(구역 전용)을
  `_pending_focus = {"kind": ..., "id": ...}`로 바꿔서 zone/vehicle/person/accident
  네 종류를 전부 같은 코드 경로로 처리한다. 라우트도 `/api/focus/<zone_id>`에서
  `/api/focus/<kind>/<target_id>`로 통합. `gui_viewport.py`에 `point_bounds(x, y,
  width)`를 새로 만들어 임의 좌표 중심 포커스를 지원하고, 기존 `zone_bounds()`는 이걸
  재사용하도록 리팩터링(zone은 고정 좌표, vehicle/person/accident는 매 스텝
  `traci.vehicle.getPosition()`/`getPosition()`/`edge_midpoint()`로 현재 위치를 새로
  조회). 개별 대상 포커스는 구역 포커스(250m)보다 좁게 확대(`_POINT_FOCUS_WIDTH_M = 80`).
- **월드 전체 스냅샷**: `_update_world_snapshots()`가 매 스텝
  `world_vehicles`/`world_persons`/`world_accidents` 전역 리스트를 다시 계산해 둔다
  (기존 `zone_vehicle_details`와 같은 패턴 - TraCI는 simulation_loop 스레드에서만 호출
  가능하므로). 차량 레코드 생성 로직(`_vehicle_record()`)은 구역별/월드 전체 양쪽에서
  공유하도록 뽑아냄.
  **성능 주의**: 차량 ETA 계산(`_compute_eta`)은 남은 경로 전체를 edge별로 순회하는데,
  이걸 지금은 **매 스텝, 월드 전체 차량에 대해** 무조건 계산한다(구역별 계산과 동일한
  방식으로 확장한 것). 시뮬레이션이 진행되면서 동시 차량 수가 수백 대 이상으로 늘어나면
  느려질 수 있음 - 아직 실측으로 문제를 확인한 건 아니라서 일단 이렇게 뒀지만, 만약 나중에
  버벅이면 "패널이 열려있을 때만 계산"하는 식으로 게이팅을 추가할 것(zone-focus의
  `_pending_focus`처럼 Flask 쪽에서 플래그를 세우고 simulation_loop가 확인하는 패턴 재사용
  가능).
- **API 신설**: `/api/world/vehicles`, `/api/world/persons`, `/api/world/accidents`.
- **상세 모달을 4종 통합 지원하도록 일반화** (`dashboard/static/dashboard.js`의
  `DETAIL_KINDS` 설정 객체): zone(기존 그대로, 구역 카드 클릭) / vehicle / person /
  accident. 헤더(`<thead>`)도 종류별로 동적으로 바뀜. **목록의 각 행을 클릭하면 그
  대상으로 카메라가 이동**한다 - 기존 구역별 차량 목록에도 이 행 클릭 기능을 똑같이
  추가함(일관성).
- 검증: 브라우저에서 실제 클릭 이벤트(및 `fetch` 가로채기로 호출 확인) —
  요약바 3종 전부 열림/헤더/데이터 확인, 차량·보행자 행 클릭 시
  `/api/focus/vehicle/<id>`·`/api/focus/person/<id>` 정확히 호출됨, 구역 카드 클릭도
  `/api/focus/zone/<id>`로 여전히 정상 작동 확인. 사고 목록은 그 순간 활성 사고가 없어서
  빈 상태("지금 대상이 없습니다")만 확인 — 사고 발생→표시 흐름 자체는 G번에서 이미 검증됨.
  **UI 폴링(1.5초)이 accessibility tree 스냅샷보다 빨라서 read_page→click 방식으론 행이
  자꾸 stale해짐 - 검증할 땐 JS로 직접 클릭 이벤트를 발생시키는 게 안정적임.**

### I. 사고 발생 확률 상향 + 수동 "사고 발생" 버튼 (2026-08-03)

- **확률 상향**: `cctv_detector.ACCIDENT_BASE_PROB_PER_VEHICLE` 0.00003→0.001(33배),
  `ACCIDENT_MAX_PROB` 0.0006→0.01(17배). 여전히 조정 가능한 상수 - 발표 리허설해보고
  너무 잦다/뜸하다 싶으면 이 두 값만 고치면 됨.
- **수동 사고 발생 함수**: `cctv_detector.trigger_accident(zone_id, current_time)` 신설 —
  그 구역 edge 중 아직 사고 없는 것 하나를 무작위로 골라 즉시 `_active_accidents`에
  넣는다. 자동 발생(`update_accidents`)과 **같은 상태를 공유**하므로 이후 감지·시각화
  (빨간 원)·STOP 판단이 자동 발생 사고와 완전히 동일하게 처리됨 — 별도 코드 경로 없음.
  구역 내 모든 edge가 이미 사고 중이면 `None` 반환(버튼 눌러도 조용히 아무 일 안 일어남,
  에러는 아님).
- **UI**: 구역 상세 패널에 "사고 발생" 버튼 추가(`kind==="zone"`일 때만 보임, 전체
  차량/보행자/사고 목록에는 안 뜸 — 어느 구역인지 특정할 수 없어서). 클릭하면
  `/api/zone/<zone_id>/trigger_accident`로 POST, `_pending_accident_zone`에 표시만
  해두고 `simulation_loop`가 다음 스텝에서 실제로 처리(zone-focus와 같은 스레드
  제약 패턴).
- **버그를 하나 찾아서 고침 — 버튼 위치가 차량 수에 따라 흔들리던 문제**: 처음엔
  `#zone-detail-panel`에 `max-height: 80vh`만 줬는데, 이러면 flexbox가 컨텐츠 양에 맞춰
  패널 자체 높이를 줄이거나 늘려서(빈 목록이면 패널이 작아짐, 30줄이면 커짐)
  하단 footer(버튼)의 화면상 y좌표가 요청마다 최대 161px씩 움직였다(실측으로 재현
  확인). **`height: min(600px, 80vh)`로 고정값을 줘서 해결** — 이제 패널 자체가 고정
  크기이고, 표가 있는 `#zone-detail-body`만 내부적으로 스크롤되며, footer는 항상 패널
  맨 아래 같은 자리. 브라우저에서 행 0개/1개/30개 세 경우 버튼 y좌표가 정확히
  동일함(584.5px)을 실측 확인.
- 실제 트리거→감지→표시 전 과정 실측 검증(POST → 0.8초 후 `/api/world/accidents`에
  잡힘 → 구역 카드 "사고 감지"가 "발생"으로 바뀜). **주의**: 사고는 45초 지속 후
  자동 소멸하므로, 트리거하고 한참 있다가(예: 다른 작업하다가) 확인하면 이미 사라져서
  "왜 안 뜨지" 싶을 수 있음 — 트리거 직후 곧바로 확인할 것.
- **부수적으로 발견한 것** (이번 작업과 무관하지만 로그에서 눈에 띔): sumo가
  `Warning: Pedestrian vType 'DEFAULT_PEDTYPE' width 1.20 is larger than
  pedestrian.striping.stripe-width and this may cause collisions with vehicles.`를
  띄운다 — 보행자 시인성을 위해 폭을 1.2m로 키운 것(`network/pedestrian_style.xml`,
  D번 참고)의 부작용일 수 있다. 급제동/충돌 통계에 실제 영향이 있는지는 아직 확인 안 함 -
  나중에 정식 실험(현재 중단 상태) 재개할 때 염두에 둘 것.

### J. "사고 발생"→"사고 생성" 용어 정리 + 차량 밀도 2배 + 중앙 알고리즘 정교화 (2026-08-04)

**용어 정리**: 사용자가 직접 누르는 수동 트리거 버튼만 "사고 발생"→"사고 생성"으로 이름
변경(`dashboard/templates/index.html`, `dashboard.js`, `dashboard.css`, `cctv_detector.trigger_accident`
docstring, `dashboard_server.py`의 로그/라우트 docstring). **랜덤하게 자동 발생하는 사고를
가리키는 표현은 그대로 "사고 발생"으로 둠** — 사용자가 구분해서 지시함, 헷갈리지 말 것.

**차량 밀도 2배 (`network/routes.xml`/`trips.xml`)**: 기존 3600대(period=1) →
**7200대(period=0.5)**로 재생성(seed 42, `randomTrips.py -n gwangjin.net.xml -p 0.5 -e 3600
--seed 42` → `duarouter`). 더 올리려고 24000대(period=0.15)까지 실측해봤는데 **네트워크
전체가 정체로 무너지는(속도 13→1~2m/s) 게 확인돼서 7200으로 타협함** — 이 실측 과정에서
아래 J-2, J-3의 발단이 된 정체 붕괴 문제를 처음 발견함.

**재배치 시각 강조** (`dashboard_server.py`): 차량이 재배치되는 순간
`traci.vehicle.setColor()`로 15초간 마젠타색(`REROUTE_HIGHLIGHT_COLOR`, 사고=빨강/보행자=
초록과 구분)으로 바꾸고, sumo-gui에서는 `traci.vehicle.highlight()`로 잠깐 링을 띄운다
(`sumo_binary == "sumo-gui"`일 때만 — headless는 GUI 명령이라 에러남). 만료 시
`traci.vehicle.getColor()`로 미리 저장해둔 원래 색(기본 노랑)으로 복구(`_expire_optimizations`,
매 스텝 실행 — 가벼워서 스로틀 안 함). 대시보드 "경로 최적화" 배지 색도 빨강→파랑
(`#4a9eff`, 기존 포커스 강조색과 통일)으로 변경.

**차량 경로선 표시** (`cctv_detector.route_shape(veh_id)` 신설 + `dashboard_server.py`):
차량을 클릭(요약바 차량 수 클릭 → 목록 행 클릭, 또는 구역 상세 → 차량 행 클릭 — 둘 다
같은 `/api/focus/vehicle/<id>` 경로를 타므로 동일하게 동작)하면 남은 경로를
`traci.polygon.add()`로 파란 선(`ROUTE_LINE_ID="route_line"`, lineWidth=1)으로 그린다.
차량이 아닌 다른 대상(구역/보행자/사고)을 선택하거나 상세 패널을 닫으면(`/api/route/clear`)
자동으로 지움, 표시 중이던 차량이 도착해서 사라지면 그것도 자동으로 지움. **주의**:
sumo-gui 지도 위에서 차량을 직접 클릭하는 건 구현 안 함 — TraCI에 "GUI에서 뭘 클릭했는지"
알려주는 API가 없어서 우리 코드로 감지 불가능. SUMO 자체의 우클릭→"Show Route" 기능은
이것과 별개로 항상 쓸 수 있음(대시보드 상태와는 연동 안 됨).

**중앙 알고리즘 정교화 — 세 번 시도, 세 번 다 거의 효과 없었고 그 이유가 핵심 발견**:
사용자가 "정체가 왜 안 풀리냐"고 물어서 세 가지를 순서대로 실측 비교함(seed 42,
network/routes.xml 7200대 기준, t=3000s 도착 완료 차량 수로 비교):
1. `central_server.CentralServer.initial_optimization()`을 "차량 출발 시 1회"에서
   **"주행 중에도 REOPTIMIZE_INTERVAL(60s)마다 재계산"**으로 확장(`vehicle_routes`가
   이제 경로 대신 마지막 재계산 시각을 저장). → 거의 효과 없음(3165대).
2. sumo 실행 커맨드에 `--weights.random-factor 1.8` 추가해서 경로 계산에 임의성을 줘
   같은 우회로로 몰리지 않게 분산 시도(1번과 결합) → 역시 효과 없음(3116대).
3. **원인 규명**: 가장 심하게 막히던 edge들을 직접 조사(BFS로 그 edge를 막아보고
   대체 경로가 있는지 확인) → **일부는 우회로가 아예 없거나(그래프상 완전히 끊김)
   있어도 22배 이상 돌아가야 함** — 라우팅을 아무리 잘해도 못 피하는 **구조적 병목**
   이었음. 게다가 그 교차로들은 전부 `priority`(비신호) 타입 — 애초에 신호가 없어서
   차량들이 서로 얽혀 완전히 멈추는(gridlock) 현상까지 발생.
4. **구조적 병목 전수조사**: Tarjan bridge-finding 알고리즘으로 차량 통행 가능 edge
   전체(21870개)를 그래프로 만들어 "제거하면 두 지점이 끊어지는" cut-edge를 전부 찾음
   (1109쌍). 막다른 골목(스퍼) 제외하고 실제 간선도로급(양끝 degree≥3, 속도≥8m/s)만
   추리니 **92개 교차로**가 나왔고, 전부 `priority` 타입(신호 없음)이었음.
5. **net.xml 재빌드로 그 92곳에 신호 신규 추가**: 기존 net.xml에 쓰인 것과 정확히 같은
   netconvert 플래그(인도/좌표 정규화 옵션 그대로 유지, `network/gwangjin.net.xml`의
   내장 `<netconvertConfiguration>` 주석에서 그대로 가져옴) + `--tls.set <92개 노드>
   --tls.default-type actuated`로 재생성. **edge ID/개수 완전히 동일(36816개, 추가/삭제
   0개)** — CCTV 구역·인도·기존 routes.xml 전부 그대로 유효함을 확인 후 교체. 신호
   203개→295개. (교체 전 만들어뒀던 116MB짜리 백업 `gwangjin.net.xml.bak`은 이번 정리
   때 삭제함 — 필요하면 git 이력 대신 재빌드 절차를 이 섹션 보고 다시 밟을 것.)
   → 신호만 추가한 상태로는 아직 효과가 작았음(3241대) — 대기열이 있어도 무조건 같은
   시간만 켜주는 단순 연장이라서.
6. **신호 제어 v2 — 수요 비례 배분** (`core/signal_controller.py` 전면 재작성): 그냥
   "대기열 있으면 연장"이 아니라, 현재 초록 방향과 다음 순서 방향의 대기열을 서로
   비교해서 지금 방향이 더 급하면 대기 차량 수에 비례해 더 오래 연장(`EXTENSION_BASE`
   + `EXTENSION_PER_VEHICLE`×대기수, `MAX_EXTENSION`으로 상한), 반대로 다음 방향이
   현재의 `CUTOFF_RATIO`(1.8)배 이상 급하면 최소 시간(`minDur`)만 채우고 일찍 넘겨줌
   (`EARLY_CUTOFF_DURATION`=2s). 교통공학의 max-pressure 신호제어와 같은 방향.
7. **선제적 우회** (`core/predictive_reroute.py` 신설): 모든 차량의 남은 경로를
   `PREDICT_INTERVAL`(60s)마다 미리 훑어서 `PREDICT_HORIZON`(90s) 이내 도착 예정인
   edge별로 "도착 예정 차량 수가 차선 수×포화교통량(`SATURATION_FLOW_PER_LANE`=0.4대/s/차선)
   을 넘는지" 예측하고, `MIN_LEAD_TIME`(45s) 이상 여유가 있는 차량만 `adaptTraveltime`
   페널티 + `rerouteTraveltime()`으로 선제 우회시킴(이미 코앞까지 온 차량은 안 건드림 -
   그 시점엔 대안도 같이 막혀있을 확률이 높아서). **성능 주의**: 처음엔 대상 전부를
   재계산시켰더니 차량 2273대 기준 1회 계산에 10.7초 걸려서 라이브 데모가 버벅일
   수준이었음 — 여유 시간이 적어 급한 차량 순으로 정렬해 **한 사이클에
   `MAX_REROUTES_PER_CYCLE`(120)대까지만** 처리하도록 잘라서 2.5초로 줄임(놓친 차량은
   다음 60초 사이클에 다시 잡힘). `traci.edge.getTraveltime()` 결과를 사이클 내에서
   캐싱해서 같은 edge를 여러 차량이 공유해도 중복 조회 안 함.
8. **최종 검증 결과** (seed 42, 7200대, t=3000s 기준 — 위에서 언급한 순서대로):

   | 방식 | 도착 완료 | 평균 속도 | 대기 중 |
   |---|---|---|---|
   | 통제 없음 | ~2900대 | 2.1 m/s | 2775대 |
   | 재계산만(1) | 3165대 | 1.6 m/s | 2785대 |
   | +랜덤분산(2) | 3116대 | 1.6 m/s | 2833대 |
   | +신호 92곳 신규(단순연장) | 3241대 | 1.9 m/s | 2714대 |
   | **+신호 수요비례(6)+선제우회(7)** | **3358대** | **2.2 m/s** | **2601대** |

   마지막 조합이 지금까지 중 가장 좋음(처리량 최고, 대기 최소) — 다만 가장 심했던
   개별 edge 하나는 그래도 0.56m/s로 느림(차선 수로 정해지는 물리적 처리 한계로 보임,
   신호/경로로 못 뚫는 부분). 대시보드에 실제로 연결해 40초 이상 라이브로 띄워서
   에러 없음 확인 완료, 기존 테스트 전부 통과.
   **아직 확인 못 한 것**: 이 조합을 실제 40회 배치 실험(현재 중단 상태)에 넣었을 때
   baseline 대비 통계적으로 유의미한지는 안 봤음 — 정식 실험 재개 시 확인할 것.

**이번 세션에서 파일 정리**: 팀원 공유를 앞두고 불필요한 대용량 파일 삭제 —
`network/gwangjin.net.xml.bak`(위 5번 백업, 116MB), 루트/`network/`의 `routes.rou.xml`
(둘 다 `randomTrips.py`가 내부 검증용으로 만드는, 어떤 코드도 안 읽는 부산물 — 수요
재생성할 때마다 또 생길 수 있으니 보이면 지워도 됨). `network/export.osm`/
`export_buildings.osm`(19MB)과 `experiment_data/`(74MB, 중단된 배치 실험용 seed 데이터)는
**의도적으로 남김** — 전자는 지도 재빌드용 원본, 후자는 나중에 실험 재개 시 필요할 수
있음. 정리 후 전체 용량 약 345MB→221MB.

### K. 어린이보호구역(신양초) 실제 하드웨어 보드 연동 + demo_board 폐기 (2026-08-09)

**배경**: 경진대회 서면평가 제출(마감 2026-08-10 13:00) 준비 중, 사용자가 실물 하드웨어
보드가 구체적으로 제작됐다며 사진 3장(하드웨어 보드, 지도, SUMO 스크린샷)을 공유하고
"SUMO에서도 제대로 작성해야 한다"고 요청함.

**1. 구역 식별**: 신양초등학교(자양동) 인근 사거리. SUMO 스크린샷의 좌표(x:6292.42,
y:2564.48)로 근처 노드를 탐색했으나 처음 후보(`1830064528`)는 사용자가 직접 sumo-gui에서
확인한 실제 edge ID와 달랐음 — 사용자가 우클릭 "Show Parameter"로 4개 edge ID를 직접
확인해줘서 정확한 위치를 특정함. **netconvert가 이 교차로를 인접한 두 노드(`997781280`,
`1830064526`, 0.2m짜리 커넥터 edge `172058988#1`로 연결)로 쪼개서 표현**하고 있어서, 두
노드에 붙은 edge 전부(8개)를 `network/school_zones.json`(`school_zone_1`)에 등록함 — 이
파일 형식은 `cctv_zones.json`과 동일(edges/name/coord)해서 감지·판단 로직을 그대로 재사용.
CCTV 9곳과는 성격이 달라(데이터 기반 자동 선정 vs 하드웨어 연동용 수동 등록) 별도 파일로
분리, `cctv_detector.py`에 `SCHOOL_ZONES` + `ALL_ZONES`(둘의 합집합) 추가. `zone_status`/
`trigger_accident`/`poll_all_zones`는 ALL_ZONES 기준으로 일반화했지만, **자동 확률 기반
사고 발생(`update_accidents`)은 CCTV_ZONES만 대상으로 유지** — 어린이보호구역 사고는
전부 하드웨어 신호로만 발생해야 하므로 무작위 자동 발생 대상에서 제외.

**2. 일방통행 반영**: 사용자가 "`-172058984`(SE)·`-85960673#2`(NW) 둘 다 북서쪽 방향
일방통행"이라고 알려줘서, netconvert `--remove-edges.explicit`로 반대 방향(`172058984`,
`85960673#2`, 둘 다 양의 방향)을 net.xml에서 완전히 제거함(재빌드 시 **이전에 이미 심어둔
`--tls.set`을 또 넘기면 세그폴트남 - 이미 신호가 있는 net.xml을 `-s`로 다시 입력할 땐
`--tls.set`을 빼야 함**, J번 참고). edge 36816→36814(2개 삭제), 신호 295개 그대로, CCTV
구역 전부 정상. `school_zones.json`의 edges도 삭제된 2개를 빼고 갱신.

**3. 대시보드 카드**: 처음엔 CCTV 그리드 아래 별도 섹션으로 만들었다가, 사용자 요청으로
**같은 `#zone-grid` 안에 교차로 9 바로 옆으로 재배치**(`.school-zone-card` 클래스로 초록
테두리+🚸 아이콘만 다르게). 클릭 시 카메라 확대 폭도 CCTV 구역(250m)과 다르게
`_SCHOOL_ZONE_FOCUS_VIEW_WIDTH_M = 110`으로 별도 지정(사거리 하나뿐이라 화면에 꽉 차게).

**4. 도로 시각 강조 시도 → 롤백**: 사용자가 "이 사거리 도로만 빨간색으로" 요청 → **TraCI에
도로/차선 색상을 바꾸는 API 자체가 없음을 확인**(`traci.lane`/`traci.edge`에 `setColor`
없음 - 차량은 있음). 우회책으로 `gwangjin.poly.xml`에 도로 폭만큼 빨간 폴리곤을 겹쳐 그리는
방법을 시도했으나(처음엔 방향별 얇은 선 → 채워진 사각형으로 개선) 사용자가 실제로 보기엔
여전히 만족스럽지 않다고 판단, **완전히 제거하고 원상복구함**. (다른 방법: 도로 type을
새로 만들고 지도 전체의 edge 색상 모드를 "타입별"로 바꾸는 방법도 있으나, 지도 전체
렌더링 방식이 바뀌는 부작용이 커서 시도 안 함 - 필요하면 이 문서 참고해서 재검토.)

**5. 하드웨어 연동 스텁 — 실물 하드웨어가 아직 코드로 연결되지 않아 대시보드 버튼으로
대신 시뮬레이션**(`cctv_detector.py`에 함수 신설, `dashboard_server.py`에 pending-flag
패턴으로 연결, 대시보드에 버튼 2개 추가):
  - **차량 감지**(`spawn_hardware_vehicle`): `HARDWARE_SPAWN_EDGE = "-172058984"`(일방통행
    시작점, 하드웨어 사진의 "기점"/검은 도로)에 무작위 목적지를 가진 차량을 즉시 생성.
    `traci.simulation.findRoute()` + `traci.route.add()` + `traci.vehicle.add()`.
  - **보행자 감지**(`set_hardware_pedestrian_present`): `HARDWARE_PEDESTRIAN_EDGE =
    "-85960673#2"`(NW 진출로 초입부, 사용자가 지정한 정확한 위치)에 사고를 발생시킴.
    **다른 사고와 달리 고정 시간(45초)이 아니라 신호(present=True/False)로만 켜지고
    꺼짐** - `float('inf')`는 JSON 직렬화가 안 돼서(JS `JSON.parse`가 리터럴 `Infinity`를
    못 읽음) 대신 `HARDWARE_ACCIDENT_SENTINEL_DURATION = 999999`(초)를 씀. 프론트엔드
    `accidentRowCells()`가 remaining_s>3600이면 초 대신 "보행자 통과 대기 중"으로 표시.
  - 대시보드 API: `POST /api/school_zone/vehicle_detected`, `POST /api/school_zone/pedestrian`
    ({"present": true|false}) - **나중에 실제 하드웨어(YOLO 카메라)가 연결되면 하드웨어
    쪽에서 이 두 엔드포인트를 그대로 호출하면 됨**, 대시보드 버튼은 그 신호를 흉내낸 것.
  - 두 기능 다 기존 `_active_accidents`/감지·판단 로직을 그대로 공유해서, 사고가 생기면
    중앙 제어 알고리즘이 자동으로 반응함(별도 코드 경로 없음). 라이브 대시보드로 검증 완료.

**6. `demo_board/` 폴더 삭제**: 위 1~5번 방식(광진구 실도로망 안의 진짜 교차로 연동)이
기존 `demo_board/`(완전히 무관한 축소판 미니 네트워크 + `traci.vehicle.moveToXY()` 위치
동기화 방식)를 대체한다고 사용자가 확인. 어떤 코드도 `demo_board`/`board_calibration`/
`live_position_sync`를 참조하지 않는 것을 grep으로 재확인 후 폴더 통째로 삭제(24KB).

**7. `live_demo_controller.py`/`configs/*.json`도 같이 정리함** (사용자가 "같이 정리
수정해야 돼"라고 명시적으로 확인해줌): 옛 `demo_board` 방식은 RC카 여러 대(`car_1/2/3`)가
각자 미리 등록된 고정 경로를 반복 주행한다는 전제였는데, 실제 보드는 카메라가 인식하는
차량마다 매번 새로 등장하는 방식(vehicle_id를 미리 알 수 없음)이라 안 맞았음.
  - `load_routes()`가 이제 `(vehicles, default_route, coordinate_space)` 3-tuple을
    반환(기존 2-tuple에서 확장) — `vehicles`에 등록 안 된 차량은 `default_route`(신양초
    사거리 경로, SE 진입→사거리→NW 진출 3점)를 공용으로 씀.
  - `build_live_decisions()`에 `default_route=None`(기본값) 키워드 인자 추가 — **기존
    위치 인자 순서는 안 건드려서 하위 호환 유지**(테스트 파일의 기존 호출부 그대로 통과).
  - **버그 하나 미리 방지**: `default_route`를 여러 차량이 공유하면 `route_id`도 똑같이
    나가서 서로 다른 물리적 차량의 "경로 진행 상태"가 하나로 뒤섞일 뻔함 — `_attach_route`가
    `route_id`가 없는 경우(=default_route) `f"default-{veh_id}"`로 차량마다 고유하게
    합성하도록 고침. 새 테스트(`test_unregistered_vehicle_uses_default_route`)로 고정함.
  - `configs/demo_routes.json`: `car_1/2/3`(무관한 대각선 경로) 삭제, `default_route` +
    빈 `vehicles: {}`로 교체. **path 좌표는 여전히 PLACEHOLDER** — 하드웨어 담당자가
    실측해서 채워야 함(구조만 새 보드에 맞게 고쳤을 뿐, 숫자는 못 채움 - 실제 도로판
    좌표 측정이 필요).
  - `configs/live_demo_config.json`: 주석만 새 보드 맥락으로 갱신, `danger_zone`/
    `proximity` 값 자체는 여전히 placeholder(측정 필요).
  - 기존 테스트 + 새 테스트 전부 통과 확인함.

**검증용 실험 재실행**(보고서 3번 자료용, seed 1~3 baseline/treatment, 신호+선제우회
포함): `run_single_simulation.py`에 `SignalController`/`PredictiveRerouter`를 새로
연결하고 밀도도 대시보드와 맞춤(`-p 0.5`). seed 1은 완료(baseline 3846대/treatment
3798대 도착 - **treatment가 오히려 살짝 나쁘게 나옴, seed 1개라 아직 판단 이름**), seed
2 baseline도 완료. 세션이 한 번(컴퓨터 절전모드) 끊겨서 seed 2부터 재시작했었음 -
`results_validation_2026-08-09.csv`에 결과 누적 중, 아직 seed 2 treatment/seed 3 진행
중일 수 있음 - 이어서 확인할 것.

### L. 예선 제출 세션 — 견인차 신설 + TSTT 지표 + 밀도 재조정 + 보고서 3종 (2026-08-10)

**배경**: 서면평가 제출 당일. seed마다 결과가 들쭉날쭉하다는 문제를 조사하다가 **더 근본적인
버그를 발견**함 — 충돌한 차량이 시뮬레이션에서 사라지지 않고 도로 한복판에 계속 껴 있어서
아무리 알고리즘을 개선해도 정체가 영구적으로 안 풀리는 현상.

1. **`core/stuck_vehicle_remover.py` 신설**: `traci.vehicle.getWaitingTime()`(연속 정지
   시간, 0.1m/s 넘게 움직이면 리셋)이 `STUCK_THRESHOLD_S=180`을 넘는 차량을 `traci.vehicle.
   remove()`로 제거("견인차가 와서 치웠다"는 현실 보정). **baseline/treatment 둘 다 동일하게
   적용** — 알고리즘 효과로 착각되면 비교가 왜곡되므로. 특정 차량 하나를 1000초+ 직접 추적해서
   "~280~300초 멈춤 → SUMO 기본 teleport(300초)로 풀림 → 즉시 다시 멈춤"이 무한 반복되는 걸
   실측으로 확인 후 만든 기능. **보고서에는 이 기능을 언급하지 않기로 함**(사용자 명시적 지시,
   "견인 기능은 굳이 표에서 언급하지 말자") — 표에는 없지만 코드를 열어보면 바로 드러나므로
   본선 자료에선 먼저 밝히고 정당화하는 걸 검토할 것(M번 참고).
2. **TSTT(총 시스템 통행시간) 지표 추가**: 기존 `avg_travel_time`은 **도착한 차량만** 집계해서,
   treatment가 처리량을 늘리면(원래 못 갔을 차량까지 도착 처리) 그 차량들이 평균을 오히려
   끌어올리는 착시가 생김(seed4 실측으로 확인). TSTT는 도착 여부 무관하게 "차량이 도로 위에
   머문 시간 전부"(미도착 차량은 SIM_END까지)를 더해서 이 편향을 없앰.
3. **차량 밀도 하향**: `-p 0.5`(7200대) → `-p 0.75`(4800대) — 충돌이 계속 늘어나는 문제가
   있어 낮춤. 대시보드 시연용 `network/routes.xml`과 동일 조건으로 맞춤(실험 조건이 데모와
   다르면 비교 의미 없음).
4. **seed 1~3 재실행**(위 변경 전부 반영, `results_final_tow.csv`) — 평균 TSTT -3.1%,
   대기시간 -5.9%, 충돌 -20.3%, 처리량 +0.1%로 나왔음. **이 숫자는 이후 M번에서 두 개의
   숨은 버그가 있었던 것으로 드러남 — 그대로 믿지 말 것.**
5. **보고서 자료 3종** 제작(`docs/report_assets/`): 구조도(`architecture_diagram.svg`),
   핵심 알고리즘 요약(`central_algorithm_summary.md`), 비교표(`comparison_table.md`).
   사용자 피드백에 따라 여러 차례 톤 조정(더 간결하게 → 다시 내용 보강, "비슷하다" →
   "감소했다" 뉘앙스 등) — **최종본은 이미 이 세 파일에 반영돼 있음, 뉘앙스 재작업 요청
   시 이 파일들을 베이스로 수정할 것.**
6. **건국대 시작 화면**: `core/gui_viewport.py`에 `KONKUK_UNIV_COORD` 상수 추가(37.5419N,
   127.0764E → sumolib+pyproj 변환), sumo-gui 기본 시작 위치를 건대로 설정.
7. **폴더 대청소**: 폐기된 seed4~20(옛 방법론, 7200대) 데이터·더미 파일·백업 파일 전부 삭제
   (약 80MB). `experiment_data/`엔 seed1~3만 남김.

### M. 예선 이후 정리 세션 — 버그 2건 발견/수정 + 재실험(n=10) 후 효과 소멸 확인 (2026-09-07~09)

**배경**: 예선 마감(2026-08-10)은 이미 지났고 본선(운영기간 12월까지) 준비 단계. 다른 AI에게
폴더 상황 정리를 요청했더니 나온 지적(통계 유의성 없음/보고서 12쪽 모순 문장/신광초·신양초
표기 불일치/보행자 width 물리적 영향 미검증 등)을 전부 직접 재검증함 — **전부 정확했음**
(p-value까지 소수점 셋째 자리까지 일치, edge 수·신호 수·엔드포인트·PLACEHOLDER 전부 확인됨).
학교 이름은 **"신양초등학교"가 맞음**(사용자 확인) — 보고서 PDF의 "신광초"는 오타지만 이미
제출된 예선 PDF라 고칠 수 없고, 본선 자료는 `docs/report_assets/`(이미 신양초로 일관됨)를
소스로 쓰면 재발 안 함.

이 재검증 과정에서 **버그 2건을 새로 발견해 고침**:

1. **REROUTE가 사실상 한 번도 작동 안 하고 있었음** (가장 심각) — 하드웨어 데모에서 "사고
   지점까지 그냥 가서 멈춘다"는 사용자 제보를 조사하다 발견.
   - **원인 A(분류 문제)**: `cctv_detector._classify_vehicles()`가 `NEARBY_HOPS=2`/
     `REROUTE_HOPS=5`로 차량을 감속(SLOW) 대상과 우회(REROUTE) 대상으로 나누는데,
     `HARDWARE_SPAWN_EDGE`가 `HARDWARE_PEDESTRIAN_EDGE`에서 정확히 2 hop 거리라 항상
     감속 대상에만 걸리고 우회 대상엔 못 들어감. `detect_accidents()`에서 이 hazard edge만
     `nearby_hops=0`으로 특례 처리해서 고침.
   - **원인 B(진짜 근본 원인)**: `vehicle_controller._reroute_around()`가 회피 경로 계산에
     쓰는 `traci.edge.adaptTraveltime()` 페널티 창을 `PREVENTIVE_SLOWDOWN_DURATION=2.0`초로
     걸었는데, **실측 결과 SUMO 라우터는 이 창이 20초는 넘어야 실제로 경로 재계산에 반영하고
     2~10초는 조용히 무시하고 원래 경로를 그대로 반환**함(`findRoute`로 직접 스윕해서 확인 —
     dur=10 실패, dur=20부터 안정적으로 성공). **결정적으로 `predictive_reroute.py`(혼잡
     예측 기반 선제 우회, `REROUTE_DURATION=60`초)는 이 버그의 영향을 안 받아 정상 작동
     중이었음** — 즉 예선 보고서의 "선제적 우회" 주장 자체는 무효가 아니지만, `decision_policy`
     의 STOP>REROUTE>SLOW 중 CCTV/하드웨어가 즉시 감지한 사고에 대한 REROUTE는 예선 데이터
     수집 기간 내내 사실상 죽어 있었음. `vehicle_controller.py`에 `REROUTE_PENALTY_WINDOW =
     30.0`(명령의 `duration`과 분리된 별도 상수)을 추가해서 고침. 하드웨어 차량이 실제로
     사고 지점을 피해가는 것까지 end-to-end로 검증함(경로가 물리적으로 hazard edge를
     한 번도 안 지나감을 확인).
2. **보행자 물리적 크기(width) 왜곡**: `network/pedestrian_style.xml`의 `DEFAULT_PEDTYPE`
   width가 SUMO 기본값 0.478m가 아니라 **1.2m로 하드코딩**돼 있었음(주석에 "시인성 우선,
   물리적 정확도는 후순위"라고 명시 — 지도에서 잘 안 보여서 키운 것). 이 값이 GUI 렌더링뿐
   아니라 `--intermodal-collision`(차량-보행자) 판정 반경에도 그대로 들어가서 **충돌 건수
   지표 자체를 왜곡**시키고 있었음. width/length 오버라이드를 삭제해 SUMO 기본값(0.478m/
   0.215m)으로 복원하고, 대신 GUI 전용 `person_exaggeration`(`core/gui_viewport.py`)을
   2.50→5.00으로 올려서 화면 시인성만 보완(물리 계산엔 영향 없음).

**두 버그를 고친 뒤 seed 1~10으로 재실험**(`experiment_data/results_v2.csv`, 병렬 실행 — 과정에서
`randomTrips.py`가 병렬 실행 시 검증용 임시 파일(`routes.rou.xml`)을 공유해서 충돌하는 문제,
`--route-file`로 우회하려다 오히려 요청한 4800대 중 250대 안팎만 생성되는 부작용을 겪음 →
**demand 생성 단계만 순차로 먼저 끝내고 무거운 시뮬레이션만 병렬로 돌리는 방식**으로 정착).

**결과 — 효과가 사실상 사라짐**:

| 지표 | baseline | treatment | 변화 | p(대응) |
|---|---|---|---|---|
| TSTT | 2,976,738 | 2,976,597 | -0.00% | 0.997 |
| 누적 대기시간 | 50,442,238 | 49,771,210 | -1.33% | 0.605 |
| 충돌 건수 | 21.8 | 22.2 | **+1.83%**(방향 반전) | 0.913 |
| 급제동 | 396.2 | 383.2 | -3.28% | 0.378 |
| 처리량 | 4,153.1 | 4,146.6 | -0.16% | 0.730 |

예선 보고서의 -3.1%/-5.9%/-20.3%는 n=3 + 위 두 버그가 만든 착시에 가까웠던 것으로 보임.
**가설(미검증)**: REROUTE가 실제로 작동하기 시작하면서 `adaptTraveltime`이 특정 차량이
아니라 그 시점에 해당 edge를 지나려던 **네트워크 전역의 모든 차량**에게 똑같이 적용되는
글로벌 가중치라, 도시 전역에서 사고가 계속 나는 상황에서는 "위험 회피"가 아니라 "여기저기서
경로를 산발적으로 흔드는" 효과가 되어 국지적 이득을 상쇄시켰을 가능성. **사용자가 이 조사를
보류하고 다른 작업으로 넘어가기로 결정함(2026-09-09)** — 다음에 이어서 진행할 때는 이 가설
검증(REROUTE가 다른 차량 경로에 실제로 얼마나 영향 주는지 로그로 확인) 또는 알고리즘/보고서
방향 재설정 중 사용자가 고를 것.

### N. REROUTE 전역 파급효과 재조사 — 진범은 predictive_reroute였음 + random.seed 버그 발견/수정 (2026-09-10~16)

M번에서 보류했던 "REROUTE가 다른 차량 경로를 흔드는지" 조사를 재개함. 사용자의 최우선순위가
"차량 정체 문제 해결"로 명확해짐.

**1. 계측 조사 — 원래 가설은 기각, 진범은 다른 모듈**: `vehicle_controller._reroute_around()`
(사고 대응 REROUTE)와 `predictive_reroute.py`(정체 예측 선제 우회) 양쪽의 `adaptTraveltime`
호출을 monkeypatch로 계측해서 seed1 전체 3600초를 라이브로 추적함(`central_server.
initial_optimization()`이 60초마다 전체 차량을 재계산할 때, 경로가 바뀐 차량이 어느 모듈의
페널티 때문인지 원인별로 집계).
- **사고 REROUTE의 전역 파급효과 — 기각**. 3600초 동안 사고가 4번, REROUTE 실행이 8번밖에
  안 일어났고, 그로 인해 무관한 다른 차량 경로가 바뀐 사례는 **0건**. 페널티 대상 edge가
  너무 적고(4개) 활성 시간도 짧아서(30초) 다른 차량이 우연히 그 시점에 그 edge를 지날
  확률 자체가 거의 없음 — 표본이 너무 적어 통계에 영향을 줄 수 있는 구조가 아님.
- **`predictive_reroute.py`가 진범**: 경로가 바뀐 854대 중 524대(61%)가 이 모듈의 페널티
  때문이었음 — 이 모듈 자체의 안전장치(`MAX_REROUTES_PER_CYCLE`=120/사이클)는 자기 자신의
  직접 호출에만 적용되고, `central_server`가 독립적으로 60초마다 전체 차량을 재계산할 때
  같은 페널티를 우연히 만나 안전장치 밖에서 추가로 재계산되는 차량이 훨씬 많았음.

**2. predictive_reroute 소거 실험(seed 1~3, 켬 vs 끔)**: 예상과 달리 "버그"가 아니라
**일관된 트레이드오프**였음 — 3개 seed 전부 TSTT는 +0.9~2.7% 악화, 누적 대기시간은
-0.7~8.8% 개선. 예방적으로 미리 돌아가게 만드니 총 이동거리(TSTT)는 늘고 정체로 인한
대기(wait)는 주는, 설계 의도대로의 동작이었음. "정체 해결"을 어느 지표로 보느냐에 따라
평가가 갈림(대기시간 기준으론 도움, TSTT 기준으론 손해).

**3. 튜닝 시도 → 되돌림**: 페널티를 고정값(`REROUTE_PENALTY=1e5`, 사실상 "무조건 회피")에서
edge 실측 통행시간의 4배수로 바꿔서 "진짜 이득일 때만 우회"하도록 시도(`REROUTE_PENALTY_FACTOR`).
seed 1~3 재검증 결과 **seed마다 결과가 뒤섞임**(어떤 seed는 두 지표 다 개선, 어떤 seed는 둘 다
악화) — 일관된 개선이라는 근거가 없어서 **원래 고정값(1e5)으로 되돌림**. 나중에 다시 튜닝을
시도한다면 seed를 훨씬 더 많이(10+) 돌려서 검증할 것, 고정 배수 하나로 3개 seed만 보고
판단하지 말 것.

**4. random.seed 버그 발견/수정 (중요, 구조적 문제)**: 소거 실험 중 "같은 seed로 같은 모드를
두 번 돌렸는데 숫자가 다른" 현상을 발견 — `cctv_detector.py`의 사고 발생(`update_accidents`)이
Python 표준 `random` 모듈을 쓰는데, 이게 SUMO `--seed`와 완전히 별개 상태라 **프로세스를 새로
실행할 때마다 OS 엔트로피로 새로 시드됨**. 즉 지금까지의 모든 treatment 실험(`results.csv`,
`results_v2.csv` 포함)은 "seed"가 차량/보행자 수요와 SUMO 내부 난수만 고정했을 뿐, **사고가
언제 어디서 나는지는 매번 랜덤**이었다는 뜻 — 치명적인 재현성 결함. `run_single_simulation.py`
의 `run()` 시작 부분에 `random.seed(seed)`를 추가해서 고침(baseline은 원래 `poll_all_zones()`를
호출 안 해서 이 버그 영향이 없었음 — baseline 수치가 매번 완전히 동일했던 이유).

**5. 최종 재실험 (`experiment_data/results_v3.csv`, seed 1~10, random.seed 수정 + 원래
predictive_reroute 그대로)**:

| 지표 | baseline | treatment | 변화 | p(대응) |
|---|---|---|---|---|
| TSTT | 2,976,738 | 2,992,056 | +0.51% | 0.744 |
| 누적 대기시간 | 50,442,238 | 50,124,796 | -0.63% | 0.844 |
| 충돌 건수 | 21.8 | 19.8 | -9.17% | 0.440 |
| 급제동 | 396.2 | 401.3 | +1.29% | 0.755 |
| 처리량 | 4,153.1 | 4,153.4 | +0.01% | 0.985 |

M번의 `results_v2.csv`(random.seed 버그가 아직 있던 시점의 n=10)와 방향은 조금 다르지만
(이번엔 충돌이 -9.17%로 개선 쪽, TSTT는 소폭 악화) **결론은 동일함 — 전부 p>0.44로 여전히
통계적으로 유의미하지 않음.** 이걸로 "n=10, 알려진 버그 다 고친 상태"에서 두 번째로 유의미한
개선을 못 찾은 것이라 재현성 있는 결론으로 봐도 됨.

### O. "차량 정체 문제 해결"이 실제 목표 — 그리드락·만성정체 직접 탐지 및 완화 (2026-09-23~25)

**배경**: 사용자가 명확히 함 - "보고서 수치로 눈속임하는 게 아니라 실제로 차량이 단체로
막혀서 못 움직이는 걸 막고 싶다." 통계 실험(M/N번)은 보류하고, 실제 시뮬레이션 안에서
"막힘"을 정의하고 찾아서 고치는 작업으로 전환함. 미리 5개 해결 방안(A~E)을 순서대로
검토하기로 함:
- **A. 그리드락 사전 차단** (2개 이상 방향이 동시에 오래 완전정지)
- **B. 충돌-재정체 사이클의 진짜 원인 규명**
- **C. 신호에 게이팅(진입 제한) 추가**
- **D. predictive_reroute가 특정 대안 경로로 몰아주는지 확인**
- **E. 도로망 자체(신호/연결) 수정**

**A. 그리드락 탐지 + 신호 신설**: "2개 방향 이상이 동시에 60초 넘게 완전정지"를 직접
계측하는 스크립트를 짜서 seed1 전체(3600초)를 돌림 - **12건, 총 559초, 특정 9개
교차로에 집중**(무작위 아님). 이 9곳을 열어보니 5곳은 아직 미신호(priority) 상태였고,
공통적으로 시속 100km급 도로가 작은 도로와 만나는 지점이었음. **이 5곳(8743773046,
436821916, 436832681, 8319213994, 4176800256)에 netconvert로 신호 신규 추가**
(`--tls.set` + `--tls.default-type actuated`, edge 수/CCTV존/기존 route 전부 그대로
유지 확인 후 적용 - 이 재빌드 자체는 세션이 한 번 끊긴 사이 이미 실행돼 있었고, 이어서
검증만 함).

**신호 추가 후 오히려 악화되는 경우 발견 → 진짜 원인은 `signal_controller.py`의
네트워크 전역 버그**: 신호 5곳을 추가했더니 그리드락이 12건/559초 → 17건/1012초로
악화됨. 원인 조사 결과, `signal_controller.py`가 "보행자 신호만 끄는 짧은 부속
phase"(예: minDur=maxDur=5초)를 별개의 "다음 방향"으로 오인식해서, `_next_green_phase()`
가 진짜 반대 방향이 아니라 **자기 자신의 부속 phase와 비교**하고 있었음 - "반대 방향이
급하면 일찍 끊기" 로직이 사실상 죽어있었던 것. **이 버그는 이 5곳만이 아니라
signal_controller가 관리하던 274개 신호 교차로 전부(100%)에 영향을 주고 있었음**
(old_green_order 길이가 거의 항상 new의 정확히 2배 - 274곳 중 166곳은 진짜 두 방향을
잘못 비교, 104곳은 애초에 방향이 1개뿐이라 관리 대상이 아니어야 했음). 보행자 lane
제외 + 같은 방향 중복 phase 병합으로 고침(`core/signal_controller.py`). **J번 세션에서
소개된 "신호 수요비례 배분"이 이 수정 전까지 네트워크 전체에서 제대로 작동한 적이
없었다는 뜻** - 이후 통계 재실험을 한다면 이 사실을 꼭 반영할 것.

**436832681은 신호를 고쳐도 여전히 일부 남음**: 실측해보니 이 교차로는 작은 도로가
거의 항상 텅 비어있는데(평균 0.9대) 6차선 도로에 8.1대가 몰림 - **minDur(최소 보장
시간, 보행자 안전용)이 작은 도로에도 매 주기 강제로 배정되면서 6차선 쪽이 손해를 보는
구조적 문제**로 판명(신호 로직 버그가 아니라 안전 파라미터와의 트레이드오프).

**B. 충돌-재정체 원인 추적**: 실제 충돌 하나를 감지 즉시 400초간 추적함. 결과: 충돌
당사자 한 대는 `stuck_vehicle_remover`가 정확히 180초 만에 깔끔하게 제거함(의도대로
작동). 다른 당사자는 후유증 없이 잘 달리다가도 **전혀 다른 3곳에서 연달아 막혔는데,
그 지점들이 A번에서 찾은 만성 교차로들과 같은 도로 계열**이었음. **결론: "충돌이
대규모 정체를 만든다"는 기존 가설은 과장이었고, 진짜 원인은 네트워크에 이미 있는
만성 정체 지점들 - B는 별도 문제가 아니라 A를 더 넓혀야 한다는 신호였음.**

**A 확장 - 단일 방향 만성 정체**: "2방향 이상 동시 정지"만 보던 기준을 "한 방향이라도
2m/s 이하로 120초 이상 지속"으로 넓혀서 재조사 → **그리드락(559초)보다 17배 큰
9628초**가 나옴(9개 edge). 상위 edge들의 목적지 교차로 8곳에 마찬가지로 netconvert로
신호 신규 추가(3840739116, 436821905, 7387363205, 7856245568, 7856245663,
8952652969, 9622890707, 9651134456) - 전체 신호 300→308개.

**D. predictive_reroute 몰림 확인**: 우회 대상 차량들의 새 경로를 계측한 결과, **한
사이클에 73대 중 71대(97%)가 전부 같은 edge 하나로 몰리는** 심한 herd effect를 확인함.
`traci.vehicle.setAdaptedTraveltime()`(차량별 개별 가중치)을 이용해, 한 사이클 안에서
순차적으로 배정하면서 이미 많이 몰린 대안 edge에는 그 차량만 추가 회피시키는 로직을
추가함(`MAX_DETOUR_SHARE_PER_LANE`, `core/predictive_reroute.py`). **seed 고정 후
"갈라지기 전 첫 사이클"만 비교 - 몰림 96%→56%로 확실히 개선 확인.**

**중대한 방법론 실수 발견 - random.seed 없이 비교함 + "이전" net.xml 백업 안 함**:
minDur을 "차도 사람도 없으면 건너뛴다"로 추가 실험했다가(신호 308개 전역 적용) 만성
정체가 7678→11029초로 악화된 것처럼 보여서 되돌렸는데, **이 비교 자체가 `find_gridlock.py`
/`find_chronic_edges.py`류 스크립트에 `random.seed()`가 없어서 매 실행마다 사고가 다르게
나는 상태로 측정한 것**이었다(D번은 이 문제를 알고 고정해서 비교했었음). seed를 고정해서
다시 재보니 "off"와 "on"이 11907 vs 11917로 사실상 동일(노이즈 범위) - **minDur 스킵은
효과가 없었을 뿐 역효과도 아니었음**(되돌린 결정 자체는 무해하지만 이유는 틀렸었음).
더 심각한 문제: **오늘 신호를 추가하기 전(A번 초반)의 net.xml을 백업해두지 않아서, 이제
와서 "신호 추가 자체가 얼마나 도움이 됐는지"는 영영 증명할 수 없게 됨.** 이후로는
① 네트워크/신호를 바꾸기 전 반드시 `.net.xml` 백업, ② 사고/정체 계측 스크립트엔 항상
`random.seed(seed)`를 SUMO `--seed`와 같은 값으로 고정, 이 두 가지를 원칙으로 삼음.

**"지금 상태"의 정직한 5-seed 기준선** (신호 13곳 추가 + signal_controller 버그 수정 +
predictive_reroute 몰림 방지 전부 반영, seed 고정): 만성정체 평균 **9904초**, 그리드락
평균 **1159초** (seed별 편차 큼 - 만성 8079~11907, 그리드락 666~1766). 이 숫자를
이후 모든 변경의 비교 기준점으로 쓸 것.

**E. 도로망(신호 구성) 자체 수정 - 검증된 개선**: 만성 정체 최상위 3곳(7856245663,
7856245568, 436821905)을 다시 열어보니, 간선도로(priority 11)와 골목(priority 1~3,
시속 10~50km, 1~2차선)의 **edge priority 차이가 크게 나는 곳**이었음(반면 436832681은
세 진입로 priority가 11~12로 비슷해서 이 방법이 안 맞음 - 제외함). 이런 극단적
불균형은 신호로 "공평하게" 나누는 것 자체가 비현실적(실제 도로라면 골목 쪽에 신호가
아니라 일시정지 표지를 쓴다) - `netconvert --tls.unset 7856245663,7856245568,436821905`
로 이 3곳만 신호를 빼고 SUMO의 우선순위 기반(priority) 교차로로 되돌림(edge priority
차이가 크므로 간선도로가 자동으로 우선권을 가짐). **5-seed 평균으로 검증**: 만성정체
9904→9420초(-4.9%), 그리드락 1159→876초(-24.4%) - seed별로는 5개 중 2개(seed2, 5)가
악화, 3개가 개선(seed1·3은 그리드락이 절반 이하로) - 평균은 확실한 개선이나 모든
상황에서 무조건 좋아지는 건 아님. 이번엔 지난 minDur 스킵 실패와 달리 **극소수(3곳)
교차로에만 좁혀서 적용**해서 네트워크 전역 부작용을 피함.

**C. 신호 게이팅 - 시도했으나 역효과로 원복**: 하류 edge가 이미 꽉 찼으면(점유율
80% 이상) 지금 방향 초록을 더 연장하지 않는 방식을 시도함(`sumolib`로 각 phase의
green lane이 이어지는 하류 edge를 미리 계산). 5-seed로 검증한 결과 만성정체는 거의
그대로(9420→9224)인데 **그리드락이 오히려 45% 악화됨(876→1272, 5개 중 4개 seed에서
악화)** - 하류를 보호하려고 지금 교차로에서 안 흘려보내니 그 대기가 지금 교차로
자체에 쌓여서 새로운 그리드락을 만든 것으로 보임. `core/signal_controller.py`를
원래 상태(인자 없는 `SignalController()`)로 완전히 되돌림.

**정식 계측 스크립트로 승격**: 이번 세션에서 스크래치패드에 임시로 짰던 그리드락/
만성정체 계측 로직을 `scripts/measure_congestion.py`로 옮겨서 정식 도구로 만듦
(`python scripts/measure_congestion.py --seeds 1 2 3 4 5`) - seed 고정 필수라는 교훈을
코드 자체에 박아뒀다. **앞으로 신호/알고리즘을 바꿀 때마다 이 스크립트로 여러 seed
평균을 재서 비교할 것.**

**미완료(다음에 이어갈 것)**: 436832681의 남은 그리드락(minDur 제약)은 아직 해법
없음 - edge priority 차이가 크지 않아 E번 방식(신호 제거)도 못 씀, 차로 채널화(전용
우회전 차로 등) 같은 다른 접근이 필요할 수 있음. A~E 중 A/D/E는 순효과 확인(또는
확인 시도), B는 A로 흡수됨, C는 역효과로 폐기 - 5개 방안을 전부 검토 완료함.

### P. 차량 쪽 저장소 연동 + 쪼개진 사거리 신호 합치기 (2026-09-26)

**1. 차량 쪽 저장소 `invuc02/capstone-sumo-bridge`** (로컬 `C:\capstone-sumo-bridge`):
하드웨어(차량 호스트) 팀이 두 시스템의 접점만 모아둔 저장소. `INTERFACE.md`(규격),
`samples/`(9/25 실제 두 대 주행에서 뽑은 6장면: 주행/보행자 정지/후행 후진/후행 B 우회/
마커 손실/도착), `replay.py`(샘플을 UDP 9002로 송신), `listen.py`(수신 확인). 하드웨어
없이 SUMO 쪽 개발 가능. 좌표는 보드 남서쪽 모서리 원점 미터(x 0~1.34, y 0~0.91), 보행자는
A 도로 x=0.30. 차량이 경로를 이름(`lead_C_to_A`, `follow_C_to_A`, `divert_to_B_x710/680/740`)
으로 관리하고, 보행자 정지·차간 정지·B 우회를 이미 차량 스스로 판단한다.

**2. SUMO → 차량 판단 메시지 형식을 우리가 제안해 PR로 올림** (브랜치
`decision-message-format`, 차량 쪽 `DecisionReceiver`가 맞추기로 함 - 필드 이름이 다르면
그쪽이 알려주기로 함). 요점: `{"type":"decisions","timestamp_ms","decisions":[...]}`, 경로
좌표 안 보냄, 재경로는 차량 쪽 경로 이름으로만, ttl 지나면 정지가 아니라 차량 자체 판단으로
복귀, 로컬/SUMO 중 보수적인 쪽 우선. 이 PC엔 GitHub CLI(`gh`)가 없어 PR 작성은 사용자가
브라우저에서 했고, git 전역 사용자 정보도 미설정이라 커밋할 때 작성자를 명령마다 지정함.

**3. `scripts/live_demo_controller.py`를 새 형식으로 변경**: `type`/`timestamp_ms` 추가,
`path`/`coordinate_space` 제거, 마커 안 보이는 차엔 판단 안 보냄, REROUTE 판단 추가
(`_can_reroute()` - 규칙은 `docs/SUMO_LIVE_DEMO_HANDOFF.md` 4절). `configs/demo_routes.json`
과 `load_routes`/`--routes` 삭제. `configs/live_demo_config.json`의 `danger_zone`을 자리표시
`[0,0,0,0]`에서 보드 전체 `[0,0,1.34,0.91]`로 - **자리표시 값 때문에 보행자에 전혀 반응하지
않던 걸 replay.py로 발견함.** replay.py 6장면으로 end-to-end 확인: 보행자 장면에서 선행
STOP + 후행 REROUTE→divert_to_B_x710(실물 차가 실제로 한 우회와 일치). 테스트 22→27개.

**4. 쪼개진 사거리 신호 합치기 (`netconvert --tls.join`) - 적용했으나 효과 측정 전**:
사용자가 sumo-gui에서 "사거리 한가운데 뜬금없는 신호등들이 뒤죽박죽 꼬여 있다"고 지적. 확인
결과 netconvert가 실제 사거리 하나를 여러 노드로 쪼개고 **노드마다 서로 연동 안 되는 별개
신호**를 달아둔 구조였음 - 신호 305개 중 242개가 40m 안에 다른 신호가 붙은 쪼개진 사거리
83곳에 속함(최악은 한 사거리에 신호 10개). 첫 신호에서 초록 받고 들어간 차가 10m 앞 안쪽
신호의 빨강에 갇혀 사거리 한복판을 막는 게 그리드락의 근본 원인으로 보임. O번에서 제가
추가한 `436832681`+`8743773046`도 같은 사거리 안에 신호 두 개를 박은 셈이었음.
`--tls.join --tls.join-dist 20 --tls.ignore-internal-junction-jam`으로 재빌드해서 적용함:
신호 프로그램 305→207개, edge 36814 그대로, CCTV/스쿨존/경로 누락 없음, 테스트 통과.
- join-dist 40은 주기 442초짜리 신호가 생기고 10개짜리 사거리도 여전히 안 합쳐져서 버림.
- `--tls.ignore-internal-junction-jam`은 join만 했을 때 생긴 "서로 충돌하는 두 방향에 동시
  초록" 신호 계획 1건(`joinedS_11105986500_436821890_8952652945`)을 없애려고 넣음(SUMO 권장).
  다만 교차로에 갇힌 차를 무시하고 진행하는 옵션이라 **충돌이 늘 위험이 있음.**
- 남은 문제: 합쳐진 4곳은 주기가 259~272초로 김(방향마다 phase가 따로 생김). 신호 10개짜리
  사거리((7695,3735) 부근)는 노드 간격이 20m를 넘어 안 합쳐짐.
- **효과 측정(5-seed 전후 비교)은 사용자 요청으로 중간에 멈춰서 결과가 없다.** 되돌리려면
  `experiment_data/gwangjin_backup_before_tlsjoin_2026-09-26.net.xml`을 `network/gwangjin.net.xml`
  로 복사. 측정은 `scripts/measure_congestion.py`에 `--net`(비교용 네트워크 지정)과 충돌 건수
  집계를 추가해둠 - 예: `python scripts/measure_congestion.py --seeds 1 2 3 4 5 --net
  experiment_data/gwangjin_backup_before_tlsjoin_2026-09-26.net.xml --out <파일>`.
- `experiment_data/`에 117MB짜리 백업이 세 개 있다(before_E, before_yellow, before_tlsjoin).
  before_yellow는 이번 세션이 만든 게 아니고 내용이 before_tlsjoin과 똑같다(다른 세션이나
  사용자가 만든 것으로 보임). 용량이 크니 필요 없어지면 정리할 것.

### Q. 견인 상위 9개 사거리 노드 자체를 합침 — 정체 대폭 감소 확인 (2026-09-26~27)

**원인 확인**: 신호 프로그램만 합친(P-4) 뒤에도 seed 1 견인 923건 중 상위 2곳이 44%, 상위 10곳이
82%. 대기열 맨 앞 차를 추적해보니 세 곳 모두 **사거리 안에 0.2~6m짜리 edge가 끼어 있어서
차가 사거리 한가운데에서 두 번째 정지선을 만나 멈춤** - 1위는 비보호('g') 양보 대기로 127초,
4위는 교차로 내부 차선에서 빨강(259초 주기 중 31초만 초록) 대기. 신호 프로그램 합치기로는
이 중간 정지선이 사라지지 않음.

**조치**: 상위 9곳(join_nodes_applied.nod.xml)에서 신호 노드 + 20m 미만 edge로 이어진
priority 노드를 `<join nodes="..."/>`로 한 노드로 합쳐 netconvert 재빌드(`-s 기존net -n
join.nod.xml --tls.ignore-internal-junction-jam`). 9곳 모두 90초 주기로 재생성, 초록 못 받는
방향 없음. 신호 204개, edge 134개 삭제.
- **함정**: 합친 신호(joinedS_...)의 노드 일부만 join 목록에 넣으면 남은 연결이 없는 링크
  번호를 가리켜 SUMO가 "Invalid linkIndex"로 안 뜸 → 관련 신호의 노드는 전부 넣을 것.
- **경로 파일도 같이 고쳐야 함**(삭제된 edge를 지나는 경로): 해당 차량/보행자만 출발·도착
  edge를 유지한 채 duarouter로 재계산, 나머지 경로는 그대로 둠. network/routes.xml,
  pedestrian_routes.xml, experiment_data/routes_seed1~10, pedestrian_routes_seed1~10 전부 적용.
  차량 4800대 전부 유지. 횡단보도 없던 첫 버전에선 보행자가 seed마다 0~14명 빠졌으나, 현재
  (횡단보도 포함) 버전으로 다시 고친 뒤엔 누락 0명. 코드/설정은 삭제 edge를 참조 안 함.

**측정(5 seed, measure_congestion.py, 전: 백업 net+백업 경로 / 후: 현재)**:

| 지표 | 전 | 후 |
|---|---|---|
| 견인 | 892 | 200 (-78%) |
| 도착 | 3112 | 3940 (+27%) |
| 만성정체(s) | 11769 | 2941 (-75%) |
| 그리드락(s) | 1164 | 341 (-71%) |
| 충돌 | 775 | 507 (-35%) |

다섯 seed 모두 같은 방향. 원자료는 `experiment_data/junctionjoin_measure_2026-09-27/`.

**⚠ 위 표는 횡단보도가 사라진 상태의 수치 - 인용하지 말 것.** netconvert로 노드를 합치면
합친 사거리의 횡단보도(crossing)가 다시 만들어지지 않는다(9곳 모두 0개였음 → 보행자가 못 건너고
차는 보행자에게 양보할 일이 없어져 개선이 부풀려짐). `--crossings.guess`를 붙여 재빌드하면 합친
9곳에만 61개가 생기고 나머지는 그대로(전체 18185→18182). **현재 적용된 net은 이 횡단보도 포함
버전**이고, 경로 파일도 이 net 기준으로 다시 고침(보행자 누락 0명). 재측정(5 seed, afterc_*.json):

| 지표 | 전 | 후(횡단보도 포함, 현재) |
|---|---|---|
| 견인 | 892 | 179 (-80%) |
| 도착 | 3112 | 3912 (+26%) |
| 만성정체(s) | 11769 | 2950 (-75%) |
| 그리드락(s) | 1164 | 783 (-33%) |
| 충돌 | 775 | 357 (-54%) |

- 4위 사거리는 보행자 phase가 들어가면서 주기 197초(17 phase)가 됨.
- **2차 시도(적용 안 함, 2026-09-27)**: ① 4위에서 차가 시간당 1~5대인 골목 진입로 전용 phase
  (p11, p14)를 26→5초, 34대인 p8을 26→12초로 줄여 주기 197→141초 ② 5위에 옆 right_before_left
  노드 3991888760·7856245561까지 합침. 둘 다 적용(5 seed): 그리드락 783→565s(5/5 개선)였지만
  견인 179→239(0/5 개선), 충돌 357→490 → 기각. 따로 떼어 seed 1~3: 4위만 = 그리드락은 3/3 개선,
  견인 악화(242/187/175 vs 242/144/142), 충돌 38~725로 요동. 5위만 = 견인 157 vs 176, 만성정체
  3538 vs 2995s, 충돌 268 vs 324 - 뒤섞임. **결론: 사거리 한 곳 phase를 조금 바꾸는 수준의 효과는
  seed 간 요동(같은 변경에 충돌이 38건~725건)보다 작아서 seed 3~5개로는 판별 불가.** 원자료는
  `experiment_data/junctionjoin_measure_2026-09-27/`(r2_*, only4_*, only5_*). 5위에서 합치며 사라진
  0m edge 5개는 어떤 차량 경로도 안 지나던 것이었음.
- **3차: 새로 드러난 쪼개진 사거리 3곳 합침(적용함, 2026-09-27)**: 9곳 합친 뒤 seed 1~3 견인
  위치를 다시 뽑으니 1위(9340,3707) 108건(교차로 안 50건, 신호 joinedS_7851953103... + 안쪽
  priority 노드 414683265·8743773136), 2위(6987,5200) 61건(joinedS_436538616..., 노드 4개),
  7위(6894,3892) 26건(joinedS_11105986500_436821890_8952652945)이 같은 구조 문제였음. 같은
  방법(join + `--crossings.guess`, `backup_before_round3_2026-09-27/join_nodes_round3.nod.xml`)으로
  합침: 세 곳 모두 90초 주기, 횡단보도 1위 7·2위 4·7위 5개, 전체 18182→18166, edge 42개 삭제.
  5 seed(r3_*.json):

  | 지표 | 9곳 합친 뒤 | +3곳 |
  |---|---|---|
  | 견인 | 179 | 117 (-34%, 4/5 개선) |
  | 도착 | 3912 | 3984 (+2%, 5/5) |
  | 만성정체(s) | 2950 | 2876 (-3%, 3/5) |
  | 그리드락(s) | 783 | 697 (-11%, 4/5) |
  | 충돌 | 357 | 66 (-81%, 4/5) |

  적용 전 전체 상태 대비(최초 백업 기준): 견인 892→117, 도착 3112→3984.
  되돌리기: ~~`experiment_data/backup_before_round3_2026-09-27/`~~ (2026-09-28 삭제 - 이제 못 되돌림).
- **3차 적용 후 남은 견인(seed 1~3: 160/182/100)**: 1위가 (5036,6038) 사거리와 그 앞
  218831325 / -1346095016 구간 158건(36%, 세 seed 모두). 대기열 맨 앞 차 추적 결과 신호
  joinedS_10708182323_414685840 링크12 앞에서 150초 넘게 정지 - ① 진입 edge가 0m(218831325#4)라
  signal_controller가 대기열을 0으로 보고 해당 phase(원래 33초)를 5초 만에 끊음 ② 초록이어도
  신호 0m 앞 priority 노드 12389365913에서 옆길에 양보하느라 못 감. 그다음은 이미 합친 사거리의
  진입로 396816938#8(40건), 출구 516648936#6(39건).
- **4차 시도(적용 안 함)**: 위 사거리 노드 13개(신호 2 + priority 11, 반경 30m)를 합침
  (11 phase, 링크 79개). 5 seed(r4_*.json, 기준 r3): 견인 117→95(4/5 개선)지만 만성정체
  2876→3819s(2/5), 그리드락 697→807s(2/5), 충돌 66→127(평균은 seed 2의 17→403 탓, 4/5는 개선)
  → 기각. 막히던 방향은 풀렸지만 거대해진 신호에서 다른 방향들 초록이 줄어 정체가 옮겨간
  것으로 보임.
- **5차 시도(원복함)**: ①만 겨냥해 signal_controller가 15m 미만 진입 edge면 상류 lane(최대
  3단계)의 대기열도 세게 함(신호 203개 중 151개, 진입 lane 448개가 해당). 5 seed(sc_*.json,
  기준 r3): 견인 117→123, 만성정체 2876→3277s, 그리드락 697→739s, 충돌 66→173 - 대부분 1~2/5만
  개선 → 원복. 상세는 signal_controller.py 상단 주석. **signal_controller를 전역으로 바꾸는
  시도는 이로써 세 번째 실패(minDur 건너뛰기, 하류 게이팅, 상류 대기열) - 네트워크 구조를 고치는
  쪽(노드 합치기)만 효과가 컸다.**
- **전체 128곳 합치기(plan: 신호노드 + 20m 미만 edge로 이어진 신호/priority + 5m 미만
  right_before_left, 45m 이내)는 seed 1에서 오히려 나빠서 적용 안 함**: 만성정체 3868→8865s,
  그리드락 978→2376s, 도착 3855→3747(충돌만 559→34). 보행자 phase 때문에 주기 173~239초짜리
  신호가 8곳 생긴 탓으로 보임. 하려면 긴 주기 신호를 먼저 다듬어야 함.
- `measure_congestion.py`는 `--net`으로 다른 net을 잴 때 `cctv_detector._NET`도 그 net으로
  바꾸도록 고침(전에는 항상 network/gwangjin.net.xml로 상류 edge를 찾았음 - 없는 edge 조회로
  죽거나 CCTV 주변 분류가 틀어짐. 위 "전" 측정도 이 영향이 약간 있었음).
`measure_congestion.py`에 `--route-dir`, 견인(`tows`)·도착(`arrived`) 집계 추가.
되돌리기: ~~`experiment_data/backup_before_junctionjoin_2026-09-27/`~~ (2026-09-28 삭제 - 이제 못 되돌림).
- 5위(1168013959 일대)는 거의 그대로(52→48) - 옆 15m의 right_before_left 노드(3991888760)가
  0m edge로 붙어 있는데 이번 join에서 뺐기 때문으로 보임.

### R. 실물 보드 → 신양초 사거리 자동 반영 + 시연 화면 품질 (2026-09-28 밤, 사용자 취침 중 진행)

**상세·되돌리는 법은 `docs/OVERNIGHT_BRIEFING_2026-09-28.md`** (단계별 백업:
`experiment_data/backup_overnight_2026-09-28/step0_original ~ step3_after_demo_pacing`).

- 팀원 결정(9/26): 연동은 **차량 → SUMO 한 방향**. SUMO는 판단하지 않고 그리기만 한다. 우리가 낸
  SUMO→차량 판단 형식(P-2, PR #1)은 참고용으로만 남음 - `live_demo_controller.py`는 2026-09-28 삭제.
- **실물 상황은 광진구 net 안의 신양초 사거리에 그린다**(별도 소형 보드 네트워크는 만들지 않음 - 사용자 확인).
  `core/hardware_twin.py` + `configs/hardware_twin.json`: 대시보드가 UDP 9002로 traffic_state를 받아, 보드 위
  진행 거리를 기준점(출발/사거리 입구/LED 선/도착)끼리 보간해 SUMO 경로 위에 차를 놓는다. 보드 C=남동 진입
  `-172058984`, A=북서 `-85960673#2`(LED 보행자), B=남서 `172058988#2`(좌회전), D=북동 `-172058988#0`(우회전).
  실물 차(`hwtwin_…`)는 중앙 재계산·사고 대응·선제 우회·견인에서 제외. D 경로 좌표는 추정값(팀원 작업 중).
- 하드웨어 없이 리허설: `python scripts/fake_hardware_sender.py [--lead A|B|D --follow A|B|D --no-pedestrian --loop]`.
- 시연 화면: `scripts/build_visual_assets.py`(PIL로 그린 차·사람·나무 이미지 + `network/vehicle_style.xml`),
  `scripts/build_styled_polys.py`(OSM 지도 화풍 배경 + 건물 테두리 + 나무 → `network/gwangjin_styled.poly.xml`),
  `core/gui_viewport.py`(아스팔트 도로, raster 차량). 대시보드 `POLY_FILE`이 새 두 파일을 씀. 물리 값은 그대로.
- 실물 연결 중엔 대시보드가 실제 시간 속도(1스텝=1초)로 돌고, 처음 연결 시 카메라가 신양초로 이동.

### S. 견인 1·2위 사거리 횡단보도 정리 (2026-09-28) — **사용자 요청으로 원복함(적용 안 된 상태)**

> 적용 직후 사용자가 "전으로 돌려줘"라고 해서 `backup_before_crossings_2026-09-28/gwangjin.net.xml`로 되돌림
> (횡단보도 18161 → 18166, 두 사거리 신호도 원래대로). 효과 측정은 도중에 멈춰서 결과 없음.
> `scripts/unify_crossings.py`와 비교 그림은 남아 있으니 다시 적용하려면 아래 방법 그대로 쓰면 됨.

사용자 지적: 합친 두 사거리(cluster_7056665195…, cluster_436832681…)의 횡단보도가 이상함. 기준은
cluster_436538601…처럼 **"사거리 중심으로 들어가기 직전, 각 도로에 도로 전체를 건너는 횡단보도 하나,
중심엔 없음"**. 원인: `--crossings.guess`가 합친 큰 사거리에서 한 도로의 들어오는/나가는 차선마다
횡단보도를 따로 만들어 조각나고 어긋남(1위 8조각 → 도로 4개, 2위 남서 갈래 2조각).
- `scripts/unify_crossings.py NET OUT NODE_PREFIX...`: 차도 edge를 바깥 방향 각도(35° 이내)로 묶어 갈래를
  찾고, 조각난 갈래는 기존 횡단보도를 discard + 갈래 전체를 건너는 하나로 다시 만든다. **신호 사거리는 기존
  프로그램을 억지로 이어 붙이면 새 횡단보도가 신호에서 빠지거나(링크 없음) 초록 5초짜리로 남아서**, 잠깐
  priority로 바꿨다가 다시 traffic_light로 지정해 프로그램을 새로 만든다(90초 주기, 이 두 신호만 바뀜).
- 결과: 두 사거리 모두 횡단보도 4개(도로마다 1개), 빈 링크·초록 못 받는 링크 없음, edge 동일(경로 파일 그대로).
  보행자 초록 5초짜리가 일부 있는데 기준 사거리(cluster_436538601…)도 6개 중 4개가 5초라 같은 방식.
  1위 북동 횡단보도는 그 도로에 삼각 교통섬이 있어 비스듬함.
- 비교 그림: `docs/report_assets/overnight_2026-09-28/crosswalk_*.png`. 되돌리기:
  `experiment_data/backup_before_crossings_2026-09-28/gwangjin.net.xml`을 `network/`로 복사.

### T. 사거리 한가운데 횡단보도 - 원리 정리 + #29 사거리 하나 고침 (2026-09-28)

**횡단보도 배치 규칙(netconvert --crossings.guess, 우리 net에서 실측 확인)**
1. 횡단보도는 노드(교차점) 하나에 속하고, 그 노드에 붙은 도로가 교차로 영역에 닿는 지점(정지선 자리)에
   도로를 가로질러 놓인다. 교차로 영역 안쪽엔 생기지 않는다 → **사거리가 노드 하나면 중심에 횡단보도가 없다.**
   한 사거리가 노드 여러 개로 쪼개져 있으면 노드 사이 짧은 연결 도로도 "노드에 붙은 도로"라서 그 위에
   횡단보도가 생긴다 → **사거리 한가운데 횡단보도**(사용자가 처음 지적한 문제의 정체).
2. 보도가 있는 차도는 모두 건넌다.
3. 한 도로의 들어오는/나가는 차로를 하나로 건널지는 두 차로 중앙선 쪽 끝 간격이 정한다: 3.2~4.7m면 하나,
   7.2m 이상(중앙분리대·교통섬)이면 따로(가운데 보행섬). 따로 놓인 조각이 어긋나 보이는 건 차로 끝 위치가
   달라서 - **정상이며 고칠 대상 아님**(S번에서 이걸 문제로 잘못 봤음).
4. 보행 신호는 그 횡단보도를 지나는 차 흐름이 모두 빨강인 단계에만 초록. 그 도로 차가 거의 모든 단계에서
   움직이면 모든 차가 서는 5초짜리 보행 전용 단계에서만 초록 - 이것도 정상.

**나쁜 사거리 찾기**: 노드 사이 20m 미만 연결 도로를 건너는 횡단보도가 net 전체 18166개 중 6516개, 1720곳
(신호 95곳). 신호 95곳 + 무신호 중 견인 상위 25곳을 캡처해 눈으로 확인 - 확실히 나쁜 곳: 신호 #4 #5 #8 #20
#23 #29 #30 #39 #44 #61 #71 #80 #85, 무신호 #96(견인 95건, 현재 1위) #104 #109 #113. 나머지 다수는 골목 작은
교차점이거나 20m 안에 붙은 이웃 사거리. (번호·좌표·캡처는 세션 스크래치패드에 있었음 - 필요하면 같은 기준으로
다시 뽑을 것: 노드 사이 연결 도로 <20m를 건너는 횡단보도.)

**#29 사거리(7665,2330) 고침**: 신호 하나(joinedS_11076288675_436839042…, P-4에서 프로그램만 합침)가 노드 8개를
제어하고 있었고 연결 도로 위에 횡단보도 7개. 그 노드 8개를 join + `--crossings.guess`로 합침 → 연결 도로 12개
삭제, 노드 하나에 갈래 4개, 횡단보도 6개 모두 갈래 입구(분리 도로 두 갈래는 규칙 3대로 두 조각), 이 신호만 새로
생성(90초, 빈 링크·초록 못 받는 링크 없음). 경로: 차량 172~212대/seed 재계산, 누락 0.
비교 그림 `docs/report_assets/overnight_2026-09-28/crosswalk_fix29.png`. **교통 효과는 아직 안 잼.**
되돌리기: `experiment_data/backup_before_fix29_2026-09-28/`의 net·경로 파일을 원위치로(합친 노드 목록도 거기).

### U. 신호 충돌 2곳 수정 + 한가운데 횡단보도 사거리 11곳 합침 (2026-09-28)

**신호 충돌(동시 우선초록)**: 교차점 하나짜리 신호 162개 전수 점검(`scripts/fix_tls_conflicts.py NET --check`) -
2곳이 "교차로 충돌표상 겹치는 두 흐름에 한 단계에서 동시에 G". 둘 다 9/27 노드 합칠 때 netconvert가 만든 것.
① cluster_13906093861…(예전 견인 4위) 26초 단계 2개: **직진 차량 G + 그 차가 지나는 횡단보도 보행자 G**(차가
보행자에게 양보 안 함) ② cluster_436538601…(사용자가 기준으로 든 사거리) 6초 단계: 마주 보는 두 좌회전 동시 G.
교차로 규칙(response)상 양보하는 쪽을 G→g(양보 초록)로 바꿈 - 신호 시간은 그대로, phase 3줄만 바뀜.
여러 노드를 묶은 신호(joinedS_…, 당시 41개)는 링크 번호 대응이 달라 이 방식으로 점검 불가.

**한가운데 횡단보도 사거리 11곳 합침**: T번 후보 중 확실히 나쁜 16곳(#4 #5 #8 #20 #23 #30 #39 #44 #61 #71 #80 #85
#96 #104 #109 #113)을 "가운데 횡단보도가 놓인 연결 도로 양 끝 노드 + 20m 미만 도로로 이어진 노드 + 같은 신호의
노드 전부, 중심 35m 이내"로 묶어 join + `--crossings.guess`. 전후 캡처(`docs/report_assets/overnight_2026-09-28/
crosswalk_fix16_pairs_*.png`)로 보고 **5곳은 뺌**: #20(이웃 사거리 둘이 거대한 덩어리로 - 폭 84m, 신호 2개),
#44·#85(Y자 분기가 뭉개짐), #109(쐐기 모양), #8(왼쪽 도로 엉킴). 이 5곳은 묶는 범위를 줄이거나 다른 방법 필요.
나머지 11곳(#4 #5 #23 #30 #39 #61 #71 #80 #96 #104 #113) **테스트 net으로만 만듦 - 실제 net엔 미반영**(5 seed 측정: 견인 127→113(3/5 개선), 충돌 118→86(3/5), 도착 4007→4010, 그런데 만성정체 3557→4330s(+22%, 1/5 개선), 그리드락 624→861s(+38%, **0/5 개선**) → 사용자 결정 대기): 연결 도로 101개 삭제, 신호 11개 → 새 신호 8개
(모두 90초, 빈 링크·초록 없는 링크·노란불 없는 차량 전환 없음, #61의 동시 우선초록 1건은 g로 고침), 나머지 192개
그대로. 경로: 차량 2260~2352대/seed 재계산(누락 0), 보행자 seed마다 0~3명 빠짐.
노드 목록: `experiment_data/backup_before_signal_and_crosswalk_fix_2026-09-28/join_nodes_fix11.nod.xml`.
현재 실제 net = #29 + 신호 충돌 수정까지. 되돌리기: 같은 폴더의 net·경로 파일(#29까지 반영, 신호 충돌 수정 전)을 원위치로.

### V. 가운데 횡단보도만 지우기 - 도로 모양은 그대로 (2026-09-28, 적용함)

사용자 요청: "횡단보도는 줄이되 도로 모양은 최대한 건드리지 말 것". U번의 노드 합치기(11곳)는 **미반영으로 두고**
대신 문제 사거리 16곳(#4 #5 #8 #20 #23 #30 #39 #44 #61 #71 #80 #85 #96 #104 #109 #113)에서 **노드 사이 연결 도로 위
횡단보도만** netconvert `<crossing … discard="true"/>`로 지움(노드·도로 그대로).
- 고르는 기준: 사거리 중심 40m 안 횡단보도 중, 건너는 차도가 모두 "양 끝이 중심 30m 안인 20m 미만 연결 도로"인 것.
  이 기준이 **입구 도로의 짧은 첫 조각**(예: #39 서쪽 0.6m `1210200077#0`) 위의 입구 횡단보도까지 잡아서, 캡처로
  확인한 #23·#39는 "바깥쪽 끝이 이웃 2개 이하 이음점이면 입구 조각"으로 되살리고, #39의 입구 횡단보도 1개는
  수동으로 제외, 입구 횡단보도 바로 안쪽에 겹친 신호 없는 중복 3개(#39)는 수동으로 추가 삭제. 규칙 하나로는
  사거리 구조가 제각각이라 안 맞아서 **캡처 확인이 필수**.
- 결과: 횡단보도 18162 → 18094(68개), 도로 목록·교차점 좌표 동일, 신호 10개가 보행 링크만 빠짐(빈 링크·초록 없는
  링크·동시 우선초록 충돌 없음). 보행자 경로: seed 1~3 전원 재계산해도 경로 찾는 사람 수 동일(412/414/410),
  바깥 횡단보도로 돌아가느라 길어진 사람 seed당 4~16명.
- **부수효과(알려진 문제)**: netconvert를 `--crossings.guess` 없이 돌리면 무관한 도로 중간 이음점 8502528414
  (도로 915344007, (5496,7020), 가장 가까운 대상에서 250m)의 보행 구역을 다시 계산해 그 도로 4개가 최대 13m
  짧아짐(원래 모양 고정 `keepshape.nod.xml`을 줘도 남음). `--crossings.guess`를 켜면 도로 변화는 0이지만 횡단보도가
  하나도 안 남는 노드에 지운 횡단보도를 다시 만들어 버림(74개 중 38개 복구) - 그래서 끈 쪽을 택함.
- 전후 캡처: `docs/report_assets/overnight_2026-09-28/crosswalk_cut_pairs_1~3.png`. 지운 목록·되돌리기:
  `experiment_data/backup_before_crosswalk_cut_2026-09-28/`(적용 전 net + discarded_crossings.con.xml).
- **교통 효과는 안 잼** - W번(측정 재현성) 참고.

### W. 측정값이 실행마다 달라짐 - 원인 조사 (2026-09-28, 미해결)

같은 net·경로·seed인데 결과가 가끔 크게 다름: 고치기 전 seed 2는 8번 중 7번 견인 149, 1번 79 / seed 4는 9번 중
7번 105, 181·108 각 1번 / 11곳 합친 net seed 2는 3번 모두 다름(100·64·107). 만성정체는 같은 조건에서 seed당
1000초 넘게 흔들림 → **그동안 "5 seed로 효과가 흔들려 판별 불가"로 버린 비교들(Q 2차, 5차, T/U 11곳 등)은 이
흔들림 폭 안이었을 수 있음.**
- 조사: Python 집합 순서(PYTHONHASHSEED)가 명령 순서를 바꾸는 곳 5개를 정렬로 고침(`cctv_detector._classify_vehicles`
  2곳 + 하드웨어 목적지 후보, `measure_congestion.py` 읽기 순서 2곳) - 해가 없어 유지. 그래도 **같은 설정·같은
  코드로 두 번 돌려 다른 값이 나온 적이 있음**(seed 4, hash 0: 108 vs 105). 우리 코드가 SUMO에 보내는 상태
  변경 명령(재경로·감속·신호 시간·견인 등)을 전부 기록해 비교하면 2600초까지 동일 → 남은 무작위성은 SUMO
  내부(메모리 주소 순 처리 등)로 추정, 우리 쪽에선 못 고침.
- 대응 제안: seed를 10개로 늘리고 평균 대신 중앙값으로 비교(1회 측정 약 2시간).
- `measure_congestion.py`에 위치별 합계(`deadlock_by_node`, `chronic_by_edge`) 추가.

### X. 국내 규칙으로 사거리 전수 점검 + 횡단보도 정리 적용 (2026-09-29)

상세: `docs/INTERSECTION_AUDIT_2026-09-29.md`. 규칙(한가운데 금지·같은 차로 겹침 금지·입구 설치·정지선 2~3m·보행
초록 7초+길이/1.0m/s·동시 우선초록 금지)으로 원본 사거리와 현재 net을 모두 점검.
- U번의 "신호 충돌 2곳"은 **오탐**이었음(충돌표 번호 오해석). `scripts/tls_conflicts_traci.py`(SUMO 내부 차선 충돌
  목록 사용)로 보면 원본·현재 모두 0.
- 원본 기반 수정은 9/27 노드 합치기가 빠져 정체가 합치기 전 수준이라 미적용.
- 현재 net 기준 전체 수정은 악화 → 단계별 측정 결과 **한가운데·겹침 삭제 + 정지선 3m만 적용**(사용자 결정). 보행 초록
  늘리기·입구 횡단보도 추가(신호 재생성)는 정체를 키워 보류.
- `experiment_data/routes_seed4.xml`이 seed1과 같은 파일이었음 → 새로 만듦.
- **같은 날 사용자 요청으로 원복함**: net·대시보드 경로·보행자 경로(seed1~10)를
  `experiment_data/backup_before_rule_crossings_2026-09-29/`로 되돌림 = V번(한가운데 68개 삭제)까지 반영된 상태.
  새로 만든 routes_seed4.xml만 유지(도로와 무관한 버그 수정, 옛 파일은 같은 백업 폴더에 있음).

### Y. 도로망 재빌드 — OSM Web Wizard와 같은 변환 설정 (2026-09-29, 적용함)

사용자가 SUMO OSM Web Wizard로 만든 건국대 주변 도로망이 더 정확해 보인다고 해서 비교: 지도 원본(OSM)은 같고
**변환 설정**이 달랐음. 예전 net은 `junctions.join` 없이 만들어 사거리 하나가 노드 여러 개로 쪼개져 있었고, Q~X번의
한가운데 횡단보도·짧은 연결 도로·견인 다발 문제의 뿌리가 이것. 광진구 전체를 `network/export.osm`에서 위저드 설정
(junctions.join, tls.join, tls.guess-signals, tls.discard-simple, geometry.remove, ramps.guess) + 보도·횡단보도
(sidewalks/crossings.guess, walkingareas)로 다시 변환. 설정은 `network/gwangjin.netccfg`
(`cd network && netconvert -c gwangjin.netccfg`로 재현).
- 좌표 기준점을 예전 net과 같게 고정(offset) → 건물·강 폴리곤, CCTV 좌표 그대로 맞음.
- 신양초 SE/NW 일방통행은 `remove-edges.explicit`로 다시 반영. 신양초는 두 노드(997781280, 1830064526)가 하나
  (`cluster_1830064526_997781280`)로 합쳐지고 0.2m 연결 도로 `172058988#1`이 없어짐 → `school_zones.json`,
  `configs/hardware_twin.json` 경로(A: -172058984 → -85960673#2 등)에서 뺌. 회전 방향(C에서 A 직진·B 좌회전·D 우회전) 확인.
- **유턴 허용이 필수**: `--no-turnarounds`로 만들었더니 막다른 길이 "들어가면 못 나오는 곳"이 되어 경로가 끊김 →
  빼서 위저드·예전 net과 같게 함.
- CCTV 9곳은 같은 위치(7m 안)의 새 교차점으로 옮김(`cctv_zones.json`의 `previous_junction_id`에 옛 id).
- 경로: 옛 경로의 출발·도착·출발시각을 유지해 새 net에서 다시 계산(없어진/이어지지 않는 끝 edge는 가까운 edge로).
  차량 4800/4800(모든 seed·대시보드), 보행자 424~448/450(예전 net 410~450). `routes_seed1~10`,
  `pedestrian_routes_seed1~10`, `network/routes.xml`, `network/pedestrian_routes.xml` 교체.
- 신호: 위저드 설정 그대로면 203개 → 100개로 줄고, 예전 net에서 병목 교차로에 손으로 추가했던 신호(J·O번 tls.set)가
  빠져 만성정체가 4305 → 24296초로 폭증. 빠진 84곳을 같은 자리 교차점에 `tls.set`으로 다시 지정하고, 신호 합치기
  (`tls.join`)는 끔(켜면 주기 238~296초짜리 합친 신호가 생김). 3 seed 비교: 합치기 켬 견인 63·그리드락 633초 /
  끔 견인 13·그리드락 163초 → 끈 쪽 채택. 최종 신호 197개(모두 90초 주기). 동시 우선초록 검사: 1곳(대형 합친
  사거리의 마주 보는 두 좌회전 보호 단계, netconvert 기본 - 그대로 둠).
- **최종 5 seed 측정(예전 net → 새 net)**: 견인 115 → **13**(5/5 감소), 도착 3969 → **4215**, 그리드락 851 → **176초**,
  충돌 147 → **12**, 만성정체 4305 → **13894초(악화)** - 능동로(516648936#2~7)·광나루로(519089677)·아차산로(516647743,
  1038157018)의 차로 1개짜리 진입로가 신호 대기열로 계속 막힘(도로 차로 수는 예전 net과 같음). 다음 과제: 이 사거리들의
  신호 배분 조정.
- 하드웨어 쌍둥이의 노란 횡단보도가 새 net에서 안 보였음 → 두 원인 수정(`core/hardware_twin.py`): 도로가 layer
  0.2~2 위에 그려져 묻힘(→ layer 3), 도로 방향이 바뀌며 사각형 꼭짓점이 시계 방향이 되어 sumo-gui가 안 그림(→ 반시계로 정렬).
- 기능 점검(새 net): 단위 테스트 15개 통과, CCTV 9곳 사고 생성·알림·재경로, 신양초 차량 감지 → 보행자 출현 → 우회(A 대신 D),
  가짜 하드웨어 송신기 4개 시나리오(A/B/D, 보행자, B 우회), 대시보드 카메라 이동, `run_gui_preview.py` 모두 정상.
- 되돌리기: `experiment_data/backup_before_network_rebuild_2026-09-29/`(net, cctv/school zones, 대시보드·seed 경로,
  hardware_twin.json, cctv_detector.py).

### Z. 대시보드 재생 속도 = 실제 시간 (2026-09-29)

전에는 스텝 사이 고정 0.05초 지연이라 계산 속도에 따라 실제의 3~10배로 흘러 차가 비현실적으로 빨라 보였음.
`scripts/dashboard_server.py`가 이제 기본으로 시뮬레이션 1초(1스텝)를 실제 1초에 맞춘다(스텝 계산 시간을 빼고 남은
만큼만 대기 - 고정 딜레이 1000ms를 주면 계산 시간만큼 더 느려짐). 실측: 실제 20초 동안 시뮬레이션 20초. 빨리 보려면
환경변수 `DASHBOARD_SPEED=5`(5배속), `0`이면 최대 속도. 실물 하드웨어 연결 중엔 배속과 상관없이 실제 시간.
`scripts/run_gui_preview.py`도 같은 방식으로 바꿈: `--delay`(ms) 옵션 대신 `--speed`(기본 1 = 실제 시간, 0 = 최대 속도).
실측: 시뮬레이션 19초가 실제 20.0초.
주의: 1시간 시나리오(3600초)는 실제로 1시간 걸림.

### AA. 사고 20초마다 도로망 전역 + 차량·보행자 증가 (2026-09-29)

- **사고**: 예전엔 CCTV 9곳 안에서만 차량 수 비례 확률로 나서 드물었고, 알림 목록이 같은 사고를 매 스텝 반복해
  어디서 났는지 안 보였음. `core/cctv_detector.py`: `update_accidents()`가 20초(`RANDOM_ACCIDENT_INTERVAL`)마다
  도로망 전체에서 지금 차가 있는 차도(20m 이상, 어린이보호구역 제외) 하나에 사고(45초). 구역 밖 사고는
  `detect_road_accidents()`가 같은 alert(zone="road", zone_name=도로 이름)를 만들어 정지/우회 판단을 똑같이 받음.
  `reset_accidents()` 추가(측정 스크립트가 seed마다 호출).
- **대시보드**: 같은 알림은 60스텝 안에 한 번만 목록에 올림, 사고 알림에 도로 이름 + 클릭하면 sumo-gui 카메라가
  사고 위치로 이동(도로 id의 '#' 때문에 카메라 이동 요청이 깨지던 것도 인코딩으로 수정), 지도 사고 마커 8m → 25m.
  사고 목록(요약 카드)에도 도로 이름.
- **수요**: 차량 `-p 0.75`(4800대) → `-p 0.5`(7200대), 보행자 `-p 8`(450명) → `-p 4`(900명).
  `run_single_simulation.py`의 생성 조건을 바꾸고 대시보드(seed 42/43)와 seed 1~10 전부 새 도로망에서 새로 생성.
  옛 파일: `experiment_data/backup_before_demand_increase_2026-09-29/`.
- `.claude/launch.json`에 `sumo-dashboard-fast`(10배속) 추가 - 점검용.
- 측정(5 seed, 새 도로망, 4800대·사고 드묾 → 7200대+900명·사고 20초마다 - 두 변화가 섞인 값): 견인 13 → 98,
  도착 4215 → 5857, 그리드락 176 → 939초, 충돌 12 → 44, 만성정체 13894 → 46690초. 예전 도로망 4800대(견인 115,
  충돌 147)보다는 여전히 나음. 만성정체 상위는 여전히 아차산로·능동로·광나루로·왕십리로의 차로 1개 진입로.
- **사고 규칙 변경(같은 날 뒤)**: 30초마다 1건, 30초 지속(새 사고가 나면 이전 사고가 풀림 - 항상 1건).
  위치 = 도로 위 모든 차의 남은 경로에 가장 많이 들어 있는 도로(앞으로 가장 많은 차가 지나갈 도로), 최근 5건의
  사고 도로는 제외(안 그러면 같은 간선도로만 반복). 사고 추적 목록에 정지(사고 도로 위)·감속(1~2칸 전)·우회
  (3~5칸 전) 모두 표시 - `decision_policy`의 모든 명령에 `hazard_edge` 추가. 우회의 "전" 예상 도착은 원래 경로로
  가서 사고 해제까지 기다렸을 때 기준. **알려진 약점**: 사고가 간선도로에 나고 30초면 풀리므로, 우회가 기다리는
  것보다 늦는 경우가 꽤 있었음(예: 137초 → 227초) → **"기다리는 게 빠르면 원래 경로 유지" 추가(같은 날, 사용자 요청)**:
  `core/vehicle_controller._reroute_around()`가 우회 경로를 찾은 뒤, 원래 경로로 사고 도로까지 가서 사고 해제
  (`hazard_until` - cctv_detector alert → decision_policy reroute 명령으로 전달)까지 기다리는 예상 도착과 비교해
  빠르지 않으면 `setRoute`로 원래 경로 복귀, 사고가 끝날 때까지 그 차는 재계산 안 함. 예상 도착 계산은 도로당
  통행시간 300초 상한(멈춘 도로에서 SUMO 추정치가 수만 초로 튐). 10배속 확인: 우회한 18대 모두 대기보다 빠름(평균 13초,
  최대 25초 단축), 유지한 20대는 우회했으면 중앙값 33초 더 걸렸을 것. 사고 추적 목록에 "원래 경로 유지"(파랑) 표시.
- **네트워크 전체 효과 측정(5 seed, 새 사고 규칙, 판단 끔 vs 켬 - `SUMO_KEEP_ROUTE=0`으로 끔)**: 견인 128 → 145
  (켬이 나은 seed 2/5), 도착 5683 → 5714(4/5), 만성정체 61088 → 57188초(3/5), 그리드락 1213 → 1402초(2/5),
  충돌 60 → 57(2/5). **seed마다 방향이 갈려 전체 교통에 대한 효과는 판별 불가(노이즈 범위)** - 차 한 대 기준으로는
  확실히 이득(위 대시보드 확인)이지만 도시 전체 지표를 움직일 정도는 아님. 기본은 켜 둠.
  같은 조건 비교로 보면, 이전 측정(20초 간격·무작위 도로, 견인 98) 대비 악화의 대부분은 **사고를 가장 많이 지나갈
  도로(간선도로)에 내도록 바꾼 사고 규칙 탓**(판단 끈 상태도 견인 128).
- `measure_congestion.py`: 300스텝마다 진행 상황 출력, seed가 끝날 때마다 결과 저장. seed를 따로 동시에 돌리면
  빠름(seed 하나 SUMO 약 1.4GB 메모리): `--seeds N --out seedN.json`을 5개 동시에.

### AB. 파일 정리 (2026-09-29, 사용자 요청)

프로젝트 1.1GB → 약 218MB. **이 문서 위쪽에 나오는 백업 폴더·측정 자료는 대부분 이제 없다(되돌리기 불가).**
- 삭제: `experiment_data/backup_*` 7개(옛 도로망·옛 수요·밤샘 단계별 코드 백업 포함, 약 850MB),
  `junctionjoin_measure_2026-09-27/`, `congestion_after_mindur436832681.json`, `results_v2.csv`, `results_v3.csv`
  (코드가 안 읽음 - 수치는 이 문서 M·N번에 있음), `collisions_seed*_*.xml`(옛 실험 출력), 루트 `routes.rou.xml`·
  `viewsettings.xml`(부산물), 캐시, `docs/report_assets/intersection_audit_2026-09-29/`·`overnight_2026-09-28/`
  (되돌린 작업·옛 도로망 캡처), `network/pedestrian_style.xml`(`vehicle_style.xml`이 대신함).
- 삭제한 스크립트(되돌린 횡단보도 작업용): `add_missing_crossings.py`, `plan_crossing_fixes.py`, `fix_ped_green.py`,
  `unify_crossings.py`, `fix_tls_conflicts.py`(충돌표 해석이 틀렸던 검사기 - `tls_conflicts_traci.py`로 대체).
- `network/gwangjin.sumocfg`(sumo-gui로 바로 열 때)가 현재 배경·차량 그림을 쓰도록 수정.
- 코드: 안 쓰는 import·변수 정리(`hardware_twin.py`, `build_visual_assets.py`, `test_decision_policy.py`),
  `audit_intersections.py`에서 더는 안 쓰는 충돌표 파싱 제거(충돌은 `tls_conflicts_traci`로 판정), 사고 규칙 변경에
  맞춰 주석 갱신. 테스트 15개 통과, 감사 스크립트 실행 확인.
- 남긴 것: `experiment_data/results.csv`(대시보드 비교 페이지가 읽음), `routes_seed1~10`·`pedestrian_routes_seed1~10`
  (측정용 수요), `tls_set_nodes_2026-09-29.json`(netccfg 신호 목록 출처), `network/export*.osm`·`gwangjin.poly.xml`
  (재빌드·배경 생성 원본), `docs/`의 PDF·보고서·`Claude outputs/`.

### AC. 신양초 사거리 일반 차량 통행 금지 (2026-09-30, 사용자 요청)

신양초 사거리는 실물 보드를 비추는 곳이라 다른 차가 경로로 쓰지 않게 했다.
- `network/sinyang_closed.edg.xml`: 사거리 노드 `cluster_1830064526_997781280`에 붙은 차도 6개(`-172058984`,
  `-172058988#2`, `172058988#0`, `-172058988#0`, `-85960673#2`, `172058988#2`)의 차로를 `allow="custom1"`로.
  `gwangjin.netccfg`의 `edge-files`로 빌드 때 적용(OSM 변환 뒤·보도 추가 전에 들어가서 index 0 = 차도). 보도는 그대로.
  재빌드 결과 net은 이 차로·사거리 내부 차로 권한 외엔 바뀐 것 없음(diff 확인).
- 실물 연동 차종 `hwtwin_lead/follow/diverted`는 `vClass="custom1"`(`vehicle_style.xml`, `build_visual_assets.py`),
  vehicle_style이 없을 때 쓰는 `hwtwin`도 `hardware_twin.py`에서 custom1로 설정.
- 권한으로 막았으므로 randomTrips·duarouter·TraCI 재경로(중앙 서버·예측 우회·사고 우회) 모두 자동으로 피한다.
- `network/routes.xml`(7200대) 중 여기를 지나던 13대는 출발·도착을 사거리 밖 가장 가까운 edge로 바꿔 duarouter로
  다시 계산(버린 차 없음). 측정용 `experiment_data/routes_seed*.xml`은 지웠다 - 다음 측정 때 새 net으로 다시 생성됨.
- 확인: 900초 전체 제어 실행에서 일반 차량 진입 0대, A·B·D 경로 연동 차량 3대 모두 도착. 테스트 15개 통과.
  이전 측정값(AA번 등)은 이 변경 전 조건이다.
- 같이 고침: 대시보드 "차량 감지 시뮬레이션" 버튼(`cctv_detector.spawn_hardware_vehicle`)은 일반 차종으로 신양초
  진입로에 차를 넣었어서 막힌 뒤로 경로를 못 찾게 됐다 - `HARDWARE_VTYPE = "hwtwin_follow"`(custom1)로 넣게 바꿈.

### AD. 보드에서 나온 RC카가 SUMO에서 계속 주행 (2026-09-30, 사용자 요청)

"신양초 사거리에서 벗어나도 중앙 제어 알고리즘의 영향을 받으며 계속 주행 - 시뮬레이션의 일부라는 느낌으로".
- 전에는 보드 차가 도착하면(`arrived`) SUMO 차(`hwtwin_…`)를 지웠다. 이제 `HardwareTwin._release()`가 그 차를 지우고
  같은 자리·같은 그림(차종 `hwtwin_lead/follow/diverted`)으로 새 일반 차량 `rc_{vehicle_id}_{n}`을 넣는다.
  ID가 `hwtwin_`로 시작하지 않으므로 `is_hardware_twin()` 필터에 안 걸려 중앙 경로 재계산·사고 대응·선제 우회·견인을
  다른 차와 똑같이 받는다. 목적지는 도로망 전체에서 무작위(1.5km 이상 떨어진 곳 우선, 전역 random은 안 건드림).
- 도착 신호 없이 인식이 끊겨도(`forget_after_s`) 사거리를 이미 지났으면 넘기고, 진입로에서 끊겼으면 예전처럼 지운다.
- 도착 처리 때 `car["kind"]`도 비워, 다음 판에 같은 갈래로 다시 나타나면 보드 차를 새로 만든다(예전엔 지운 뒤 같은
  갈래로 다시 오면 차가 안 생기던 문제가 있었다).
- 대시보드 신양초 카드: "보드 도착 → SUMO에서 계속 주행 (rc_…)". `status()`에 `released_as`, `released` 추가.
- 확인(가짜 송신기 `--lead A --follow B`, 7200대 + 전체 제어, 헤드리스): rc 차 2대 모두 넘겨져 최고 28~30m/s로
  주행, 선행 차는 중앙 제어로 경로 2번 갱신, 둘 다 목적지 도착(순간이동 없음). 테스트 15개 통과.

### AE. 사거리 상세 창을 사고 추적 창과 같은 모양으로 (2026-09-30, 사용자 요청)

- 사거리(구역) 카드를 누르면 뜨는 창: 제목 = 구역 이름 + 도는 표시 + "화면 안 차량 N대 · 사고 · 실물 보드 연결".
  표 = 차량 ID / 현재 도로 / 적용 알고리즘(배지+설명, 마우스 올리면 알고리즘 설명) / 예상 도착(전 → 후).
  최근 제어를 받은 차가 위. 사고 추적 창과 같은 줄 함수(`controlRowCells`)를 쓴다.
- 카메라 폭: 구역 250m·신양초 110m → 둘 다 사고 추적과 같은 200m.
- 창에 나오는 차: CCTV 구역 도로(8~10개, 수십 m)만 세면 0~1대라 창이 비어서, 200m 화면 안의 차도 전부
  (`_zone_view_edges`, 시작 때 sumolib로 계산). 카드의 차량 수는 예전처럼 CCTV 구역 도로 기준.
- 적용 알고리즘 판정(`dashboard_server._control_row`, 우선순위 순):
  실물 차(`hwtwin_`, RC카 제어기가 보낸 event 라벨) > 진행 중인 사고 대응(정지·감속·우회·유지, `accident_reroutes`) >
  60초 안의 경로 변경(`vehicle_control` - 선제 우회 `PredictiveRerouter.route_changes`, 실시간 재계산
  `CentralServer.route_changes`, 바뀌기 전/후 경로의 예상 도착을 그때 계산) > 앞 신호(120m 안)가 30초 안에 조정됨
  (`SignalController.recent_adjust` - 연장/조기 전환) > 평소("실시간 경로 재계산 · 지금 경로가 최단 · N초 전 확인").
  `route_changes` 기록은 재계산 앞뒤로 경로를 더 읽어야 해서 `record_changes=True`(대시보드)일 때만 한다 - 측정은 그대로.
- 같이 고침: 보드 보행자 사고(`-85960673#2`)가 그 도로 위 모든 차를 세워, 보행자 지점(10m)을 이미 지난 차(보드에서
  넘어온 rc_ 차 등)까지 멈춰 있었다 → `HARDWARE_PEDESTRIAN_OFFSET_M`+2m 안의 차만 "사고 도로 위"로 센다.
  보행자 사고는 해제 시각이 없어(아주 큰 값) 예상 도착이 1,000,185s처럼 나오던 것 → "보행자 통과 후".
- 실물 차 판단 표시: 팀원 저장소(invuc02/capstone-sumo-bridge)의 `sumo_patches/2026-09-29_hardware-event-display.patch`를
  사용자 허락을 받아 적용(겹친 3곳은 손으로 맞춤). 차량 호스트가 보내는 `event` 코드(pedestrian_stop, divert_wait,
  reverse, diverting 등)를 `EVENT_LABELS`로 한국어로 바꿔 신양초 카드·구역 상세 창("실물 · 보행자 앞 정지선 정지")에 보이고,
  정지선 정지·우회 준비·후진·우회로 바뀌는 순간을 "실물 판단" 알림으로 올린다. fake_hardware_sender도 event를 보낸다.

## 정식 실험 결과 — 현재 상태

**가장 최신/신뢰할 수 있는 결과는 위 N-5번의 `experiment_data/results_v3.csv`**(seed 1~10,
random.seed 버그까지 고친 뒤 재실험, 2026-09-16). `results.csv`도 이 파일과 동일하게
갱신해둠(대시보드가 읽는 파일). **통계적으로도 실질적으로도 유의미한 개선을 아직 못 찾았고,
이제 두 번(v2, v3) 다른 조건에서 같은 결론이 나왔으므로 우연이 아닐 가능성이 높다.** 이
문제를 어떻게 풀지는 여전히 열려있는 질문 — predictive_reroute의 트레이드오프(N-2번)를
받아들이고 "정체 완화" 쪽으로 지표/서술 방향을 재정의하거나, 알고리즘 자체를 더 손보거나
선택이 필요함. `results_v2.csv`(N번 조사 전, random.seed 버그 있던 상태)와 그 이전
`results_final_tow.csv`(2026-08-10, n=3)는 전부 낡은 데이터이니 참고만 하고 새로 인용하지 말 것.

**주의(겪은 문제)**: bash 도구가 보여주는 PID와 실제 Windows PID가 다르게 매핑되는 경우가
있어서, `kill -9 <bash가 보여준 PID>`로 sumo-gui 등을 죽였다고 생각해도 실제로는 안 죽고
백그라운드에서 계속 CPU를 먹는 좀비가 될 수 있다. 확실하게 죽이려면 PowerShell
`Get-Process`로 실제 PID를 확인하고 `Stop-Process -Id <PID> -Force`를 쓸 것.

## 이 기기에서 새로 확인해야 할 것

- `SUMO_HOME` 환경변수, Python 패키지(`traci`, `sumolib`, `pandas`, `scipy`, `flask`,
  `flask-socketio`, `pyproj`, `pytest`, `pdfplumber`) 설치 여부 확인.
- Bash/PowerShell 새 프로세스가 방금 설정한 환경변수를 못 읽는 경우가 있음(Windows 특성) —
  매 명령마다 `$env:SUMO_HOME`을 직접 지정해서 실행하는 게 안전함.

## 알아두면 좋은 함정들 (이미 겪었던 실수, 반복하지 말 것)

- `sumolib`의 `getFunction()`은 이 SUMO 버전(1.27.x)에서 일반 edge에 `"normal"`이 아니라
  빈 문자열을 반환함.
- net.xml 검증 시 `function="crossing"`, `type="highway.footway"`로 검색할 것 (다른 패턴은
  오탐 발생).
- 균일 랜덤 수요(randomTrips)에서는 특정 몇 개 edge만으로 병목을 측정하면 대부분 0이 나옴 —
  네트워크 전체 차량 대기시간으로 측정해야 의미 있는 값이 나옴.
- Windows 콘솔 기본 코드페이지(cp949)는 em dash(—) 등 일부 유니코드 문자를 인코딩 못 해
  `print()` 한 줄이 스크립트를 죽일 수 있음 — 콘솔에 출력하는 스크립트는 시작 부분에
  `sys.stdout.reconfigure(encoding="utf-8")`를 넣을 것(`live_demo_controller.py` 참고).
- `run_single_simulation.py`/`dashboard_server.py`는 각자 독립적으로 TraCI 세션을 띄운다 —
  둘을 동시에 실행하면 CPU를 두 배로 쓰니, 대시보드 브라우저 미리보기를 테스트할 때
  배치 실험과 동시에 띄우지 않는 게 안전함(느려질 뿐 죽지는 않음).
- `dashboard_server.py`는 `Flask(__name__, template_folder="dashboard/templates",
  static_folder="dashboard/static")`처럼 폴더를 명시해야 함 — 기본값은 루트의 `templates/`를
  찾아서 404가 남.
- **`randomTrips.py`를 여러 seed로 동시(병렬) 실행하지 말 것.** `--validate`(기본 True)가
  내부적으로 duarouter 검증 패스를 한 번 더 도는데, 이때 출력 파일명을 `--route-file`로
  명시하지 않으면 고정된 `routes.rou.xml`을 CWD에 써서 병렬 프로세스끼리 충돌한다.
  그렇다고 `--route-file`로 이름을 분리하면(직관적인 우회책처럼 보이지만) randomTrips.py의
  재시도 로직이 왜인지 훨씬 일찍 포기해서 4800대 요청에 250대 안팎만 생성한다(원인 미상,
  2026-09-09 실측). **올바른 해결책: demand 생성(`ensure_demand`/`ensure_pedestrian_demand`)
  단계만 순차로 먼저 다 끝내두고, 캐시가 준비된 뒤에 무거운 시뮬레이션 단계만 병렬로 돌릴 것.**
- 배치 실험을 백그라운드로 돌리는 도중 세션(터미널/에이전트 프로세스)이 끊기면 그 아래
  자식 프로세스(python/sumo)도 전부 같이 죽는다(Windows 프로세스 트리 특성) — 재개할 때는
  각 seed의 결과 CSV를 열어서 baseline/treatment 중 어디까지 실제로 끝났는지 확인하고,
  끝난 부분은 건너뛰고 이어서 돌릴 것(전체 재시작 X). baseline은 `poll_all_zones()`를
  아예 안 부르므로 재현성 문제가 없다(항상 완전히 동일한 값) — treatment만 확인하면 됨.
- **정체/그리드락 계측 스크립트엔 반드시 `random.seed(seed)`를 SUMO `--seed`와 같은 값으로
  넣을 것.** `cctv_detector.py`의 사고 발생이 Python 표준 `random`을 쓰는데, 이건 SUMO
  `--seed`와 완전히 별개 상태라 스크립트에 직접 안 넣으면 매 실행마다 사고가 다르게 나서
  "이전/이후" 비교 자체가 성립하지 않는다(2026-09-25, O번에서 이걸 놓쳐서 "악화됐다"고
  잘못 결론 내렸다가 재검증으로 뒤집음 - `run_single_simulation.py`엔 이미 고쳐져 있지만
  임시로 짜는 계측 스크립트마다 매번 직접 넣어야 함). 한 번의 seed로도 부족하다 - 최소
  5개 seed로 평균 내서 비교할 것(O번 E항목 참고, seed별 편차가 꽤 크다).
- **net.xml이나 신호 프로그램을 바꾸기 전엔 반드시 현재 파일을 백업해둘 것.** "고치기 전"
  상태를 못 남겨두면 나중에 "정말 개선됐는지" 영영 증명할 수 없게 된다(2026-09-25, O번의
  13개 신호 추가 - 5개는 이전 세션에서 이미 적용된 채로 물려받았고 백업을 안 남겨서 그
  전/후 비교가 불가능해짐). `experiment_data/` 등 세션이 끝나도 남는 위치에 저장할 것 -
  스크래치패드(`C:\Users\song0\AppData\Local\Temp\claude\...`)는 세션 종료 시 사라진다.
  (2026-09-25~27의 net 백업들 - before_E / before_tlsjoin / before_yellow / before_junctionjoin /
  before_round3 - 은 2026-09-28 사용자 요청으로 모두 삭제함. 그 이전 상태로는 이제 못 되돌린다.)

## 참고 문서

- **차량 쪽 저장소 `invuc02/capstone-sumo-bridge`의 `INTERFACE.md`**: traffic_state(차량→SUMO) 규격의
  기준 문서(9/26부터 한 방향 - decisions는 `decision-message-format` 브랜치에만). P·R번 참고.
- `OVERNIGHT_BRIEFING_2026-09-28.md`: R번 작업의 단계별 브리핑·되돌리는 법·전후 비교 그림 위치.
- `SUMO_LIVE_DEMO_HANDOFF.md`: SUMO 쪽 구현 요약 - 매핑표, 우회 판단 규칙, 설정값, hold/TTL
  타임라인, 테스트 실행법. 3~5절은 2026-09-26에 새 형식으로 고침(1~2절, 6절 이후는 예전 그대로).
- `HARDWARE_CALIBRATION_REQUEST.md`: 2026-09-09 좌표 실측 요청서였으나 2026-09-26에 전부
  해결됨 - 무엇이 어떻게 해결됐는지 요약만 남김.
- `cctv_zones.json`: 데이터 기반 선정된 CCTV 9곳의 edge ID·연결도·실측 통행량(발표 자료용).

## 요청

**경진대회 예선(서면평가)은 2026-08-10 13:00에 이미 제출 완료됐다** — 지금은 본선(운영기간
~12월) 준비 단계다. 위 N번 상태를 이해했다는 전제로 이어서 진행해줘.

**하드웨어 방향이 2026-09-09 팀 회의로 3단계 순차 구조로 확정됨** (SUMO 프로젝트 외부,
`C:\Users\song0\Downloads\capstone\capstone`의 YOLO/하드웨어 코드베이스 쪽 — 이 SUMO
프로젝트에서 직접 손댈 영역은 아니지만 연동 스펙이 맞물려 있으니 알고 있을 것):
1단계(현재 집중, 임계 경로) = ArUco 차량 인식(소재 확인 필요) + 호모그래피 캘리브레이션 +
경로 추종 제어 + ESP32 명령 인터페이스, "SUMO 없이 RC카가 도로 이탈 없이 목적지 도달"이
완료 기준. 2단계 = SUMO→제어SW 경로 전달(UDP 9001/9002 스키마 확장) + danger_zone 실측.
3단계 = 웨이포인트 + `traci.vehicle.moveTo()` 기반 위치 동기화(차량 재생성 금지, 안전판단은
연속 유지). **YOLO(보행자 감지)는 1단계의 임계 경로가 아님** — ArUco/좌표변환만 있으면 됨,
YOLO는 시연 시나리오 단계에서 필요. YOLO 쪽엔 별도로 알려진 문제 있음(참고만): `best.pt`
검증셋이 학습 영상에서 0.4초 간격으로 뽑은 근접중복 프레임이라 recall 1.000이 과대평가일
가능성 높음(별도 영상으로 test set 새로 만들 것), 좌표를 SUMO로 보내는 UDP 송신 코드 자체가
아직 없음(`live_demo_controller.py`가 기다리는 `vision/main.py`가 존재하지 않음).

시뮬레이션 트랙(이 프로젝트) 우선순위:
(1) N번 결론(predictive_reroute 트레이드오프, 통계적 유의성 여전히 없음)을 어떻게 다룰지는
아직 열린 질문 — 사용자가 방향(지표 재정의/알고리즘 추가 개선/현재 결과 그대로 서술)을
정하기 전에 먼저 나서서 큰 구조를 바꾸지 말 것. 다만 소규모 검증(소거 실험, 계측 조사 등)은
이미 여러 번 승인받은 패턴이라 필요하면 이어가도 됨.
(2) 본선 자료 작성 시 `docs/report_assets/`(구조도·핵심 코드 요약·비교표)를 소스로 쓰되,
그 안의 숫자(TSTT -3.1% 등)는 M/N번에서 무효화됐으므로 최신 결론(N-5번, 유의미한 개선
없음)을 반영해서 새로 쓸 것 — 방법론/구조 설명은 그대로 활용 가능.
(3) 급제동 지표를 비교표에 포함하고, 견인차 로직을 각주로 명시하는 것을 본선 자료 작성 시
검토(예선 때는 사용자 지시로 생략했었음, L번 참고).
(4) 하드웨어 연동은 R번 상태 - 차량 → SUMO 한 방향, 대시보드가 신양초 사거리에 그린다.
팀원이 C→D 등 경로를 올리면 `configs/hardware_twin.json`의 D 좌표를 맞출 것(지금은 추정값).
`live_demo_controller.py`(SUMO→차량 판단 전송)와 그 테스트·설정은 2026-09-28에 삭제함.
(5) 사용자가 별도로 지시하는 작업. 시작 전에 각 파일이 실제로 폴더에 있는지, 지난 세션에서
뭐가 검증됐고 뭐가 아직 사용자 확인 대기 중인지 먼저 확인하고 진행할 것.
