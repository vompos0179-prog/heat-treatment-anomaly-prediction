"""최신 저장 IF 판정으로 5-1·5-2 IQR을 실행하고 전후 비교·검산표를 만든다.

XGBoost는 이 실행에 포함하지 않는다. 이전 결과 수치는 비교의 기준일 뿐이며,
새 계산값을 이전 숫자에 맞추지 않는다. 필요한 입력은 결과기준 TXT에 고정한다.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

import stage5_common as common

HERE = Path(__file__).resolve().parent
SENSORS = {"4": "솔트조 온도 1 Zone", "5": "솔트조 온도 2 Zone"}
# 2026-10-15 최초 5단계 결과 및 10-16 팀 피드백의 '이전 값'. 새 결과의 정답이 아니다.
OLD_IF_INTERVALS = [
    {"배정번호": 139116, "시작": "2022-06-06 07:32:37", "끝_미포함": "2022-06-06 07:35:44"},
    {"배정번호": 139417, "시작": "2022-06-07 20:32:45", "끝_미포함": "2022-06-07 20:36:56"},
    {"배정번호": 139417, "시작": "2022-06-07 20:52:41", "끝_미포함": "2022-06-07 20:56:52"},
    {"배정번호": 141554, "시작": "2022-06-17 07:43:43", "끝_미포함": "2022-06-17 07:45:08"},
    {"배정번호": 141893, "시작": "2022-06-19 03:49:19", "끝_미포함": "2022-06-19 03:50:37"},
]


def load_module(filename, module_name):
    spec = importlib.util.spec_from_file_location(module_name, HERE / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def json_write(value, path):
    def clean(v):
        if isinstance(v, dict):
            return {str(k): clean(x) for k, x in v.items()}
        if isinstance(v, (tuple, list)):
            return [clean(x) for x in v]
        if isinstance(v, np.generic):
            return clean(v.item())
        if isinstance(v, float) and not np.isfinite(v):
            return None
        return v
    Path(path).write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding="utf-8")


def find_table(folder, prefix):
    if folder is None or not Path(folder).is_dir():
        return None
    matches = sorted(Path(folder).glob(f"{prefix}_*.csv"))
    if len(matches) != 1:
        return None
    return matches[0]


def same_value(a, b):
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (list, dict)) or isinstance(b, (list, dict)):
        return a == b
    if pd.isna(a) or pd.isna(b):
        return bool(pd.isna(a) and pd.isna(b))
    if isinstance(a, (int, float, np.number)) and isinstance(b, (int, float, np.number)):
        return bool(np.isclose(a, b, rtol=1e-10, atol=1e-12))
    return str(a).strip() == str(b).strip()


def serialize(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def stage4_parameters(folder):
    """기준값·5월 점검 결과는 새 4단계 표에서 읽는다. 행별 양성 수는 읽어 오지 않는다."""
    output = {"thresholds": {}, "may_zone2": {}, "source_paths": []}
    path = find_table(folder, "05")
    if path:
        table = common.read_csv(path)
        if {"sensor", "IF점수기준"}.issubset(table.columns):
            for i, sensor in SENSORS.items():
                row = table[table["sensor"] == sensor]
                if len(row) == 1:
                    output["thresholds"][i] = float(row.iloc[0]["IF점수기준"])
        output["source_paths"].append(str(path))
    path = find_table(folder, "03")
    if path:
        table = common.read_csv(path)
        qcol = next((c for c in ("기준기간_분위수", "분위수") if c in table), None)
        if qcol and {"sensor", "5월_60초이상구간수"}.issubset(table.columns):
            for q in (.99, .995, .999):
                row = table[(table["sensor"] == SENSORS["5"]) & np.isclose(table[qcol].astype(float), q)]
                if len(row) == 1:
                    output["may_zone2"][str(q)] = int(row.iloc[0]["5월_60초이상구간수"])
        output["source_paths"].append(str(path))
    return output


def normalize_intervals(rows):
    return sorted([{"배정번호": int(r["배정번호"]), "시작": str(pd.Timestamp(r["시작"])),
                    "끝_미포함": str(pd.Timestamp(r["끝_미포함"]))} for r in rows],
                  key=lambda r: (r["배정번호"], r["시작"], r["끝_미포함"]))


def before_after(config, main, iqr, output):
    p = stage4_parameters(config["stage4"])
    rows = []

    def add(name, old, new, unit, reason):
        status = "미확인" if new is None else "같음" if same_value(old, new) else "다름"
        if status == "같음":
            note = "최신 저장 판정으로 다시 계산한 값이 이전 값과 같음" if config["mode"] == "production" else "시험 입력 결과와 이전 값 비교; 최신 제출 결과 아님"
        elif status == "미확인":
            note = "필요한 새 결과 또는 원표가 없어 확인하지 못함"
        else:
            note = reason
        rows.append({"항목": name, "이전_초기IF": serialize(old), "새_저장IF": serialize(new),
                     "단위": unit, "같은가": status, "차이확인내용": note,
                     "이전출처": "20261015 초기 5단계·20261016 피드백", "실행모드": config["mode"]})

    for i, old in (("4", .702616584213438), ("5", .6893985154652883)):
        add(f"IF 점수 기준값 {SENSORS[i]}", old, p["thresholds"].get(i), "점수", "학습 대상·환경·저장한 모델 기준값을 4단계 전후 표와 학습행 해시로 확인")
    for q, old in ((.99, 66), (.995, 59), (.999, 12)):
        add(f"5월 2 Zone 60초 구간 ({q * 100:g}%)", old, p["may_zone2"].get(str(q)), "구간", "새 4단계의 해당 분위수 결과가 바뀜; 기준값·학습행·판정 가능 범위를 함께 확인")
    add("공통 판정 기록 수", 770509, main["total_common"], "기록", "A1·A2 두 센서와 저장 IF_valid의 교집합이 바뀜; 작업별 전후 표에서 제외가 달라진 작업 확인")
    for i in ("4", "5"):
        add(f"6~7월 IF 판정 가능 기록 {SENSORS[i]}", 770803, main["if_valid_by_sensor"].get(i), "기록", "저장된 최신 IF_valid의 합계가 초기 실행과 다름; 240→300 조건 및 학습 특성 유효 범위 차이 확인")
    for i, old in (("4", 55), ("5", 3424)):
        add(f"6~7월 IF 후보 기록 {SENSORS[i]}", old, main["if_cand_by_sensor"].get(i), "기록", "IF_valid·점수·기준값의 변경에 따른 후보 차이; 공통분모 안 양성과 구분")
    add("IF 양성 기록 (2센서 통합·공통범위)", 828, main["counts"]["IF"], "기록", "같은 시각의 두 센서 IF_qual을 OR로 합산하고 공통 마스크를 적용한 결과가 달라짐")
    add("A1·IF 공통 양성 기록", 178, main["intersection"], "기록", "같은 기록에서 A1·IF 저장 qual 교집합이 달라짐; 작업별 검산표와 양성기록목록 확인")
    add("같은 센서 2 Zone 공통 양성 기록", 103, main["same_sensor_common"]["5"], "기록", "2 Zone끼리의 같은 기록 판정이 달라짐; 설비 통합 공통과 구분")
    add("A1만 양성 기록", 412, main["onlyA1"], "기록", "A1 양성에서 IF 공통 양성을 제외한 실제 기록 수가 달라짐")
    add("IF만 양성 기록", 650, main["onlyIF"], "기록", "IF 양성에서 A1 공통 양성을 제외한 실제 기록 수가 달라짐")
    add("A1 설비 구간", 6, main["equipment_counts"]["A1"], "구간", "3단계 ②·4단계 21번 설비 구간의 변화 확인; 센서 구간 수와 혼용하지 않음")
    add("IF 설비 구간", 5, main["equipment_counts"]["IF"], "구간", "최신 4단계가 선정하고 설비별로 묶은 조사 구간이 달라짐")
    add("공통 양성 기록이 있는 설비 구간쌍", 2, main["common_interval_count"], "구간쌍", "공통 기록을 포함한 A1·IF 구간쌍이 달라져 우선 조사 목록도 확인해야 함")
    add("공통 양성 작업 목록", [139116, 139417], main["common_jobs"], "배정번호", "함께 지목한 작업이 달라짐; 조사 우선순위 설명 및 발표 자료를 새 목록으로 맞춤")
    add("IF 설비 구간의 작업·시작·종료 시각", normalize_intervals(OLD_IF_INTERVALS), normalize_intervals(main["if_equipment_intervals"]), "[시작, 끝_미포함)", "시각까지 동일하지 않음; 새 구간을 우선 조사 목록 및 그림에 적용")
    add("구간 범위 공통 시간", 183, main["range_common_seconds"], "초", "두 방법의 선정 구간 시간범위가 바뀜; 기록별 양성 노출시간과 다른 지표")
    add("공통 양성 노출 시간", 179, main["positive_common_seconds"], "초", "공통 양성인 앞 기록의 다음 기록까지 간격(5초 이하)을 합한 결과가 바뀜")
    add("IQR 공통 범위 양성 기록", 26536, iqr.get("iqr_qualified_records"), "기록", "새 IF_valid를 포함한 공통범위에서 IQR 양성 포함 상태가 달라짐")
    add("IQR 공통 범위 설비 구간", 64, iqr.get("iqr_equipment_intervals"), "구간", "새 공통범위에서 IQR 구간을 계산한 결과가 달라짐; 원래 범위 107구간과 구분")
    table = pd.DataFrame(rows)
    common.save_csv(table, output / "5단계_IF통일_전후비교.csv")
    return table, p


def compare_stage4_tables(config, output):
    """저장만 추가한 전후의 06·07·12·22 표를 의미 값으로 비교한다."""
    comparisons, differences = [], []
    for prefix in ("06", "07", "12", "22"):
        old_path, new_path = find_table(config.get("stage4_previous"), prefix), find_table(config["stage4"], prefix)
        row = {"표번호": prefix, "저장추가전": str(old_path or ""), "저장추가후": str(new_path or ""),
               "판정": "미확인", "이전행수": None, "새행수": None, "다른셀수": None,
               "설명": "전후 표 한 쌍을 찾지 못함", "수치비교허용오차": "rtol=1e-10, atol=1e-12; 시각·문자열은 정확히 비교"}
        if old_path and new_path:
            old, new = common.read_csv(old_path), common.read_csv(new_path)
            row.update({"이전행수": len(old), "새행수": len(new), "이전_SHA256": common.sha256(old_path), "새_SHA256": common.sha256(new_path)})
            if set(old.columns) != set(new.columns):
                row.update({"판정": "다름", "설명": f"열 구성 다름: 이전만 {sorted(set(old)-set(new))}, 새것만 {sorted(set(new)-set(old))}"})
            elif len(old) != len(new):
                row.update({"판정": "다름", "설명": "행 수 다름"})
            else:
                columns = sorted(old.columns)
                keys = [key for key in ("비교", "범위", "sensor", "method", "배정번호", "start_time", "end_time", "구분") if key in old]
                keys += [col for col in columns if col not in keys]
                old = old.sort_values(keys, kind="stable", na_position="last").reset_index(drop=True)
                new = new.sort_values(keys, kind="stable", na_position="last").reset_index(drop=True)
                count = 0
                for i in range(len(old)):
                    for col in columns:
                        av, bv = old.at[i, col], new.at[i, col]
                        if not same_value(av, bv):
                            count += 1
                            differences.append({"표번호": prefix, "정렬후행": i + 1, "열": col, "이전": av, "새": bv})
                row.update({"판정": "같음" if count == 0 else "다름", "다른셀수": count,
                            "설명": "열 순서·행 순서를 맞춰 모든 값 비교" if count == 0 else "값 차이는 4단계_전후_다른셀.csv 참조"})
        comparisons.append(row)
    table = pd.DataFrame(comparisons)
    common.save_csv(table, output / "4단계_06_07_12_22_전후검증.csv")
    common.save_csv(pd.DataFrame(differences, columns=["표번호", "정렬후행", "열", "이전", "새"]), output / "4단계_전후_다른셀.csv")
    return table


def verify_new_outputs(config, main, iqr, main_output, output):
    """새 NPZ로 계산한 값과 같은 실행의 새 4단계 요약표를 서로 대조한다."""
    rows = []

    def add(name, computed, stated, scope):
        rows.append({"점검": name, "기록판정_재계산값": serialize(computed), "새4단계표_또는기대관계": serialize(stated),
                     "판정": "미확인" if stated is None else "일치" if same_value(computed, stated) else "불일치", "범위": scope})

    p12 = find_table(config["stage4"], "12")
    t12 = common.read_csv(p12) if p12 else pd.DataFrame()
    if "범위" in t12:
        for i, sensor in SENSORS.items():
            sub = t12[t12["범위"] == sensor]
            target = int(sub.iloc[0]["IF양성기록수"]) if len(sub) == 1 and "IF양성기록수" in sub else None
            add(f"IF_{i} 저장 qual과 표12", main["if_common_qual_by_sensor"][i], target, "A1·A2·IF 두 센서 공통 판정 범위")
        group = t12[t12["범위"] == "솔트조 2센서 통합"]
        if len(group) == 1:
            row = group.iloc[0]
            expected = {"공통판정가능기록수": main["total_common"], "A1양성기록수": main["counts"]["A1"],
                        "A2양성기록수": main["counts"]["A2"], "IF양성기록수": main["counts"]["IF"],
                        "A1_IF공통기록수": main["intersection"], "A1_A2공통기록수": main["pair_intersections"]["A1_A2"],
                        "A2_IF공통기록수": main["pair_intersections"]["A2_IF"],
                        "공통판정가능시간_sec": main["eligible_seconds"], "A1_IF공통시간_sec": main["positive_common_seconds"]}
            for field, computed in expected.items():
                alias = "공통양성기록수" if field == "A1_IF공통기록수" else "공통양성시간_sec" if field == "A1_IF공통시간_sec" else field
                value = row.get(field, row.get(alias, None))
                add(f"표12 통합 {field}", computed, float(value) if value is not None else None, "새 4단계 표와 같은 기록별 판정으로 계산")
    else:
        add("새4단계 표12 검산", main["counts"]["IF"], None, "표12 없거나 범위 열 없음")

    p22 = find_table(config["stage4"], "22")
    t22 = common.read_csv(p22) if p22 else pd.DataFrame()
    pair_table = common.read_csv(main_output / "12_전체방법쌍_기록및설비구간_비교.csv")
    if "비교" in t22:
        for row in pair_table.to_dict("records"):
            a, b = row["방법A"], row["방법B"]
            sub = t22[t22["비교"] == f"{a} vs {b}"]
            if len(sub) != 1:
                sub = t22[t22["비교"] == f"{b} vs {a}"]
            target = sub.iloc[0] if len(sub) == 1 else {}
            for m in (a, b):
                value = target.get(f"{m}_설비구간수", None)
                add(f"표22 {a}-{b} {m} 설비구간", main["equipment_counts"][m], int(value) if value is not None and not pd.isna(value) else None, "새4단계 21번표의 설비구간; 센서 구간 수와 구별")
            for m, side in ((a, "A"), (b, "B")):
                value = target.get(f"공통_{m}구간수", None)
                add(f"표22 {a}-{b} 공통 {m}구간", int(row[f"공통양성기록이있는_{side}구간수"]), int(value) if value is not None and not pd.isna(value) else None, "공통 양성 기록을 실제 포함한 설비 구간")
            value = target.get("공통작업수", None)
            add(f"표22 {a}-{b} 공통 작업", int(row["공통양성작업수"]), int(value) if value is not None and not pd.isna(value) else None, "공통 양성 기록이 있는 작업")
    else:
        add("새4단계 표22 설비구간 검산", main["equipment_counts"], None, "표22 없거나 비교 열 없음")

    add("공통+A1만=A1", main["intersection"] + main["onlyA1"], main["counts"]["A1"], "기록 항등식")
    add("공통+IF만=IF", main["intersection"] + main["onlyIF"], main["counts"]["IF"], "기록 항등식")
    expected_j = main["intersection"] / main["union"] * 100 if main["union"] else None
    if expected_j is not None:
        add("Jaccard=공통÷합집합", main["jaccard_pct"], expected_j, "기록 겹침 비율; 정확도 아님")
    else:
        rows.append({"점검": "Jaccard=공통÷합집합", "기록판정_재계산값": "", "새4단계표_또는기대관계": "합집합 0이므로 계산하지 않음", "판정": "일치" if main["jaccard_pct"] is None else "불일치", "범위": "빈 분모 처리"})
    add("5-1·IQR 공통 분모", iqr.get("common_records"), main["total_common"], "세 방법·두 센서 valid 교집합")
    for m in ("A1", "A2", "IF"):
        add(f"5-1·IQR {m} 양성수", iqr.get("counts", {}).get(m), main["counts"][m], "같은 저장 판정과 공통 분모")
    result = pd.DataFrame(rows)
    common.save_csv(result, output / "5단계_새기록판정_자기점검.csv")
    return result


def work_differences(config, main_output, output):
    """이전 작업별 검산표가 있으면 IF 유효범위 등이 바뀐 작업을 직접 제시한다."""
    old_root = config.get("old_stage5")
    new = common.read_csv(main_output / "02_작업별_기록단위검산.csv")
    old_path = None
    if old_root and Path(old_root).is_dir():
        candidates = list(Path(old_root).rglob("02_작업별_A1_A2_공통기록검산.csv"))
        if len(candidates) == 1:
            old_path = candidates[0]
    if old_path is None:
        table = new.copy()
        table["이전작업별대조"] = "이전 작업별 검산표를 지정하지 않아 미확인; 새 기록별 값만 제시"
    else:
        old = common.read_csv(old_path).rename(columns={"A1_A2_공통판정기록수": "공통판정기록수"})
        keep = [c for c in ("배정번호", "관측기록수", "공통판정기록수", "A1_양성기록수", "A2_양성기록수") if c in old]
        table = new.merge(old[keep], on="배정번호", how="outer", suffixes=("_새", "_이전"), validate="one_to_one")
        for col in keep:
            if col != "배정번호" and f"{col}_새" in table:
                table[f"{col}_변화"] = table[f"{col}_새"] - table[f"{col}_이전"]
        table["이전작업별대조"] = str(old_path)
    # 이전 패키지를 지정한 경우에만 그 안의 역사적 IF 유효성 캐시도 대조한다.
    # 이 캐시는 이전 실행의 출처이며, 새 IF 유효성을 만드는 데 사용하지 않는다.
    cache_dir = Path(old_root) / "inputs/솔트조_후속비교_중간자료" if old_root else None
    if cache_dir and cache_dir.is_dir():
        old_valid = []
        for p in sorted(cache_dir.glob("*.npz")):
            with np.load(p, allow_pickle=False) as z:
                if not {"if_valid_1", "if_valid_2"}.issubset(z.files):
                    continue
                old_valid.append({"배정번호": int(p.stem), "IF_4_판정가능기록수_이전": int(z["if_valid_1"].sum()),
                                  "IF_5_판정가능기록수_이전": int(z["if_valid_2"].sum()),
                                  "이전IF유효성출처": str(p), "이전IF유효성_SHA256": common.sha256(p)})
        if old_valid:
            table = table.merge(pd.DataFrame(old_valid), on="배정번호", how="left", validate="one_to_one")
            for i in ("4", "5"):
                col = f"IF_{i}_판정가능기록수"
                table[f"{col}_변화"] = table[col] - table[f"{col}_이전"]
            table["IF유효기록_변화설명"] = table.apply(
                lambda r: "초기 유효성 캐시와 최신 저장 IF_valid의 기록 수가 다름; 과거 기록 최소조건 및 입력 유효성 차이 확인"
                if any(pd.notna(r[f"IF_{i}_판정가능기록수_변화"]) and r[f"IF_{i}_판정가능기록수_변화"] != 0 for i in ("4", "5"))
                else "초기 캐시와 최신 IF_valid의 작업별 기록 수 같음(위치의 일치까지 뜻하지 않음)", axis=1)
    common.save_csv(table, output / "5단계_IF통일_작업별전후비교.csv")
    return old_path


def run(config, output, skip_plots=False):
    missing = common.readiness(config, include_raw=not skip_plots)
    if missing:
        raise FileNotFoundError("5단계 입력을 준비해 주세요.\n" + "\n".join(missing))
    output = Path(output).resolve()
    if (output / "전체실행_정보.json").exists():
        raise FileExistsError("이미 완료한 실행 폴더입니다. --output에 새 폴더를 지정해 주세요.")
    output.mkdir(parents=True, exist_ok=True)
    a = load_module("5-1_주분석_A1_IF.py", "stage5_main_run")
    b = load_module("5-2_대안접근_한계.py", "stage5_iqr_run")
    main_output, iqr_output = output / "5-1_주분석", output / "5-2_IQR"
    print("5-1: 저장된 기록별 판정으로 비교합니다.", flush=True)
    main = a.mainrun(config, main_output, skip_plots=skip_plots)
    print("5-2: 같은 공통 범위에서 IQR 결과를 비교합니다. XGBoost는 실행하지 않습니다.", flush=True)
    iqr = b.run(config, iqr_output, skip_plots=skip_plots)
    before, parameters = before_after(config, main, iqr, output)
    stage4_check = compare_stage4_tables(config, output)
    internal = verify_new_outputs(config, main, iqr, main_output, output)
    old_job_path = work_differences(config, main_output, output)
    differences = before[before["같은가"] == "다름"]
    unverified = before[before["같은가"] == "미확인"]
    consistent = bool((internal["판정"] == "일치").all())
    production = config["mode"] == "production"
    metadata = {"실행환경": common.runtime_info(), "실행모드": config["mode"], "제출결과여부": production,
                "입력": common.input_manifest(config), "코드_SHA256": {p.name: common.sha256(p) for p in sorted(HERE.glob("*.py"))},
                "5-1": main, "5-2_IQR": iqr, "IF기준및5월점검": parameters,
                "이전비교": {"다른항목수": len(differences), "미확인항목수": len(unverified), "이전작업표": str(old_job_path or "")},
                "새4단계와자기점검_모두일치": consistent, "새4단계와자기점검_미확인수": int((internal["판정"] == "미확인").sum()),
                "저장추가전후4단계표": stage4_check.to_dict("records"),
                "XGBoost재실행": False, "독립적인고장정답": False}
    json_write(metadata, output / "전체실행_정보.json")
    changed_names = "\n".join(f"- {r['항목']}: {r['이전_초기IF']} → {r['새_저장IF']}" for r in differences.to_dict("records")) or "이전과 다른 항목 없음"
    stage4_note = " / ".join(f"{r['표번호']}번 {r['판정']}" for r in stage4_check.to_dict("records"))
    recommendation_changed = any((row["같은가"] == "다름") for row in before[before["항목"].isin(["공통 양성 기록이 있는 설비 구간쌍", "공통 양성 작업 목록", "IF 설비 구간의 작업·시작·종료 시각"])].to_dict("records"))
    status = "새 기록별 판정과 새 4단계 표가 모두 일치했습니다." if consistent else "새 기록별 판정과 새 4단계 표에 불일치 또는 미확인이 있습니다. 자기점검표를 해결한 뒤 제출하세요."
    note = f"""5단계 IF 기준 통일 — 이번 실행 결과

