#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
4단계 보완 — Boxplot(IQR) 기반 그룹별 통계 이상치 확인

목적
- 강사 피드백: "그룹별로 묶어서 비교 후 이상치 확인(통계적으로 접근)"
- 기존 4단계 Isolation Forest를 대체하지 않고, 별도의 통계 결과를 만든다.
- 대상: 솔트조 온도 1 Zone, 솔트조 온도 2 Zone

주 분석
1) 그룹 = 배정번호 × 센서
2) Q1, Median, Q3, IQR 계산
3) 하한 = Q1 - 1.5×IQR / 상한 = Q3 + 1.5×IQR
4) 범위 밖 기록 = Boxplot 통계 이상치 후보
5) 후보끼리 실제 시각 차이 <=2초이면 연결
6) 마지막 후보 - 첫 후보 + 1초가 60초 이상이면 별도 조사 후보 구간

보조 분석
- 각 배정번호의 센서 중앙값을 대표값으로 만든 뒤
  1~4월 / 5월 / 6~7월 기간 안에서 작업 중앙값끼리 다시 Boxplot 비교

주의
- Boxplot 이상치는 고장/불량 확정이 아니다.
- 1.5×IQR은 Tukey boxplot의 일반적 통계 기준이며 현장 규격이 아니다.
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import sys
import time
import platform

PROJECT = Path(__file__).resolve().parents[2]

def safe_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")

def check_python_env():
    # Python·패키지 버전이 권장 환경과 다르면 [주의]만 보여 주고 계속합니다(src/env_check.py).
    sys.path.insert(0, str(PROJECT))
    from src.env_check import check_python_env as check
    check(PROJECT)

if __name__ == "__main__":
    safe_console()
    check_python_env()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.font_manager as fm  # noqa: E402
plt.ioff()

sys.path.insert(0, str(PROJECT))
from src.data_contract import TIME_COL, BATCH_COL, load_raw, add_segments  # noqa: E402

SENSORS = ["솔트조 온도 1 Zone", "솔트조 온도 2 Zone"]

PERIOD_BY_MONTH = {
    1: "기준작성(1~4월)", 2: "기준작성(1~4월)",
    3: "기준작성(1~4월)", 4: "기준작성(1~4월)",
    5: "조건점검(5월)",
    6: "후속비교(6~7월)", 7: "후속비교(6~7월)",
}
PERIOD_ORDER = ["기준작성(1~4월)", "조건점검(5월)", "후속비교(6~7월)"]

IQR_MULTIPLIER = 1.5
MIN_VALID_RECORDS_PER_GROUP = 300
EVENT_GAP_SEC = 2
MIN_DURATION_SEC = 60
BOXES_PER_FIGURE = 20

OUT = PROJECT / "reports" / "4단계_참고_Boxplot_IQR_온도이상치" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
FIG_DIR = OUT / "figures_작업별_Boxplot"

def normalize_batch(series):
    return series.astype(str).str.replace(r"\.0$", "", regex=True)

def set_korean_font():
    installed = {f.name for f in fm.fontManager.ttflist}
    for name in ["Malgun Gothic", "맑은 고딕", "AppleGothic", "NanumGothic", "Noto Sans CJK KR"]:
        if name in installed:
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False

def save(df, name):
    df.to_csv(OUT / name, index=False, encoding="utf-8-sig")

def attach_first_record_period(df):
    jobs = (
        df.groupby(BATCH_COL, sort=False)
        .agg(첫기록시각=(TIME_COL, "min"), 마지막기록시각=(TIME_COL, "max"), 원본행수=(TIME_COL, "size"))
        .reset_index()
    )
    jobs["첫기록월"] = jobs["첫기록시각"].dt.month
    jobs["period"] = jobs["첫기록월"].map(PERIOD_BY_MONTH)

    if jobs["period"].isna().any():
        raise ValueError("1~7월 밖의 작업이 있습니다.")

    pmap = dict(zip(jobs[BATCH_COL], jobs["period"]))
    mmap = dict(zip(jobs[BATCH_COL], jobs["첫기록월"]))
    df["period"] = df[BATCH_COL].map(pmap)
    df["첫기록월"] = df[BATCH_COL].map(mmap)

    month_counts = (
        jobs.groupby("첫기록월", as_index=False)
        .agg(작업수=(BATCH_COL, "size"), 기록수=("원본행수", "sum"))
        .sort_values("첫기록월")
        .reset_index(drop=True)
    )
    return df, jobs, month_counts

