"""5단계 품질예측: 원본 ZIP 재구축 또는 검증된 136작업 캐시로 재실행.

원본/기존 결과를 덮어쓰지 않는다. 결과는 --output-dir 아래에 쓴다.
준비: pip install numpy pandas openpyxl scipy scikit-learn xgboost==3.4.1 matplotlib
실행: python stages/5단계_평가/quality_xgboost.py --source-zip 원본.zip
재실행: python stages/5단계_평가/quality_xgboost.py --output-dir 새결과폴더
저장 결과 검증만: python stages/5단계_평가/quality_xgboost.py --verify-only
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
COLS = ["건조 1존 OP", "건조 2존 OP", "건조로 온도 1 Zone", "건조로 온도 2 Zone",
        "세정기", "소입1존 OP", "소입2존 OP", "소입3존 OP", "소입4존 OP", "소입로 CP 값",
        "소입로 온도 1 Zone", "소입로 온도 2 Zone", "소입로 온도 3 Zone", "소입로 온도 4 Zone",
        "솔트 컨베이어 온도 1 Zone", "솔트 컨베이어 온도 2 Zone", "솔트조 온도 1 Zone", "솔트조 온도 2 Zone"]
TEMPS = ["소입로 온도 1 Zone", "소입로 온도 2 Zone", "소입로 온도 3 Zone", "소입로 온도 4 Zone", "솔트조 온도 1 Zone", "솔트조 온도 2 Zone"]
FEATURES = [f"{c}_{s}" for c in COLS for s in ["Avg", "Std"]]
TEMP_FEATURES = [f"{c}_{s}" for c in TEMPS for s in ["Avg", "Std"]]
THRESHOLD = 0.5
FIXED_SEED = 20261015
MODEL_CONFIGS = {
    "온도12": dict(n_estimators=100, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8),
    "전체36": dict(n_estimators=100, max_depth=3, learning_rate=0.05, subsample=0.8, colsample_bytree=0.8),
}
BASE_PARAMS = dict(objective="binary:logistic", eval_metric="logloss", tree_method="hist",
                   n_jobs=2, reg_alpha=0.0, reg_lambda=1.0, min_child_weight=1.0, gamma=0.0,
                   max_delta_step=0.0, colsample_bylevel=1.0, colsample_bynode=1.0,
                   scale_pos_weight=1.0, max_bin=256, grow_policy="depthwise")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=str), encoding="utf-8")


def write_csv(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    value.to_csv(path, index=False, encoding="utf-8-sig", float_format="%.17g")


def original(name):
    p = ROOT / "inputs" / "팀원원본" / name
    if not p.is_file():
        raise FileNotFoundError(f"원본 감사 입력이 없습니다: {p}")
    return p


def merge_stats(store, frame, cols):
    """Merge per-chunk (n, mean, M2) using the parallel variance formula."""
    grouped = frame.groupby("배정번호", sort=False)[cols].agg(["count", "mean", "var"])
    for job, row in grouped.iterrows():
        n2 = np.array([row[(c, "count")] for c in cols], dtype=np.int64)
        m2 = np.array([row[(c, "mean")] for c in cols], dtype=float)
        v2 = np.array([row[(c, "var")] for c in cols], dtype=float)
        ss2 = np.nan_to_num(v2) * np.maximum(n2 - 1, 0)
        m2 = np.nan_to_num(m2)
        job = int(job)
        if job not in store:
            store[job] = [n2, m2, ss2]
            continue
        n1, m1, ss1 = store[job]
        nt = n1 + n2
        delta = m2 - m1
        denom = np.where(nt == 0, 1, nt)
        mt = m1 + delta * n2 / denom
        sst = ss1 + ss2 + delta * delta * n1 * n2 / denom
        store[job] = [nt, mt, sst]


def stat_frame(store, cols):
    rows = []
    for job, (n, mean, m2) in store.items():
        row = {"배정번호": job}
        for k, col in enumerate(cols):
            row[f"{col}_Avg"] = mean[k] if n[k] else np.nan
            row[f"{col}_Std"] = np.sqrt(max(m2[k], 0) / (n[k] - 1)) if n[k] > 1 else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def build_cache(source_zip, cache, out):
    stats, complete_stats, times, totals = {}, {}, {}, {}
    missing = pd.Series(0, index=COLS, dtype="int64")
    raw_rows = any_missing = temp_incomplete = 0
    with zipfile.ZipFile(source_zip) as z:
        quality = pd.read_excel(io.BytesIO(z.read("data/열처리_품질데이터.xlsx")))
        provided_train = pd.read_csv(io.BytesIO(z.read("data/train.csv")), encoding="cp949")
        # Retain the supplied subset unaltered, including its original row index.
        (cache / "source_train.csv").write_bytes(z.read("data/train.csv"))
        with z.open("data/data.csv") as f:
            for chunk_no, chunk in enumerate(pd.read_csv(f, encoding="cp949", usecols=["TAG_MIN", "배정번호"] + COLS,
                                                        chunksize=150000), 1):
                if chunk["배정번호"].isna().any():
                    raise ValueError("원본에 결측 배정번호가 있어 명시적 처리 없이는 진행할 수 없습니다.")
                chunk[COLS] = chunk[COLS].apply(pd.to_numeric, errors="raise").replace([np.inf, -np.inf], np.nan)
                raw_rows += len(chunk)
                missing += chunk[COLS].isna().sum()
                any_missing += int(chunk[COLS].isna().any(axis=1).sum())
                temp_incomplete += int(chunk[TEMPS].isna().any(axis=1).sum())
                merge_stats(stats, chunk, COLS)
                merge_stats(complete_stats, chunk.dropna(subset=TEMPS), TEMPS)
                for job, group in chunk.groupby("배정번호", sort=False):
                    job = int(job)
                    lo, hi = group["TAG_MIN"].min(), group["TAG_MIN"].max()
                    if job not in times:
                        times[job] = [lo, hi]
                    else:
                        times[job] = [min(lo, times[job][0]), max(hi, times[job][1])]
                    totals[job] = totals.get(job, 0) + len(group)
                print(f"원본 집계 {chunk_no}: {raw_rows:,}행", flush=True)
    if quality["배정번호"].duplicated().any():
        raise ValueError("품질표에 중복 배정번호가 있습니다.")
    if not ((quality["총수량"] > 0) & (quality["불량수량"] >= 0) & (quality["불량수량"] <= quality["총수량"])).all():
        raise ValueError("품질 수량 범위를 확인하세요.")
    quality.insert(0, "quality_row", np.arange(len(quality)))
    quality["불량률_ppm"] = quality["불량수량"] / quality["총수량"] * 1e6
    quality["위험여부"] = (quality["불량률_ppm"] >= 450).astype(int)
    quality["구_반올림라벨"] = ((quality["불량수량"] / quality["총수량"] * 100).round(3) >= 0.046).astype(int)
    features = quality.merge(stat_frame(stats, COLS), on="배정번호", how="left", validate="one_to_one", indicator=True)
    if not features["_merge"].eq("both").all():
        raise ValueError("품질 작업에 대응하는 공정 기록이 없습니다.")
    features = features.drop(columns="_merge")
    features["최초관측"] = features["배정번호"].map(lambda j: times[int(j)][0])
    features["최종관측"] = features["배정번호"].map(lambda j: times[int(j)][1])
    features["최초관측월"] = pd.to_datetime(features["최초관측"]).dt.month
    features["공정관측수"] = features["배정번호"].map(totals)
    features["분석포함"] = True
    features["제외사유"] = ""
    write_csv(cache / "quality_job_features.csv", features)
    write_csv(cache / "quality_mapping.csv", features[[c for c in features.columns if c not in FEATURES]])
    counts = pd.DataFrame([{"배정번호": j, **{c: int(n[k]) for k, c in enumerate(COLS)}} for j, (n, _, _) in stats.items()])
    write_csv(cache / "valid_observation_counts.csv", counts)
    write_csv(cache / "missing_observations.csv", missing.rename_axis("변수").reset_index(name="원본결측관측수"))
    # Reconstruct the old whole-dataset-mean imputation only for provenance audit, never for new training.
    gn = sum(v[0] for v in stats.values())
    gm = sum(v[0] * v[1] for v in stats.values()) / gn
    filled = {}
    for job, (n, mean, m2) in stats.items():
        nt = totals[job]
        nm = nt - n
        newmean = (n * mean + nm * gm) / nt
        newm2 = m2 + n * (mean - newmean) ** 2 + nm * (gm - newmean) ** 2
        filled[job] = [np.full(len(COLS), nt), newmean, newm2]
    order = quality[["배정번호"]]
    observed = order.merge(stat_frame(stats, COLS), on="배정번호", validate="one_to_one")
    filled_df = order.merge(stat_frame(filled, COLS), on="배정번호", validate="one_to_one")
    complete_df = order.merge(stat_frame(complete_stats, TEMPS), on="배정번호", validate="one_to_one")
    comparisons = []
    for supplied_name, cols in [("04_학습용_온도입력_품질정답.csv", TEMP_FEATURES), ("전처리_학습용데이터.csv", FEATURES)]:
        supplied = pd.read_csv(original(supplied_name), encoding="utf-8-sig")
        for method, candidate in [("유효관측별_집계", observed), ("전체평균_사전대체_감사용", filled_df), ("온도6개_완전관측행", complete_df)]:
            common = [c for c in cols if c in candidate]
            diff = np.abs(supplied[common].to_numpy() - candidate[common].to_numpy())
            comparisons.append(dict(비교파일=supplied_name, 재구축방법=method, 비교변수수=len(common),
                                    최대절대오차=float(np.nanmax(diff)), 모든변수일치작업수=int(np.all(diff <= 1e-7, axis=1).sum()),
                                    허용절대오차=1e-7))
    write_csv(out / "감사" / "전처리_111행차이_원인확인.csv", pd.DataFrame(comparisons))
    # Retain the mapping from original ZIP train.csv row indices to named batches.
    rowcol = provided_train.columns[0]
    indices = pd.to_numeric(provided_train[rowcol], errors="raise").astype(int)
    if indices.duplicated().any() or not indices.between(0, len(quality)-1).all():
        raise ValueError("ZIP train.csv 원본 행 번호가 잘못되었습니다.")
    train_mapping = quality.set_index("quality_row").loc[indices, ["배정번호", "위험여부"]].reset_index()
    train_mapping.insert(0, "train_csv_order", np.arange(len(train_mapping)))
    write_csv(cache / "source_train_mapping.csv", train_mapping)
    train_difference = np.abs(provided_train[FEATURES].to_numpy() - filled_df.iloc[indices][FEATURES].to_numpy())
    meta = dict(schema_version=1, source_zip_name=Path(source_zip).name, source_zip_sha256=sha(source_zip),
                source_members=["data/data.csv", "data/열처리_품질데이터.xlsx", "data/train.csv"],
                raw_process_rows=raw_rows, raw_process_jobs=len(stats), quality_jobs=len(quality),
                quality_duplicate_ids=int(quality["배정번호"].duplicated().sum()), unmatched_quality_jobs=0,
                raw_jobs_without_quality=sorted(set(stats)-set(map(int, quality["배정번호"]))),
                analyzed_jobs=len(features), excluded_jobs=0, raw_rows_with_any_feature_missing=any_missing,
                raw_rows_with_any_temperature_missing=temp_incomplete,
                missing_policy="No imputation. Per-job columnwise observed mean and sample std (ddof=1); any remaining NaN is handled by XGBoost trained missing routing.",
                target="unrounded defects / total * 1,000,000 >= 450", target_counts=features["위험여부"].value_counts().sort_index().to_dict(),
                labels_different_from_old_round_percent_rule=int((features["위험여부"] != features["구_반올림라벨"]).sum()),
                month_counts=features["최초관측월"].value_counts().sort_index().to_dict(),
                missing_aggregate_cells=int(features[FEATURES].isna().sum().sum()), feature_names=FEATURES,
                source_train_rows=len(provided_train), source_train_vs_old_imputed_max_abs_error=float(np.nanmax(train_difference)),
                preprocessing_comparisons=comparisons)
    meta["cache_sha256"] = {p.name: sha(p) for p in cache.iterdir() if p.is_file() and p.name != "cache_manifest.json"}
    write_json(cache / "cache_manifest.json", meta)
    return features, meta


def load_cache(cache):
    meta = json.loads((cache / "cache_manifest.json").read_text(encoding="utf-8"))
    for name, expected in meta["cache_sha256"].items():
        actual = sha(cache / name)
        if actual != expected:
            raise ValueError(f"캐시 SHA-256 불일치: {name}")
    data = pd.read_csv(cache / "quality_job_features.csv", encoding="utf-8-sig")
    if len(data) != 136 or data["배정번호"].duplicated().any():
        raise ValueError("검증된 136작업 캐시가 아닙니다.")
    return data, meta


def scores(y, prob, threshold=THRESHOLD):
    from sklearn.metrics import accuracy_score, average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
    pred = (np.asarray(prob) > threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
    has_both = len(np.unique(y)) == 2
    return dict(n=len(y), stable=int(np.sum(np.asarray(y)==0)), risk=int(np.sum(np.asarray(y)==1)),
                TN=int(tn), FP=int(fp), FN=int(fn), TP=int(tp),
                accuracy=accuracy_score(y, pred), precision=precision_score(y, pred, zero_division=0),
                recall=recall_score(y, pred, zero_division=0), F1=f1_score(y, pred, zero_division=0),
                macro_F1=f1_score(y, pred, average="macro", labels=[0,1], zero_division=0),
                ROC_AUC=float(roc_auc_score(y, prob)) if has_both else None,
                AP=float(average_precision_score(y, prob)) if np.sum(y) else None, threshold=threshold)


def audit_original(out):
    from sklearn.model_selection import train_test_split
    from xgboost import XGBClassifier
    records, predictions, comparison = [], [], []
    for model_name, data_name, target, seed, strat, performance_name in [
        ("XGBoost_온도품질모델.json", "04_학습용_온도입력_품질정답.csv", "위험여부", 1, True, "XGBoost_모델성능결과.csv"),
        ("XGBoost_모델.json", "전처리_학습용데이터.csv", "불량단계", 2, False, "XGBoost_모델성능결과 (1).csv")]:
        df = pd.read_csv(original(data_name), encoding="utf-8-sig")
        y = df[target].to_numpy() if target == "위험여부" else df[target].map({"안정":0,"위험":1}).to_numpy()
        train, test = train_test_split(np.arange(len(y)), test_size=.2, random_state=seed, stratify=y if strat else None)
        model = XGBClassifier()
        model.load_model(original(model_name))
        features = model.get_booster().feature_names
        probability = model.predict_proba(df.loc[test, features])[:,1]
        supplied = pd.read_csv(original(performance_name), encoding="utf-8-sig")
        supplied_map = dict(zip(supplied.iloc[:,0], supplied.iloc[:,1]))
        def supplied_value(names):
            return next((float(supplied_map[n]) for n in names if n in supplied_map), None)
        for cut in ([.5] if strat else [.5,.4]):
            row = dict(model=model_name, seed=seed, stratify=strat, train_n=len(train), **scores(y[test], probability, cut))
            records.append(row)
            mapping = {"accuracy":["정확도 Accuracy","정확도"], "precision":["위험 정밀도 Precision","위험 정밀도"],
                       "recall":["위험 재현율 Recall","위험 재현율"], "F1":["위험 F1-score","위험 F1"], "ROC_AUC":["ROC-AUC"],
                       "TN":["실제 안정 → 예측 안정 TN","TN"], "FP":["실제 안정 → 예측 위험 FP","FP"],
                       "FN":["실제 위험 → 예측 안정 FN","FN"], "TP":["실제 위험 → 예측 위험 TP","TP"]}
            for metric, names in mapping.items():
                old = supplied_value(names)
                comparison.append(dict(model=model_name, threshold=cut, metric=metric, supplied=old, rescored=row[metric],
                                       agrees=old is not None and bool(np.isclose(old,row[metric], atol=1e-8))))
        for i,p in zip(test, probability):
            predictions.append(dict(model=model_name, quality_row=int(i), actual=int(y[i]), probability=float(p),
                                    predict_05=int(p>.5), predict_04=int(p>.4)))
    write_csv(out / "감사" / "원본모델_재평가.csv", pd.DataFrame(records))
    write_csv(out / "감사" / "원본성능표_일치검증.csv", pd.DataFrame(comparison))
    write_csv(out / "감사" / "원본모델_평가예측.csv", pd.DataFrame(predictions))
    return records


def evaluate(data, cache, out):
    from sklearn.model_selection import RepeatedStratifiedKFold, train_test_split
    from xgboost import XGBClassifier
    y = data["위험여부"].to_numpy(dtype=int)
    indices = np.arange(len(y))
    specs = []
    def add(scheme, run, seed, train, test, repeat=None, fold=None):
        train, test = np.asarray(train), np.asarray(test)
        assert not set(train)&set(test)
        assert set(train)|set(test) == set(indices)
        specs.append(dict(scheme=scheme, run=run, seed=seed, train=train, test=test, repeat=repeat, fold=fold))
    tr,te = train_test_split(indices, test_size=.2, random_state=2)
    add("공유무작위80_20_seed2", "seed2",2,tr,te)
    source_idx = pd.read_csv(cache / "source_train_mapping.csv", encoding="utf-8-sig")["quality_row"].to_numpy(dtype=int)
    source_same_order = bool(np.array_equal(source_idx,tr))
    source_same_set = bool(set(source_idx)==set(tr))
    if not source_same_set:
        add("ZIP제공_train108", "source108",2,source_idx,np.setdiff1d(indices,source_idx))
    tr = indices[data["최초관측월"].between(1,5)]
    te = indices[data["최초관측월"].between(6,7)]
    add("시간외삽_1_5월학습_6_7월평가", "time",FIXED_SEED,tr,te)
    for seed in [11,22,33,44,55]:
        tr,te = train_test_split(indices, test_size=.2, random_state=seed, stratify=y)
        add("동일작업_층화무작위5회", f"seed{seed}",seed,tr,te)
    splitter = RepeatedStratifiedKFold(n_splits=5, n_repeats=10, random_state=FIXED_SEED)
    for k,(tr,te) in enumerate(splitter.split(indices,y)):
        add("반복층화5겹10회", f"r{k//5+1:02d}f{k%5+1}", FIXED_SEED+k,tr,te,k//5+1,k%5+1)
    records,predictions,mapping = [],[],[]
    for spec in specs:
        tag = {k:v for k,v in spec.items() if k not in ["train","test"]}
        tr,te = spec["train"],spec["test"]
        for part,idx in [("train",tr),("test",te)]:
            for i in idx:
                mapping.append(dict(**tag,partition=part,quality_row=int(i),배정번호=int(data.iloc[i]["배정번호"]),actual=int(y[i])))
        for name,config in MODEL_CONFIGS.items():
            feats = TEMP_FEATURES if name=="온도12" else FEATURES
            params = {**BASE_PARAMS, **config, "random_state":spec["seed"]}
            model = XGBClassifier(**params)
            model.fit(data.iloc[tr][feats],y[tr])
            modeldir = out / "모델" / spec["scheme"]
            modeldir.mkdir(parents=True,exist_ok=True)
            modelpath = modeldir / f"{spec['run']}_{name}.json"
            model.save_model(modelpath)
            write_json(modelpath.with_suffix(".config.json"),dict(model=name, params=params, input_features=feats,
                        threshold=THRESHOLD, target="raw_ppm>=450", train_batch_ids=data.iloc[tr]["배정번호"].tolist(),
                        test_batch_ids=data.iloc[te]["배정번호"].tolist(), model_sha256=sha(modelpath)))
            for part,idx in [("train",tr),("test",te)]:
                probs = model.predict_proba(data.iloc[idx][feats])[:,1]
                records.append(dict(**tag,model=name,partition=part,**scores(y[idx],probs)))
                for i,p in zip(idx,probs):
                    predictions.append(dict(**tag,model=name,partition=part,quality_row=int(i),배정번호=int(data.iloc[i]["배정번호"]),
                                            actual=int(y[i]),probability=float(p),predicted=int(p>THRESHOLD)))
        for name,constant in [("기준_전부안정",0.0),("기준_전부위험",1.0),("기준_학습위험비율",float(y[tr].mean()))]:
            for part,idx in [("train",tr),("test",te)]:
                probs = np.full(len(idx),constant)
                records.append(dict(**tag,model=name,partition=part,**scores(y[idx],probs)))
                for i,p in zip(idx,probs):
                    predictions.append(dict(**tag,model=name,partition=part,quality_row=int(i),배정번호=int(data.iloc[i]["배정번호"]),
                                            actual=int(y[i]),probability=float(p),predicted=int(p>THRESHOLD)))
        print(f"평가 완료: {spec['scheme']} {spec['run']} (학습{len(tr)}, 평가{len(te)})",flush=True)
    metrics = pd.DataFrame(records)
    pred = pd.DataFrame(predictions)
    write_csv(out/"회별성능_학습및평가.csv",metrics)
    write_csv(out/"모든작업_회별예측.csv",pred)
    write_csv(out/"모든분리_작업번호.csv",pd.DataFrame(mapping))
    value_cols=["accuracy","precision","recall","F1","macro_F1","ROC_AUC","AP","TN","FP","FN","TP"]
    summary=metrics[metrics.partition.eq("test")].groupby(["scheme","model"])[value_cols].agg(["mean","std","min","max"])
    summary.columns=[f"{c}_{s}" for c,s in summary.columns]
    summary=summary.reset_index()
    write_csv(out/"평가성능_평균표준편차범위.csv",summary)
    # Every batch is a held-out observation once within each repetition. These are not 1,360 independent jobs.
    oof=[]
    cv=pred[pred.scheme.eq("반복층화5겹10회") & pred.partition.eq("test")]
    for (name,rep),group in cv.groupby(["model","repeat"]):
        assert len(group)==len(data) and group["배정번호"].nunique()==len(data)
        oof.append(dict(model=name,repeat=int(rep),**scores(group.actual.to_numpy(),group.probability.to_numpy())))
    write_csv(out/"반복별_OOF136작업성능.csv",pd.DataFrame(oof))
    paired=[]
    testing=metrics[metrics.partition.eq("test") & metrics.model.isin(MODEL_CONFIGS)]
    for scheme,g in testing.groupby("scheme"):
        left=g[g.model.eq("전체36")].set_index("run")
        right=g[g.model.eq("온도12")].set_index("run")
        for run in left.index:
            paired.append(dict(scheme=scheme,run=run,**{f"{m}_전체36_빼기_온도12":float(left.loc[run,m]-right.loc[run,m]) for m in value_cols[:7]}))
    write_csv(out/"동일분리_모델차이.csv",pd.DataFrame(paired))
    return metrics,pred,summary,dict(source_train_same_indices_as_seed2=source_same_set, source_train_same_order_as_seed2=source_same_order, evaluation_runs=len(specs), saved_models=len(specs)*2)


def plots(out,metrics,pred):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib import font_manager
        from sklearn.metrics import precision_recall_curve,roc_curve
    except ImportError:
        return "matplotlib unavailable: CSV outputs remain complete"
    # Windows uses the installed Korean font. On another OS, use an installed Noto/Nanum font.
    korean_font=Path("C:/Windows/Fonts/malgun.ttf")
    if korean_font.is_file():
        font_manager.fontManager.addfont(str(korean_font))
        plt.rcParams["font.family"]=font_manager.FontProperties(fname=str(korean_font)).get_name()
    else:
        available={f.name for f in font_manager.fontManager.ttflist}
        for candidate in ["Noto Sans CJK KR","Noto Sans KR","NanumGothic","AppleGothic"]:
            if candidate in available:
                plt.rcParams["font.family"]=candidate
                break
        else:
            return "Korean font unavailable: install Noto Sans CJK KR; CSV outputs remain complete"
    plt.rcParams["axes.unicode_minus"]=False
    labels={"온도12":"온도 12개 입력","전체36":"전체 공정 36개 입력"}
    scheme="시간외삽_1_5월학습_6_7월평가"
    test=pred[pred.scheme.eq(scheme)&pred.partition.eq("test")&pred.model.isin(labels)]
    fig,axes=plt.subplots(1,2,figsize=(11,4.4))
    for name,g in test.groupby("model"):
        fpr,tpr,_=roc_curve(g.actual,g.probability)
        pre,rec,_=precision_recall_curve(g.actual,g.probability)
        met=scores(g.actual.to_numpy(),g.probability.to_numpy())
        axes[0].plot(fpr,tpr,label=f"{labels[name]} (AUC {met['ROC_AUC']:.3f})")
        axes[1].step(rec,pre,where="post",label=f"{labels[name]} (AP {met['AP']:.3f})")
    axes[0].plot([0,1],[0,1],"--",color="gray",linewidth=1)
    prevalence=float(test.drop_duplicates("배정번호").actual.mean())
    axes[1].axhline(prevalence,linestyle="--",color="gray",label=f"평가 작업의 위험 비율 {prevalence:.3f}")
    axes[0].set(xlabel="안정을 위험으로 예측한 비율",ylabel="위험을 찾아낸 비율(재현율)",title="6~7월 회고비교: ROC 곡선")
    axes[1].set(xlabel="위험을 찾아낸 비율(재현율)",ylabel="위험 예측 중 실제 위험 비율(정밀도)",title="6~7월 회고비교: 정밀도·재현율 곡선")
    for ax in axes:
        ax.set_xlim(0,1);ax.set_ylim(0,1.02);ax.legend(fontsize=8);ax.grid(alpha=.2)
    fig.suptitle("1~5월 학습 · 두 모델의 설정 동일 · AP는 평균정밀도")
    fig.tight_layout();fig.savefig(out/"시간평가_ROC_PR.png",dpi=300);plt.close(fig)
    fig,axes=plt.subplots(1,2,figsize=(8.6,3.8))
    for ax,(name,g) in zip(axes,test.groupby("model")):
        m=scores(g.actual.to_numpy(),g.probability.to_numpy());cm=np.array([[m["TN"],m["FP"]],[m["FN"],m["TP"]]])
        ax.imshow(cm,cmap="Blues",vmin=0,vmax=36)
        for (i,j),v in np.ndenumerate(cm):ax.text(j,i,str(v),ha="center",va="center",fontsize=19)
        ax.set(xticks=[0,1],yticks=[0,1],xticklabels=["안정","위험"],yticklabels=["안정","위험"],xlabel="모델의 예측",ylabel="실제 정답",title=labels[name])
    fig.suptitle("6~7월 36작업 회고비교 · 위험 예측 기준: 확률 0.5 초과")
    fig.tight_layout();fig.savefig(out/"시간평가_혼동행렬.png",dpi=300);plt.close(fig)
    return "saved: 시간평가_ROC_PR.png, 시간평가_혼동행렬.png"


def verify_outputs(cache,out):
    """Verify persisted outputs without fitting any model."""
    from xgboost import XGBClassifier
    data,meta=load_cache(cache)
    metrics=pd.read_csv(out/"회별성능_학습및평가.csv",encoding="utf-8-sig")
    pred=pd.read_csv(out/"모든작업_회별예측.csv",encoding="utf-8-sig")
    splits=pd.read_csv(out/"모든분리_작업번호.csv",encoding="utf-8-sig")
    runs=splits[["scheme","run"]].drop_duplicates().shape[0]
    models=list((out/"모델").rglob("*.json"))
    models=[p for p in models if not p.name.endswith(".config.json")]
    assert len(metrics)==runs*5*2
    assert len(pred)==runs*5*len(data)
    assert len(splits)==runs*len(data)
    assert len(models)==runs*2
    error_max=0.0
    for keys,g in pred.groupby(["scheme","run","model","partition"]):
        old=metrics[(metrics.scheme==keys[0])&(metrics.run==keys[1])&(metrics.model==keys[2])&(metrics.partition==keys[3])].iloc[0]
        actual=scores(g.actual.to_numpy(),g.probability.to_numpy())
        for name,value in actual.items():
            if value is not None:
                error=abs(float(old[name])-value);error_max=max(error_max,error)
                assert error<1e-12,(keys,name,error)
        assert g.배정번호.nunique()==len(g)
    for keys,g in splits.groupby(["scheme","run"]):
        train=set(g[g.partition.eq("train")].배정번호);test=set(g[g.partition.eq("test")].배정번호)
        assert not train&test and train|test==set(data.배정번호),(keys,"overlap or missing IDs")
    cross=int(((data.최초관측월<=5)&(pd.to_datetime(data.최종관측).dt.month>=6)).sum())
    assert cross==0,"Training jobs contain observations from June or later"
    reloads=[]
    for name in MODEL_CONFIGS:
        model=XGBClassifier();model.load_model(out/"모델"/"시간외삽_1_5월학습_6_7월평가"/f"time_{name}.json")
        probability=model.predict_proba(data[model.get_booster().feature_names])[:,1]
        saved=pred[(pred.scheme=="시간외삽_1_5월학습_6_7월평가")&(pred.model==name)].set_index("quality_row").sort_index()
        err=float(np.max(np.abs(probability-saved.probability.to_numpy())))
        assert err<1e-8
        reloads.append(dict(model=name,reload_prediction_max_error=err))
    checked=0
    if (out/"산출물_SHA256.json").is_file():
        manifest=json.loads((out/"산출물_SHA256.json").read_text(encoding="utf-8"))
        for name,digest in manifest.items():
            assert sha(out/name)==digest,name
            checked+=1
    checks=dict(cache_sha256_validated=True,metrics_rows=len(metrics),prediction_rows=len(pred),split_rows=len(splits),
                models=len(models),all_saved_metrics_recomputed_max_error=error_max,disjoint_complete_splits=runs,
                train_jobs_observations_crossing_into_june=cross,reloaded_time_models=reloads,output_hashes_checked=checked,
                time_training_label_counts=data[data.최초관측월<=5].위험여부.value_counts().sort_index().to_dict(),
                time_test_label_counts=data[data.최초관측월>=6].위험여부.value_counts().sort_index().to_dict())
    write_json(out/"검증_실행점검.json",checks)
    write_json(out/"산출물_SHA256.json",{str(p.relative_to(out)).replace("\\","/"):sha(p) for p in sorted(out.rglob("*")) if p.is_file() and p.name!="산출물_SHA256.json"})
    print("저장 결과 검증 통과:",checks,flush=True)
    return checks


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip",type=Path,help="선택: 원본 ZIP에서 136작업 입력을 재구축. 생략하면 SHA-256 검증 캐시 사용")
    parser.add_argument("--cache-dir",type=Path,default=ROOT/"inputs"/"재구축_품질예측")
    parser.add_argument("--output-dir",type=Path,default=ROOT/"reports"/"5단계_평가"/"5-2_대안접근"/"20261015"/"품질예측")
    parser.add_argument("--verify-only",action="store_true",help="재학습 없이 캐시와 저장 산출물만 검증")
    args=parser.parse_args()
    out=args.output_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    cache=args.cache_dir.resolve();cache.mkdir(parents=True,exist_ok=True)
    if args.verify_only:
        verify_outputs(cache,out)
        return
    if args.source_zip:
        data,meta=build_cache(args.source_zip,cache,out);origin="rebuilt_from_original_zip"
    else:
        data,meta=load_cache(cache);origin="sha256_verified_cached_136_job_features"
        write_csv(out/"감사"/"전처리_111행차이_원인확인.csv",pd.DataFrame(meta["preprocessing_comparisons"]))
    import sklearn, scipy, xgboost
    versions=dict(python=platform.python_version(),numpy=np.__version__,pandas=pd.__version__,scipy=scipy.__version__,sklearn=sklearn.__version__,xgboost=xgboost.__version__)
    runinfo=dict(input_origin=origin,cache_manifest_sha256=sha(cache/"cache_manifest.json"),versions=versions,
                 target="raw_ppm >= 450; no rounding",positive_label=1,negative_label=0,probability_threshold=THRESHOLD,
                 predicted_risk_rule="P(risk)>0.5; exact 0.5 is stable, matching XGBClassifier.predict",
                 base_parameters=BASE_PARAMS,model_configs=MODEL_CONFIGS,base_seed=FIXED_SEED,
                 comparison_config_note="Both feature sets use the original temperature-code explicit parameters (100 trees, depth 3, learning_rate .05, subsample .8, colsample .8). Shared settings were chosen for a controlled input-set comparison, not selected by June-July scores. This does not recover or claim the original full36 tuning parameters.",
                 time_evaluation_role="Retrospective temporal comparison of previously accessed historical data, not an untouched independent final test. The initial unequal-settings comparison is preserved separately; the protocol was corrected to equal settings for input-set comparability, not optimized against June-July scores.",
                 ap_definition="sklearn.average_precision_score; Average Precision, not trapezoidal PR-AUC",
                 exclusions=meta.get("excluded_jobs"),class_counts=meta["target_counts"],data_meta=meta)
    write_json(out/"실행설정_버전_입력출처.json",runinfo)
    original_results=audit_original(out)
    metrics,pred,summary,eval_info=evaluate(data,cache,out)
    runinfo.update(eval_info)
    runinfo["charts"]=plots(out,metrics,pred)
    write_json(out/"실행설정_버전_입력출처.json",runinfo)
    selected=metrics[metrics.partition.eq("test") & metrics.scheme.eq("시간외삽_1_5월학습_6_7월평가")]
    lines=["품질예측 5단계 검증 결과", "", f"입력 출처: {origin}",
           f"작업 {len(data)}개 / 안정 {(data.위험여부==0).sum()} / 위험 {(data.위험여부==1).sum()} / 작업 제외 {meta['excluded_jobs']}개",
           "목표는 개별 설비 고장 또는 순간 이상이 아니라, 작업 종료 후 확인한 불량률 450ppm 이상 여부입니다.",
           "특성은 작업 전체 관측구간 평균·표준편차이므로 이번 결과는 작업 완료 시점 분류이며 실시간 조기예측으로 해석하지 않습니다.",
           "결측은 전체 데이터 평균으로 사전 대체하지 않았습니다. 작업 내부 변수별 유효 관측만 집계하고, 남은 NaN은 학습 데이터에서 학습한 XGBoost 분기 규칙으로 처리합니다.",
           f"집계 후 결측 셀: {meta['missing_aggregate_cells']}; 이전 반올림 라벨과 달라진 작업: {meta['labels_different_from_old_round_percent_rule']}",
           "온도12와 전체36은 동일 작업·전처리·분리·모델 설정을 사용하며 입력 변수 집합만 다릅니다. 트리100개, 깊이3, 학습률.05, 행·열 표본비율 각각.8로 같게 고정했습니다.",
           "이 공통 설정은 기존 온도 코드의 명시된 설정을 사용해 공정한 입력 집합 비교를 하기 위해 정했습니다. 전체36 원래 최적 설정을 복원했다고 주장하지 않으며, 6~7월 점수로 설정을 고르지 않았습니다.",
           "초기 서로 다른 모델 설정 결과는 공유 패키지 기본 보고서의 부록_초기서로다른모델설정에 보존했으며 주분석에 혼합하지 않습니다.",
           "6~7월은 기존·초기 분석에서 이미 접근한 과거 자료의 시간 순서 회고비교이며, 한 번도 열어보지 않은 독립 최종시험이 아닙니다.",
           "초기 설정 차이를 바로잡아 입력 집합 비교를 공정하게 만든 절차 수정이며, 6~7월 점수가 좋아지는 설정을 탐색하지 않았습니다.",
           "확률 기준 .5를 평가 전에 고정했으며 6~7월을 보고 재조정하지 않았습니다.",
           "", "시간 순서 회고비교(1~5월 학습, 6~7월 평가):"]
    for _,r in selected.iterrows():
        lines.append(f"{r['model']}: 평가{int(r['n'])}작업(안정{int(r['stable'])}/위험{int(r['risk'])}), TN/FP/FN/TP={int(r.TN)}/{int(r.FP)}/{int(r.FN)}/{int(r.TP)}, 정확도={r.accuracy:.4f}, 정밀도={r.precision:.4f}, 재현율={r.recall:.4f}, F1={r.F1:.4f}, ROC-AUC={r.ROC_AUC:.4f}, AP={r.AP:.4f}")
    lines += ["", "반복층화 5겹×10회는 136작업을 재사용하는 내부 검증입니다. 1,360개 독립 작업이 아니며 표준편차는 독립 표본 신뢰구간이 아닙니다.",
              "AP는 평균정밀도(average_precision_score)이며 사다리꼴 적분 PR-AUC와 구분합니다. 분모가 없는 정밀도/F1은 0으로 기록했습니다.",
              "원본 저장 모델/결과표 감사: 온도 모델은 제공 성능표를 재현합니다. 전체36 저장 모델은 기준.5에서 위험을 모두 놓치며 확률 AUC .6125입니다. 기준.4가 제공 혼동행렬은 재현하지만 제공 AUC .575는 재현하지 못합니다.",
              "이번 새 실행은 원본 불일치를 덮어쓰지 않고 별도 고정 설정 모델·실행 정보·평가표를 새로 저장했습니다.",
              "원본 train.csv의 108행은 source_train_mapping.csv로 배정번호에 연결했습니다. seed2 학습 집합 일치: "+str(eval_info['source_train_same_indices_as_seed2']),
              "전체평균대체 결과는 전처리 차이 감사에만 사용했으며 새 모델 입력으로 사용하지 않았습니다."]
    (out/"검증결과_설명.txt").write_text("\n".join(lines)+"\n",encoding="utf-8")
    write_json(out/"산출물_SHA256.json",{str(p.relative_to(out)).replace("\\","/"):sha(p) for p in sorted(out.rglob("*")) if p.is_file() and p.name!="산출물_SHA256.json"})
    verify_outputs(cache,out)
    print("완료:",out,flush=True)


if __name__=="__main__":
    main()