{'최신 4단계 저장 판정으로 실행했습니다.' if production else '이 결과는 시험용입니다. 최신 제출·발표 결과로 사용하지 마세요.'}
{status}

이번에 한 일
1. IF 판정 가능 여부와 양성을 4단계 NPZ에서 읽었습니다.
2. 같은 시각의 A1·A2·IF가 모두 판단 가능한 기록만 남겨 다시 셌습니다.
3. 기록별 겹침, 센서 구간, 설비 구간, IQR 결과를 각각 비교했습니다.
4. 새 4단계 표와 NPZ 합계, 저장 추가 전후 표, 이전 5단계 결과를 대조했습니다.
XGBoost는 변경하거나 다시 실행하지 않았습니다.

현재 결과
공통 판정 기록 {main['total_common']:,}개.
A1 {main['counts']['A1']:,}개, IF {main['counts']['IF']:,}개, 공통 {main['intersection']:,}개.
설비 구간 A1 {main['equipment_counts']['A1']}개, IF {main['equipment_counts']['IF']}개.
실제 공통 양성 기록이 있는 설비 구간쌍 {main['common_interval_count']}개, 작업 {main['common_jobs']}.
IQR 공통 범위 양성 {iqr.get('iqr_qualified_records')}개, 설비 구간 {iqr.get('iqr_equipment_intervals')}개.
구간 범위 공통 시간 {main['range_common_seconds']:g}초, 공통 양성 노출 시간 {main['positive_common_seconds']:g}초.
두 시간은 계산 목적이 다르므로 같은 숫자로 맞추지 않습니다.