def link_candidate_events(times_ns, candidate):
    candidate = np.asarray(candidate, dtype=bool)
    pos = np.flatnonzero(candidate)
    if len(pos) == 0:
        return []

    t_sec = times_ns[pos] // 1_000_000_000
    cuts = np.r_[0, np.flatnonzero(np.diff(t_sec) > EVENT_GAP_SEC) + 1, len(pos)]

    events = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        p = pos[a:b]
        duration = (times_ns[p[-1]] - times_ns[p[0]]) / 1e9 + 1.0
        events.append({
            "st": int(p[0]),
            "en": int(p[-1]),
            "duration_sec": float(duration),
            "candidate_count": int(len(p)),
            "priority": bool(duration >= MIN_DURATION_SEC),
        })
    return events

def build_within_job_iqr(df):
    criteria_parts = []
    outlier_parts = []
    event_rows = []

    for sensor in SENSORS:
        print(f"   작업 내부 IQR 계산: {sensor}")
        work = df[[BATCH_COL, TIME_COL, "period", sensor]].copy()
        work["값"] = pd.to_numeric(work[sensor], errors="coerce")

        g = work.groupby(BATCH_COL, sort=False)["값"]
        q1 = g.transform(lambda s: s.quantile(0.25))
        med = g.transform("median")
        q3 = g.transform(lambda s: s.quantile(0.75))
        n = g.transform("count")
        iqr = q3 - q1
        lower = q1 - IQR_MULTIPLIER * iqr
        upper = q3 + IQR_MULTIPLIER * iqr

        valid = work["값"].notna() & (n >= MIN_VALID_RECORDS_PER_GROUP)
        outlier = valid & ((work["값"] < lower) | (work["값"] > upper))

        work["sensor"] = sensor
        work["유효기록수"] = n.astype("Int64")
        work["Q1"] = q1
        work["중앙값"] = med
        work["Q3"] = q3
        work["IQR"] = iqr
        work["하한"] = lower
        work["상한"] = upper
        work["판정가능"] = valid
        work["Boxplot이상치"] = outlier
        work["방향"] = np.select(
            [work["값"] < lower, work["값"] > upper],
            ["하한미만", "상한초과"],
            default="",
        )
        work["IQR경계초과량"] = np.where(
            work["값"] < lower,
            lower - work["값"],
            np.where(work["값"] > upper, work["값"] - upper, 0.0),
        )

        crit = (
            work.groupby(BATCH_COL, sort=False)
            .agg(
                period=("period", "first"),
                유효기록수=("유효기록수", "first"),
                Q1=("Q1", "first"),
                중앙값=("중앙값", "first"),
                Q3=("Q3", "first"),
                IQR=("IQR", "first"),
                하한=("하한", "first"),
                상한=("상한", "first"),
                판정가능기록수=("판정가능", "sum"),
                이상치기록수=("Boxplot이상치", "sum"),
            )
            .reset_index()
        )
        crit["sensor"] = sensor
        crit["이상치비율_pct"] = np.where(
            crit["판정가능기록수"] > 0,
            crit["이상치기록수"] / crit["판정가능기록수"] * 100,
            np.nan,
        )
        crit["IQR배수"] = IQR_MULTIPLIER
        criteria_parts.append(crit)

        outlier_parts.append(
            work.loc[
                work["Boxplot이상치"],
                [BATCH_COL, TIME_COL, "period", "sensor", "값", "Q1", "중앙값", "Q3", "IQR", "하한", "상한", "방향", "IQR경계초과량"],
            ].copy()
        )

        cand_global = work["Boxplot이상치"].to_numpy(dtype=bool)

        for batch, idx in df.groupby(BATCH_COL, sort=False).indices.items():
            idx = np.asarray(idx, dtype=np.int64)
            local = cand_global[idx]
            if not local.any():
                continue

            times_ns = (
                df.iloc[idx][TIME_COL]
                .to_numpy(dtype="datetime64[ns]")
                .astype("int64")
            )
            vals = pd.to_numeric(df.iloc[idx][sensor], errors="coerce").to_numpy(dtype="float64")

            for e in link_candidate_events(times_ns, local):
                if not e["priority"]:
                    continue
                st, en = e["st"], e["en"]
                pos = np.flatnonzero(local[st:en + 1]) + st
                vv = vals[pos]
                event_rows.append({
                    "method": "Boxplot_IQR",
                    BATCH_COL: str(batch),
                    "period": df.iloc[idx]["period"].iloc[0],
                    "sensor": sensor,
                    "start_time": pd.Timestamp(times_ns[st]),
                    "end_time": pd.Timestamp(times_ns[en]),
                    "duration_sec": e["duration_sec"],
                    "outlier_record_count": e["candidate_count"],
                    "최소온도": float(np.nanmin(vv)) if len(vv) else np.nan,
                    "최대온도": float(np.nanmax(vv)) if len(vv) else np.nan,
                })

    return (
        pd.concat(criteria_parts, ignore_index=True),
        pd.concat(outlier_parts, ignore_index=True) if outlier_parts else pd.DataFrame(),
        pd.DataFrame(event_rows),
    )

