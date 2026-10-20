"""저장된 기록별 A1·A2·IF 판정을 같은 범위에서 비교한다.

IF 판정 가능 여부나 점수를 다시 만들지 않는다. 3단계 ① NPZ와 최신 4단계
IF NPZ를 시각별로 대조하고, 같은 기록에서 양성·교집합·합집합을 직접 센다.
독립적인 실제 이상 정답이 없으므로 결과는 방법 사이의 겹침이다.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd

import stage5_common as common

SENSORS = {4: "솔트조 온도 1 Zone", 5: "솔트조 온도 2 Zone"}
METHODS = ("A1", "A2", "IF")
NS = 1_000_000_000
EVENT_COLUMNS = ["센서구간ID", "방법", "배정번호", "센서", "시작", "끝_미포함",
                 "원본종료_포함", "선정용길이_초", "원본후보기록수", "공통범위양성기록수"]
EQUIPMENT_COLUMNS = ["방법", "배정번호", "시작", "끝_미포함", "원센서구간ID", "센서", "설비구간ID", "범위길이_초"]
TIMELINE_COLUMNS = ["배정번호", "구분", "시작", "끝_미포함", "범위길이_초",
                    "A1_설비구간ID", "A1_원센서구간ID", "A1_센서", "IF_설비구간ID",
                    "IF_원센서구간ID", "IF_센서", "해석"]


def pct(numerator, denominator):
    """분모가 0이면 비율을 만들지 않는다."""
    return float(numerator / denominator * 100) if denominator else None


def write_json(value, path):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def path_for(config, name):
    # 공통 모듈의 경로를 사용한다. 결과 파일이 없다고 다른 버전을 골라 쓰지 않는다.
    return Path(config.get("paths", config)[name])


def bool_array(source, key, n):
    arr = np.asarray(source[key])
    if arr.shape != (n,) or not np.isin(arr, [False, True]).all():
        raise ValueError(f"{key}: 길이가 맞는 0/1 판정 배열이 아닙니다.")
    return arr.astype(bool, copy=False)


def union_events(events):
    """센서별 구간을 팀 규칙(포함 종료~다음 시작 2초 이내)으로 묶는다."""
    output = []
    if events.empty:
        return pd.DataFrame(columns=EQUIPMENT_COLUMNS)
    for (method, job), group in events.groupby(["방법", "배정번호"], sort=True):
        merged = []
        for r in group.sort_values(["시작", "끝_미포함"]).to_dict("records"):
            if merged and r["시작"] <= merged[-1]["끝_미포함"] + pd.Timedelta(seconds=1):
                merged[-1]["끝_미포함"] = max(merged[-1]["끝_미포함"], r["끝_미포함"])
                merged[-1]["원센서구간ID"].append(r["센서구간ID"])
                merged[-1]["센서"].add(r["센서"])
            else:
                merged.append({"방법": method, "배정번호": int(job), "시작": r["시작"],
                               "끝_미포함": r["끝_미포함"], "원센서구간ID": [r["센서구간ID"]], "센서": {r["센서"]}})
        for r in merged:
            r["설비구간ID"] = f"{method}-E{sum(x['방법'] == method for x in output) + 1:03d}"
            r["원센서구간ID"] = "|".join(r["원센서구간ID"])
            r["센서"] = "|".join(sorted(r["센서"]))
            r["범위길이_초"] = (r["끝_미포함"] - r["시작"]).total_seconds()
            output.append(r)
    return pd.DataFrame(output, columns=EQUIPMENT_COLUMNS)


def load_equipment(config, events):
    """최신 4단계가 저장한 설비 구간을 유지하고 센서 원구간의 포함을 검사한다."""
    path = path_for(config, "stage4") / "21_설비단위_방법별구간.csv"
    if not path.is_file() and config.get("mode") != "production":
        # 오래된 자료로 코드만 시험할 때의 명시적인 대체. 제출 실행에서는 허용하지 않는다.
        return union_events(events), "시험 입력에 21번표 없음: 2초 연결 규칙으로 센서 구간 합침"
    source = common.read_csv(path)
    required = {"method", "배정번호", "start_time", "end_time", "설비"}
    if not required.issubset(source.columns):
        raise ValueError(f"{path}: 필요한 열이 없습니다: {required - set(source.columns)}")
    source = source[(source["설비"] == "솔트조") & source["method"].isin(METHODS)].copy()
    rows, counters = [], {m: 0 for m in METHODS}
    covered = {event_id: 0 for event_id in events["센서구간ID"]}
    for row in source.sort_values(["method", "배정번호", "start_time", "end_time"]).to_dict("records"):
        method, job = row["method"], int(row["배정번호"])
        left, right = pd.Timestamp(row["start_time"]), pd.Timestamp(row["end_time"]) + pd.Timedelta(seconds=1)
        parents = events[(events["방법"] == method) & (events["배정번호"] == job) & (events["시작"] >= left) & (events["끝_미포함"] <= right)]
        if parents.empty:
            raise ValueError(f"21번표 {method}/{job}/{left}: 포함되는 센서 원구간이 없습니다.")
        for event_id in parents["센서구간ID"]:
            covered[event_id] += 1
        counters[method] += 1
        rows.append({"방법": method, "배정번호": job, "시작": left, "끝_미포함": right,
                     "원센서구간ID": "|".join(parents["센서구간ID"]), "센서": "|".join(sorted(set(parents["센서"]))),
                     "설비구간ID": f"{method}-E{counters[method]:03d}", "범위길이_초": (right - left).total_seconds()})
    if any(count != 1 for count in covered.values()):
        raise ValueError("21번 설비 구간표가 모든 센서 원구간을 정확히 한 번 포함하지 않습니다.")
    result = pd.DataFrame(rows, columns=EQUIPMENT_COLUMNS)
    for (method, job), group in result.groupby(["방법", "배정번호"]):
        ordered = group.sort_values("시작")
        starts, ends = list(ordered["시작"]), list(ordered["끝_미포함"])
        if any(start < end for start, end in zip(starts[1:], ends[:-1])):
            raise ValueError(f"21번표 {method}/{job}: 같은 방법의 설비 구간이 서로 겹칩니다.")
    return result, str(path)


def split_timeline(equipment):
    """A1·IF 구간을 모든 경계에서 자른다. 기록별 양성과는 별도 계산이다."""
    output = []
    relevant = equipment[equipment["방법"].isin(["A1", "IF"])]
    for job, group in relevant.groupby("배정번호", sort=True):
        edges = sorted(set(group["시작"]) | set(group["끝_미포함"]))
        for left, right in zip(edges[:-1], edges[1:]):
            active = group[(group["시작"] <= left) & (group["끝_미포함"] >= right)]
            methods = set(active["방법"])
            if not methods:
                continue
            category = "공통" if methods == {"A1", "IF"} else next(iter(methods)) + "만"
            row = {"배정번호": int(job), "구분": category, "시작": left, "끝_미포함": right,
                   "범위길이_초": (right - left).total_seconds()}
            for method in ("A1", "IF"):
                a = active[active["방법"] == method]
                for suffix in ("설비구간ID", "원센서구간ID", "센서"):
                    row[f"{method}_{suffix}"] = "|".join(a[suffix].astype(str))
            row["해석"] = "두 방법의 구간 시간범위가 겹침; 실제 이상 정답이 아님" if category == "공통" else "한 방법만 선정한 시간범위; 오탐·미탐으로 단정하지 않음"
            if category == "공통" and not set(row["A1_센서"].split("|")).intersection(row["IF_센서"].split("|")):
                row["해석"] = "서로 다른 센서의 설비 시간범위 겹침; 같은 센서의 판정 일치와 다름"
            output.append(row)
    return pd.DataFrame(output, columns=TIMELINE_COLUMNS)


def overlap_intervals(timeline):
    """연속된 공통 시간조각을 합쳐 공통 구간 수를 센다."""
    result = []
    for job, group in timeline[timeline["구분"] == "공통"].groupby("배정번호", sort=True):
        merged = []
        for r in group.sort_values("시작").to_dict("records"):
            if merged and r["시작"] <= merged[-1]["끝_미포함"]:
                merged[-1]["끝_미포함"] = max(merged[-1]["끝_미포함"], r["끝_미포함"])
            else:
                merged.append({"배정번호": int(job), "시작": r["시작"], "끝_미포함": r["끝_미포함"]})
        result.extend(merged)
    return result


def export_times(table):
    result = table.copy()
    for name in ("시작", "끝_미포함", "원본종료_포함"):
        if name in result:
            result[name] = result[name].map(lambda x: pd.Timestamp(x).isoformat(sep=" "))
    return result


def load_events(config, aligned):
    """구간은 3·4단계가 저장한 원표를 읽고 NPZ와 행별로 검산한다.

    qual 배열의 연속 참값만 새 구간으로 묶으면, 원래 구간 안의 비후보 기록
    때문에 구간이 잘리는 문제가 생긴다. 따라서 원표의 시작·끝을 유지한다.
    """
    paths = {
        # 팀 4단계와 동일하게 구간표는 ②, 기록별 판정은 ①을 읽고 일치 여부를 확인한다.
        "A": path_for(config, "stage3_b") / "03_A1_A2_이상이벤트.csv",
        "IF": path_for(config, "stage4") / "07_6_7월_IF_우선조사구간.csv",
    }
    tables = {k: common.read_csv(v) for k, v in paths.items()}
    job_ids = set(aligned)
    raw_rows = []
    for source_name, table in tables.items():
        required = {"배정번호", "sensor", "start_time", "end_time", "duration_sec", "anomaly_sample_count"}
        if source_name == "A":
            required.add("method")
        if not required.issubset(table.columns):
            raise ValueError(f"{paths[source_name]}: 필요한 열이 없습니다: {sorted(required - set(table.columns))}")
        table = table[table["배정번호"].astype(int).isin(job_ids) & table["sensor"].isin(SENSORS.values())]
        if source_name == "A":
            table = table[table["method"].isin(["A1", "A2"])]
        for row in table.to_dict("records"):
            row["_method"] = row["method"] if source_name == "A" else "IF"
            raw_rows.append(row)
    raw_rows.sort(key=lambda r: (r["_method"], int(r["배정번호"]), r["start_time"], r["sensor"]))
    covered = {(job, method, i): np.zeros(len(a["t"]), dtype=bool)
               for job, a in aligned.items() for method in METHODS for i in SENSORS}
    rows, checks, counters = [], [], {m: 0 for m in METHODS}
    seen_events = set()
    for row in raw_rows:
        method, job = row["_method"], int(row["배정번호"])
        sensor_id = next(i for i, name in SENSORS.items() if name == row["sensor"])
        left, end = pd.Timestamp(row["start_time"]), pd.Timestamp(row["end_time"])
        key = (method, job, sensor_id, left.value, end.value)
        if key in seen_events:
            raise ValueError(f"중복 센서 구간: {key}")
        seen_events.add(key)
        if end < left:
            raise ValueError(f"종료가 시작보다 빠릅니다: {key}")
        a = aligned[job]
        z = a["z4"] if method == "IF" else a["z3"]
        times = a["t"]
        inside = (times >= left.value) & (times <= end.value)
        qual = bool_array(z, f"{method}_{sensor_id}_qual", len(times))
        expected_count = int(row["anomaly_sample_count"])
        if expected_count < 1 or expected_count != float(row["anomaly_sample_count"]):
            raise ValueError(f"{key}: 원표 후보기록수는 양의 정수여야 합니다.")
        got_count = int((inside & qual).sum())
        if got_count != expected_count:
            raise ValueError(f"{key}: 구간 표 후보 {expected_count}개와 NPZ qual {got_count}개가 다릅니다.")
        if left.value not in times or end.value not in times:
            raise ValueError(f"{key}: 구간의 시작·끝이 실제 기록 시각에 없습니다.")
        endpoints = np.searchsorted(times, [left.value, end.value])
        if not qual[endpoints].all():
            raise ValueError(f"{key}: 구간 시작·끝이 저장된 양성 기록이 아닙니다.")
        candidate_key = f"{method}_{sensor_id}_cand"
        candidate_check = None
        if candidate_key in z:
            cand = bool_array(z, candidate_key, len(times))
            if not np.array_equal(cand & inside, qual & inside):
                raise ValueError(f"{key}: 선정 구간 안 후보 기록과 qual 기록이 다릅니다.")
            candidate_check = True
        duration = (end - left).total_seconds() + 1
        if duration < 60 or not np.isclose(duration, float(row["duration_sec"])):
            raise ValueError(f"{key}: 선정용 길이는 마지막−첫 시각+1초여야 합니다.")
        if (inside & qual & covered[(job, method, sensor_id)]).any():
            raise ValueError(f"{key}: 같은 센서의 원구간들이 같은 양성 기록을 중복 포함합니다.")
        covered[(job, method, sensor_id)] |= inside
        counters[method] += 1
        event_id = f"{method}-S{counters[method]:03d}"
        rows.append({"센서구간ID": event_id, "방법": method, "배정번호": job, "센서": row["sensor"],
                     "시작": left, "끝_미포함": end + pd.Timedelta(seconds=1), "원본종료_포함": end,
                     "선정용길이_초": duration, "원본후보기록수": expected_count,
                     "공통범위양성기록수": int((inside & qual & a["mask"]).sum())})
        checks.append({"센서구간ID": event_id, "배정번호": job, "방법": method, "센서": row["sensor"],
                       "원표후보기록수": expected_count, "NPZ양성기록수": got_count,
                       "후보배열검증": candidate_check, "시작끝양성검증": True, "선정길이검증": True})
    for (job, method, sensor_id), cov in covered.items():
        a = aligned[job]
        z = a["z4"] if method == "IF" else a["z3"]
        qual = bool_array(z, f"{method}_{sensor_id}_qual", len(a["t"]))
        if (qual & ~cov).any():
            raise ValueError(f"{job}/{method}/{sensor_id}: 구간 표에 없는 양성 기록이 있습니다.")
    check_columns = ["센서구간ID", "배정번호", "방법", "센서", "원표후보기록수", "NPZ양성기록수", "후보배열검증", "시작끝양성검증", "선정길이검증"]
    return pd.DataFrame(rows, columns=EVENT_COLUMNS), pd.DataFrame(checks, columns=check_columns), paths


def aggregate_records(config):
    """요약 CSV의 숫자를 가져오지 않고 NPZ 배열에서 직접 계산한다."""
    aligned, rows, points = {}, [], []
    totals = {m: 0 for m in METHODS}
    exposures = {m: 0.0 for m in METHODS}
    intersections = {f"{a}_{b}": 0 for a, b in itertools.combinations(METHODS, 2)}
    if_valid = {str(i): 0 for i in SENSORS}
    if_cand = {str(i): 0 for i in SENSORS}
    if_qual = {str(i): 0 for i in SENSORS}
    if_common_qual = {str(i): 0 for i in SENSORS}
    same_sensor = {str(i): 0 for i in SENSORS}
    total_common = total_rows = 0
    eligible_seconds = common_seconds = 0.0
    for job, t, z3, z4, provided_mask in common.iter_aligned(config):
        job, t = int(job), np.asarray(t, dtype=np.int64)
        if job in aligned:
            raise ValueError(f"{job}: 같은 작업이 두 번 전달되었습니다.")
        if t.ndim != 1 or not len(t) or np.any(np.diff(t) <= 0):
            raise ValueError(f"{job}: 기록 시각은 중복 없이 오름차순이어야 합니다.")
        n = len(t)
        valid = {m: {i: bool_array(z4 if m == "IF" else z3, f"{m}_{i}_valid", n) for i in SENSORS} for m in METHODS}
        qual = {m: {i: bool_array(z4 if m == "IF" else z3, f"{m}_{i}_qual", n) for i in SENSORS} for m in METHODS}
        mask = np.logical_and.reduce([valid[m][i] for m in METHODS for i in SENSORS])
        if not np.array_equal(mask, np.asarray(provided_mask, dtype=bool)):
            raise ValueError(f"{job}: 공통 마스크가 A1·A2·IF 두 센서 valid 교집합과 다릅니다.")
        for m in METHODS:
            for i in SENSORS:
                if (qual[m][i] & ~valid[m][i]).any():
                    raise ValueError(f"{job}/{m}/{i}: 판정 불가 기록에 양성이 있습니다.")
        positive = {m: mask & (qual[m][4] | qual[m][5]) for m in METHODS}
        dt = np.diff(t) / NS
        # 기존 4단계와 동일하게 앞 기록의 공통 판정 상태를 시간 조각에 적용한다.
        # 다음 기록까지의 실제 간격이 5초 이하인 조각만 사용하고 마지막 기록은 0초다.
        piece = mask[:-1] & (dt > 0) & (dt <= 5)
        seconds = float(dt[piece].sum())
        shared = positive["A1"] & positive["IF"]
        shared_seconds = float(dt[piece & shared[:-1]].sum())
        row = {"배정번호": job, "첫기록시각": str(pd.Timestamp(t[0])), "관측기록수": n,
               "공통판정기록수": int(mask.sum()), "제외기록수": int((~mask).sum()),
               "공통판정가능시간_초": seconds, "A1_IF공통양성기록수": int(shared.sum()),
               "A1만_양성기록수": int((positive["A1"] & ~positive["IF"]).sum()),
               "IF만_양성기록수": int((positive["IF"] & ~positive["A1"]).sum()),
               "공통양성노출시간_초": shared_seconds}
        for m in METHODS:
            count, exposure = int(positive[m].sum()), float(dt[piece & positive[m][:-1]].sum())
            totals[m] += count
            exposures[m] += exposure
            row[f"{m}_양성기록수"] = count
            row[f"{m}_양성노출시간_초"] = exposure
        for a, b in itertools.combinations(METHODS, 2):
            intersections[f"{a}_{b}"] += int((positive[a] & positive[b]).sum())
        for i in SENSORS:
            cand = bool_array(z4, f"IF_{i}_cand", n)
            score = np.asarray(z4[f"IF_{i}_score"])
            if score.shape != (n,) or not np.isfinite(score[valid["IF"][i]]).all():
                raise ValueError(f"{job}/IF/{i}: 판정 가능한 기록의 점수가 유한하지 않습니다.")
            if (cand & ~valid["IF"][i]).any() or (qual["IF"][i] & ~cand).any():
                raise ValueError(f"{job}/IF/{i}: qual ⊆ cand ⊆ valid 조건을 만족하지 않습니다.")
            values = [int(valid["IF"][i].sum()), int(cand.sum()), int(qual["IF"][i].sum()), int((qual["IF"][i] & mask).sum())]
            for total, value in zip((if_valid, if_cand, if_qual, if_common_qual), values):
                total[str(i)] += value
            for name, value in zip(("판정가능", "후보", "구간선정양성", "공통범위양성"), values):
                row[f"IF_{i}_{name}기록수"] = value
            same = int((mask & qual["A1"][i] & qual["IF"][i]).sum())
            same_sensor[str(i)] += same
            row[f"A1_IF_{i}_동일센서공통양성기록수"] = same
        selected = positive["A1"] | positive["A2"] | positive["IF"]
        frame = pd.DataFrame({"배정번호": job, "TAG_MIN": pd.to_datetime(t[selected]),
                              **{f"{m}_설비양성": positive[m][selected] for m in METHODS},
                              **{f"{m}_{i}_양성": qual[m][i][selected] for m in METHODS for i in SENSORS}})
        points.append(frame)
        total_common += int(mask.sum())
        total_rows += n
        eligible_seconds += seconds
        common_seconds += shared_seconds
        rows.append(row)
        aligned[job] = {"t": t, "z3": z3, "z4": z4, "mask": mask}
    if not aligned:
        raise ValueError("6~7월의 정렬된 기록별 판정을 찾지 못했습니다.")
    both = intersections["A1_IF"]
    summary = {"total_common": total_common, "total_rows": total_rows, "job_count": len(aligned),
               "counts": totals, "intersection": both, "pair_intersections": intersections,
               "onlyA1": totals["A1"] - both, "onlyIF": totals["IF"] - both,
               "union": totals["A1"] + totals["IF"] - both,
               "same_sensor_common": same_sensor, "if_valid_by_sensor": if_valid,
               "if_cand_by_sensor": if_cand, "if_qual_by_sensor": if_qual,
               "if_common_qual_by_sensor": if_common_qual, "eligible_seconds": eligible_seconds,
               "positive_seconds": exposures, "positive_common_seconds": common_seconds}
    if summary["intersection"] + summary["onlyA1"] != totals["A1"] or summary["intersection"] + summary["onlyIF"] != totals["IF"]:
        raise AssertionError("교집합과 단독 기록의 합계가 각 방법 양성 기록 수와 다릅니다.")
    summary["jaccard_pct"] = pct(both, summary["union"])
    return summary, pd.DataFrame(rows), pd.concat(points, ignore_index=True), aligned


def pair_comparisons(summary, equipment, aligned):
    rows = []
    for a, b in itertools.combinations(METHODS, 2):
        an, bn = summary["counts"][a], summary["counts"][b]
        shared = summary["pair_intersections"][f"{a}_{b}"]
        ea, eb = equipment[equipment["방법"] == a], equipment[equipment["방법"] == b]
        hits_a, hits_b, overlap_pairs = set(), set(), 0
        positive_hits_a, positive_hits_b, positive_pairs, positive_jobs = set(), set(), 0, set()
        for ar in ea.to_dict("records"):
            for br in eb.to_dict("records"):
                if ar["배정번호"] == br["배정번호"] and ar["시작"] < br["끝_미포함"] and br["시작"] < ar["끝_미포함"]:
                    hits_a.add(ar["설비구간ID"])
                    hits_b.add(br["설비구간ID"])
                    overlap_pairs += 1
                    data = aligned[int(ar["배정번호"])]
                    za = data["z4"] if a == "IF" else data["z3"]
                    zb = data["z4"] if b == "IF" else data["z3"]
                    qa = np.asarray(za[f"{a}_4_qual"]) | np.asarray(za[f"{a}_5_qual"])
                    qb = np.asarray(zb[f"{b}_4_qual"]) | np.asarray(zb[f"{b}_5_qual"])
                    left, right = max(ar["시작"], br["시작"]), min(ar["끝_미포함"], br["끝_미포함"])
                    both = data["mask"] & qa & qb & (data["t"] >= left.value) & (data["t"] < right.value)
                    if both.any():
                        positive_hits_a.add(ar["설비구간ID"])
                        positive_hits_b.add(br["설비구간ID"])
                        positive_pairs += 1
                        positive_jobs.add(int(ar["배정번호"]))
        rows.append({"방법A": a, "방법B": b, "공통판정기록수": summary["total_common"],
                     "A_양성기록수": an, "B_양성기록수": bn, "공통양성기록수": shared,
                     "A만_양성기록수": an - shared, "B만_양성기록수": bn - shared,
                     "기록_Jaccard_pct": pct(shared, an + bn - shared),
                     "A기준_기록겹침_pct": pct(shared, an), "B기준_기록겹침_pct": pct(shared, bn),
                     "A_설비구간수": len(ea), "B_설비구간수": len(eb),
                     "시간범위가겹친_설비구간쌍수": overlap_pairs,
                     "A_겹친설비구간수": len(hits_a), "B_겹친설비구간수": len(hits_b),
                     "공통양성기록이있는_설비구간쌍수": positive_pairs,
                     "공통양성기록이있는_A구간수": len(positive_hits_a), "공통양성기록이있는_B구간수": len(positive_hits_b),
                     "공통양성작업수": len(positive_jobs), "공통양성작업목록": ", ".join(map(str, sorted(positive_jobs))),
                     "해석": "저장된 기록별 판정의 겹침과 원표 구간 시간범위의 겹침; 실제 이상 정답 대비 성능 아님"})
    return pd.DataFrame(rows)


def choose_cases(by_job, timeline, fixed=None):
    """분류별 1사례: 단독은 상대 방법이 해당 작업 전체에서 양성이 없는 작업을 우선한다.

    fixed: {'A1만': 140314}처럼 분류별로 지정한 작업(5단계_결과기준.txt [사례]).
    발표 영상·보고서와 같은 사례를 쓰기 위한 것이며, 지정한 작업에 그 분류 기록이 없으면 멈춘다.
    """
    fixed = fixed or {}
    chosen = []
    for category, column, other in (("공통", "A1_IF공통양성기록수", None),
                                    ("A1만", "A1만_양성기록수", "IF_양성기록수"),
                                    ("IF만", "IF만_양성기록수", "A1_양성기록수")):
        candidates = by_job[by_job[column] > 0].copy()
        possible = set(timeline[timeline["구분"] == category]["배정번호"].astype(int))
        candidates = candidates[candidates["배정번호"].isin(possible)]
        if category in fixed:
            pick = candidates[candidates["배정번호"].astype(int) == int(fixed[category])]
            if pick.empty:
                raise ValueError(f"[사례] {category}={fixed[category]}: 이 작업에는 '{category}' 기록이 없습니다.")
            row = pick.iloc[0]
            chosen.append({"배정번호": int(row["배정번호"]), "분류": category,
                           "분류기록수": int(row[column]),
                           "선정방법": "5단계_결과기준.txt [사례]에서 지정(발표 영상·보고서와 같은 사례)"})
            continue
        if candidates.empty:
            continue
        preferred = candidates[candidates[other] == 0] if other else candidates
        if not preferred.empty:
            candidates = preferred
        row = candidates.sort_values([column, "배정번호"], ascending=[False, True]).iloc[0]
        chosen.append({"배정번호": int(row["배정번호"]), "분류": category,
                       "분류기록수": int(row[column]),
                       "선정방법": "분류 기록이 있는 작업 중 기록 수가 가장 많은 작업; 단독은 상대 방법 양성이 없는 작업 우선; 동률은 작은 번호"})
    return chosen


def case_baseline(times, values):
    """그림 해석용 A1 기준선. 저장 판정 자체는 바꾸지 않는다."""
    segment = np.cumsum(np.r_[True, np.diff(times.as_unit("ns").asi8) > 60 * NS])
    result = np.full(len(times), np.nan)
    for sid in np.unique(segment):
        ix = np.flatnonzero(segment == sid)
        result[ix] = pd.Series(values[ix], index=times[ix]).rolling("600s", closed="left", min_periods=300).median().to_numpy()
    return result


def broken_line(times, values):
    xs, ys = [], []
    previous = None
    for t, value in zip(times, values):
        if previous is not None and (t - previous).total_seconds() > 5:
            xs.append(t)
            ys.append(np.nan)
        xs.append(t)
        ys.append(value)
        previous = t
    return xs, ys


def make_plots(config, output, cases, events, equipment, timeline, aligned):
    if not cases:
        return []
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib import font_manager
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    for font in (Path("C:/Windows/Fonts/malgun.ttf"), Path("/usr/share/fonts/truetype/nanum/NanumGothic.ttf")):
        if font.exists():
            font_manager.fontManager.addfont(str(font))
            plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(font)).get_name()
            break
    plt.rcParams.update({"axes.unicode_minus": False, "font.size": 11, "savefig.facecolor": "white"})
    colors = {"A1": "#2563EB", "IF": "#9333EA", "공통": "#059669"}
    raw = common.raw_jobs(config, sorted({r["배정번호"] for r in cases}))
    figdir = output / "figures"
    figdir.mkdir(exist_ok=True)
    metadata = []
    for number, case in enumerate(cases, 1):
        job, category = case["배정번호"], case["분류"]
        data = raw[job].sort_values("TAG_MIN", kind="stable")
        times = pd.DatetimeIndex(pd.to_datetime(data["TAG_MIN"]))
        times_ns = times.as_unit("ns").asi8
        if not np.array_equal(times_ns, aligned[job]["t"]):
            raise ValueError(f"{job}: 원본 CSV와 기록별 판정의 시각 배열이 다릅니다.")
        focus = timeline[(timeline["배정번호"] == job) & (timeline["구분"] == category)].sort_values("범위길이_초", ascending=False).iloc[0]
        left, right = focus["시작"] - pd.Timedelta(minutes=4), focus["끝_미포함"] + pd.Timedelta(minutes=5)
        keep = (times >= left) & (times <= right)
        frame = pd.DataFrame({"TAG_MIN": times[keep]})
        fig, axes = plt.subplots(3, 1, figsize=(13.2, 8.6), sharex=True, gridspec_kw={"height_ratios": [2.5, 2.5, 1.4]})
        for ax, (i, sensor) in zip(axes[:2], SENSORS.items()):
            values = pd.to_numeric(data[sensor], errors="coerce").to_numpy(dtype=float)
            baseline = case_baseline(times, values)
            ax.plot(*broken_line(times[keep], values[keep]), color="#263445", lw=1.3)
            ax.plot(*broken_line(times[keep], baseline[keep]), color="#E88924", lw=1.6)
            for r in events[(events["배정번호"] == job) & (events["센서"] == sensor) & events["방법"].isin(["A1", "IF"])].to_dict("records"):
                ax.axvspan(r["시작"], r["끝_미포함"], color=colors[r["방법"]], alpha=.13)
            ax.set_ylabel("온도 (℃)")
            ax.set_title(sensor, loc="left", fontsize=12, fontweight="bold")
            ax.grid(color="#E8ECF0", lw=.6)
            frame[sensor] = values[keep]
            frame[f"{sensor}_과거10분중앙값"] = baseline[keep]
            for method, z in (("A1", aligned[job]["z3"]), ("IF", aligned[job]["z4"])):
                frame[f"{method}_{i}_qual"] = np.asarray(z[f"{method}_{i}_qual"])[keep]
            frame["공통판정가능"] = aligned[job]["mask"][keep]
        ax = axes[2]
        for ypos, method in ((2, "A1"), (1, "IF")):
            for r in equipment[(equipment["배정번호"] == job) & (equipment["방법"] == method)].to_dict("records"):
                ax.broken_barh([(mdates.date2num(r["시작"]), (r["끝_미포함"] - r["시작"]).total_seconds() / 86400)], (ypos - .28, .56), facecolors=colors[method])
        for r in timeline[timeline["배정번호"] == job].to_dict("records"):
            color = colors["공통"] if r["구분"] == "공통" else colors[r["구분"].replace("만", "")]
            ax.broken_barh([(mdates.date2num(r["시작"]), r["범위길이_초"] / 86400)], (-.28, .56), facecolors=color)
        ax.set_yticks([0, 1, 2], ["시간범위 분해", "IF 설비 구간", "A1 설비 구간"])
        ax.set_ylim(-.7, 2.7)
        ax.set_xlim(left, right)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=9))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        ax.set_xlabel(f"실제 기록 시각 · {times[0]:%Y-%m-%d}")
        ax.grid(axis="x", color="#E8ECF0", lw=.6)
        for a in axes:
            a.spines[["top", "right"]].set_visible(False)
        fig.suptitle(f"{number:02d}  {category} 사례  |  배정번호 {job}", x=.09, ha="left", y=.97, fontsize=18, fontweight="bold")
        handles = [Line2D([0], [0], color="#263445", lw=1.5, label="실제 원본 온도"),
                   Line2D([0], [0], color="#E88924", lw=1.8, label="과거 10분 중앙값"),
                   *[Patch(color=colors[m], label=m) for m in ("A1", "IF", "공통")]]
        fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(.085, .925), frameon=False, ncol=5, fontsize=10)
        fig.text(.09, .025, "음영·띠는 구간의 시간범위이며, 안의 모든 기록이 양성이라는 뜻은 아닙니다. 공통도 실제 이상 정답은 아닙니다.\n원본의 결측은 유지하며 선은 5초 초과 공백에서 끊었습니다. 과거 중앙값은 그림 해석용이며 저장된 판정을 수정하지 않습니다.", fontsize=9, color="#495568", va="bottom", linespacing=1.6)
        fig.subplots_adjust(left=.09, right=.975, top=.85, bottom=.14, hspace=.4)
        name = f"{number:02d}_{category}_{job}.png"
        fig.savefig(figdir / name, dpi=240)
        plt.close(fig)
        common.save_csv(frame, output / f"사례{number:02d}_{job}_그래프원본값.csv")
        metadata.append({**case, "원본시각_NPZ시각일치": True, "원본작업기록수": len(times),
                         "표시기록수": int(keep.sum()), "그림": f"figures/{name}"})
    return metadata


def mainrun(config, output, skip_plots=False):
    missing = common.readiness(config, include_raw=not skip_plots, scope="main")
    if missing:
        raise FileNotFoundError("5-1 실행에 필요한 입력이 준비되지 않았습니다.\n" + "\n".join(missing))
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    mode = config.get("mode", "production")
    production = mode == "production"
    if_source = "최신 4단계(과거 유효 기록 300개 조건)" if production else "시험용 4단계 입력(최신 제출 결과로 사용하지 않음)"
    summary, by_job, point_table, aligned = aggregate_records(config)
    events, event_checks, event_paths = load_events(config, aligned)
    equipment, equipment_source = load_equipment(config, events)
    timeline = split_timeline(equipment)
    common_intervals = overlap_intervals(timeline)
    summary["sensor_counts"] = {m: int((events["방법"] == m).sum()) for m in METHODS}
    summary["equipment_counts"] = {m: int((equipment["방법"] == m).sum()) for m in METHODS}
    summary["range_overlap_interval_count"] = len(common_intervals)
    summary["range_overlap_jobs"] = sorted({r["배정번호"] for r in common_intervals})
    summary["range_common_seconds"] = float(timeline.loc[timeline["구분"] == "공통", "범위길이_초"].sum())
    summary["sensor_events_without_common_positive"] = int((events["공통범위양성기록수"] == 0).sum())
    summary["if_equipment_intervals"] = export_times(equipment[equipment["방법"] == "IF"])[["배정번호", "시작", "끝_미포함", "범위길이_초"]].to_dict("records")
    for method in ("A1", "IF"):
        original = equipment.loc[equipment["방법"] == method, "범위길이_초"].sum()
        decomposed = timeline.loc[timeline["구분"].isin([method + "만", "공통"]), "범위길이_초"].sum()
        if not np.isclose(original, decomposed):
            raise AssertionError(f"{method}: 시간범위 분해 전후 길이가 다릅니다.")
    pairs = pair_comparisons(summary, equipment, aligned)
    a1if = pairs[(pairs["방법A"] == "A1") & (pairs["방법B"] == "IF")].iloc[0]
    summary["common_interval_count"] = int(a1if["공통양성기록이있는_설비구간쌍수"])
    summary["common_A1_interval_count"] = int(a1if["공통양성기록이있는_A구간수"])
    summary["common_IF_interval_count"] = int(a1if["공통양성기록이있는_B구간수"])
    summary["common_jobs"] = [int(v.strip()) for v in str(a1if["공통양성작업목록"]).split(",") if v.strip()]
    summary["equipment_source"] = equipment_source
    methods = pd.DataFrame([
        {"방법": "A1", "입력판정": "3단계 ① 기록별 A1_valid·A1_qual", "이번처리": "저장 판정 직접 합산", "해석": "같은 작업의 최근 흐름과 비교한 조사 후보"},
        {"방법": "A2", "입력판정": "3단계 ① 기록별 A2_valid·A2_qual", "이번처리": "저장 판정 직접 합산", "해석": "앞선 작업의 고정 온도 수준과 비교한 조사 후보"},
        {"방법": "IF", "입력판정": f"{if_source}의 저장 IF_valid·score·cand·qual", "이번처리": "판정 가능 여부·점수·후보를 다시 계산하지 않음", "해석": "여러 입력 특성의 조합이 다른 조사 후보"},
    ])
    metrics = pd.DataFrame([{"방법": m, "공통분모_기록수": summary["total_common"],
                             "우선조사_양성기록수": summary["counts"][m],
                             "기록비율_pct": pct(summary["counts"][m], summary["total_common"]),
                             "공통분모_노출초": summary["eligible_seconds"],
                             "우선조사_노출초": summary["positive_seconds"][m],
                             "노출비율_pct": pct(summary["positive_seconds"][m], summary["eligible_seconds"])} for m in METHODS])
    overlaps = pd.DataFrame([{"항목": name, "기록수": value, "전체공통기록대비_pct": pct(value, summary["total_common"])}
                             for name, value in (("공통 양성", summary["intersection"]), ("A1만 양성", summary["onlyA1"]),
                                                 ("IF만 양성", summary["onlyIF"]), ("양성 합집합", summary["union"]))])
    for table, name in ((methods, "01_방법과평가범위.csv"), (by_job, "02_작업별_기록단위검산.csv"),
                        (metrics, "03_방법별_공통분모_기록및노출비율.csv"), (overlaps, "04_A1_IF_기록겹침.csv"),
                        (export_times(events), "05_원센서_조사구간.csv"), (export_times(equipment), "06_설비합집합_조사구간.csv"),
                        (export_times(timeline), "07_시간경계분해_공통_A1만_IF만.csv"),
                        (export_times(timeline[timeline["구분"] == "공통"]), "08_설비공통구간_센서차이설명.csv"),
                        (event_checks, "09_원구간표_NPZ검산.csv"), (pairs, "12_전체방법쌍_기록및설비구간_비교.csv"),
                        (point_table, "13_공통범위_양성기록목록.csv")):
        common.save_csv(table, output / name)
    cases = choose_cases(by_job, timeline, config.get("fixed_cases"))
    common.save_csv(pd.DataFrame(cases, columns=["배정번호", "분류", "분류기록수", "선정방법"]), output / "14_대표사례_선정근거.csv")
    plots = [] if skip_plots else make_plots(config, output, cases, events, equipment, timeline, aligned)
    summary["plots"] = plots
    summary["output"] = str(output)
    summary["mode"] = mode
    summary["submission_result"] = production
    summary["record_input"] = f"3단계 ① NPZ와 {if_source} NPZ의 실제 기록별 판정"
    summary["independent_ground_truth"] = False
    write_json(summary, output / "요약.json")
    manifest = common.input_manifest(config)
    metadata = {"실행시각": datetime.now().isoformat(timespec="seconds"), "실행환경": common.runtime_info(), "실행모드": mode, "제출결과여부": production,
                "코드_SHA256": common.sha256(Path(__file__)), "입력": manifest,
                "원구간표_SHA256": {key: common.sha256(value) for key, value in event_paths.items()},
                "설비구간출처": equipment_source,
                "모델재학습": False, "IF판정재계산": False,
                "공통범위": "A1·A2·IF 각 솔트조 2센서 valid 배열 6개의 교집합",
                "판정불가": "기록 비율 분자·분모에서 모두 제외",
                "시간범위": "원표의 [첫 후보 시각, 마지막 후보 시각+1초); 중간 비후보·공백을 포함할 수 있음",
                "구간비교범위": "3·4단계 원표의 선정 구간을 유지; 공통 기록 범위와 별개로 원구간 및 공통 범위 양성 수를 함께 제시",
                "양성노출시간": "앞 기록이 공통 판정 가능하고 다음 기록까지 간격이 5초 이하인 시간조각에 앞 기록의 판정을 적용; 마지막 기록 0초",
                "기간": "작업 첫 기록이 6~7월인 작업 전체; 이전 탐색 이력이 있는 후속 비교",
                "검증": {"배열공통범위일치": True, "양성부분집합조건": True, "기록항등식": True,
                         "구간표_양성배열일치": True, "원구간누락없음": True, "시간범위분해보존": True},
                "사례그림": plots}
    write_json(metadata, output / "실행정보_검증.json")
    jaccard = "계산하지 않음(합집합 0)" if summary["jaccard_pct"] is None else f"{summary['jaccard_pct']:.4f}%"
    text = f"""5-1 결과 읽기 — 저장된 기록별 판정으로 같은 자료에서 비교
{'제출용 최신 입력에 대한 결과입니다.' if production else '시험 실행입니다. 아래 수치는 코드 동작 확인용이며 최신 제출·발표 결과로 사용하지 않습니다.'}

