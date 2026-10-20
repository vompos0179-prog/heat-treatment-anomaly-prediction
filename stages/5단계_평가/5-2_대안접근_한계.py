"""5-2 IQR: 저장된 A1·A2·IF 판정을 같은 기록에서 비교한다.

이 코드는 IF의 판정 가능 여부를 다시 계산하거나 모델을 학습하지 않는다.
최신 4단계가 저장한 IF_valid·IF_qual과 3단계 기록별 판정을 직접 읽는다.
IQR의 기존 후보와 60초 구간은 유지하고, 공통 판정 기록에 포함되는 수만
다시 센다. 공통 범위로 잘라낸 뒤 60초 조건을 다시 적용하지 않는다.
품질 자료와 XGBoost는 이 실행의 대상이 아니다.
"""
from pathlib import Path
import argparse
import json

import numpy as np
import pandas as pd

from stage5_common import (
    load_config, iter_aligned, read_csv, save_csv, sha256,
    input_manifest, runtime_info, raw_jobs, readiness,
)

NS = 1_000_000_000
SENSORS = {4: "솔트조 온도 1 Zone", 5: "솔트조 온도 2 Zone"}
EVENT_COLUMNS = ["배정번호", "sensor", "start_time", "end_time",
                 "원래시작", "원래종료", "common_candidate_count"]
UNION_COLUMNS = ["배정번호", "start_ns", "end_ns", "시작", "종료",
                 "조사범위길이초", "센서"]


def _required(df, columns, name):
    missing = sorted(set(columns) - set(df.columns))
    if missing:
        raise ValueError(f"{name}: 필요한 열이 없습니다: {missing}")


def _csv(folder, filename):
    path = Path(folder) / filename
    if not path.is_file():
        raise FileNotFoundError(f"IQR 원래 결과가 없습니다: {path}")
    return read_csv(path)


def _follow(df):
    """IQR 원래 결과의 기간 분류를 보존한다."""
    return df.loc[df["period"].astype(str).str.contains("6~7", regex=False)
                  & df["sensor"].isin(SENSORS.values())].copy()


def union_events(rows):
    """센서 구간을 설비 구간으로 합친다. 내부 표현은 [시작, 종료+1초)."""
    answer = []
    if rows.empty:
        return pd.DataFrame(columns=UNION_COLUMNS)
    for batch, group in rows.groupby("배정번호", sort=True):
        intervals = sorted((int(pd.Timestamp(r.start_time).value),
                            int(pd.Timestamp(r.end_time).value) + NS,
                            str(r.sensor)) for r in group.itertuples())
        merged = []
        for start, end, sensor in intervals:
            if end <= start:
                raise ValueError(f"{batch}: 종료가 시작보다 앞선 구간")
            if merged and start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], end)
                merged[-1][2].add(sensor)
            else:
                merged.append([start, end, {sensor}])
        for start, end, sensors in merged:
            answer.append({"배정번호": int(batch), "start_ns": start, "end_ns": end,
                           "시작": str(pd.Timestamp(start)),
                           "종료": str(pd.Timestamp(end - NS)),
                           "조사범위길이초": (end - start) / NS,
                           "센서": "; ".join(sorted(sensors))})
    return pd.DataFrame(answer, columns=UNION_COLUMNS)


def _qualified_runs(job, t, qualified, common, sensor):
    """이미 선정된 기록의 2초 연결을 복원한다. 60초 조건은 재검사하지 않는다."""
    indices = np.flatnonzero(qualified)
    if not len(indices):
        return []
    splits = np.flatnonzero(np.diff(t[indices]) > 2 * NS) + 1
    rows = []
    for original in np.split(indices, splits):
        kept = original[common[original]]
        if not len(kept):
            continue
        rows.append({"배정번호": int(job), "sensor": sensor,
                     "start_time": str(pd.Timestamp(t[kept[0]])),
                     "end_time": str(pd.Timestamp(t[kept[-1]])),
                     "원래시작": str(pd.Timestamp(t[original[0]])),
                     "원래종료": str(pd.Timestamp(t[original[-1]])),
                     "common_candidate_count": int(len(kept))})
    return rows