def build_between_job_median_iqr(df):
    parts = []
    for sensor in SENSORS:
        t = (
            df.groupby([BATCH_COL, "period"], as_index=False)[sensor]
            .median()
            .rename(columns={sensor: "작업중앙값"})
        )
        t["sensor"] = sensor
        parts.append(t)

    med = pd.concat(parts, ignore_index=True)
    g = med.groupby(["period", "sensor"], sort=False)["작업중앙값"]
    med["Q1"] = g.transform(lambda s: s.quantile(0.25))
    med["전체중앙"] = g.transform("median")
    med["Q3"] = g.transform(lambda s: s.quantile(0.75))
    med["IQR"] = med["Q3"] - med["Q1"]
    med["하한"] = med["Q1"] - IQR_MULTIPLIER * med["IQR"]
    med["상한"] = med["Q3"] + IQR_MULTIPLIER * med["IQR"]
    med["이상작업"] = (med["작업중앙값"] < med["하한"]) | (med["작업중앙값"] > med["상한"])
    med["방향"] = np.select(
        [med["작업중앙값"] < med["하한"], med["작업중앙값"] > med["상한"]],
        ["하한미만", "상한초과"],
        default="",
    )

    criteria = (
        med.groupby(["period", "sensor"], as_index=False)
        .agg(
            작업수=(BATCH_COL, "size"),
            Q1=("Q1", "first"),
            중앙값=("전체중앙", "first"),
            Q3=("Q3", "first"),
            IQR=("IQR", "first"),
            하한=("하한", "first"),
            상한=("상한", "first"),
            이상작업수=("이상작업", "sum"),
        )
    )
    criteria["IQR배수"] = IQR_MULTIPLIER
    return med, criteria, med.loc[med["이상작업"]].copy()

def build_period_summary(criteria, outliers, events):
    rows = []
    for period in PERIOD_ORDER:
        for sensor in SENSORS:
            c = criteria.loc[(criteria["period"] == period) & (criteria["sensor"] == sensor)]
            o = outliers.loc[(outliers["period"] == period) & (outliers["sensor"] == sensor)] if len(outliers) else outliers
            e = events.loc[(events["period"] == period) & (events["sensor"] == sensor)] if len(events) else events

            n_valid = int(c["판정가능기록수"].sum()) if len(c) else 0
            n_out = int(c["이상치기록수"].sum()) if len(c) else 0

            rows.append({
                "period": period,
                "sensor": sensor,
                "작업수": int(c[BATCH_COL].nunique()) if len(c) else 0,
                "판정가능기록수": n_valid,
                "Boxplot이상치기록수": n_out,
                "Boxplot이상치비율_pct": (n_out / n_valid * 100) if n_valid else np.nan,
                "이상치관련작업수": int(o[BATCH_COL].nunique()) if len(o) else 0,
                "60초이상_조사후보구간수": int(len(e)),
                "60초이상_관련작업수": int(e[BATCH_COL].nunique()) if len(e) else 0,
            })
    return pd.DataFrame(rows)

def build_boxplot_figures(criteria):
    saved = []
    for sensor in SENSORS:
        sc = criteria.loc[criteria["sensor"] == sensor].copy()

        for period in PERIOD_ORDER:
            cp = sc.loc[sc["period"] == period].copy()
            batches = cp[BATCH_COL].astype(str).tolist()

            for chunk_no, start in enumerate(range(0, len(batches), BOXES_PER_FIGURE), start=1):
                chosen = batches[start:start + BOXES_PER_FIGURE]
                sub = cp.loc[cp[BATCH_COL].astype(str).isin(chosen)].copy()
                stats = []

                for _, r in sub.iterrows():
                    stats.append({
                        "label": f"{r[BATCH_COL]}\n({int(r['이상치기록수'])})",
                        "q1": float(r["Q1"]),
                        "med": float(r["중앙값"]),
                        "q3": float(r["Q3"]),
                        # Tukey fence를 whisker 위치로 표시하여 기준을 눈으로 확인
                        "whislo": float(r["하한"]),
                        "whishi": float(r["상한"]),
                        "fliers": [],
                    })

                if not stats:
                    continue

                fig, ax = plt.subplots(figsize=(max(12, len(stats) * 0.75), 6))
                ax.bxp(stats, showfliers=False)
                ax.set_title(
                    f"{period} | {sensor} | 배정번호별 Boxplot\n"
                    "(괄호 = 1.5×IQR 밖 원본 기록 수)"
                )
                ax.set_xlabel("배정번호")
                ax.set_ylabel("온도 (℃)")
                ax.tick_params(axis="x", rotation=60)
                ax.grid(axis="y", alpha=0.25)
                fig.tight_layout()

                safe_period = period.replace("(", "_").replace(")", "").replace("~", "-").replace("/", "_")
                filename = f"{safe_period}_{sensor}_part{chunk_no:02d}.png"
                fig.savefig(FIG_DIR / filename, dpi=150)
                plt.close(fig)

                saved.append({
                    "period": period,
                    "sensor": sensor,
                    "part": chunk_no,
                    "작업수": len(stats),
                    "그래프파일": filename,
                })
    return pd.DataFrame(saved)

