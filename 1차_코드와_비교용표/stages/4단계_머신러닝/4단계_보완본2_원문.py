#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""4단계 머신러닝 전체실행 — 팀 피드백(G01/G02/G03/G06) 반영본.

프로젝트 구조는 3단계와 같은 상대경로 방식을 사용합니다.
개인 PC의 C:\projects\... 같은 절대경로는 코드에 넣지 않습니다.

파일 위치:
  프로젝트/stages/4단계_머신러닝/4단계_머신러닝_전체실행.py

실행:
  .\.venv\Scripts\python.exe "stages/4단계_머신러닝/4단계_머신러닝_전체실행.py"

필수:
  - data/raw/data.csv
  - src/data_contract.py
  - 고정한 3단계 결과 폴더

3단계 비교 기준:
  - stages/4단계_머신러닝/3단계_비교기준.txt 파일을 사용합니다.
  - TXT에서 ① 팀 코드 재현본 결과와 ② 설명용 정리본 결과를 각각 고정합니다.
  - ①의 검증용_기록라벨/*.npz를 A1·A2 기록 단위 판정의 원본으로 사용합니다.
  - 가장 최근 폴더를 자동 선택하지 않습니다.

이번 보완의 핵심
  G02 설비 단위 비교
    - 센서 단위 표는 그대로 유지합니다.
    - A1·A2 설비 구간은 3단계 ②의 추가_설비그룹_이벤트.csv를 그대로 읽습니다.
    - IF는 같은 작업의 솔트조 1·2 Zone 우선조사 구간이 겹치거나 2초 이내이면
      같은 설비 단위 구간으로 합칩니다.
    - A1/A2/IF의 설비 단위 구간 수와 방법 간 공통 구간을 별도 표로 저장합니다.
    - '솔트조 2센서 통합' 기록 수가 무엇을 세는 값인지 출력 표에 정의를 넣습니다.

  G03 A2 비교 / 기록 단위 공통 범위
    - 3단계 ① 재현본이 저장한 검증용_기록라벨/*.npz의 A1·A2 valid/qual을 직접 읽습니다.
    - 3단계_공통범위_비교.py와 같은 정의(설비 모든 센서 valid, 센서 하나라도 qual)를 사용합니다.
    - A1·A2·IF와 솔트조 1·2 Zone이 모두 판단 가능한 6~7월 기록만 방법 비교에 사용합니다.
    - A2/IF 센서 단위 비교도 추가합니다.

  G06 3단계 결과 고정
    - 가장 최근 폴더를 자동 선택하지 않습니다.
    - 3단계_비교기준.txt에서 ① 재현본 폴더와 ② 정리본 폴더를 각각 고정합니다.
    - ① NPZ의 시각이 현재 원본과 기록 하나하나 일치하는지 확인합니다.
    - ① NPZ의 qual로 복원한 A1·A2 이벤트가 ②의 03_A1_A2_이상이벤트.csv와
      배정번호·센서·시작시각·종료시각·길이·후보기록수까지 일치하는지 확인합니다.
    - 다르면 A1/A2/IF 비교를 진행하지 않고 중단합니다.

  2단계_평소모습_종합.py 반영
    - 작업의 기간은 품질표 작업일이 아니라 '작업 첫 기록 월'로 정합니다.
    - 1~4월 = 기준작성, 5월 = 조건점검, 6~7월 = 후속비교.
    - 작업을 월 경계에서 쪼개지 않습니다.

Isolation Forest
  - 대상: 솔트조 온도 1 Zone, 솔트조 온도 2 Zone
  - 학습: 첫 기록 월 기준 1~4월
  - 5월: 99%, 99.5%, 99.9% 민감도 비교
  - 최종 조건: 99.9% 분위수
  - 6~7월: 조건 재조정 없이 고정 적용
  - 특성:
      1. 현재 온도
      2. 현재 온도 - 직전 최대 10분 중앙값
      3. 직전 최대 5분 표준편차
      4. 직전 기록 대비 초당 변화량

3단계와 같은 이벤트 규칙
  - 후보끼리 실제 시각 차이가 2초 이내이면 연결
  - 후보 사이 정상/판정불가 기록이 있어도 연결 가능
  - 중간 비후보 기록 자체를 후보로 바꾸지 않음
  - 선정용 길이 = 마지막 후보 시각 - 첫 후보 시각 + 1초
  - 선정용 길이 60초 이상 = 우선조사
  - 시간 집계는 이웃 관측 간격 5초 이하 실제 시간조각 사용

주의
  - 조사 후보이지 실제 고장/불량 확정이 아닙니다.
  - A1만/A2만/IF만을 바로 오탐으로 표현하지 않습니다.
  - 그래프는 화면 GUI가 아닌 matplotlib Agg 백엔드로 저장합니다.
    (Windows Tkinter 종료 오류 방지)
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime
import hashlib
import sys
import time
import platform

# 3단계와 같은 프로젝트 경로 규칙:
# stages/4단계_머신러닝/파일.py 의 두 단계 위 = 프로젝트 루트
PROJECT = Path(__file__).resolve().parents[2]


# ════════════════════════════════════════════════════════════════════
# 0. 실행 환경
# ════════════════════════════════════════════════════════════════════

def safe_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def check_python_env():
    venv = (PROJECT / ".venv").resolve()
    if Path(sys.prefix).resolve() != venv:
        raise ValueError(
            "프로젝트 전용 .venv 파이썬으로 실행하세요.\n"
            f"  지금 쓰는 파이썬 : {sys.executable}\n"
            f'  써야 하는 파이썬: {venv / "Scripts" / "python.exe"}'
        )


if __name__ == "__main__":
    safe_console()
    check_python_env()


import warnings  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib  # noqa: E402

# 이 스크립트는 그래프를 화면에 띄우지 않고 PNG로 저장만 합니다.
# Windows에서 TkAgg/Tkinter가 선택되면 종료 시
# 'main thread is not in main loop' / 'Tcl_AsyncDelete' 오류가 날 수 있으므로
# GUI가 필요 없는 Agg 백엔드를 pyplot import 전에 고정합니다.
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.font_manager as fm  # noqa: E402
plt.ioff()

# 롤링 이력 초반의 NaN을 float 배열로 바꾸는 과정에서 pandas가 내는
# 반복 경고입니다. IF 판정에서는 아래 build_features()의 np.isfinite 조건으로
# 해당 행을 이미 제외하므로 계산 결과에는 영향을 주지 않습니다.
warnings.filterwarnings(
    "ignore",
    message="invalid value encountered in cast",
    category=RuntimeWarning,
    module=r"pandas\.core\.base",
)

try:
    from sklearn.ensemble import IsolationForest  # noqa: E402
    import sklearn  # noqa: E402
except ImportError as error:
    raise ValueError(
        "scikit-learn이 필요합니다.\n"
        r'설치: .\.venv\Scripts\python.exe -m pip install scikit-learn'
    ) from error

sys.path.insert(0, str(PROJECT))
from src.data_contract import (  # noqa: E402
    TIME_COL,
    BATCH_COL,
    load_raw,
    add_segments,
    load_quality,
)


# ════════════════════════════════════════════════════════════════════
# 1. 고정 설정
# ════════════════════════════════════════════════════════════════════

SENSORS = [
    "솔트조 온도 1 Zone",
    "솔트조 온도 2 Zone",
]

TRAIN_PERIOD = "기준작성(1~4월)"
TUNE_PERIOD = "조정(5월)"
FOLLOW_PERIOD = "후속비교(6~7월)"

# 3단계(data_contract.load_quality)의 기간명 → 4단계 표기
TEAM_PERIOD = {
    "학습(1~4월)": TRAIN_PERIOD,
    "조정(5월)": TUNE_PERIOD,
    "후속적용(6~7월)": FOLLOW_PERIOD,
}

PERIOD_BY_MONTH = {
    1: TRAIN_PERIOD,
    2: TRAIN_PERIOD,
    3: TRAIN_PERIOD,
    4: TRAIN_PERIOD,
    5: TUNE_PERIOD,
    6: FOLLOW_PERIOD,
    7: FOLLOW_PERIOD,
}

# 2단계 종합본/문제정의서에 기록된 월별 작업 수
EXPECTED_JOBS = {
    1: 14,
    2: 8,
    3: 22,
    4: 34,
    5: 22,
    6: 22,
    7: 14,
}

# A1/IF 공통 최소 과거 기록 조건
MIN_HISTORY_COUNT = 300

# 3단계 이벤트 규칙
EVENT_GAP_SEC = 2
MIN_DURATION_SEC = 60
PIECE_MAX_GAP_SEC = 5

# A1/A2 공통 Z 조건
Z_LIMIT = 4.0

# Isolation Forest
RANDOM_STATE = 42
N_ESTIMATORS = 300
MAX_TRAIN_ROWS = 200_000
THRESHOLD_QUANTILES = [0.99, 0.995, 0.999]
FINAL_IF_QUANTILE = 0.999

FEATURE_NAMES = [
    "현재온도",
    "최근10분차이",
    "최근5분표준편차",
    "초당변화량",
]

# 원본 검토 그래프
TOP_REVIEW_POINTS = 5
REVIEW_SEPARATION_MIN = 10
PLOT_BEFORE_MIN = 10
PLOT_AFTER_MIN = 10

# G06: 가장 최근 3단계 결과를 자동으로 고르지 않습니다.
# 아래 TXT에서 두 결과를 각각 고정합니다.
#   재현본=...  → reports/3단계_이상구간_팀코드재현/.../검증용_기록라벨/*.npz
#   정리본=...  → reports/3단계_이상구간/.../03_A1_A2_이상이벤트.csv 등
STAGE3_LOCK_FILE = (
    PROJECT
    / "stages"
    / "4단계_머신러닝"
    / "3단계_비교기준.txt"
)

# 3단계 ① 재현본의 센서 순서에서 솔트조는 4, 5번입니다.
NPZ_SENSOR_INDEX = {
    "솔트조 온도 1 Zone": 4,
    "솔트조 온도 2 Zone": 5,
}

OUT = (
    PROJECT
    / "reports"
    / "4단계_머신러닝"
    / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
)

MAY_FIG_DIR = OUT / "figures_5월_IF"
COMPARE_FIG_DIR = OUT / "figures_A1_IF_비교"


# ════════════════════════════════════════════════════════════════════
# 2. 공통 유틸
# ════════════════════════════════════════════════════════════════════

def set_korean_font():
    installed = {f.name for f in fm.fontManager.ttflist}
    for name in [
        "Malgun Gothic",
        "맑은 고딕",
        "AppleGothic",
        "NanumGothic",
        "Noto Sans CJK KR",
    ]:
        if name in installed:
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False


def save(table: pd.DataFrame, name: str):
    table.to_csv(
        OUT / name,
        index=False,
        encoding="utf-8-sig",
    )


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_batch(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.replace(r"\.0$", "", regex=True)
    )


def resolve_fixed_stage3_dirs():
    """G06: TXT에서 고정한 ① 재현본 / ② 정리본만 사용합니다.

    TXT 형식:
      재현본=20261007_131646_348915
      정리본=20261007_134935_263964

    전체 경로가 아니라 각 reports 하위의 실행 폴더명만 적습니다.
    """
    if not STAGE3_LOCK_FILE.is_file():
        raise FileNotFoundError(
            "3단계 비교기준 TXT 파일이 없습니다.\n"
            f"필요한 위치: {STAGE3_LOCK_FILE}\n"
            "stages/4단계_머신러닝/3단계_비교기준.txt를 넣어주세요."
        )

    settings = {}
    for raw_line in STAGE3_LOCK_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(
                "3단계_비교기준.txt는 '재현본=폴더명', '정리본=폴더명' 형식이어야 합니다."
            )
        key, value = [x.strip() for x in line.split("=", 1)]
        settings[key] = value

    need = ["재현본", "정리본"]
    missing_keys = [k for k in need if k not in settings]
    if missing_keys:
        raise ValueError(
            f"3단계_비교기준.txt에 필요한 항목이 없습니다: {missing_keys}"
        )

    for key in need:
        value = settings[key]
        if (
            not value
            or value.startswith("<")
            or value.endswith(">")
            or "/" in value
            or "\\" in value
            or ":" in value
        ):
            raise ValueError(
                f"{key} 값에는 전체 경로가 아니라 실행 폴더명만 적으세요: {value}"
            )

    ref1 = (
        PROJECT
        / "reports"
        / "3단계_이상구간_팀코드재현"
        / settings["재현본"]
    ).resolve()

    ref2 = (
        PROJECT
        / "reports"
        / "3단계_이상구간"
        / settings["정리본"]
    ).resolve()

    required_ref1 = [
        ref1 / "검증용_기록라벨",
    ]
    required_ref2 = [
        ref2 / "03_A1_A2_이상이벤트.csv",
        ref2 / "추가_설비그룹_이벤트.csv",
        ref2 / "추가_기간별_설비별_요약.csv",
    ]

    missing = [
        str(p)
        for p in required_ref1 + required_ref2
        if not p.exists()
    ]

    if missing:
        recon_root = PROJECT / "reports" / "3단계_이상구간_팀코드재현"
        clean_root = PROJECT / "reports" / "3단계_이상구간"
        recon_candidates = [
            p.name for p in sorted(recon_root.glob("*"))
            if p.is_dir() and (p / "검증용_기록라벨").is_dir()
        ] if recon_root.is_dir() else []
        clean_candidates = [
            p.name for p in sorted(clean_root.glob("*"))
            if p.is_dir()
            and (p / "03_A1_A2_이상이벤트.csv").is_file()
            and (p / "추가_설비그룹_이벤트.csv").is_file()
        ] if clean_root.is_dir() else []

        raise FileNotFoundError(
            "고정한 3단계 결과에 필요한 파일/폴더가 부족합니다.\n"
            + "\n".join(missing)
            + f"\n검증용 라벨이 있는 재현본 후보: {recon_candidates[-10:]}"
            + f"\n정리본 후보: {clean_candidates[-10:]}"
            + "\n재현본이 없다면 3단계_이상구간_팀코드재현.py를 --no-labels 없이 한 번 실행하세요."
        )

    return ref1, ref2


# ════════════════════════════════════════════════════════════════════
# 3. 2단계 종합본과 같은 '첫 기록 월' 기간 구분
# ════════════════════════════════════════════════════════════════════

def attach_first_record_period(df: pd.DataFrame):
    """작업 전체를 그 작업의 첫 기록 월에 배정합니다. 월 경계에서 작업을 쪼개지 않습니다."""
    jobs = (
        df.groupby(BATCH_COL, sort=False)
        .agg(
            첫기록시각=(TIME_COL, "min"),
            마지막기록시각=(TIME_COL, "max"),
            원본행수=(TIME_COL, "size"),
            연속구간수=("segment_id", "nunique"),
        )
        .reset_index()
    )

    jobs["첫기록월"] = jobs["첫기록시각"].dt.month
    jobs["period"] = jobs["첫기록월"].map(PERIOD_BY_MONTH)

    if jobs["period"].isna().any():
        bad = jobs.loc[
            jobs["period"].isna(),
            [BATCH_COL, "첫기록시각", "첫기록월"],
        ]
        raise ValueError(
            "1~7월 밖의 작업이 있어 기간을 정할 수 없습니다.\n"
            + bad.to_string(index=False)
        )

    period_map = dict(zip(jobs[BATCH_COL], jobs["period"]))
    month_map = dict(zip(jobs[BATCH_COL], jobs["첫기록월"]))

    df["period"] = df[BATCH_COL].map(period_map)
    df["첫기록월"] = df[BATCH_COL].map(month_map)

    month_counts = (
        jobs.groupby("첫기록월", as_index=False)
        .agg(
            작업수=(BATCH_COL, "size"),
            기록수=("원본행수", "sum"),
        )
        .sort_values("첫기록월")
        .reset_index(drop=True)
    )

    actual = dict(
        zip(
            month_counts["첫기록월"].astype(int),
            month_counts["작업수"].astype(int),
        )
    )
    expected_match = actual == EXPECTED_JOBS

    month_counts["문제정의서_기대작업수"] = (
        month_counts["첫기록월"]
        .map(EXPECTED_JOBS)
        .astype("Int64")
    )
    month_counts["기대값일치"] = (
        month_counts["작업수"]
        .eq(month_counts["문제정의서_기대작업수"])
    )

    return df, jobs, month_counts, expected_match


def verify_first_record_period_vs_stage3(df: pd.DataFrame):
    """2단계 첫 기록 월 기간과 3단계 품질 작업일 기반 세 기간의 작업 집합이 같은지 확인합니다."""
    q = load_quality().copy()
    q[BATCH_COL] = normalize_batch(q[BATCH_COL])
    q["3단계_period"] = q["기간"].map(TEAM_PERIOD)

    first = (
        df[[BATCH_COL, "period"]]
        .drop_duplicates(BATCH_COL)
        .rename(columns={"period": "2단계_첫기록월_period"})
    )

    check = first.merge(
        q[[BATCH_COL, "3단계_period"]],
        on=BATCH_COL,
        how="outer",
        validate="one_to_one",
    )
    check["세기간구분일치"] = check["2단계_첫기록월_period"].eq(check["3단계_period"])

    if not check["세기간구분일치"].all():
        bad = check.loc[~check["세기간구분일치"]]
        raise ValueError(
            "2단계 첫 기록 월 기준과 3단계 세 기간 작업 집합이 다릅니다. "
            "공통 비교 전에 기준을 다시 확인해야 합니다.\n"
            + bad.head(20).to_string(index=False)
        )

    return check


# ════════════════════════════════════════════════════════════════════
# 4. IF/A1 공용 과거 특성
# ════════════════════════════════════════════════════════════════════

def build_features(df: pd.DataFrame, sensor: str):
    """현재값을 제외한 과거 실제 기록으로만 특성을 계산합니다."""
    n = len(df)

    baseline10 = np.full(n, np.nan, dtype="float64")
    count10 = np.zeros(n, dtype="int32")
    std5 = np.full(n, np.nan, dtype="float64")

    for idx in df.groupby(
        [BATCH_COL, "segment_id"],
        sort=False,
    ).indices.values():

        idx = np.asarray(idx, dtype=np.int64)

        ts = pd.DatetimeIndex(
            df.iloc[idx][TIME_COL]
        )

        values = (
            df.iloc[idx][sensor]
            .to_numpy(dtype="float64")
        )

        s = pd.Series(values, index=ts)

        roll10 = s.rolling(
            "600s",
            closed="left",
            min_periods=MIN_HISTORY_COUNT,
        )

        baseline10[idx] = roll10.median().to_numpy()

        count10[idx] = (
            s.rolling(
                "600s",
                closed="left",
                min_periods=1,
            )
            .count()
            .to_numpy(dtype="int32")
        )

        std5[idx] = (
            s.rolling(
                "300s",
                closed="left",
                min_periods=2,
            )
            .std()
            .to_numpy()
        )

    current = df[sensor].to_numpy(dtype="float64")
    diff10 = current - baseline10

    prev = (
        df.groupby(
            [BATCH_COL, "segment_id"],
            sort=False,
        )[sensor]
        .shift(1)
        .to_numpy(dtype="float64")
    )

    dt_prev = (
        pd.to_numeric(
            df["dt_prev"],
            errors="coerce",
        )
        .to_numpy(dtype="float64")
    )

    rate = np.full(n, np.nan, dtype="float64")

    rate_ok = (
        np.isfinite(current)
        & np.isfinite(prev)
        & np.isfinite(dt_prev)
        & (dt_prev > 0)
        & (dt_prev <= 12)
    )

    rate[rate_ok] = (
        current[rate_ok] - prev[rate_ok]
    ) / dt_prev[rate_ok]

    feat = pd.DataFrame(
        {
            "현재온도": current,
            "최근10분중앙값": baseline10,
            "최근10분차이": diff10,
            "최근10분유효값수": count10,
            "최근5분표준편차": std5,
            "초당변화량": rate,
        },
        index=df.index,
    )

    # A1과 IF 모두 직전 10분 300개 이상이라는 공통 최소 이력 조건을 가집니다.
    # IF는 추가 특성까지 모두 계산 가능해야 합니다.
    if_valid = (
        np.isfinite(feat["현재온도"])
        & np.isfinite(feat["최근10분중앙값"])
        & np.isfinite(feat["최근5분표준편차"])
        & np.isfinite(feat["초당변화량"])
        & (feat["최근10분유효값수"] >= MIN_HISTORY_COUNT)
    ).to_numpy()

    return feat, if_valid


def fit_iforest(X: np.ndarray):
    model = IsolationForest(
        n_estimators=N_ESTIMATORS,
        max_samples="auto",
        contamination="auto",
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(X)
    return model


def anomaly_score(model, X: np.ndarray):
    # 클수록 더 드문 패턴으로 보이도록 부호 반전
    return -model.score_samples(X)


# ════════════════════════════════════════════════════════════════════
# 5. 3단계와 같은 이벤트 연결
# ════════════════════════════════════════════════════════════════════

def link_all_events(times_ns, candidate):
    """후보끼리 2초 이내 연결. 중간 비후보는 양성으로 바꾸지 않습니다."""
    candidate = np.asarray(candidate, dtype=bool)

    qual = np.zeros(len(candidate), dtype=bool)
    events = []

    pos = np.flatnonzero(candidate)
    if len(pos) == 0:
        return qual, events

    t_sec = times_ns[pos] // 1_000_000_000

    cuts = np.r_[
        0,
        np.flatnonzero(
            np.diff(t_sec) > EVENT_GAP_SEC
        ) + 1,
        len(pos),
    ]

    for a, b in zip(cuts[:-1], cuts[1:]):
        p = pos[a:b]

        duration = (
            times_ns[p[-1]] - times_ns[p[0]]
        ) / 1e9 + 1.0

        priority = duration >= MIN_DURATION_SEC

        if priority:
            qual[p] = True

        events.append(
            {
                "st": int(p[0]),
                "en": int(p[-1]),
                "duration_sec": float(duration),
                "candidate_count": int(len(p)),
                "priority": bool(priority),
            }
        )

    return qual, events


def self_test():
    sec = 1_000_000_000
    t = np.arange(0, 101, dtype="int64") * sec

    c = np.zeros(101, dtype=bool)
    c[0:31] = True
    c[32:62] = True
    qual, ev = link_all_events(t, c)

    assert len(ev) == 1
    assert ev[0]["duration_sec"] == 62.0
    assert ev[0]["candidate_count"] == 61
    assert ev[0]["priority"]
    assert not qual[31]

    c2 = np.zeros(101, dtype=bool)
    c2[0:31] = True
    c2[33:63] = True
    assert len(link_all_events(t, c2)[1]) == 2

    c3 = np.zeros(101, dtype=bool)
    c3[0:60] = True
    assert link_all_events(t, c3)[1][0]["duration_sec"] == 60.0

    print(
        "[규칙검사 통과] "
        "2초 후보 연결 / 중간 비후보 유지 / +1초 60초 선정"
    )


def event_table_from_candidate(
    df,
    sensor,
    method,
    score,
    candidate,
    threshold=np.nan,
):
    """기록 후보 → 이벤트. 짧은 후보와 우선조사를 모두 반환."""
    rows = []
    qual_all = np.zeros(len(df), dtype=bool)

    for batch, idx in df.groupby(
        BATCH_COL,
        sort=False,
    ).indices.items():

        idx = np.asarray(idx, dtype=np.int64)
        local_cand = np.asarray(candidate[idx], dtype=bool)

        if not local_cand.any():
            continue

        times_ns = (
            df.iloc[idx][TIME_COL]
            .to_numpy(dtype="datetime64[ns]")
            .astype("int64")
        )

        local_qual, events = link_all_events(
            times_ns,
            local_cand,
        )

        qual_all[idx] = local_qual

        local_score = np.asarray(score[idx], dtype="float64")
        temp = (
            df.iloc[idx][sensor]
            .to_numpy(dtype="float64")
        )

        for e in events:
            st = e["st"]
            en = e["en"]

            pos = (
                np.flatnonzero(
                    local_cand[st : en + 1]
                )
                + st
            )

            vals = temp[pos]

            rows.append(
                {
                    "method": method,
                    BATCH_COL: str(batch),
                    "period": df.iloc[idx]["period"].iloc[st],
                    "sensor": sensor,
                    "start_time": pd.Timestamp(times_ns[st]),
                    "end_time": pd.Timestamp(times_ns[en]),
                    "duration_sec": e["duration_sec"],
                    "실제길이_sec": e["duration_sec"] - 1.0,
                    "anomaly_sample_count": e["candidate_count"],
                    "사이에_낀_비후보기록수": int(
                        (en - st + 1) - e["candidate_count"]
                    ),
                    "max_score": (
                        float(np.nanmax(local_score[pos]))
                        if len(pos)
                        else np.nan
                    ),
                    "threshold": threshold,
                    "시작온도": (
                        float(temp[st])
                        if np.isfinite(temp[st])
                        else np.nan
                    ),
                    "종료온도": (
                        float(temp[en])
                        if np.isfinite(temp[en])
                        else np.nan
                    ),
                    "최소온도": (
                        float(np.nanmin(vals))
                        if len(vals)
                        else np.nan
                    ),
                    "최대온도": (
                        float(np.nanmax(vals))
                        if len(vals)
                        else np.nan
                    ),
                    "구간구분": (
                        "우선조사"
                        if e["priority"]
                        else "짧은후보_보존"
                    ),
                }
            )

    columns = [
        "method",
        BATCH_COL,
        "period",
        "sensor",
        "start_time",
        "end_time",
        "duration_sec",
        "실제길이_sec",
        "anomaly_sample_count",
        "사이에_낀_비후보기록수",
        "max_score",
        "threshold",
        "시작온도",
        "종료온도",
        "최소온도",
        "최대온도",
        "구간구분",
    ]

    return pd.DataFrame(rows, columns=columns), qual_all


# ════════════════════════════════════════════════════════════════════
# 6. 3단계 ① 기록별 판정 NPZ + ② 이벤트/설비구간 읽기
# ════════════════════════════════════════════════════════════════════

def load_stage3_outputs(ref2_dir: Path):
    """3단계 ② 설명용 정리본의 센서 이벤트와 설비 그룹 이벤트를 읽습니다."""
    events = pd.read_csv(
        ref2_dir / "03_A1_A2_이상이벤트.csv",
        encoding="utf-8-sig",
        dtype={BATCH_COL: str},
    )
    group_events = pd.read_csv(
        ref2_dir / "추가_설비그룹_이벤트.csv",
        encoding="utf-8-sig",
        dtype={BATCH_COL: str},
    )

    for table in (events, group_events):
        table[BATCH_COL] = normalize_batch(table[BATCH_COL])
        table["start_time"] = pd.to_datetime(table["start_time"])
        table["end_time"] = pd.to_datetime(table["end_time"])

    required_events = {
        "method", BATCH_COL, "period", "sensor",
        "start_time", "end_time", "duration_sec", "anomaly_sample_count",
    }
    if not required_events.issubset(events.columns):
        raise ValueError(
            "3단계 03_A1_A2_이상이벤트.csv 열 구성이 예상과 다릅니다: "
            f"{sorted(required_events - set(events.columns))}"
        )

    required_group = {
        "method", BATCH_COL, "period", "설비",
        "start_time", "end_time", "실제길이_sec", "포함센서",
    }
    if not required_group.issubset(group_events.columns):
        raise ValueError(
            "3단계 추가_설비그룹_이벤트.csv 열 구성이 예상과 다릅니다: "
            f"{sorted(required_group - set(group_events.columns))}"
        )

    return events, group_events


def load_stage3_npz_labels(df: pd.DataFrame, ref1_dir: Path):
    """3단계 ①의 검증용_기록라벨/*.npz를 기록 단위 A1/A2 판정의 원본으로 사용합니다.

    4단계에서 A1/A2를 다시 계산하지 않습니다.
    NPZ의 TAG_MIN_ns와 현재 원본의 작업별 시각이 하나라도 다르면 중단합니다.
    """
    label_dir = ref1_dir / "검증용_기록라벨"
    files = sorted(label_dir.glob("*.npz"))

    batches = set(df[BATCH_COL].astype(str).unique())
    file_batches = {p.stem for p in files}

    if file_batches != batches:
        raise ValueError(
            "3단계 ① NPZ 작업 목록과 현재 원본 작업 목록이 다릅니다.\n"
            f"NPZ에만 있음: {sorted(file_batches - batches)[:20]}\n"
            f"원본에만 있음: {sorted(batches - file_batches)[:20]}"
        )

    labels = {
        method: {
            sensor: {
                "valid": np.zeros(len(df), dtype=bool),
                "qual": np.zeros(len(df), dtype=bool),
            }
            for sensor in SENSORS
        }
        for method in ("A1", "A2")
    }

    by_batch = {
        str(batch): np.asarray(idx, dtype=np.int64)
        for batch, idx in df.groupby(BATCH_COL, sort=False).indices.items()
    }

    check_rows = []

    for p in files:
        batch = p.stem
        idx = by_batch[batch]
        raw_times = (
            df.iloc[idx][TIME_COL]
            .to_numpy(dtype="datetime64[ns]")
            .astype("int64")
        )

        with np.load(p) as z:
            needed = {"TAG_MIN_ns"}
            for method in ("A1", "A2"):
                for sensor in SENSORS:
                    k = NPZ_SENSOR_INDEX[sensor]
                    needed |= {
                        f"{method}_{k}_valid",
                        f"{method}_{k}_qual",
                    }

            missing = needed - set(z.files)
            if missing:
                raise ValueError(
                    f"{p.name}에 필요한 기록별 판정 배열이 없습니다: {sorted(missing)}"
                )

            npz_times = np.asarray(z["TAG_MIN_ns"], dtype="int64")
            time_equal = (
                len(npz_times) == len(raw_times)
                and np.array_equal(npz_times, raw_times)
            )

            check_rows.append(
                {
                    BATCH_COL: batch,
                    "원본기록수": len(raw_times),
                    "NPZ기록수": len(npz_times),
                    "시각_완전일치": bool(time_equal),
                }
            )

            if not time_equal:
                raise ValueError(
                    f"3단계 ① NPZ와 현재 원본의 기록 시각이 다릅니다: 배정번호 {batch}"
                )

            for method in ("A1", "A2"):
                for sensor in SENSORS:
                    k = NPZ_SENSOR_INDEX[sensor]
                    valid = np.asarray(z[f"{method}_{k}_valid"], dtype=bool)
                    qual = np.asarray(z[f"{method}_{k}_qual"], dtype=bool)
                    if len(valid) != len(idx) or len(qual) != len(idx):
                        raise ValueError(
                            f"{p.name}: {method} {sensor} 배열 길이가 원본과 다릅니다."
                        )
                    labels[method][sensor]["valid"][idx] = valid
                    labels[method][sensor]["qual"][idx] = qual

    return labels, pd.DataFrame(check_rows)


def events_from_npz_qual(df, method, qual_by_sensor):
    """NPZ의 60초 이상 선정 후보(qual) 시각만으로 센서 이벤트 키를 복원합니다.

    score/이탈값을 다시 계산하지 않고, ② 이벤트 CSV와
    시작·종료·길이·후보기록수 일치 여부만 확인하는 검증용입니다.
    """
    rows = []
    for sensor in SENSORS:
        qual = np.asarray(qual_by_sensor[sensor], dtype=bool)
        for batch, idx in df.groupby(BATCH_COL, sort=False).indices.items():
            idx = np.asarray(idx, dtype=np.int64)
            local = qual[idx]
            if not local.any():
                continue
            times_ns = (
                df.iloc[idx][TIME_COL]
                .to_numpy(dtype="datetime64[ns]")
                .astype("int64")
            )
            _, events = link_all_events(times_ns, local)
            for e in events:
                # link_all_events()는 튜플이 아니라 dict를 반환합니다.
                st = e["st"]
                en = e["en"]
                duration = e["duration_sec"]
                npts = e["candidate_count"]
                priority = e["priority"]

                if not priority:
                    # qual은 이미 3단계에서 60초 이상 선정 이벤트의 후보 기록만 True여야 함
                    raise ValueError(
                        f"NPZ qual에서 60초 미만 이벤트가 복원되었습니다: {method} {batch} {sensor}"
                    )

                rows.append(
                    {
                        "method": method,
                        BATCH_COL: str(batch),
                        "sensor": sensor,
                        "start_time": pd.Timestamp(times_ns[st]),
                        "end_time": pd.Timestamp(times_ns[en]),
                        "duration_sec": float(duration),
                        "anomaly_sample_count": int(npts),
                    }
                )
    return pd.DataFrame(rows)


def event_key_table(df: pd.DataFrame):
    columns = [
        "method", BATCH_COL, "sensor", "start_time", "end_time",
        "duration_sec", "anomaly_sample_count",
    ]
    if df.empty:
        return pd.DataFrame(columns=columns)
    out = df[columns].copy()
    out[BATCH_COL] = normalize_batch(out[BATCH_COL])
    out["start_time"] = pd.to_datetime(out["start_time"])
    out["end_time"] = pd.to_datetime(out["end_time"])
    out["duration_sec"] = pd.to_numeric(out["duration_sec"], errors="coerce").round(6)
    out["anomaly_sample_count"] = pd.to_numeric(
        out["anomaly_sample_count"], errors="coerce"
    ).astype("Int64")
    return out


def verify_npz_events_against_stage3(stage3_events, npz_events):
    """① 기록 라벨로 복원한 이벤트와 ② 이벤트 CSV를 시각·길이까지 대조합니다."""
    fixed = event_key_table(
        stage3_events.loc[
            stage3_events["method"].isin(["A1", "A2"])
            & stage3_events["sensor"].isin(SENSORS)
        ]
    )
    recon = event_key_table(npz_events)

    key = [
        "method", BATCH_COL, "sensor", "start_time", "end_time",
        "duration_sec", "anomaly_sample_count",
    ]
    fixed["_fixed"] = 1
    recon["_npz"] = 1
    merged = fixed.merge(recon, on=key, how="outer")
    merged["상태"] = np.select(
        [
            merged["_fixed"].eq(1) & merged["_npz"].eq(1),
            merged["_fixed"].eq(1) & merged["_npz"].isna(),
            merged["_fixed"].isna() & merged["_npz"].eq(1),
        ],
        ["일치", "② 이벤트에만 있음", "① NPZ 복원에만 있음"],
        default="확인필요",
    )
    detail = merged.loc[~merged["상태"].eq("일치"), key + ["상태"]].copy()

    rows = []
    for method in ["A1", "A2"]:
        for sensor in SENSORS:
            f = fixed.loc[fixed["method"].eq(method) & fixed["sensor"].eq(sensor)]
            r = recon.loc[recon["method"].eq(method) & recon["sensor"].eq(sensor)]
            d = detail.loc[detail["method"].eq(method) & detail["sensor"].eq(sensor)]
            rows.append(
                {
                    "method": method,
                    "sensor": sensor,
                    "②_이벤트수": len(f),
                    "①_NPZ복원이벤트수": len(r),
                    "시작종료길이후보기록수_완전일치": len(d) == 0,
                    "불일치행수": len(d),
                }
            )
    return pd.DataFrame(rows), detail


def build_stage3_a1a2_common_check(df, piece, a1_valid, a2_valid, a1_qual, a2_qual):
    """3단계_공통범위_비교.py의 솔트조 정의를 그대로 적용한 확인표."""
    v1 = np.logical_and.reduce([a1_valid[s] for s in SENSORS])
    v2 = np.logical_and.reduce([a2_valid[s] for s in SENSORS])
    q1 = np.logical_or.reduce([a1_qual[s] for s in SENSORS])
    q2 = np.logical_or.reduce([a2_qual[s] for s in SENSORS])
    c = v1 & v2

    rows = []
    for period in [TRAIN_PERIOD, TUNE_PERIOD, FOLLOW_PERIOD]:
        p = df["period"].eq(period).to_numpy()
        cp = c & p
        rows.append(
            {
                "period": period,
                "설비": "솔트조",
                "공통범위_기록수": int(cp.sum()),
                "공통범위_시간_sec": float(piece[cp].sum()),
                "A1양성_기록수": int((q1 & cp).sum()),
                "A1양성_시간_sec": float(piece[q1 & cp].sum()),
                "A2양성_기록수": int((q2 & cp).sum()),
                "A2양성_시간_sec": float(piece[q2 & cp].sum()),
                "둘다양성_기록수": int((q1 & q2 & cp).sum()),
                "둘다양성_시간_sec": float(piece[q1 & q2 & cp].sum()),
                "A1만_기록수": int((q1 & ~q2 & cp).sum()),
                "A2만_기록수": int((q2 & ~q1 & cp).sum()),
                "정의": (
                    "3단계_공통범위_비교.py와 동일: 솔트조 1·2 Zone이 모두 valid인 기록이 방법별 판정가능, "
                    "A1·A2 둘 다 판정가능한 기록이 공통범위, 설비 양성은 두 Zone 중 하나라도 qual=True"
                ),
            }
        )
    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════════
# 7. 실제 시간조각 / 공통 판정가능 범위
# ════════════════════════════════════════════════════════════════════

def make_piece_array(df):
    """각 행 → 다음 행까지 5초 이하인 실제 관측 시간조각."""
    dt = (
        pd.to_numeric(
            df["dt_next"],
            errors="coerce",
        )
        .to_numpy(dtype="float64")
    )

    same_batch = (
        df[BATCH_COL]
        .eq(df[BATCH_COL].shift(-1))
        .to_numpy()
    )

    same_segment = (
        df["segment_id"]
        .eq(df["segment_id"].shift(-1))
        .to_numpy()
    )

    ok = (
        same_batch
        & same_segment
        & np.isfinite(dt)
        & (dt > 0)
        & (dt <= PIECE_MAX_GAP_SEC)
    )

    return np.where(ok, dt, 0.0)


def build_three_method_record_summary(
    df,
    common_valid,
    piece,
    a1_qual,
    a2_qual,
    if_qual,
):
    """A1/A2/IF 세 방법을 똑같은 공통 판정가능 범위에서 집계."""
    rows = []

    def one_row(label, a1, a2, iff, definition):
        a1 = common_valid & a1
        a2 = common_valid & a2
        iff = common_valid & iff

        a1_a2 = a1 & a2
        a1_if = a1 & iff
        a2_if = a2 & iff
        all3 = a1 & a2 & iff

        rows.append(
            {
                "범위": label,
                "정의": definition,
                "공통판정가능기록수": int(common_valid.sum()),
                "공통판정가능시간_sec": float(
                    piece[common_valid].sum()
                ),
                "A1양성기록수": int(a1.sum()),
                "A2양성기록수": int(a2.sum()),
                "IF양성기록수": int(iff.sum()),
                "A1_A2공통기록수": int(a1_a2.sum()),
                "A1_IF공통기록수": int(a1_if.sum()),
                "A2_IF공통기록수": int(a2_if.sum()),
                "세방법공통기록수": int(all3.sum()),
                "A1만기록수": int(
                    (a1 & ~a2 & ~iff).sum()
                ),
                "A2만기록수": int(
                    (a2 & ~a1 & ~iff).sum()
                ),
                "IF만기록수": int(
                    (iff & ~a1 & ~a2).sum()
                ),
                "A1양성시간_sec": float(piece[a1].sum()),
                "A2양성시간_sec": float(piece[a2].sum()),
                "IF양성시간_sec": float(piece[iff].sum()),
                "A1_IF공통시간_sec": float(piece[a1_if].sum()),
                "A2_IF공통시간_sec": float(piece[a2_if].sum()),
                "세방법공통시간_sec": float(piece[all3].sum()),
            }
        )

    for sensor in SENSORS:
        one_row(
            sensor,
            a1_qual[sensor],
            a2_qual[sensor],
            if_qual[sensor],
            (
                "해당 센서의 실제 원본 한 행을 1회로 집계. "
                "A1/A2/IF 모두 판정 가능한 6~7월 기록만 사용."
            ),
        )

    # G02: '2센서 통합 공통 178' 같은 숫자의 정의를 명시
    a1_union = np.logical_or.reduce(
        [a1_qual[s] for s in SENSORS]
    )
    a2_union = np.logical_or.reduce(
        [a2_qual[s] for s in SENSORS]
    )
    if_union = np.logical_or.reduce(
        [if_qual[s] for s in SENSORS]
    )

    one_row(
        "솔트조 2센서 통합",
        a1_union,
        a2_union,
        if_union,
        (
            "이벤트 개수가 아니라 원본 기록(행) 수. "
            "같은 원본 행에서 솔트조 1·2 Zone 중 하나라도 해당 방법의 "
            "60초 이상 선정 이벤트에 속한 실제 후보 기록이면 그 방법 양성으로 보고, "
            "두 Zone이 동시에 양성이어도 그 행은 1회만 센다. "
            "예: A1_IF공통기록수는 같은 원본 행에서 A1은 두 Zone 중 하나 이상, "
            "IF도 두 Zone 중 하나 이상 양성인 행의 수이다."
        ),
    )

    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════════
# 8. 센서 단위 방법 비교
# ════════════════════════════════════════════════════════════════════

def interval_overlap(a_start, a_end, b_start, b_end):
    start = max(pd.Timestamp(a_start), pd.Timestamp(b_start))
    end = min(pd.Timestamp(a_end), pd.Timestamp(b_end))
    if end < start:
        return None
    return start, end


def build_batch_lookup(df):
    lookup = {}
    for batch, idx in df.groupby(
        BATCH_COL,
        sort=False,
    ).indices.items():
        idx = np.asarray(idx, dtype=np.int64)
        lookup[str(batch)] = {
            "idx": idx,
            "times_ns": (
                df.iloc[idx][TIME_COL]
                .to_numpy(dtype="datetime64[ns]")
                .astype("int64")
            ),
        }
    return lookup


def event_has_common_positive(
    row,
    method_qual,
    common_valid,
    lookup,
):
    batch = str(row[BATCH_COL])
    sensor = row["sensor"]

    item = lookup.get(batch)
    if item is None:
        return False

    idx = item["idx"]
    times_ns = item["times_ns"]

    left = int(
        np.searchsorted(
            times_ns,
            pd.Timestamp(row["start_time"]).value,
            side="left",
        )
    )
    right = int(
        np.searchsorted(
            times_ns,
            pd.Timestamp(row["end_time"]).value,
            side="right",
        )
    )

    if left >= right:
        return False

    gidx = idx[left:right]

    return bool(
        (
            common_valid[gidx]
            & method_qual[sensor][gidx]
        ).any()
    )


def compare_sensor_events(
    df,
    events1,
    events2,
    name1,
    name2,
    qual1,
    qual2,
    common_valid,
    piece,
):
    """센서 단위 구간표는 유지하되, 공통판정범위 안에서만 두 방법 비교."""
    e1 = events1.reset_index(drop=True).copy()
    e2 = events2.reset_index(drop=True).copy()

    lookup = build_batch_lookup(df)

    eligible1 = np.array(
        [
            event_has_common_positive(
                row,
                qual1,
                common_valid,
                lookup,
            )
            for _, row in e1.iterrows()
        ],
        dtype=bool,
    )

    eligible2 = np.array(
        [
            event_has_common_positive(
                row,
                qual2,
                common_valid,
                lookup,
            )
            for _, row in e2.iterrows()
        ],
        dtype=bool,
    )

    hit1 = np.zeros(len(e1), dtype=bool)
    hit2 = np.zeros(len(e2), dtype=bool)

    common_rows = []

    for i, a in e1.iterrows():
        if not eligible1[i]:
            continue

        candidates = e2.loc[
            e2[BATCH_COL].astype(str).eq(str(a[BATCH_COL]))
            & e2["sensor"].eq(a["sensor"])
        ]

        for j, b in candidates.iterrows():
            if not eligible2[j]:
                continue

            ov = interval_overlap(
                a["start_time"],
                a["end_time"],
                b["start_time"],
                b["end_time"],
            )

            if ov is None:
                continue

            ov_start, ov_end = ov

            item = lookup[str(a[BATCH_COL])]
            idx = item["idx"]
            times_ns = item["times_ns"]

            left = int(
                np.searchsorted(
                    times_ns,
                    ov_start.value,
                    side="left",
                )
            )
            right = int(
                np.searchsorted(
                    times_ns,
                    ov_end.value,
                    side="right",
                )
            )

            gidx = idx[left:right]

            both = (
                common_valid[gidx]
                & qual1[a["sensor"]][gidx]
                & qual2[a["sensor"]][gidx]
            )

            if not both.any():
                continue

            hit_idx = gidx[both]

            hit1[i] = True
            hit2[j] = True

            common_rows.append(
                {
                    BATCH_COL: str(a[BATCH_COL]),
                    "sensor": a["sensor"],
                    f"{name1}_start": a["start_time"],
                    f"{name1}_end": a["end_time"],
                    f"{name1}_duration_sec": a["duration_sec"],
                    f"{name2}_start": b["start_time"],
                    f"{name2}_end": b["end_time"],
                    f"{name2}_duration_sec": b["duration_sec"],
                    "공통양성_첫기록": df.loc[
                        hit_idx, TIME_COL
                    ].min(),
                    "공통양성_마지막기록": df.loc[
                        hit_idx, TIME_COL
                    ].max(),
                    "공통양성기록수": int(both.sum()),
                    "공통양성시간_sec": float(
                        piece[hit_idx].sum()
                    ),
                }
            )

    only1 = (
        e1.loc[eligible1 & ~hit1]
        .copy()
        .reset_index(drop=True)
    )
    only2 = (
        e2.loc[eligible2 & ~hit2]
        .copy()
        .reset_index(drop=True)
    )

    excluded1 = (
        e1.loc[~eligible1]
        .copy()
        .assign(
            제외방법=name1,
            제외이유="공통 판정가능 범위에 해당 방법 양성 기록이 없음",
        )
    )

    excluded2 = (
        e2.loc[~eligible2]
        .copy()
        .assign(
            제외방법=name2,
            제외이유="공통 판정가능 범위에 해당 방법 양성 기록이 없음",
        )
    )

    excluded = pd.concat(
        [excluded1, excluded2],
        ignore_index=True,
        sort=False,
    )

    summary = pd.DataFrame(
        [
            {
                "비교": f"{name1} vs {name2}",
                "구분": f"{name1} 전체",
                "구간수": len(e1),
                "관련작업수": e1[BATCH_COL].nunique() if len(e1) else 0,
            },
            {
                "비교": f"{name1} vs {name2}",
                "구분": f"{name2} 전체",
                "구간수": len(e2),
                "관련작업수": e2[BATCH_COL].nunique() if len(e2) else 0,
            },
            {
                "비교": f"{name1} vs {name2}",
                "구분": f"{name1}+{name2} 공통({name1} 구간 기준)",
                "구간수": int(hit1.sum()),
                "관련작업수": (
                    e1.loc[hit1, BATCH_COL].nunique()
                    if hit1.any()
                    else 0
                ),
            },
            {
                "비교": f"{name1} vs {name2}",
                "구분": f"{name1}+{name2} 공통({name2} 구간 기준)",
                "구간수": int(hit2.sum()),
                "관련작업수": (
                    e2.loc[hit2, BATCH_COL].nunique()
                    if hit2.any()
                    else 0
                ),
            },
            {
                "비교": f"{name1} vs {name2}",
                "구분": f"{name1}만(공통판정범위)",
                "구간수": len(only1),
                "관련작업수": (
                    only1[BATCH_COL].nunique()
                    if len(only1)
                    else 0
                ),
            },
            {
                "비교": f"{name1} vs {name2}",
                "구분": f"{name2}만(공통판정범위)",
                "구간수": len(only2),
                "관련작업수": (
                    only2[BATCH_COL].nunique()
                    if len(only2)
                    else 0
                ),
            },
        ]
    )

    return (
        pd.DataFrame(common_rows),
        only1,
        only2,
        excluded,
        summary,
    )


# ════════════════════════════════════════════════════════════════════
# 9. G02 설비 단위 구간 통합/비교
# ════════════════════════════════════════════════════════════════════

def merge_equipment_events(sensor_events: pd.DataFrame, method: str):
    """같은 작업 솔트조 1·2 Zone 구간이 겹치거나 2초 이내면 설비 구간 하나로 합칩니다."""
    events = sensor_events.loc[
        sensor_events["sensor"].isin(SENSORS)
    ].copy()

    if "period" in events.columns:
        events = events.loc[
            events["period"].eq(FOLLOW_PERIOD)
        ].copy()

    events = events.sort_values(
        [BATCH_COL, "start_time", "end_time", "sensor"]
    )

    rows = []

    for batch, group in events.groupby(
        BATCH_COL,
        sort=False,
    ):
        merged = []

        for _, row in group.iterrows():
            st = pd.Timestamp(row["start_time"])
            en = pd.Timestamp(row["end_time"])
            sensor = row["sensor"]

            if (
                merged
                and (
                    st - merged[-1]["end_time"]
                ).total_seconds() <= EVENT_GAP_SEC
            ):
                merged[-1]["end_time"] = max(
                    merged[-1]["end_time"],
                    en,
                )
                merged[-1]["sensors"].add(sensor)
                merged[-1]["source_count"] += 1
            else:
                merged.append(
                    {
                        "start_time": st,
                        "end_time": en,
                        "sensors": {sensor},
                        "source_count": 1,
                    }
                )

        for m in merged:
            rows.append(
                {
                    "method": method,
                    BATCH_COL: str(batch),
                    "period": FOLLOW_PERIOD,
                    "설비": "솔트조",
                    "start_time": m["start_time"],
                    "end_time": m["end_time"],
                    "실제길이_sec": (
                        m["end_time"] - m["start_time"]
                    ).total_seconds(),
                    "선정범위길이_sec": (
                        m["end_time"] - m["start_time"]
                    ).total_seconds() + 1.0,
                    "포함센서": ", ".join(
                        s for s in SENSORS
                        if s in m["sensors"]
                    ),
                    "두Zone포함": len(m["sensors"]) == 2,
                    "원래센서구간수": m["source_count"],
                    "통합규칙": (
                        "같은 작업의 솔트조 1·2 Zone 선정 구간이 "
                        "겹치거나 앞 구간 끝~다음 구간 시작 차이가 2초 이내이면 합침"
                    ),
                }
            )

    return pd.DataFrame(rows)


def event_has_common_equipment_positive(
    row,
    method_union_qual,
    common_valid,
    lookup,
):
    batch = str(row[BATCH_COL])
    item = lookup.get(batch)
    if item is None:
        return False

    idx = item["idx"]
    times_ns = item["times_ns"]

    left = int(
        np.searchsorted(
            times_ns,
            pd.Timestamp(row["start_time"]).value,
            side="left",
        )
    )
    right = int(
        np.searchsorted(
            times_ns,
            pd.Timestamp(row["end_time"]).value,
            side="right",
        )
    )

    if left >= right:
        return False

    gidx = idx[left:right]

    return bool(
        (
            common_valid[gidx]
            & method_union_qual[gidx]
        ).any()
    )


def compare_equipment_events(
    df,
    equipment1,
    equipment2,
    name1,
    name2,
    union_qual1,
    union_qual2,
    common_valid,
    piece,
):
    """센서 통합 후 설비 단위에서 방법 구간을 비교합니다."""
    e1 = equipment1.reset_index(drop=True).copy()
    e2 = equipment2.reset_index(drop=True).copy()

    lookup = build_batch_lookup(df)

    eligible1 = np.array(
        [
            event_has_common_equipment_positive(
                row,
                union_qual1,
                common_valid,
                lookup,
            )
            for _, row in e1.iterrows()
        ],
        dtype=bool,
    )

    eligible2 = np.array(
        [
            event_has_common_equipment_positive(
                row,
                union_qual2,
                common_valid,
                lookup,
            )
            for _, row in e2.iterrows()
        ],
        dtype=bool,
    )

    hit1 = np.zeros(len(e1), dtype=bool)
    hit2 = np.zeros(len(e2), dtype=bool)

    common_rows = []

    for i, a in e1.iterrows():
        if not eligible1[i]:
            continue

        candidates = e2.loc[
            e2[BATCH_COL].astype(str).eq(str(a[BATCH_COL]))
        ]

        for j, b in candidates.iterrows():
            if not eligible2[j]:
                continue

            ov = interval_overlap(
                a["start_time"],
                a["end_time"],
                b["start_time"],
                b["end_time"],
            )

            if ov is None:
                continue

            ov_start, ov_end = ov

            item = lookup[str(a[BATCH_COL])]
            idx = item["idx"]
            times_ns = item["times_ns"]

            left = int(
                np.searchsorted(
                    times_ns,
                    ov_start.value,
                    side="left",
                )
            )
            right = int(
                np.searchsorted(
                    times_ns,
                    ov_end.value,
                    side="right",
                )
            )

            gidx = idx[left:right]

            both = (
                common_valid[gidx]
                & union_qual1[gidx]
                & union_qual2[gidx]
            )

            if not both.any():
                continue

            hit_idx = gidx[both]
            hit1[i] = True
            hit2[j] = True

            common_rows.append(
                {
                    "비교": f"{name1} vs {name2}",
                    BATCH_COL: str(a[BATCH_COL]),
                    f"{name1}_start": a["start_time"],
                    f"{name1}_end": a["end_time"],
                    f"{name1}_포함센서": a["포함센서"],
                    f"{name2}_start": b["start_time"],
                    f"{name2}_end": b["end_time"],
                    f"{name2}_포함센서": b["포함센서"],
                    "공통양성기록수": int(both.sum()),
                    "공통양성시간_sec": float(
                        piece[hit_idx].sum()
                    ),
                }
            )

    common = pd.DataFrame(common_rows)

    summary = pd.DataFrame(
        [
            {
                "비교": f"{name1} vs {name2}",
                f"{name1}_설비구간수": len(e1),
                f"{name2}_설비구간수": len(e2),
                f"공통_{name1}구간수": int(hit1.sum()),
                f"공통_{name2}구간수": int(hit2.sum()),
                "공통작업수": (
                    common[BATCH_COL].nunique()
                    if len(common)
                    else 0
                ),
                "공통작업목록": (
                    ", ".join(
                        sorted(
                            common[BATCH_COL]
                            .astype(str)
                            .unique()
                        )
                    )
                    if len(common)
                    else ""
                ),
                "설비통합정의": (
                    "방법별로 같은 작업의 솔트조 1·2 Zone 선정구간이 "
                    "겹치거나 2초 이내이면 먼저 하나의 설비 구간으로 합친 뒤 비교"
                ),
            }
        ]
    )

    return common, summary


# ════════════════════════════════════════════════════════════════════
# 10. 그래프
# ════════════════════════════════════════════════════════════════════

def plot_temperature_with_gaps(
    ax,
    data,
    sensor,
    label="실제 온도",
):
    """5초를 넘는 공백에서는 선을 연결하지 않습니다."""
    if data.empty:
        return

    w = data.sort_values(TIME_COL).copy()

    gap = (
        w[TIME_COL]
        .diff()
        .dt.total_seconds()
        .fillna(0)
    )

    block = (
        gap > PIECE_MAX_GAP_SEC
    ).cumsum()

    first = True

    for _, seg in w.groupby(block, sort=False):
        ax.plot(
            seg[TIME_COL],
            seg[sensor],
            color="black",
            linewidth=1.0,
            label=label if first else None,
        )
        first = False


def select_review_points(
    df,
    sensor,
    score,
    valid,
):
    may = df["period"].eq(TUNE_PERIOD).to_numpy()

    idx = np.flatnonzero(
        may
        & valid
        & np.isfinite(score)
    )

    if len(idx) == 0:
        return []

    order = idx[
        np.argsort(score[idx])[::-1]
    ]

    selected = []

    for i in order:
        t = df.at[i, TIME_COL]
        batch = str(df.at[i, BATCH_COL])

        too_close = False

        for j in selected:
            if str(df.at[j, BATCH_COL]) != batch:
                continue

            if abs(
                (
                    t - df.at[j, TIME_COL]
                ).total_seconds()
            ) < REVIEW_SEPARATION_MIN * 60:
                too_close = True
                break

        if not too_close:
            selected.append(int(i))

        if len(selected) >= TOP_REVIEW_POINTS:
            break

    return selected


def plot_may_review(
    df,
    sensor,
    score,
    idx,
    rank,
):
    batch = str(df.at[idx, BATCH_COL])
    t = df.at[idx, TIME_COL]

    start = t - pd.Timedelta(minutes=PLOT_BEFORE_MIN)
    end = t + pd.Timedelta(minutes=PLOT_AFTER_MIN)

    w = df.loc[
        df[BATCH_COL].astype(str).eq(batch)
        & df[TIME_COL].between(start, end),
        [TIME_COL, sensor],
    ].copy()

    fig, ax = plt.subplots(figsize=(13, 5))

    plot_temperature_with_gaps(
        ax,
        w,
        sensor,
    )

    ax.axvline(
        t,
        color="tab:red",
        linestyle="--",
        linewidth=1.2,
        label="IF 검토 시점",
    )

    ax.set_title(
        f"5월 Isolation Forest 검토 #{rank} | "
        f"{sensor} | 배정번호 {batch}\n"
        f"IF점수={score[idx]:.6f}"
    )

    ax.set_xlabel("시간")
    ax.set_ylabel("온도")
    ax.legend()

    fig.autofmt_xdate()
    fig.tight_layout()

    filename = (
        f"{sensor}_{rank:02d}_{batch}_"
        f"{t.strftime('%Y%m%d_%H%M%S')}.png"
    )

    fig.savefig(
        MAY_FIG_DIR / filename,
        dpi=150,
    )
    plt.close(fig)

    return filename


def plot_a1_if_comparison(
    df,
    a1_events,
    if_events,
):
    pairs = pd.concat(
        [
            a1_events[[BATCH_COL, "sensor"]],
            if_events[[BATCH_COL, "sensor"]],
        ],
        ignore_index=True,
    ).drop_duplicates()

    rows = []

    for num, (_, pair) in enumerate(
        pairs.iterrows(),
        start=1,
    ):
        batch = str(pair[BATCH_COL])
        sensor = pair["sensor"]

        a = a1_events.loc[
            a1_events[BATCH_COL].astype(str).eq(batch)
            & a1_events["sensor"].eq(sensor)
        ]

        b = if_events.loc[
            if_events[BATCH_COL].astype(str).eq(batch)
            & if_events["sensor"].eq(sensor)
        ]

        starts = pd.concat(
            [a["start_time"], b["start_time"]],
            ignore_index=True,
        )
        ends = pd.concat(
            [a["end_time"], b["end_time"]],
            ignore_index=True,
        )

        if starts.empty or ends.empty:
            continue

        start = starts.min() - pd.Timedelta(minutes=10)
        end = ends.max() + pd.Timedelta(minutes=10)

        w = df.loc[
            df[BATCH_COL].astype(str).eq(batch)
            & df[TIME_COL].between(start, end),
            [TIME_COL, sensor],
        ].copy()

        if w.empty:
            continue

        fig, ax = plt.subplots(figsize=(13, 5))

        plot_temperature_with_gaps(
            ax,
            w,
            sensor,
        )

        first = True
        for _, r in a.iterrows():
            ax.axvspan(
                r["start_time"],
                r["end_time"],
                color="tab:orange",
                alpha=0.22,
                label="A1 우선조사" if first else None,
            )
            first = False

        first = True
        for _, r in b.iterrows():
            ax.axvspan(
                r["start_time"],
                r["end_time"],
                color="tab:red",
                alpha=0.20,
                hatch="//",
                label="IF 우선조사" if first else None,
            )
            first = False

        ax.set_title(
            f"A1 vs Isolation Forest | {sensor} | 배정번호 {batch}"
        )
        ax.set_xlabel("시간")
        ax.set_ylabel("온도")
        ax.legend()

        fig.autofmt_xdate()
        fig.tight_layout()

        filename = f"{num:02d}_{sensor}_{batch}.png"

        fig.savefig(
            COMPARE_FIG_DIR / filename,
            dpi=150,
        )
        plt.close(fig)

        rows.append(
            {
                "번호": num,
                BATCH_COL: batch,
                "sensor": sensor,
                "A1구간수": len(a),
                "IF구간수": len(b),
                "그래프파일": filename,
            }
        )

    return pd.DataFrame(rows)


# ════════════════════════════════════════════════════════════════════
# 11. 99.9% 선택 근거
# ════════════════════════════════════════════════════════════════════

def build_threshold_reason(sensitivity):
    def get(sensor, q, column):
        hit = sensitivity.loc[
            sensitivity["sensor"].eq(sensor)
            & sensitivity["기준기간_분위수"].eq(q),
            column,
        ]
        return int(hit.iloc[0]) if len(hit) else 0

    z1 = "솔트조 온도 1 Zone"
    z2 = "솔트조 온도 2 Zone"

    return (
        "5월 민감도 검토 결과, "
        f"Zone 2의 60초 이상 조사후보는 "
        f"99%={get(z2, 0.99, '5월_60초이상구간수')}개, "
        f"99.5%={get(z2, 0.995, '5월_60초이상구간수')}개, "
        f"99.9%={get(z2, 0.999, '5월_60초이상구간수')}개였다. "
        f"Zone 1의 99.9%는 "
        f"{get(z1, 0.999, '5월_60초이상구간수')}개였다. "
        "99%·99.5%보다 우선조사 목록을 좁히면서도 "
        "후보를 억지로 늘리기 위해 센서별 기준을 따로 낮추지 않기 위해 "
        "센서별 1~4월 IF 점수 99.9% 분위수를 최종 조건으로 고정했다."
    )


# ════════════════════════════════════════════════════════════════════
# 12. 전체 실행
# ════════════════════════════════════════════════════════════════════

def main():
    started = time.time()
    set_korean_font()
    self_test()

    ref1_dir, ref2_dir = resolve_fixed_stage3_dirs()

    OUT.mkdir(parents=True, exist_ok=False)
    MAY_FIG_DIR.mkdir()
    COMPARE_FIG_DIR.mkdir()

    print("=" * 80)
    print(
        "4단계 머신러닝 전체실행 "
        "— 3단계 ① 기록라벨 + ② 이벤트 고정 / G02·G03·G06 반영"
    )
    print("=" * 80)

    print("\n[고정한 3단계 결과]")
    print("  ① 팀코드 재현본:", ref1_dir)
    print("  ② 설명용 정리본:", ref2_dir)

    stage3_events, stage3_group_events = load_stage3_outputs(ref2_dir)

    print("\n1) 원본 읽기 + 2단계 첫 기록 월 기준 적용")
    df = add_segments(
        load_raw(
            SENSORS,
            sensor_dtype="float32",
        )
    )
    df[BATCH_COL] = normalize_batch(df[BATCH_COL])

    (
        df,
        jobs,
        month_counts,
        expected_month_counts_match,
    ) = attach_first_record_period(df)

    period_check = verify_first_record_period_vs_stage3(df)

    save(month_counts, "00_첫기록월별_작업수.csv")
    save(period_check, "00A_2단계첫기록월_vs_3단계기간_확인.csv")

    print(
        f"   원본 {len(df):,}행 / 작업 {df[BATCH_COL].nunique()}개"
    )
    print("   기간 기준: 작업 첫 기록 월 (2단계_평소모습_종합과 동일)")
    print("   3단계 세 기간 작업 집합과 일치: True")
    print("   월별 작업 수 기대값 일치:", expected_month_counts_match)

    print("\n2) 3단계 ① 검증용_기록라벨/*.npz 읽기")
    labels, npz_time_check = load_stage3_npz_labels(df, ref1_dir)
    save(npz_time_check, "15_3단계①_NPZ_원본시각대조.csv")

    a1_valid = {s: labels["A1"][s]["valid"] for s in SENSORS}
    a2_valid = {s: labels["A2"][s]["valid"] for s in SENSORS}
    a1_qual = {s: labels["A1"][s]["qual"] for s in SENSORS}
    a2_qual = {s: labels["A2"][s]["qual"] for s in SENSORS}

    npz_events = pd.concat(
        [
            events_from_npz_qual(df, "A1", a1_qual),
            events_from_npz_qual(df, "A2", a2_qual),
        ],
        ignore_index=True,
    )
    event_check, event_mismatch = verify_npz_events_against_stage3(
        stage3_events,
        npz_events,
    )
    save(event_check, "16_3단계①NPZ_vs_②이벤트_대조.csv")
    save(event_mismatch, "16A_3단계①NPZ_vs_②이벤트_불일치.csv")
    print(event_check.to_string(index=False))
    if not event_check["시작종료길이후보기록수_완전일치"].all():
        raise ValueError(
            "3단계 ① NPZ 기록 판정으로 복원한 이벤트와 ② 이벤트 CSV가 다릅니다. "
            "16A_3단계①NPZ_vs_②이벤트_불일치.csv를 확인하세요."
        )

    train_mask = df["period"].eq(TRAIN_PERIOD).to_numpy()
    may_mask = df["period"].eq(TUNE_PERIOD).to_numpy()
    follow_mask = df["period"].eq(FOLLOW_PERIOD).to_numpy()
    piece = make_piece_array(df)

    # 새 3단계 공통범위 코드와 같은 정의를 먼저 재확인해 둠
    stage3_common_check = build_stage3_a1a2_common_check(
        df, piece, a1_valid, a2_valid, a1_qual, a2_qual
    )
    save(stage3_common_check, "12A_3단계_A1A2_공통범위_재확인.csv")

    rng = np.random.default_rng(RANDOM_STATE)
    model_rows = []
    threshold_rows = []
    sensitivity_rows = []
    review_rows = []
    final_summary_rows = []
    final_if_event_parts = []
    if_valid = {}
    if_qual = {}

    print("\n3) Isolation Forest 학습 / 5월 조건점검 / 6~7월 고정적용")

    for sensor in SENSORS:
        print(f"\n   센서: {sensor}")
        feat, valid_if = build_features(df, sensor)
        if_valid[sensor] = valid_if

        train_idx = np.flatnonzero(valid_if & train_mask)
        may_idx = np.flatnonzero(valid_if & may_mask)
        follow_idx = np.flatnonzero(valid_if & follow_mask)

        if len(train_idx) == 0:
            raise ValueError(f"{sensor}: 1~4월 IF 학습 가능 기록이 없습니다.")

        if len(train_idx) > MAX_TRAIN_ROWS:
            fit_idx = np.sort(
                rng.choice(train_idx, size=MAX_TRAIN_ROWS, replace=False)
            )
        else:
            fit_idx = train_idx

        model = fit_iforest(
            feat.loc[fit_idx, FEATURE_NAMES].to_numpy(dtype="float64")
        )
        score = np.full(len(df), np.nan, dtype="float64")
        for idx in [train_idx, may_idx, follow_idx]:
            if len(idx):
                score[idx] = anomaly_score(
                    model,
                    feat.loc[idx, FEATURE_NAMES].to_numpy(dtype="float64"),
                )

        thresholds = {
            q: float(np.quantile(score[train_idx], q))
            for q in THRESHOLD_QUANTILES
        }

        model_rows.append(
            {
                "sensor": sensor,
                "학습기간": TRAIN_PERIOD,
                "기간배정": "작업 첫 기록 월",
                "입력특성": " / ".join(FEATURE_NAMES),
                "1~4월_유효행": len(train_idx),
                "실제_fit행": len(fit_idx),
                "n_estimators": N_ESTIMATORS,
                "random_state": RANDOM_STATE,
            }
        )

        for q, threshold in thresholds.items():
            threshold_rows.append(
                {"sensor": sensor, "분위수": q, "IF점수기준": threshold}
            )
            candidate = valid_if & may_mask & (score >= threshold)
            may_events, may_qual = event_table_from_candidate(
                df, sensor, "IsolationForest", score, candidate, threshold=threshold
            )
            priority = may_events.loc[may_events["구간구분"].eq("우선조사")]
            may_valid_n = int((valid_if & may_mask).sum())
            may_piece_ok = may_mask & valid_if & (piece > 0)
            may_exposure = may_mask & may_qual & valid_if & (piece > 0)
            sensitivity_rows.append(
                {
                    "sensor": sensor,
                    "기준기간_분위수": q,
                    "IF점수_임계값": threshold,
                    "5월_계산가능기록수": may_valid_n,
                    "5월_후보기록수": int(candidate.sum()),
                    "5월_후보기록비율_pct": (
                        candidate.sum() / may_valid_n * 100 if may_valid_n else np.nan
                    ),
                    "5월_모든후보구간수": len(may_events),
                    "5월_60초이상구간수": len(priority),
                    "5월_60초이상관련작업수": (
                        priority[BATCH_COL].nunique() if len(priority) else 0
                    ),
                    "5월_평가가능시간_sec": float(piece[may_piece_ok].sum()),
                    "5월_우선조사노출시간_sec": float(piece[may_exposure].sum()),
                }
            )

        points = select_review_points(df, sensor, score, valid_if)
        for rank, idx in enumerate(points, start=1):
            filename = plot_may_review(df, sensor, score, idx, rank)
            review_rows.append(
                {
                    "sensor": sensor,
                    "순위": rank,
                    BATCH_COL: str(df.at[idx, BATCH_COL]),
                    "TAG_MIN": df.at[idx, TIME_COL],
                    "실제온도": float(df.at[idx, sensor]),
                    "IF점수": float(score[idx]),
                    "그래프파일": filename,
                    "자동검토안내": (
                        "급격한 변화인지, 완만한 온도 수준 이동/운전 전환인지 확인. "
                        "IF는 현재 온도 자체도 특성으로 사용함."
                    ),
                    "사람검토_메모": "",
                }
            )

        final_threshold = thresholds[FINAL_IF_QUANTILE]
        follow_candidate = valid_if & follow_mask & (score >= final_threshold)
        follow_events, follow_qual = event_table_from_candidate(
            df,
            sensor,
            "IsolationForest",
            score,
            follow_candidate,
            threshold=final_threshold,
        )
        follow_priority = (
            follow_events.loc[follow_events["구간구분"].eq("우선조사")]
            .copy()
            .reset_index(drop=True)
        )
        if_qual[sensor] = follow_qual
        final_if_event_parts.append(follow_priority)

        final_summary_rows.append(
            {
                "sensor": sensor,
                "고정분위수": FINAL_IF_QUANTILE,
                "IF점수기준": final_threshold,
                "6~7월_후보기록수": int(follow_candidate.sum()),
                "6~7월_60초이상구간수": len(follow_priority),
                "6~7월_60초이상관련작업수": (
                    follow_priority[BATCH_COL].nunique() if len(follow_priority) else 0
                ),
                "6~7월_IF판정가능시간_sec": float(
                    piece[follow_mask & valid_if & (piece > 0)].sum()
                ),
                "6~7월_IF우선조사노출시간_sec": float(
                    piece[follow_mask & valid_if & follow_qual & (piece > 0)].sum()
                ),
            }
        )

    if_events = pd.concat(final_if_event_parts, ignore_index=True)

    # ②의 센서 이벤트를 최종 구간표로 사용
    stage3_salt = stage3_events.loc[
        stage3_events["sensor"].isin(SENSORS)
        & stage3_events["period"].eq(FOLLOW_PERIOD)
    ].copy()
    a1_events = stage3_salt.loc[stage3_salt["method"].eq("A1")].copy().reset_index(drop=True)
    a2_events = stage3_salt.loc[stage3_salt["method"].eq("A2")].copy().reset_index(drop=True)

    print("\n4) A1·A2·IF 세 방법 공통 판정가능 범위 비교")
    common_valid = (
        follow_mask
        & np.logical_and.reduce([a1_valid[s] for s in SENSORS])
        & np.logical_and.reduce([a2_valid[s] for s in SENSORS])
        & np.logical_and.reduce([if_valid[s] for s in SENSORS])
    )

    record_summary = build_three_method_record_summary(
        df, common_valid, piece, a1_qual, a2_qual, if_qual
    )
    save(record_summary, "12_A1_A2_IF_공통판정기록_비교요약.csv")

    (
        a1_if_common, a1_only, if_only_a1,
        a1_if_excluded, a1_if_summary,
    ) = compare_sensor_events(
        df, a1_events, if_events, "A1", "IF",
        a1_qual, if_qual, common_valid, piece,
    )
    save(a1_if_common, "08_A1_IF_공통구간.csv")
    save(a1_only, "09_A1만_우선조사구간.csv")
    if len(if_only_a1):
        if_only_a1["해석확인사항"] = (
            "IF는 현재 온도 자체를 특성으로 사용하므로 급변뿐 아니라 "
            "작업별 온도 수준 차이/운전 전환 가능성도 원본에서 확인"
        )
    save(if_only_a1, "10_IF만_우선조사구간.csv")
    save(a1_if_summary, "11_A1_IF_비교요약.csv")
    save(a1_if_excluded, "13_A1_IF_공통판정범위밖_제외구간.csv")

    (
        a2_if_common, a2_only, if_only_a2,
        a2_if_excluded, a2_if_summary,
    ) = compare_sensor_events(
        df, a2_events, if_events, "A2", "IF",
        a2_qual, if_qual, common_valid, piece,
    )
    save(a2_if_common, "17_A2_IF_공통구간.csv")
    save(a2_only, "18_A2만_우선조사구간.csv")
    save(if_only_a2, "19_IF만_A2비교_우선조사구간.csv")
    save(a2_if_summary, "20_A2_IF_비교요약.csv")
    save(a2_if_excluded, "20A_A2_IF_공통판정범위밖_제외구간.csv")

    print("\n5) G02 — 설비 단위 비교")
    # A1/A2는 3단계 ②가 이미 만든 설비 그룹 구간을 그대로 사용
    stage3_salt_group = stage3_group_events.loc[
        stage3_group_events["설비"].eq("솔트조")
        & stage3_group_events["period"].eq(FOLLOW_PERIOD)
    ].copy()
    equipment_a1 = stage3_salt_group.loc[
        stage3_salt_group["method"].eq("A1")
    ].copy().reset_index(drop=True)
    equipment_a2 = stage3_salt_group.loc[
        stage3_salt_group["method"].eq("A2")
    ].copy().reset_index(drop=True)
    equipment_if = merge_equipment_events(if_events, "IF")

    equipment_all = pd.concat(
        [equipment_a1, equipment_a2, equipment_if],
        ignore_index=True,
        sort=False,
    )
    save(equipment_all, "21_설비단위_방법별구간.csv")

    union_qual = {
        "A1": np.logical_or.reduce([a1_qual[s] for s in SENSORS]),
        "A2": np.logical_or.reduce([a2_qual[s] for s in SENSORS]),
        "IF": np.logical_or.reduce([if_qual[s] for s in SENSORS]),
    }
    equipment_common_parts = []
    equipment_summary_parts = []
    for name1, eq1, name2, eq2 in [
        ("A1", equipment_a1, "IF", equipment_if),
        ("A2", equipment_a2, "IF", equipment_if),
        ("A1", equipment_a1, "A2", equipment_a2),
    ]:
        common, summary = compare_equipment_events(
            df, eq1, eq2, name1, name2,
            union_qual[name1], union_qual[name2], common_valid, piece,
        )
        equipment_common_parts.append(common)
        equipment_summary_parts.append(summary)
    equipment_common = pd.concat(equipment_common_parts, ignore_index=True, sort=False)
    equipment_summary = pd.concat(equipment_summary_parts, ignore_index=True, sort=False)
    save(equipment_summary, "22_설비단위_방법비교요약.csv")
    save(equipment_common, "23_설비단위_공통구간.csv")
    print(equipment_summary.to_string(index=False))

    # IF 결과 저장
    models = pd.DataFrame(model_rows)
    thresholds = pd.DataFrame(threshold_rows)
    sensitivity = pd.DataFrame(sensitivity_rows)
    review = pd.DataFrame(review_rows)
    final_summary = pd.DataFrame(final_summary_rows)
    decision_reason = build_threshold_reason(sensitivity)
    fixed_if = thresholds.loc[
        thresholds["분위수"].eq(FINAL_IF_QUANTILE)
    ].copy()
    fixed_if["선정근거"] = decision_reason
    final_summary["선정근거"] = decision_reason

    save(models, "01_IF_모델설정.csv")
    save(thresholds, "02_1_4월_IF점수_분위수.csv")
    save(sensitivity, "03_5월_IF_조건후보_민감도.csv")
    save(review, "04_5월_IF_원본검토_대표지점.csv")
    save(fixed_if, "05_IF_최종고정기준.csv")
    save(final_summary, "06_IF_최종적용요약.csv")
    save(if_events, "07_6_7월_IF_우선조사구간.csv")

    graph_index = plot_a1_if_comparison(df, a1_events, if_events)
    save(graph_index, "14_A1_IF_비교그래프목록.csv")

    summary_path = OUT / "4단계_머신러닝_요약.txt"
    with summary_path.open("w", encoding="utf-8-sig") as f:
        f.write("4단계 머신러닝 전체실행 — 3단계 기록라벨 인계 반영\n")
        f.write("=" * 76 + "\n\n")
        f.write("[기간 기준]\n")
        f.write("2단계 종합본과 같이 작업 첫 기록 월로 작업 전체를 배정하고 월 경계에서 쪼개지 않음.\n")
        f.write(month_counts.to_string(index=False))
        f.write(f"\n문제정의서 월별 작업 수와 일치: {expected_month_counts_match}\n")
        f.write("3단계 세 기간 작업 집합과도 일치: True\n\n")

        f.write("[고정한 3단계 결과]\n")
        f.write(f"① 재현본(NPZ 기록판정): {ref1_dir}\n")
        f.write(f"② 정리본(이벤트/설비구간): {ref2_dir}\n")
        f.write(f"② 03 이벤트 SHA256: {file_sha256(ref2_dir / '03_A1_A2_이상이벤트.csv')}\n")
        f.write(f"② 설비그룹 SHA256: {file_sha256(ref2_dir / '추가_설비그룹_이벤트.csv')}\n\n")

        f.write("[기록 단위 검증]\n")
        f.write(f"① NPZ 작업 수: {len(npz_time_check)} / 원본 시각 전부 일치: {npz_time_check['시각_완전일치'].all()}\n")
        f.write(event_check.to_string(index=False))
        f.write("\n① NPZ qual로 복원한 이벤트가 ② 이벤트 CSV와 시작·종료·길이·후보기록수까지 일치해야 비교를 진행함.\n\n")

        f.write("[3단계 A1·A2 공통 범위 재확인]\n")
        f.write("3단계_공통범위_비교.py와 같은 정의를 NPZ에 적용함. 판정은 바꾸지 않고 집계만 함.\n")
        f.write(stage3_common_check.to_string(index=False))
        f.write("\n\n")

        f.write("[IF 최종 기준]\n")
        f.write(decision_reason + "\n")
        f.write(fixed_if.to_string(index=False))
        f.write("\n\n")

        f.write("[A1·A2·IF 세 방법 공통 판정가능 기록]\n")
        f.write(
            "A1·A2·IF와 솔트조 1·2 Zone이 모두 판정 가능한 6~7월 원본 기록만 비교함.\n"
        )
        f.write(record_summary.to_string(index=False))
        f.write("\n\n")

        f.write("[설비 단위 비교]\n")
        f.write(
            "A1·A2는 3단계 ②의 추가_설비그룹_이벤트.csv를 그대로 사용하고, "
            "IF는 같은 규칙(겹침 또는 2초 이내)으로 솔트조 1·2 Zone을 합침.\n"
        )
        f.write(equipment_summary.to_string(index=False))
        f.write("\n\n")

        f.write("[센서 단위 A1/IF 비교]\n")
        f.write(a1_if_summary.to_string(index=False))
        f.write("\n\n[센서 단위 A2/IF 비교]\n")
        f.write(a2_if_summary.to_string(index=False))
        f.write("\n\n[해석 주의]\n")
        f.write("- 조사 후보이지 실제 고장/불량 확정이 아님.\n")
        f.write("- A1만/A2만/IF만을 바로 오탐이라고 부르지 않음.\n")
        f.write("- IF는 현재 온도 자체도 특성으로 사용하므로 IF만 구간은 온도 수준 차이/운전 전환 가능성도 확인.\n")
        f.write("- 그래프는 5초를 넘는 기록 공백에서 온도선을 연결하지 않음.\n")

    run_info = [
        f"실행 시각: {OUT.name}",
        f"걸린 시간: {time.time() - started:.1f}초",
        f"Python: {platform.python_version()}",
        f"pandas: {pd.__version__}",
        f"numpy: {np.__version__}",
        f"sklearn: {sklearn.__version__}",
        f"프로젝트 루트: {PROJECT}",
        f"원본 행 수: {len(df):,}",
        f"작업 수: {df[BATCH_COL].nunique()}",
        "기간배정: 작업 첫 기록 월",
        f"고정 3단계 ① 재현본: {ref1_dir}",
        f"고정 3단계 ② 정리본: {ref2_dir}",
        "A1/A2 기록판정 원본: ① 검증용_기록라벨/*.npz",
        f"4단계 코드 SHA256: {file_sha256(Path(__file__))}",
    ]
    (OUT / "실행정보.txt").write_text(
        "\n".join(run_info) + "\n", encoding="utf-8-sig"
    )

    completion = (
        "4단계 머신러닝 전체실행 정상 완료\n"
        f"결과폴더: {OUT}\n"
        f"3단계 ① 재현본: {ref1_dir}\n"
        f"3단계 ② 정리본: {ref2_dir}\n"
        "기록단위 NPZ 시각 대조: 완료\n"
        "NPZ vs ② 이벤트 시각·길이 대조: 완료\n"
        "G02 설비단위 비교: 완료\n"
        "G03 A2 포함 세방법 공통범위 비교: 완료\n"
    )
    (OUT / "완료.txt").write_text(completion, encoding="utf-8-sig")
    (OUT / "실행완료.txt").write_text(completion, encoding="utf-8-sig")

    print("\n[완료]")
    print("결과 폴더:", OUT)
    print("핵심 추가 결과:")
    print("  12_A1_A2_IF_공통판정기록_비교요약.csv")
    print("  12A_3단계_A1A2_공통범위_재확인.csv")
    print("  15_3단계①_NPZ_원본시각대조.csv")
    print("  16_3단계①NPZ_vs_②이벤트_대조.csv")
    print("  17_A2_IF_공통구간.csv")
    print("  20_A2_IF_비교요약.csv")
    print("  21_설비단위_방법별구간.csv")
    print("  22_설비단위_방법비교요약.csv")
    print("  23_설비단위_공통구간.csv")
    print("  완료.txt")


if __name__ == "__main__":
    try:
        main()
    except (
        ValueError,
        FileNotFoundError,
        ImportError,
        KeyError,
        AssertionError,
        OSError,
    ) as error:
        print(f"[중단] {error}", file=sys.stderr)
        sys.exit(1)