1. 이번에 한 일
3단계 ①의 A1·A2 판정과 {if_source}의 IF 기록별 판정을 같은 시각끼리 맞췄습니다.
IF의 판정 가능 여부나 점수를 5단계에서 새로 계산하지 않았습니다.
두 센서에서 세 방법이 모두 판정 가능한 {summary['total_common']:,}개 기록만 함께 비교했습니다.
판정할 수 없는 기록은 비율의 분자와 분모에서 모두 뺐습니다.

2. 실제 기록별로 센 결과
A1: {summary['counts']['A1']:,}개 / IF: {summary['counts']['IF']:,}개 / 참고 A2: {summary['counts']['A2']:,}개.
A1·IF 공통: {summary['intersection']:,}개 / A1만: {summary['onlyA1']:,}개 / IF만: {summary['onlyIF']:,}개.
양성 합집합: {summary['union']:,}개. 공통÷합집합(Jaccard): {jaccard}.
같은 센서끼리의 공통 기록은 1존 {summary['same_sensor_common']['4']:,}개, 2존 {summary['same_sensor_common']['5']:,}개입니다.
설비 공통 기록에는 A1이 1존을, IF가 2존을 표시한 경우도 들어갑니다.
공통은 실제 이상 정답이라는 뜻이 아니고, 단독은 오탐·미탐이라는 뜻도 아닙니다.