def main():
    started = time.time()
    set_korean_font()
    OUT.mkdir(parents=True, exist_ok=False)
    FIG_DIR.mkdir()

    print("=" * 78)
    print("4단계 보완 — Boxplot(IQR) 기반 그룹별 통계 이상치 확인")
    print("=" * 78)

    print("\n1) 원본 읽기")
    df = add_segments(load_raw(SENSORS, sensor_dtype="float32"))
    df[BATCH_COL] = normalize_batch(df[BATCH_COL])
    df, jobs, month_counts = attach_first_record_period(df)
    save(month_counts, "00_첫기록월별_작업수.csv")
    print(f"   원본 {len(df):,}행 / 작업 {df[BATCH_COL].nunique()}개")

    print("\n2) 배정번호×센서별 IQR 계산")
    criteria, outliers, events = build_within_job_iqr(df)
    save(criteria, "01_작업별_센서별_IQR기준.csv")
    save(outliers, "02_기록단위_Boxplot이상치.csv")
    save(events, "03_60초이상_Boxplot_조사후보구간.csv")

    summary = build_period_summary(criteria, outliers, events)
    save(summary, "04_기간별_Boxplot_요약.csv")
    print(summary.to_string(index=False))

    print("\n3) 작업 중앙값끼리 기간별 비교")
    med, med_criteria, outlier_jobs = build_between_job_median_iqr(df)
    save(med, "05_작업별_센서별_중앙값.csv")
    save(med_criteria, "06_기간별_작업중앙값_IQR기준.csv")
    save(outlier_jobs, "07_작업중앙값_이상작업.csv")
    print(med_criteria.to_string(index=False))

    print("\n4) Boxplot 그림 저장")
    fig_index = build_boxplot_figures(criteria)
    save(fig_index, "08_Boxplot_그래프목록.csv")

    elapsed = time.time() - started
    summary_text = f"""4단계 Boxplot(IQR) 통계 이상치 분석
============================================================================

[주 분석]
그룹 = 배정번호 × 센서
하한 = Q1 - {IQR_MULTIPLIER} × IQR
상한 = Q3 + {IQR_MULTIPLIER} × IQR
범위 밖 원본 기록 = Boxplot 통계 이상치 후보

[지속 구간]
후보 간 실제 시각 차이 <= {EVENT_GAP_SEC}초 연결
마지막 후보 - 첫 후보 + 1초 >= {MIN_DURATION_SEC}초이면 별도 조사 후보

[보조 분석]
각 작업의 센서 중앙값을 하나의 대표값으로 만들고
같은 기간의 작업 대표값끼리 1.5×IQR 비교

[주의]
- 통계적 이상치는 실제 고장/불량 확정이 아님.
- 1.5×IQR은 현장 규격이 아니라 통계적 탐색 기준.
- 기존 Isolation Forest를 대체하지 않고 보완 비교함.

[기간별 결과]
{summary.to_string(index=False)}

[작업 대표값 결과]
{med_criteria.to_string(index=False)}

실행시간: {elapsed:.1f}초
Python: {platform.python_version()}
pandas: {pd.__version__}
numpy: {np.__version__}
"""
    (OUT / "Boxplot_IQR_요약.txt").write_text(summary_text, encoding="utf-8-sig")

    (OUT / "완료.txt").write_text(
        "Boxplot(IQR) 그룹별 통계 이상치 분석 정상 완료\n"
        f"결과폴더: {OUT}\n",
        encoding="utf-8-sig",
    )

    print("\n[완료]")
    print("결과 폴더:", OUT)
    print("먼저 볼 파일:")
    print("  04_기간별_Boxplot_요약.csv")
    print("  03_60초이상_Boxplot_조사후보구간.csv")
    print("  07_작업중앙값_이상작업.csv")
    print("  figures_작업별_Boxplot/")

if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, ImportError, KeyError, AssertionError, OSError) as error:
        print(f"[중단] {error}", file=sys.stderr)
        sys.exit(1)