def _point_mask(t, point_times, job, sensor):
    """IQR 후보의 모든 시각이 기록 라벨에 정확히 연결되는지 확인한다."""
    if not len(point_times):
        return np.zeros(len(t), dtype=bool)
    point_times = pd.to_datetime(point_times, format="ISO8601", errors="raise").to_numpy(
        dtype="datetime64[ns]").astype("int64")
    if len(np.unique(point_times)) != len(point_times):
        raise ValueError(f"{job} {sensor}: IQR 후보 시각이 중복됩니다")
    index = np.searchsorted(t, point_times)
    inside = index < len(t)
    matched = np.zeros(len(index), dtype=bool)
    matched[inside] = t[index[inside]] == point_times[inside]
    if not matched.all():
        example = [str(pd.Timestamp(v)) for v in point_times[~matched][:3]]
        raise ValueError(f"{job} {sensor}: IQR 후보 {int((~matched).sum())}개가 "
                         f"원본 시각에 연결되지 않습니다: {example}")
    mask = np.zeros(len(t), dtype=bool)
    mask[index] = True
    return mask


def _method_equipment(config, method_events, jobs):
    """4단계 21번 표의 설비 구간을 그대로 쓴다. IQR 묶기와 구분한다."""
    path = Path(config["stage4"]) / "21_설비단위_방법별구간.csv"
    if not path.is_file():
        if config.get("mode", "production") == "production":
            raise FileNotFoundError(f"최신 4단계의 설비 구간표가 없습니다: {path}")
        return {method: union_events(pd.DataFrame(rows, columns=EVENT_COLUMNS))
                for method, rows in method_events.items()}, "시험 입력: 공통 범위의 센서 기록을 합침"
    source = read_csv(path)
    _required(source, ["method", "배정번호", "설비", "start_time", "end_time"], str(path))
    source["배정번호"] = pd.to_numeric(source["배정번호"], errors="raise").astype(int)
    source = source.loc[source["배정번호"].isin(jobs) & source["설비"].eq("솔트조")
                        & source["method"].isin(method_events)].copy()
    if source.duplicated(["method", "배정번호", "start_time", "end_time"]).any():
        raise ValueError("4단계 21번 표의 설비 구간이 중복됩니다")
    result = {}
    for method, sensor_rows in method_events.items():
        selected = source.loc[source["method"].eq(method)]
        kept = pd.DataFrame(sensor_rows, columns=EVENT_COLUMNS)
        covered = np.zeros(len(kept), dtype=int)
        rows = []
        for row in selected.to_dict("records"):
            start = int(pd.Timestamp(row["start_time"]).value)
            end = int(pd.Timestamp(row["end_time"]).value) + NS
            if end <= start:
                raise ValueError("4단계 21번 표의 종료가 시작보다 앞섭니다")
            parent = (kept["배정번호"].eq(row["배정번호"])
                      & (pd.to_datetime(kept["start_time"]) >= pd.Timestamp(start))
                      & (pd.to_datetime(kept["end_time"]) < pd.Timestamp(end)))
            covered += parent.to_numpy(dtype=int)
            rows.append({"배정번호": int(row["배정번호"]), "start_ns": start, "end_ns": end,
                         "시작": str(pd.Timestamp(start)), "종료": str(pd.Timestamp(end - NS)),
                         "조사범위길이초": (end - start) / NS,
                         "센서": "; ".join(sorted(set(kept.loc[parent, "sensor"]))),
                         "공통범위후보있음": bool(parent.any())})
        if len(covered) and not (covered == 1).all():
            raise ValueError(f"{method}: 공통 범위 센서 구간이 4단계 21번 표에 정확히 한 번 포함되지 않습니다")
        result[method] = pd.DataFrame(rows, columns=UNION_COLUMNS + ["공통범위후보있음"])
    return result, str(path)


def _percent(numerator, denominator):
    return numerator / denominator * 100 if denominator else np.nan


