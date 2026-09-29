import pandas as pd
from scipy import stats

METRICS = [
    "avg_travel_time",
    "total_wait_time",
    "collision_count",
    "emergency_brake_count",
    "throughput",
]

METRIC_LABELS = {
    "avg_travel_time": "평균 이동시간(s)",
    "total_wait_time": "누적 대기시간(s)",
    "collision_count": "충돌 횟수",
    "emergency_brake_count": "급제동 횟수",
    "throughput": "처리량(도착 차량 수)",
}


def compare_metric(df, metric_name):
    baseline_vals = df[df["mode"] == "baseline"][metric_name]
    treatment_vals = df[df["mode"] == "treatment"][metric_name]

    t_stat, t_p = stats.ttest_ind(baseline_vals, treatment_vals)
    try:
        u_stat, u_p = stats.mannwhitneyu(baseline_vals, treatment_vals)
    except ValueError:
        u_stat, u_p = float("nan"), float("nan")

    return {
        "metric": metric_name,
        "label": METRIC_LABELS.get(metric_name, metric_name),
        "baseline_mean": baseline_vals.mean(),
        "baseline_std": baseline_vals.std(),
        "baseline_values": baseline_vals.tolist(),
        "treatment_mean": treatment_vals.mean(),
        "treatment_std": treatment_vals.std(),
        "treatment_values": treatment_vals.tolist(),
        "t_stat": t_stat,
        "t_p": t_p,
        "u_stat": u_stat,
        "u_p": u_p,
        "significant": bool(t_p < 0.05),
    }


def compute_comparison(results_file="experiment_data/results.csv"):
    df = pd.read_csv(results_file)
    baseline = df[df["mode"] == "baseline"]
    treatment = df[df["mode"] == "treatment"]
    return {
        "n_baseline": len(baseline),
        "n_treatment": len(treatment),
        "metrics": [compare_metric(df, m) for m in METRICS],
    }


def main():
    result = compute_comparison()
    print(f"baseline n={result['n_baseline']}, treatment n={result['n_treatment']}\n")
    for m in result["metrics"]:
        print(f"[{m['label']}]")
        print(f"  baseline mean={m['baseline_mean']:.3f}  treatment mean={m['treatment_mean']:.3f}")
        print(f"  t-test: t={m['t_stat']:.3f}, p={m['t_p']:.4f}")
        print(f"  Mann-Whitney U: U={m['u_stat']:.3f}, p={m['u_p']:.4f}")
        print(f"  유의미함(p<0.05): {m['significant']}")
        print()


if __name__ == "__main__":
    main()
