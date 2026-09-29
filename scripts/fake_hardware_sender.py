"""실물 하드웨어 없이 시연 시나리오를 흉내 내 traffic_state를 UDP로 보낸다.

팀원 저장소(invuc02/capstone-sumo-bridge)의 replay.py는 실제 주행 기록 6장면을 순서대로
쏘는 것이라 위치가 뚝뚝 끊긴다. 이 스크립트는 시연 흐름 전체를 초당 10번 부드럽게
만들어서, 대시보드(신양초 사거리 실물 연동)를 하드웨어 없이 리허설할 수 있게 한다.
메시지 모양은 INTERFACE.md의 traffic_state 그대로다(차량 판단도 차량 쪽 규칙을 흉내 냄:
보행자 앞 정지선 정지, 앞차 간격 정지, 막힌 후행차의 후진 후 B 우회).

    python scripts/fake_hardware_sender.py                      선행·후행 C→A, 보행자 있음
    python scripts/fake_hardware_sender.py --lead A --follow B --no-pedestrian
    python scripts/fake_hardware_sender.py --loop                끝나면 다시 시작
"""

import argparse
import json
import math
import os
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "core"))

from hardware_twin import load_config, point_at, polyline_length, project_to_polyline  # noqa: E402

HZ = 10
CAR_SPEED = 0.13            # m/s, 샘플 speed_mps(선회 중 0.1 안팎)보다 조금 빠르게 - 선행이 LED 앞에서 5초쯤 서도록
LED_SPEED = 0.034           # m/s, INTERFACE.md 실측
LED_X, LED_Y0, LED_Y1 = 0.30, 0.13, 0.91
LED_LEAD_TIME = 6.0         # s, "LED를 켜고 약 6초 뒤 출발"
ROAD_Y = (0.367, 0.652)     # A 도로 폭
STOP_LINE_X = 0.35          # LED 선 앞 정지선(앞범퍼가 선에서 약 5cm)
GAP_STOP = 0.50             # m, 이보다 가까우면 후행이 선다(실측 샘플 02: gap=0.53m에서 정지)
DIVERT_AFTER = 3.0          # s, 이만큼 막혀 있으면 후행이 우회
REVERSE_DIST = 0.12         # m, 우회 전 후진 거리
DEST_ZONE = {"A": "A_stop", "B": "B_stop_710", "D": "D_stop"}


def _heading(path, s):
    """보드 좌표계 기준 진행 방향(+x 기준 반시계, 도) - INTERFACE.md의 heading_deg."""
    x0, y0, _ = point_at(path, max(0.0, s - 0.01))
    x1, y1, _ = point_at(path, s + 0.01)
    return math.degrees(math.atan2(y1 - y0, x1 - x0))


class Car:
    def __init__(self, vid, marker, role, dest, path, s0):
        self.vid, self.marker, self.role, self.dest = vid, marker, role, dest
        self.path, self.s = path, s0
        self.route_id = f"{role}_C_to_{dest}+entry"
        self.dest_zone = DEST_ZONE[dest]
        self.command, self.reason = "S", "waiting for start"
        self.arrived = False
        self.blocked_since = None
        self.reverse_left = 0.0

    def xy(self):
        x, y, _ = point_at(self.path, self.s)
        return x, y

    def payload(self):
        x, y = self.xy()
        moving = self.command in ("F", "L", "R", "B")
        speed = CAR_SPEED if moving else 0.0
        return {
            "vehicle_id": self.vid, "marker_id": self.marker, "visible": True,
            "command": self.command, "reason": self.reason,
            "speed_pwm": 50 if moving else 0, "steering_percent": 0,
            "route_id": self.route_id, "start_zone": f"C_{'lead' if self.role == 'lead' else 'follower'}_start",
            "destination_zone": self.dest_zone, "start_delay_seconds": 0.0, "arrived": self.arrived,
            "x": round(x, 4), "y": round(y, 4), "heading_deg": round(_heading(self.path, self.s), 2),
            "moving": moving, "speed_mps": speed,
            "forward_speed_mps": -speed if self.command == "B" else speed,
        }


def scenario(lead_dest, follow_dest, pedestrian, cfg):
    """(경과 시간, traffic_state dict)를 0.1초마다 내는 제너레이터."""
    paths = cfg["board_paths"]
    lead = Car("car_2", 22, "lead", lead_dest, paths[lead_dest], 0.25)
    follow = Car("car_3", 222, "follow", follow_dest, paths[follow_dest], 0.0)
    cars = [lead, follow]
    depart = LED_LEAD_TIME if pedestrian else 1.0
    dt = 1.0 / HZ
    t = 0.0
    done_at = None
    while True:
        led_y = LED_Y0 + LED_SPEED * t if pedestrian else None
        led_on = led_y is not None and led_y <= LED_Y1
        hazards = []
        if led_on:
            hazards.append({"hazard_id": "hazard_1", "class_name": "pedestrian", "hazard_type": "person",
                            "active": True, "x": LED_X, "y": round(led_y, 3), "confidence": 0.68})
        if t >= depart:
            for car in cars:
                _advance(car, cars, led_on, led_y, dt, t, paths)
        state = "WAITING" if t < depart else "RUNNING"
        if all(c.arrived for c in cars):
            state = "DONE"
            done_at = done_at if done_at is not None else t
        yield t, {"type": "traffic_state", "timestamp_ms": int(time.time() * 1000), "coordinate_space": "world",
                  "vehicles": [c.payload() for c in cars], "hazards": hazards, "scenario_state": state}
        if done_at is not None and t - done_at > 3.0:
            return
        t += dt