def _figure_setup():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    font = Path("C:/Windows/Fonts/malgun.ttf")
    if font.is_file():
        fm.fontManager.addfont(str(font))
        plt.rcParams["font.family"] = "Malgun Gothic"
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def plots(config, output, criteria, medians, representatives, rows, total):
    """원래 경계·원본 온도·새 공통 분모를 이용해 설명 그림을 다시 만든다."""
    import matplotlib.dates as mdates
    plt = _figure_setup()
    figures = output / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    salt1 = criteria.loc[criteria["sensor"].eq(SENSORS[4])].copy()
    possible = set(salt1["배정번호"].astype(int))
    examples = [job for job in [147546, 146767] if job in possible]
    if not examples and not salt1.empty:
        examples = list(dict.fromkeys(salt1.sort_values("IQR")["배정번호"]
                                      .iloc[[0, -1]].astype(int).tolist()))
    if examples:
        original = raw_jobs(config, examples)
        fig, axes = plt.subplots(len(examples), 1, figsize=(12, 3.5 * len(examples)),
                                 layout="constrained", squeeze=False)
        for ax, job in zip(axes.flat, examples):
            if job not in original:
                raise ValueError(f"원본 CSV에 대표 작업 {job}이 없습니다")
            data = original[job].copy().sort_values("TAG_MIN", kind="stable")
            t = pd.to_datetime(data["TAG_MIN"]).to_numpy(dtype="datetime64[ns]").astype("int64")
            v = pd.to_numeric(data[SENSORS[4]], errors="coerce").to_numpy(dtype=float)
            gaps = np.flatnonzero(np.diff(t) > 5 * NS) + 1
            plot_t = pd.to_datetime(np.insert(t, gaps, t[gaps] - 1))
            plot_v = np.insert(v, gaps, np.nan)
            bound = salt1.loc[salt1["배정번호"].eq(job)]
            if len(bound) != 1:
                raise ValueError(f"{job}: 센서별 IQR 기준이 한 행이 아닙니다")
            bound = bound.iloc[0]
            ax.plot(plot_t, plot_v, lw=.8, color="#087F8C", label="원본 솔트조 1존")
            ax.axhline(bound["상한"], ls="--", color="#C75536", label="작업별 IQR 경계")
            ax.axhline(bound["하한"], ls="--", color="#C75536")
            ax.set_title(f"배정번호 {job} | IQR 폭 {bound['IQR']:.3f}℃ | "
                         f"경계 밖 기록 {int(bound['이상치기록수']):,}개", loc="left")
            ax.set_ylabel("온도 (℃)")
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d %H:%M"))
            ax.grid(alpha=.2)
            ax.legend(loc="upper right", fontsize=9)
        fig.suptitle("작업 전체의 온도 분포로 경계를 만들면, 크게 변한 작업의 경계도 넓어진다", fontsize=14)
        fig.savefig(figures / "5-2_fig01_IQR_작업별경계.png", dpi=220)
        plt.close(fig)

    first = medians.loc[medians["period"].astype(str).str.contains("1~4", regex=False)
                        & medians["sensor"].eq(SENSORS[4])].sort_values("배정번호").reset_index(drop=True)
    selected = set(representatives.loc[
        representatives["period"].astype(str).str.contains("1~4", regex=False)
        & representatives["sensor"].eq(SENSORS[4]), "배정번호"])
    highlighted = first["배정번호"].isin(selected)
    value = "중앙값" if "중앙값" in first.columns else "작업중앙값"
    fig, ax = plt.subplots(figsize=(11, 5.2), layout="constrained")
    ax.scatter(np.flatnonzero(~highlighted) + 1, first.loc[~highlighted, value],
               color="#087F8C", s=30, label="그 외 기준기간 작업")
    ax.scatter(np.flatnonzero(highlighted) + 1, first.loc[highlighted, value],
               color="#C75536", s=45, label="작업 대표값의 IQR 경계 밖 작업")
    ax.set(xlabel="배정번호 오름차순 작업 순서", ylabel="작업 중앙값 (℃)",
           title="1~4월 작업의 대표 온도 수준 비교: 온도 수준 차이도 후보가 된다")
    ax.legend()
    ax.grid(alpha=.2)
    fig.savefig(figures / "5-2_fig02_작업대표값.png", dpi=220)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 4.8), layout="constrained")
    values = [row["후보기록비율_pct"] for row in rows]
    bar_values = [v if np.isfinite(v) else 0 for v in values]
    bars = ax.bar(["A1", "IF", "A2", "IQR\n60초 조건"], bar_values,
                  color=["#2563EB", "#9333EA", "#80979B", "#C88737"])
    top = max(max(bar_values, default=0), .01)
    for bar, value in zip(bars, values):
        display_value = value if np.isfinite(value) else 0
        label = f"{value:.3f}%" if np.isfinite(value) else "계산 불가"
        ax.text(bar.get_x() + bar.get_width() / 2, display_value + top * .025,
                label, ha="center", fontsize=12)
    ax.set_ylim(0, top * 1.22)
    ax.set_ylabel("공통 판정 기록 중 후보 기록 비율 (%)")
    ax.set_title(f"같은 {total:,}개 기록에서 비교한 조사 후보의 양")
    ax.text(.99, .96, "실제 고장률·정확도가 아님", transform=ax.transAxes,
            ha="right", va="top", fontsize=10, color="#555555")
    fig.savefig(figures / "5-2_fig03_공통범위_후보비율.png", dpi=220)
    plt.close(fig)