3. 기록 수와 구간 수는 다릅니다
A1 센서 구간 {summary['sensor_counts']['A1']}개를 설비 시간 합집합으로 묶으면 {summary['equipment_counts']['A1']}개입니다.
IF 센서 구간은 {summary['sensor_counts']['IF']}개, 설비 구간은 {summary['equipment_counts']['IF']}개입니다.
A1·IF 구간 안에 실제 공통 양성 기록이 있는 구간쌍은 {summary['common_interval_count']}개이고, 해당 작업은 {summary['common_jobs']}입니다.
시간범위 자체가 겹치는 부분은 {summary['range_overlap_interval_count']}개입니다. 시간범위의 겹침만으로 공통 양성이라고 판정하지 않습니다.
구간 수와 시간범위는 원표의 선정 구간을 유지한 값이며, 공통 판정 범위에서 다시 자르거나 최소 길이를 다시 적용하지 않았습니다.
각 원구간 안에서 실제로 공통 비교에 들어간 양성 기록 수는 05번표에 따로 적었습니다(공통 범위 양성 0개인 원구간 {summary['sensor_events_without_common_positive']}개).
공통 구간 범위의 길이 {summary['range_common_seconds']:g}초와, 공통 양성 기록의 노출시간 {summary['positive_common_seconds']:g}초는 서로 다른 값입니다.
전자는 구간의 시작부터 끝까지를 세고, 후자는 실제 기록 사이에서 공통 양성으로 계산 가능한 시간만 셉니다.
발표의 이상 비율은 기록 수 비율을 사용하며, 시간 지표는 구별하여 보조로 제시합니다.

