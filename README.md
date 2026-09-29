# SUMO_project — V2N 중앙 제어 교통 최적화 시뮬레이션

광진구 실제 도로망(OpenStreetMap)을 SUMO로 옮겨, CCTV·차량 연결(V2N)로 사고를 감지하고 중앙 서버가 차량 경로·신호를
제어해 정체를 줄이는 시뮬레이션과 실시간 모니터링 대시보드입니다. 신양초 어린이보호구역 사거리는 실물 RC카 시연 보드와
연동됩니다.

- 차량 ↔ SUMO 연동 규격과 하드웨어 없이 쓰는 개발 도구: [invuc02/capstone-sumo-bridge](https://github.com/invuc02/capstone-sumo-bridge)
- 작업 기록·설계 결정·시행착오 전체: [`docs/HANDOFF_PROMPT.md`](docs/HANDOFF_PROMPT.md)

## 폴더 구조

```
core/            시뮬레이션 안에서 도는 중앙 제어 로직
  cctv_detector.py        CCTV 9곳·어린이보호구역·도로망 전역 사고 감지, 자동 사고 발생
  decision_policy.py      위험별 정지/감속/우회 판단 (TraCI 없이 재사용 가능)
  vehicle_controller.py   판단 실행, "기다리는 게 빠르면 원래 경로 유지"
  central_server.py       출발·60초마다 실시간 통행시간 기준 경로 재계산
  predictive_reroute.py   90초 뒤 넘칠 도로를 예측해 선제 우회(몰림 분산 포함)
  signal_controller.py    대기열 비교 기반 신호 시간 배분
  stuck_vehicle_remover.py 180초 넘게 낀 차 견인
  hardware_twin.py        실물 보드(UDP 9002) 상황을 신양초 사거리에 그대로 그림
  gui_viewport.py         sumo-gui 화면(색·확대·시작 위치)
  analysis.py             baseline/treatment 실험 비교
scripts/         실행·측정·빌드 도구
  dashboard_server.py     웹 대시보드 + sumo-gui (http://localhost:5000)
  run_gui_preview.py      발표용 sumo-gui 미리보기
  measure_congestion.py   견인·그리드락·만성정체·충돌·도착 측정 (seed별)
  run_experiments.py / run_single_simulation.py  baseline vs treatment 반복 실험, 수요 생성
  fake_hardware_sender.py 실물 보드 없이 UDP로 시연 시나리오 송신
  build_styled_polys.py / build_visual_assets.py 지도 배경·차량/보행자 그림 생성
  find_cctv_zones.py      CCTV 구역 선정
  audit_intersections.py / tls_conflicts_traci.py 사거리·신호 점검
dashboard/       웹 화면 (templates, static)
network/         도로망 빌드 설정·원본 지도·배경·구역 정의·대시보드용 수요
configs/         실물 보드 연동 설정 (hardware_twin.json)
experiment_data/ 실험 결과(results.csv), 신호 지정 목록
tests/           단위 테스트
docs/            작업 기록·보고서 자료
```

## 준비

1. [SUMO 1.27.1](https://sumo.dlr.de/docs/Downloads.php) 설치 후 `SUMO_HOME` 환경변수 설정
2. `pip install -r requirements.txt`
3. **도로망 만들기** — `network/gwangjin.net.xml`(112MB)은 GitHub 파일 크기 제한 때문에 저장소에 없습니다.
   OSM 원본(`network/export.osm`)과 빌드 설정으로 몇 초 만에 다시 만듭니다:

   ```bash
   cd network
   netconvert -c gwangjin.netccfg
   ```

   설정 내용(교차점 합치기, 보도·횡단보도, 신양초 일방통행, 신호 지정, 좌표 기준점)은 `gwangjin.netccfg` 주석 참고.

## 실행

```bash
python scripts/dashboard_server.py          # 대시보드 + sumo-gui, 브라우저로 http://localhost:5000
```

Windows에서는 `start_dashboard.bat`을 실행해도 됩니다. 기본은 실제 시간(시뮬레이션 1초 = 실제 1초)이고,
`DASHBOARD_SPEED=5`처럼 배속을 줄 수 있습니다.

```bash
python scripts/fake_hardware_sender.py --lead A --follow B   # 실물 보드 없이 신양초 연동 시연
python scripts/measure_congestion.py --seeds 1 --out seed1.json  # 정체 측정 (수요가 없으면 먼저 생성됨)
python -m pytest -q tests
```

실험용 seed별 수요(`experiment_data/routes_seed*.xml`)도 용량 때문에 저장소에 없고, 처음 실행할 때
`scripts/run_single_simulation.py`의 생성 조건(차량 `-p 0.5` 시간당 7200대, 보행자 `-p 4` 약 900명)으로 만들어집니다.