def run(config, output, skip_plots=False):
    missing = readiness(config, include_raw=not skip_plots, scope="iqr")
    if missing:
        raise FileNotFoundError("5-2 실행에 필요한 입력 확인 실패:\n" + "\n".join(missing))
    mode = config.get("mode", "production")
    production = mode == "production"
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    names = {
        "criteria": "01_작업별_센서별_IQR기준.csv",
        "points": "02_기록단위_Boxplot이상치.csv",
        "events": "03_60초이상_Boxplot_조사후보구간.csv",
        "medians": "05_작업별_센서별_중앙값.csv",
        "representatives": "07_작업중앙값_이상작업.csv",
    }
    tables = {key: _csv(config["iqr"], name) for key, name in names.items()}
    for key in ["criteria", "points", "events", "medians", "representatives"]:
        _required(tables[key], ["배정번호", "period", "sensor"], names[key])
        tables[key]["배정번호"] = pd.to_numeric(tables[key]["배정번호"], errors="raise").astype(int)
    _required(tables["points"], ["TAG_MIN"], names["points"])
    _required(tables["events"], ["start_time", "end_time"], names["events"])
    follow_points = _follow(tables["points"])
    follow_events = _follow(tables["events"])
    points_by_job = {int(job): group for job, group in follow_points.groupby("배정번호")}
    events_by_job = {int(job): group for job, group in follow_events.groupby("배정번호")}

    counts = {"A1": 0, "A2": 0, "IF": 0, "IQR_all": 0, "IQR_qualified": 0}
    job_sets = {key: set() for key in counts}
    method_events = {method: [] for method in ["A1", "A2", "IF"]}
    retained_iqr, detail, scope_rows = [], [], []
    seen, common_total, raw_total, original_points = set(), 0, 0, 0
    for job, t, stage3, stage4, common in iter_aligned(config):
        job = int(job)
        if job in seen:
            raise ValueError(f"같은 작업을 두 번 읽었습니다: {job}")
        seen.add(job)
        t = np.asarray(t, dtype=np.int64)
        common = np.asarray(common, dtype=bool)
        if len(t) != len(common) or (len(t) > 1 and (np.diff(t) <= 0).any()):
            raise ValueError(f"{job}: 기록 시각이 중복되거나 시간순이 아닙니다")
        expected_common = np.logical_and.reduce(
            [np.asarray(stage3[f"{method}_{index}_valid"], dtype=bool)
             for method in ["A1", "A2"] for index in SENSORS]
            + [np.asarray(stage4[f"IF_{index}_valid"], dtype=bool)
               for index in SENSORS])
        if not np.array_equal(common, expected_common):
            raise ValueError(f"{job}: 공통 범위가 A1·A2·IF valid 교집합과 다릅니다")
        common_total += int(common.sum())
        raw_total += len(t)
        point_group = points_by_job.get(job, follow_points.iloc[:0])
        event_group = events_by_job.get(job, follow_events.iloc[:0])
        iqr_all = np.zeros(len(t), dtype=bool)
        iqr_qual = np.zeros(len(t), dtype=bool)
        method_masks = {method: np.zeros(len(t), dtype=bool) for method in method_events}
        scope_rows.append({"배정번호": job, "원본기록수": len(t),
                           "공통판정기록수": int(common.sum()),
                           "공통범위제외기록수": int((~common).sum())})
        for index, sensor in SENSORS.items():
            points = point_group.loc[point_group["sensor"].eq(sensor), "TAG_MIN"]
            candidate = _point_mask(t, points, job, sensor)
            original_points += int(candidate.sum())
            qualified = np.zeros(len(t), dtype=bool)
            sensor_events = event_group.loc[event_group["sensor"].eq(sensor)]
            for row in sensor_events.itertuples():
                lo, hi = pd.Timestamp(row.start_time).value, pd.Timestamp(row.end_time).value
                if hi < lo:
                    raise ValueError(f"{job} {sensor}: IQR 구간 시각이 뒤집혔습니다")
                original_hit = candidate & (t >= lo) & (t <= hi)
                if not original_hit.any():
                    raise ValueError(f"{job} {sensor}: IQR 60초 구간에 후보 기록이 없습니다")
                if t[original_hit][0] != lo or t[original_hit][-1] != hi:
                    raise ValueError(f"{job} {sensor}: IQR 구간 시작·끝이 후보 기록과 다릅니다")
                qualified |= original_hit
                kept = original_hit & common
                if kept.any():
                    retained_iqr.append({"배정번호": job, "sensor": sensor,
                                         "start_time": str(pd.Timestamp(t[kept][0])),
                                         "end_time": str(pd.Timestamp(t[kept][-1])),
                                         "원래시작": str(pd.Timestamp(lo)),
                                         "원래종료": str(pd.Timestamp(hi)),
                                         "common_candidate_count": int(kept.sum())})
            iqr_all |= candidate & common
            iqr_qual |= qualified & common
            detail.append({"배정번호": job, "sensor": sensor,
                           "원래IQR단일후보기록수": int(candidate.sum()),
                           "공통기록수": int(common.sum()),
                           "IQR단일기록후보수": int((candidate & common).sum()),
                           "IQR60초구간후보수": int((qualified & common).sum()),
                           "공통범위밖IQR60초후보수": int((qualified & ~common).sum())})
            for method in method_events:
                source = stage4 if method == "IF" else stage3
                q = np.asarray(source[f"{method}_{index}_qual"], dtype=bool)
                valid = np.asarray(source[f"{method}_{index}_valid"], dtype=bool)
                if len(q) != len(t) or (q & ~valid).any():
                    raise ValueError(f"{job} {method} {sensor}: 판정 불가에 선정 기록이 있습니다")
                method_masks[method] |= q & common
                method_events[method].extend(_qualified_runs(job, t, q, common, sensor))
        for method, mask in {**method_masks, "IQR_all": iqr_all, "IQR_qualified": iqr_qual}.items():
            counts[method] += int(mask.sum())
            if mask.any():
                job_sets[method].add(job)

    expected_jobs = set(_follow(tables["criteria"])["배정번호"])
    if seen != expected_jobs:
        raise ValueError(f"IQR·기록별 판정 작업 범위 불일치: "
                         f"라벨에 없는 작업={sorted(expected_jobs-seen)}, "
                         f"IQR에 없는 작업={sorted(seen-expected_jobs)}")
    if original_points != len(follow_points):
        raise ValueError(f"IQR 후보 연결 누락: 원래 {len(follow_points)}, 연결 {original_points}")
    retained = pd.DataFrame(retained_iqr, columns=EVENT_COLUMNS)
    original_union = union_events(follow_events)
    retained_union = union_events(retained)
    equipment, equipment_source = _method_equipment(config, method_events, seen)
    rows = []
    for method in ["A1", "IF", "A2"]:
        rows.append({"방법": method, "집계단위": "솔트조 두 센서 통합·지속조건을 통과한 후보 기록",
                     "공통판정기록수": common_total, "이상후보기록수": counts[method],
                     "후보기록비율_pct": _percent(counts[method], common_total),
                     "설비단위구간수": len(equipment[method]), "작업수": len(job_sets[method]),
                     "수치출처": "기록 수는 3·4단계 valid·qual 직접 합산; 설비 구간은 4단계 21번 표 원래 선정 결과"})
    rows.append({"방법": "IQR_60초조건", "집계단위": "솔트조 두 센서 통합·지속조건을 통과한 후보 기록",
                 "공통판정기록수": common_total, "이상후보기록수": counts["IQR_qualified"],
                 "후보기록비율_pct": _percent(counts["IQR_qualified"], common_total),
                 "설비단위구간수": len(retained_union), "작업수": len(job_sets["IQR_qualified"]),
                 "수치출처": "원래 IQR 후보·60초 선정 구간에서 공통 판정 기록만 합산"})
    save_csv(pd.DataFrame(scope_rows), output / "5-2_00_작업별_공통범위.csv")
    save_csv(pd.DataFrame(detail), output / "5-2_00_작업센서별_공통범위계산.csv")
    save_csv(pd.DataFrame(rows), output / "5-2_01_IQR_vs_A1_IF.csv")
    save_csv(retained, output / "5-2_IQR_센서구간_공통범위.csv")
    save_csv(original_union.drop(columns=["start_ns", "end_ns"]), output / "5-2_IQR_설비구간_원래범위.csv")
    save_csv(retained_union.drop(columns=["start_ns", "end_ns"]), output / "5-2_IQR_설비구간_공통범위.csv")
    save_csv(pd.DataFrame([
        {"범위": "원래6~7월", "센서단위60초구간수": len(follow_events), "설비단위구간수": len(original_union)},
        {"범위": "공통기록이남은원래구간", "센서단위60초구간수": len(retained), "설비단위구간수": len(retained_union)}
    ]), output / "5-2_01a_센서와설비_구간수구분.csv")
    save_csv(pd.DataFrame([{"방법": "IQR_지속조건적용전", "공통기록수": common_total,
                           "단일기록후보수": counts["IQR_all"],
                           "비율_pct": _percent(counts["IQR_all"], common_total),
                           "작업수": len(job_sets["IQR_all"]),
                           "설명": "60초 조건 전 수치이며, A1·IF 60초 선정 결과와 같은 조건이 아님"}]),
             output / "5-2_01b_IQR_짧은후보포함.csv")
    overlap = []
    for method, own in equipment.items():
        save_csv(own.drop(columns=["start_ns", "end_ns"]), output / f"5-2_{method}_설비구간_공통범위.csv")
        for row in own.to_dict("records"):
            other = retained_union.loc[retained_union["배정번호"].eq(row["배정번호"])]
            hit = other.loc[(other["start_ns"] < row["end_ns"]) & (other["end_ns"] > row["start_ns"])]
            overlap.append({"방법": method, "배정번호": row["배정번호"], "시작": row["시작"],
                            "종료": row["종료"], "IQR설비구간과겹침": bool(len(hit)), "겹친IQR구간수": len(hit)})
    save_csv(pd.DataFrame(overlap, columns=["방법", "배정번호", "시작", "종료", "IQR설비구간과겹침", "겹친IQR구간수"]),
             output / "5-2_IQR_방법별_구간겹침.csv")
    observations = _follow(tables["criteria"])
    observations["울타리폭_℃"] = observations["상한"] - observations["하한"]
    save_csv(observations, output / "5-2_02_작업별_IQR폭_이상치수.csv")
    representatives = tables["representatives"].copy()
    representatives["해석"] = "같은 기간 다른 작업과 대표 온도 수준이 다름; 고장 정답 아님"
    representatives["A2_솔트조후속조사작업과동일"] = representatives["배정번호"].isin(job_sets["A2"])
    save_csv(representatives, output / "5-2_03_작업대표값_IQR.csv")
    if not skip_plots:
        plots(config, output, tables["criteria"], tables["medians"], representatives, rows, common_total)

    summary = {"mode": mode, "production_result": production,
               "comparison_available": bool(common_total),
               "common_records": common_total, "raw_records": raw_total,
               "excluded_records": raw_total - common_total, "jobs": len(seen),
               "counts": counts, "iqr_qualified_records": counts["IQR_qualified"],
               "iqr_equipment_intervals": len(retained_union),
               "iqr_sensor_intervals": len(retained),
               "iqr_original_equipment_intervals": len(original_union),
               "iqr_original_sensor_intervals": len(follow_events),
               "iqr_original_candidate_records_sensor_sum": original_points,
               "equipment_intervals": {method: len(table) for method, table in equipment.items()},
               "equipment_interval_source": equipment_source,
               "iqr_overlap_equipment_intervals": {
                   method: sum(r["IQR설비구간과겹침"] for r in overlap if r["방법"] == method)
                   for method in equipment},
               "checks": {"all_iqr_timestamps_mapped": True,
                          "common_scope": "A1·A2·IF의 두 센서 valid 모두의 교집합",
                          "if_source": ("최신 4단계(300개 조건)의 저장된 IF_valid·IF_qual"
                                        if production else "검증용 입력 판정. 제출 결과가 아님"),
                          "invalid_excluded_from_numerator_and_denominator": True,
                          "duration_rule": "원래 60초 선정 유지. 공통 범위 제한 후 재선정하지 않음"},
               "interpretation": "IQR은 대안적 기술통계 비교이며 실제 고장 정답·정확도가 아님",
               "quality_xgboost_rerun": False}
    (output / "IQR_검증결과.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest = input_manifest(config)
    provenance = {"runtime": runtime_info(), "input_manifest": manifest,
                  "iqr_files": [{"path": str(Path(config["iqr"]) / name),
                                 "sha256": sha256(Path(config["iqr"]) / name)} for name in names.values()],
                  "script_sha256": sha256(Path(__file__)), "summary": summary}
    (output / "IQR_실행정보.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (output / "00_읽는방법.txt").write_text(
        "5-2 IQR 비교 결과\n"
        + ("" if production else f"검증 모드: {mode} — 제출 결과로 사용하지 않습니다.\n")
        + "\n"
        f"A1·A2·IF가 모두 판정 가능한 {common_total:,}개 기록에서 비교했습니다.\n"
        "IF 판정 가능 여부와 후보 기록은 지정된 4단계가 저장한 파일을 그대로 읽었습니다.\n"
        "IQR 원래 후보의 시각을 모두 기록별 라벨과 대조했으며, 연결되지 않은 후보를 조용히 버리지 않습니다.\n"
        "60초 조건은 원래 결과에서 선정된 조건을 유지합니다. 공통 범위로 줄어든 구간에 다시 적용하지 않습니다.\n"
        "후보 기록 비율은 후보 기록 수 ÷ 공통 판정 기록 수 × 100입니다. 판정 불가는 분자와 분모 모두 제외했습니다.\n"
        "공통 판정 기록이 0개이면 비율은 빈칸(계산 불가)입니다. 0%로 해석하지 않습니다.\n"
        "A1·A2·IF 설비 구간은 최신 4단계 21번 표의 원래 선정 구간이며, IQR은 기존 선정 구간 중 공통 기록이 남은 구간입니다.\n"
        "표의 구간 길이는 시작~종료 범위이며, 모든 순간이 후보였다는 뜻은 아닙니다.\n"
        "IQR은 작업 전체의 관측값으로 경계를 정한 사후 비교입니다. 실제 고장 정답이나 실시간 탐지 성능을 뜻하지 않습니다.\n"
        "이번 실행에는 품질 연결·XGBoost 계산이 포함되지 않습니다.\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="5단계_결과기준.txt 경로")
    parser.add_argument("--output", type=Path, required=True, help="새 5-2 결과 폴더")
    parser.add_argument("--skip-plots", action="store_true")
    args = parser.parse_args()
    summary = run(load_config(args.config), args.output, args.skip_plots)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