def _advance(car, cars, led_on, led_y, dt, t, paths):
    if car.arrived:
        return
    step = CAR_SPEED * dt
    end = polyline_length(car.path)
    if car.reverse_left > 0:  # 우회 전 후진
        car.s = max(0.0, car.s - step)
        car.reverse_left -= step
        car.command, car.reason = "B", "reversing to make an angle for detour"
        if car.reverse_left <= 0:
            x, y = car.xy()
            car.path = paths["B_divert"]
            car.s = project_to_polyline(car.path, (x, y))
            car.route_id, car.dest_zone, car.dest = "divert_to_B_x710", "B_stop_710", "B"
        return
    x, y = car.xy()
    # 앞차 간격
    ahead = [c for c in cars if c is not car and not c.arrived]
    for other in ahead:
        ox, oy = other.xy()
        gap = math.dist((x, y), (ox, oy))
        nx, ny, _ = point_at(car.path, car.s + 0.05)
        closing = math.dist((nx, ny), (ox, oy)) < gap
        if gap < GAP_STOP and closing:
            car.command, car.reason = "S", f"vehicle proximity stop: ahead={other.vid} gap={gap:.2f}m"
            # 앞차도 서 있을 때만 "막혔다"고 센다 - 같이 달리며 간격만 좁혀진 건 막힌 게 아니다
            if other.command == "S":
                car.blocked_since = car.blocked_since if car.blocked_since is not None else t
            else:
                car.blocked_since = None
            if (car.role == "follow" and car.dest == "A" and led_on and car.blocked_since is not None
                    and t - car.blocked_since > DIVERT_AFTER):
                car.reverse_left = REVERSE_DIST
                car.blocked_since = None
            return
    # 보행자: A로 가는 차는 LED가 도로 근처에 있는 동안 정지선에서 선다
    if car.dest == "A" and led_on and ROAD_Y[0] - 0.08 <= led_y <= ROAD_Y[1] + 0.02:
        stop_s = project_to_polyline(car.path, (STOP_LINE_X, 0.47))
        if car.s <= stop_s + 1e-9:  # 정지선에 닿았으면 LED가 도로를 벗어날 때까지 그대로 선다
            car.blocked_since = None
            car.s = min(car.s + step, stop_s)
            creeping = car.s < stop_s
            car.command = "F" if creeping else "S"
            car.reason = ("pedestrian ahead: creeping to stop line" if creeping
                          else "pedestrian ahead: holding at stop line")
            return
    car.blocked_since = None
    car.s = min(car.s + step, end)
    h0, h1 = _heading(car.path, car.s - 0.03), _heading(car.path, car.s + 0.03)
    turn = (h1 - h0 + 180) % 360 - 180
    car.command = "L" if turn > 2 else ("R" if turn < -2 else "F")
    car.reason = "local scenario: following path"
    if car.s >= end - 1e-6:
        car.arrived, car.command, car.reason = True, "S", "arrived"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--lead", choices=["A", "B", "D"], default="A")
    parser.add_argument("--follow", choices=["A", "B", "D"], default="A")
    parser.add_argument("--no-pedestrian", action="store_true")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9002)
    parser.add_argument("--loop", action="store_true", help="끝나면 처음부터 다시 보낸다")
    parser.add_argument("--speedup", type=float, default=1.0, help="시간을 몇 배 빠르게 흘릴지(점검용)")
    args = parser.parse_args()

    cfg = load_config()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"{args.host}:{args.port}로 전송 - 선행 C→{args.lead}, 후행 C→{args.follow}, "
          f"보행자 {'없음' if args.no_pedestrian else '있음'}. Ctrl+C로 종료.")
    try:
        while True:
            last_line = None
            for t, msg in scenario(args.lead, args.follow, not args.no_pedestrian, cfg):
                sock.sendto(json.dumps(msg, ensure_ascii=False).encode("utf-8"), (args.host, args.port))
                line = " | ".join(f"{v['vehicle_id']} {v['command']} {v['route_id']} ({v['x']:.2f},{v['y']:.2f})"
                                  for v in msg["vehicles"])
                if msg["hazards"]:
                    line += f" | 보행자 y={msg['hazards'][0]['y']:.2f}"
                if int(t * HZ) % HZ == 0 and line != last_line:
                    print(f"{t:5.1f}s {msg['scenario_state']:7s} {line}")
                    last_line = line
                time.sleep(1.0 / HZ / args.speedup)
            if not args.loop:
                break
            time.sleep(2.0)
    except KeyboardInterrupt:
        print("\n종료")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