4. 파일 읽는 순서
02: 작업마다 실제로 몇 기록을 비교했는지 확인합니다.
03·04·12: 방법별 조사량과 방법 사이의 겹침을 확인합니다.
05·06·07: 어느 센서 구간을 어떻게 설비 구간으로 모으고 나눴는지 확인합니다.
09: 원구간표와 저장된 기록별 판정이 맞는지 확인합니다.
13: 공통 범위에서 하나 이상의 방법이 양성인 실제 기록을 확인합니다.
14와 figures: 정해진 선택 규칙으로 고른 대표 사례와 원본 온도를 확인합니다.

5. 어디까지 말할 수 있나
이는 과거 6~7월 자료에 대한 방법 간 비교입니다. 처음 보는 자료의 독립 검증 결과가 아닙니다.
실제 고장 정답이 없으므로 정확도·정밀도·재현율·F1이나 'IF가 더 정확하다'는 결론을 내리지 않습니다.
최신 실행에서 과거 수치와 다른 결과가 나와도, 과거 숫자에 맞추지 않고 전후비교표에 차이를 남깁니다.
"""
    (output / "00_결과읽기.txt").write_text(text, encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="5단계_결과기준.txt 경로")
    parser.add_argument("--output", type=Path, help="새 결과 폴더")
    parser.add_argument("--skip-plots", action="store_true", help="표만 생성하고 원본 사례 그림은 생략")
    args = parser.parse_args()
    config = common.load_config(args.config)
    output = args.output or path_for(config, "root") / "reports/5단계_평가" / datetime.now().strftime("%Y%m%d_%H%M%S_%f") / "5-1_주분석"
    summary = mainrun(config, output, skip_plots=args.skip_plots)
    print(json.dumps({"output": str(output), "common_records": summary["total_common"], "counts": summary["counts"],
                      "common_intervals": summary["common_interval_count"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
