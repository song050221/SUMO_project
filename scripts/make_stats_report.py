"""experiment_data/results.csv(baseline vs treatment)로 발표용 통계 비교표 HTML을 만든다(PDF는 Chrome으로 인쇄).

    python scripts/make_stats_report.py --results experiment_data/results.csv --out docs/presentation/src/statistics.html

같은 seed끼리 짝지어(대응표본) 비교한다 - 같은 seed는 차량·보행자·사고 난수가 같아서 seed 간 편차를 빼고 볼 수 있다.
검정: 대응표본 t-검정 + Wilcoxon 부호순위 검정(정규성 가정 없이), 차이의 95% 신뢰구간, 개선된 seed 수.
"""

import argparse
import html
import math

import pandas as pd
from scipy import stats

# (열, 표시 이름, 단위, 낮을수록 좋은가, 설명)
METRICS = [
    ("total_system_travel_time", "총 시스템 통행시간(TSTT)", "초", True, "모든 차가 도로 위에 있던 시간 합(도착 못 한 차 포함)"),
    ("total_wait_time", "누적 대기시간", "초", True, "모든 차의 매 초 정지 시간 합"),
    ("avg_travel_time", "평균 통행시간", "초", True, "도착한 차만의 평균"),
    ("throughput", "처리량(도착 차량)", "대", False, "1시간 안에 목적지에 도착한 차"),
    ("towed_count", "견인(180초 이상 낀 차)", "대", True, "막힘의 가장 직접적인 지표"),
    ("collision_count", "충돌", "건", True, "SUMO 충돌 판정(차간 거리 0)"),
    ("emergency_brake_count", "급제동", "회", True, "감속 4.5 m/s² 초과"),
]


def fmt(v, unit):
    if abs(v) >= 1e6:
        return f"{v / 1e6:,.2f}M"
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:,.1f}"


def analyze(df):
    b = df[df["mode"] == "baseline"].set_index("seed").sort_index()
    t = df[df["mode"] == "treatment"].set_index("seed").sort_index()
    seeds = sorted(set(b.index) & set(t.index))
    b, t = b.loc[seeds], t.loc[seeds]
    rows = []
    for col, name, unit, lower_better, desc in METRICS:
        bv, tv = b[col].astype(float), t[col].astype(float)
        diff = tv - bv
        n = len(diff)
        mean_b, mean_t = bv.mean(), tv.mean()
        pct = (mean_t / mean_b - 1) * 100 if mean_b else float("nan")
        if diff.std(ddof=1) > 0:
            t_p = stats.ttest_rel(tv, bv).pvalue
            half = stats.t.ppf(0.975, n - 1) * diff.std(ddof=1) / math.sqrt(n)
        else:
            t_p, half = float("nan"), 0.0
        try:
            w_p = stats.wilcoxon(tv, bv).pvalue
        except ValueError:
            w_p = float("nan")
        better = int(((tv < bv) if lower_better else (tv > bv)).sum())
        worse = int(((tv > bv) if lower_better else (tv < bv)).sum())
        improved = (pct < 0) if lower_better else (pct > 0)
        rows.append(dict(col=col, name=name, unit=unit, desc=desc, lower_better=lower_better, n=n,
                         mean_b=mean_b, sd_b=bv.std(ddof=1), mean_t=mean_t, sd_t=tv.std(ddof=1), pct=pct,
                         diff=diff.mean(), ci=(diff.mean() - half, diff.mean() + half), t_p=t_p, w_p=w_p,
                         better=better, worse=worse, improved=improved, sig=(t_p < 0.05),
                         per_seed=list(zip(seeds, bv.tolist(), tv.tolist()))))
    return seeds, rows


def verdict(r):
    if r["sig"]:
        return ("개선" if r["improved"] else "악화"), ("good" if r["improved"] else "bad")
    return "차이 없음", "neutral"


