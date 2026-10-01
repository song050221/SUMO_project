"""baseline(중앙 제어 없음) vs treatment(중앙 제어 켬)를 seed 범위만큼 돌려 experiment_data/results.csv에 모은다.

    python scripts/run_experiments.py --start-seed 1 --end-seed 10 --workers 3

--workers가 2 이상이면 여러 실행을 동시에 돌린다(SUMO 한 실행에 메모리 약 3GB - PC 메모리에 맞출 것). 이때
수요 파일 생성(randomTrips)은 동시에 하면 서로 충돌하므로 먼저 순서대로 다 만들어 두고(HANDOFF "알아두면 좋은
함정들"), 실행마다 따로 CSV를 쓴 뒤 끝나면 합친다(같은 파일에 동시에 쓰지 않게).
"""

import argparse
import csv
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

RESULTS_FILE = "experiment_data/results.csv"
RUN_DIR = "experiment_data/runs"


def _run_one(seed, mode):
    out = os.path.join(RUN_DIR, f"seed{seed}_{mode}.csv")
    log = os.path.join(RUN_DIR, f"seed{seed}_{mode}.log")
    if os.path.exists(out):
        return out  # 이미 끝난 실행은 건너뛴다 - 중간에 멈췄다가 다시 돌릴 때
    with open(log, "w", encoding="utf-8") as f:
        subprocess.run([sys.executable, "scripts/run_single_simulation.py", "--seed", str(seed), "--mode", mode,
                        "--out", out + ".part"], check=True, stdout=f, stderr=subprocess.STDOUT)
    os.replace(out + ".part", out)
    print(f"끝: seed={seed} mode={mode}", flush=True)
    return out


def _merge(outs):
    rows = []
    for path in outs:
        with open(path, encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    rows.sort(key=lambda r: (int(r["seed"]), r["mode"]))
    with open(RESULTS_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-seed", type=int, default=1)
    parser.add_argument("--end-seed", type=int, default=20)
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    seeds = range(args.start_seed, args.end_seed + 1)

    from run_single_simulation import ensure_demand, ensure_pedestrian_demand
    for seed in seeds:
        ensure_demand(seed)
        ensure_pedestrian_demand(seed)
    print("수요 준비 완료", flush=True)

    os.makedirs(RUN_DIR, exist_ok=True)
    jobs = [(seed, mode) for seed in seeds for mode in ("baseline", "treatment")]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        outs = list(pool.map(lambda job: _run_one(*job), jobs))
    _merge(outs)
    print(f"전부 끝 - {RESULTS_FILE}", flush=True)