전후 점검
저장 추가 전후 4단계 표: {stage4_note}
초기 IF 기준 5단계와 달라진 항목 {len(differences)}개, 미확인 항목 {len(unverified)}개.
{changed_names}
{'함께 지목한 작업 또는 구간 시각이 달라졌으므로 발표의 조사 목록·사례 화면을 새 결과로 맞춰야 합니다.' if recommendation_changed else '전후비교에서 조사 우선 목록과 관련된 구간·작업의 변경은 확인되지 않았습니다. 미확인 항목이 있으면 먼저 확인하세요.'}

팀원에게 전달할 것
이 폴더 전체와 stages/5단계_평가의 코드 4개·결과기준 TXT·README를 전달합니다.
먼저 5단계_IF통일_전후비교.csv와 5단계_새기록판정_자기점검.csv를 확인합니다.
그다음 5-1_주분석/00_결과읽기.txt, 5-2_IQR의 결과 설명과 그림을 읽습니다.
실행한 PC·도구 버전·입력 폴더·해시는 전체실행_정보.json에 있습니다.

해석
공통 후보가 실제 이상 정답이라는 뜻은 아니고, 한 방법만 표시했다고 오탐·미탐이라는 뜻도 아닙니다.
6~7월은 이전 탐색 이력이 있는 후속 비교이며, 독립적인 최종 검증으로 표현하지 않습니다.
"""
    (output / "00_팀원에게_실행결과.txt").write_text(note, encoding="utf-8")
    return {"output": str(output), "internal_checks_passed": consistent, "mode": config["mode"],
            "changed_items": len(differences), "unverified_items": len(unverified)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-only", action="store_true", help="입력이 준비되었는지만 확인")
    parser.add_argument("--skip-plots", action="store_true", help="사례 그림을 생략하고 표만 계산")
    args = parser.parse_args()
    config = common.load_config(args.config)
    if args.check_only:
        missing = common.readiness(config, include_raw=not args.skip_plots)
        if missing:
            print("입력 확인 필요:\n" + "\n".join(missing))
            return 2
        print(f"입력 확인 완료. 실행모드={config['mode']}. 최신 폴더를 자동 선택하지 않습니다.")
        return 0
    output = args.output or config["root"] / "reports/5단계_평가" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    result = run(config, output, skip_plots=args.skip_plots)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["internal_checks_passed"] else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError, FileExistsError, KeyError, AssertionError) as error:
        print(f"[확인 필요] {error}", file=sys.stderr)
        raise SystemExit(2)
