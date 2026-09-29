import argparse
import subprocess

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start-seed", type=int, default=1)
    parser.add_argument("--end-seed", type=int, default=20)
    args = parser.parse_args()

    for seed in range(args.start_seed, args.end_seed + 1):
        for mode in ["baseline", "treatment"]:
            print(f"=== seed={seed} mode={mode} ===")
            subprocess.run(
                ["python", "scripts/run_single_simulation.py", "--seed", str(seed), "--mode", mode],
                check=True,
            )