def seed_chart(r, width=520, height=150):
    """seed마다 baseline(회색)·treatment(파랑) 점을 선으로 잇는 대응 그림."""
    vals = [v for _, b, t in r["per_seed"] for v in (b, t)]
    lo, hi = min(vals), max(vals)
    pad = (hi - lo) * 0.12 or 1
    lo, hi = lo - pad, hi + pad
    n = len(r["per_seed"])
    x0, x1, y0, y1 = 46, width - 10, 12, height - 26

    def y(v):
        return y1 - (v - lo) / (hi - lo) * (y1 - y0)

    parts = [f'<svg viewBox="0 0 {width} {height}" class="chart">',
             f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" class="axis"/>']
    for k in range(3):
        v = lo + (hi - lo) * k / 2
        parts.append(f'<text x="{x0 - 6}" y="{y(v) + 4:.1f}" class="tick" text-anchor="end">{fmt(v, "")}</text>')
        parts.append(f'<line x1="{x0}" y1="{y(v):.1f}" x2="{x1}" y2="{y(v):.1f}" class="grid"/>')
    step = (x1 - x0) / max(n, 1)
    for i, (seed, bv, tv) in enumerate(r["per_seed"]):
        cx = x0 + step * (i + 0.5)
        good = (tv < bv) if r["lower_better"] else (tv > bv)
        parts.append(f'<line x1="{cx:.1f}" y1="{y(bv):.1f}" x2="{cx:.1f}" y2="{y(tv):.1f}" '
                     f'class="{"lg" if good else "lb"}"/>')
        parts.append(f'<circle cx="{cx:.1f}" cy="{y(bv):.1f}" r="5" class="pb"/>')
        parts.append(f'<circle cx="{cx:.1f}" cy="{y(tv):.1f}" r="5" class="pt"/>')
        parts.append(f'<text x="{cx:.1f}" y="{height - 8}" class="tick" text-anchor="middle">{seed}</text>')
    parts.append("</svg>")
    return "".join(parts)


def p_text(p):
    if p != p:
        return "-"
    return "&lt;0.001" if p < 0.001 else f"{p:.3f}"


def build_html(seeds, rows, title_note, conditions):
    e = html.escape
    sig_rows = [r for r in rows if r["sig"]]
    table = []
    for r in rows:
        v, cls = verdict(r)
        arrow = "▼" if r["pct"] < 0 else "▲"
        table.append(
            f'<tr><td><b>{e(r["name"])}</b><div class="desc">{e(r["desc"])}</div></td>'
            f'<td class="num">{fmt(r["mean_b"], r["unit"])}<div class="sd">±{fmt(r["sd_b"], "")}</div></td>'
            f'<td class="num">{fmt(r["mean_t"], r["unit"])}<div class="sd">±{fmt(r["sd_t"], "")}</div></td>'
            f'<td class="num {"g" if r["improved"] else "r"}">{arrow} {abs(r["pct"]):.2f}%</td>'
            f'<td class="num">{p_text(r["t_p"])}</td><td class="num">{p_text(r["w_p"])}</td>'
            f'<td class="num">{r["better"]}/{r["n"]}</td><td><span class="pill {cls}">{v}</span></td></tr>')
    charts = []
    for r in rows:
        v, cls = verdict(r)
        charts.append(f'<div class="chartbox"><div class="ch-title"><b>{e(r["name"])}</b>'
                      f'<span class="pill {cls}">{v}</span><span class="small">개선 seed {r["better"]}/{r["n"]} · '
                      f'p={p_text(r["t_p"])}</span></div>{seed_chart(r)}</div>')
    ci_rows = []
    for r in rows:
        lo, hi = r["ci"]
        ci_rows.append(f'<tr><td>{e(r["name"])}</td><td class="num">{fmt(r["diff"], "")}</td>'
                       f'<td class="num">[{fmt(lo, "")}, {fmt(hi, "")}]</td>'
                       f'<td>{"0을 포함 - 차이를 단정 못 함" if lo <= 0 <= hi else "0을 포함하지 않음"}</td></tr>')
    summary = (f"유의수준 5%에서 의미 있는 차이가 난 지표: <b>{', '.join(e(r['name']) for r in sig_rows)}</b>"
               if sig_rows else "유의수준 5%에서 의미 있는 차이가 난 지표는 <b>없다</b>")
    cond = "".join(f"<tr><th>{e(k)}</th><td>{e(v)}</td></tr>" for k, v in conditions)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>통계 비교표</title>
<link rel="stylesheet" href="slides.css"><link rel="stylesheet" href="stats.css"></head><body>
<section class="slide cover"><div class="cover-inner">
<p class="kicker">2026 창의설계경진대회 · 광진구 V2N 교통 시뮬레이션</p>
<h1>통계 비교표</h1><p class="subtitle">중앙 제어 없음(baseline) vs 중앙 제어 켬(treatment) · seed {len(seeds)}개 대응 비교</p>
<p class="cover-note">{e(title_note)}</p></div></section>

<section class="slide"><h2><span class="num">01</span>실험 설계</h2>
<div class="cols"><div class="col-7"><table class="kv">{cond}</table></div>
<div class="col-5 card soft"><h3>왜 이렇게 비교하나</h3><ul class="tight">
<li><b>같은 seed끼리 짝지어</b> 비교 — 같은 차량·보행자·사고 난수라 seed 간 편차를 빼고 알고리즘 차이만 본다</li>
<li><b>사고는 양쪽 모두</b> 같은 규칙으로 나고 사고 도로 위 차는 양쪽 다 멈춘다 — 차이는 중앙 제어 알고리즘뿐</li>
<li><b>견인도 양쪽 동일</b> — 현실 보정이라 알고리즘 효과로 착각되지 않게</li>
<li>검정 2가지: 대응표본 t-검정, Wilcoxon 부호순위(정규성 가정 없음)</li></ul></div></div></section>

<section class="slide"><h2><span class="num">02</span>결과 요약표</h2>
<table class="grid stats"><tr><th>지표</th><th>중앙 제어 없음<br><span>평균 ± 표준편차</span></th><th>중앙 제어 켬<br><span>평균 ± 표준편차</span></th>
<th>변화</th><th>t-검정 p</th><th>Wilcoxon p</th><th>개선 seed</th><th>판정</th></tr>{''.join(table)}</table>
<p class="note">판정: 대응표본 t-검정 p &lt; 0.05일 때 개선/악화, 아니면 "차이 없음". 변화 색은 방향(초록 = 좋아진 쪽)만 뜻한다. {summary}.</p></section>

<section class="slide"><h2><span class="num">03</span>seed별 비교</h2>
<p class="legend"><span class="dot pb"></span>중앙 제어 없음 <span class="dot pt"></span>중앙 제어 켬 &nbsp; 선 색: <span class="lgk">좋아짐</span> <span class="lbk">나빠짐</span> · 가로축 = seed</p>
<div class="chartgrid">{''.join(charts[:4])}</div></section>

<section class="slide"><h2><span class="num">04</span>seed별 비교 (계속) · 차이의 95% 신뢰구간</h2>
<div class="chartgrid three">{''.join(charts[4:])}</div>
<table class="grid ci mt-s"><tr><th>지표</th><th>평균 차이(켬 − 없음)</th><th>95% 신뢰구간</th><th>해석</th></tr>{''.join(ci_rows)}</table></section>
</body></html>"""


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default="experiment_data/results.csv")
    parser.add_argument("--out", default="docs/presentation/src/statistics.html")
    parser.add_argument("--note", default="")
    parser.add_argument("--interpret", default="", help="끝에 붙일 해석 슬라이드 HTML 조각")
    args = parser.parse_args()
    df = pd.read_csv(args.results)
    seeds, rows = analyze(df)
    conditions = [
        ("도로망", "광진구 OpenStreetMap → SUMO, 차도 18,521구간, 신호 197개"),
        ("수요", "시간당 차량 7,200대 + 보행자 약 900명(무작위 출발·도착), 1시간"),
        ("사고", "30초마다 1건·30초 지속, 앞으로 가장 많은 차가 지나갈 도로, 양쪽 조건 동일"),
        ("baseline", "출발 때 정한 최단 경로 + 고정 신호, 사고 도로 위 차 정지"),
        ("treatment", "사고 대응(정지·감속·우회·대기 비교) + 60초 실시간 재계산 + 정체 예측 우회 + 신호 배분"),
        ("반복", f"seed {seeds[0]}~{seeds[-1]} ({len(seeds)}쌍), 같은 seed = 같은 차량·보행자·사고 난수"),
        ("공통", "180초 이상 낀 차 견인, 충돌 시 차 유지(warn)"),
    ]
    page = build_html(seeds, rows, args.note, conditions)
    if args.interpret:  # 결과를 보고 사람이 쓴 해석 슬라이드(숫자가 바뀌면 같이 고칠 것)
        with open(args.interpret, encoding="utf-8") as f:
            page = page.replace("</body>", f.read() + "</body>")
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(page)
    for r in rows:
        print(f'{r["name"]}: {r["mean_b"]:.1f} -> {r["mean_t"]:.1f} ({r["pct"]:+.2f}%), t p={r["t_p"]:.3f}, '
              f'W p={r["w_p"]:.3f}, 개선 {r["better"]}/{r["n"]}')
    print(f"-> {args.out}")
