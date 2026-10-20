"""1단계 전처리 — 전체 한 번에 실행 (통합본). 프로젝트 맨 위 폴더에서 실행하세요.

실행: .venv\\Scripts\\python.exe "stages/1단계_전처리/1단계_전처리_전체실행.py"
입력: data/raw/data.csv(cp949), data/raw/열처리_품질데이터.xlsx
출력: reports/1단계_전처리_전체실행/실행시각/ 아래 5개 폴더
      1_원본확인 / 2_시간점검 / 3_결측공백검토 / 4_5분개요 / 5_데이터계약

이 파일은 아래 6개 코드를 순서대로 한 파일에 모은 것입니다. 검사 내용·기대값·그림은 원래 코드와 같습니다.
  1 = scripts/01_check_raw_data.py        원본 모양·결측·중복 확인
  2 = scripts/02_check_time_series.py     시간 간격·긴 공백·연속 결측 확인
  3 = scripts/03_review_missing_context.py 결측·공백 앞뒤 5분 그림
  4 = scripts/04_resample_overview.py     5분 평균 개요 그림(소개용)
  5 = stages/1단계_전처리/1단계_전처리_데이터계약점검.py + src/data_contract.py  공통 읽기 규칙 점검
원래 코드는 지우지 않았습니다. 다음 단계 코드는 계속 src/data_contract.py를 불러 씁니다.
바뀐 점: 결과 폴더 위치, 옛 계획의 "보간 후보" 안내 문구(보간 안 함 = 회의 결정 6으로 수정)뿐입니다.

원본 수정·보간·행 삭제·이상 판정 없음. 5번 기대값이 하나라도 다르면 실패(종료 코드 1)로 끝납니다.
근거: docs/plans/ANALYSIS-PLAN.md §4-1, §11-3, §11-4, §12.
"""
from pathlib import Path
from datetime import datetime
from io import StringIO
import inspect
import sys
import tempfile
import time

# 이 파일은 stages/1단계_전처리/ 안에 있으므로 두 단계 위가 프로젝트 맨 위 폴더입니다.
PROJECT = Path(__file__).resolve().parents[2]


def check_python_env():
    """Python·패키지 버전이 권장 환경(requirements.txt)과 다르면 [주의]를 보여 줍니다. 멈추지 않습니다.

    다른 버전은 결과가 조금 달라질 수 있고, 품질 파일(xlsx)을 읽는 openpyxl이 없으면 5번 검사 중간에
    멈추므로(2026-10-02 실제 발생) 아래 import보다 앞에서 먼저 알려 줍니다. 확인 내용은 src/env_check.py.
    """
    sys.path.insert(0, str(PROJECT))
    from src.env_check import check_python_env as check
    check(PROJECT)


def safe_console():
    """화면 출력이 cp949(한글 Windows 기본) 방식이어도 '−' 같은 특수문자 때문에 멈추지 않게 합니다.

    표현할 수 없는 글자만 '?'로 바꿔 보여 줍니다. 보고서 파일(TXT·CSV)은 따로 UTF-8로 저장하므로 영향이 없습니다.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')


if __name__ == '__main__':  # 직접 실행할 때만 확인(다른 코드가 불러 쓸 때는 건너뜀)
    safe_console()
    check_python_env()

import numpy as np  # noqa: E402  (환경 확인 뒤에 불러옴)
import pandas as pd  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use('Agg')  # 창을 띄우지 않고 그림 파일로만 저장
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
from matplotlib import font_manager  # noqa: E402


# ════════════════════════════════════════════════════════════════════
# 0. 공통 설정 — 모든 단계가 함께 쓰는 위치·이름·도우미 함수 (PROJECT는 맨 위에서 정함)
# ════════════════════════════════════════════════════════════════════
RAW_DIR = PROJECT / 'data' / 'raw'
RAW_CSV = RAW_DIR / 'data.csv'
QUALITY_XLSX = RAW_DIR / '열처리_품질데이터.xlsx'
RAW_ENCODING = 'cp949'  # 원본 CSV의 한글 인코딩

TIME_COL = 'TAG_MIN'
BATCH_COL = '배정번호'
TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
LONG_GAP_SEC = 60  # 같은 작업 안에서 이 간격을 넘으면 새 세그먼트(회의 결정·2번 결과와 같은 기준)

# 품질 `작업일`의 월 → 기간(B1). 6~7월은 탐색적·회고적 비교 구간이다(§4-6-0).
PERIOD_BY_MONTH = {1: '학습(1~4월)', 2: '학습(1~4월)', 3: '학습(1~4월)', 4: '학습(1~4월)',
                   5: '조정(5월)', 6: '후속적용(6~7월)', 7: '후속적용(6~7월)'}


def make_reporter(folder, report_name):
    """화면 출력과 보고서(TXT) 저장을 같은 내용으로 하는 show, 표를 CSV로 저장하는 save를 만듭니다."""
    report = folder / report_name

    def show(text=''):
        print(text, flush=True)
        with report.open('a', encoding='utf-8-sig') as f:
            f.write(str(text) + '\n')

    def save(table, name, index=False):
        # Excel에서도 한글이 깨지지 않도록 UTF-8 BOM으로 저장합니다.
        table.to_csv(folder / name, index=index, encoding='utf-8-sig')

    return show, save


def find_korean_font():
    """그림에 쓸 한글 글꼴을 찾습니다. 없으면 None(센서 번호로 대신 표기)."""
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    font = next((f for f in ['Malgun Gothic', 'AppleGothic', 'NanumGothic', 'Noto Sans CJK KR'] if f in fonts), None)
    if font:
        plt.rcParams['font.family'] = font
    plt.rcParams['axes.unicode_minus'] = False
    return font


def read_raw_all():
    """원본 전체를 읽습니다(1·2·3·4번 공통). 배정번호는 앞자리 0을 지키려고 글자로 읽습니다.

    low_memory=False: 일부만 보고 자료형을 추측하는 문제를 줄입니다.
    skip_blank_lines=False: 빈 줄도 행으로 읽어 행 수를 정확히 셉니다.
    """
    return pd.read_csv(RAW_CSV, encoding=RAW_ENCODING, dtype={BATCH_COL: 'string'},
                       low_memory=False, skip_blank_lines=False)


# ════════════════════════════════════════════════════════════════════
# 공통 데이터 계약 — src/data_contract.py와 같은 내용(복사본)
# 다음 단계 코드는 src/data_contract.py를 씁니다. 한쪽을 고치면 다른 쪽도 고치세요.
# 5번 단계가 함수 글자·기본값과 위 설정값(TIME_COL~PERIOD_BY_MONTH, 파일 위치·인코딩)이 같은지 자동으로 확인합니다.
# ════════════════════════════════════════════════════════════════════
def load_raw(columns, sensor_dtype, path=RAW_CSV):
    """원본에서 TAG_MIN·배정번호와 요청한 센서 열만 읽습니다.

    sensor_dtype은 기본값이 없습니다. 팀 동결 라벨 재현은 'float32',
    기술 통계는 'float64'처럼 호출하는 쪽이 반드시 정합니다(§2-2-1 7단계).
    path는 회귀 검사용 작은 CSV를 넣을 때만 바꿉니다.
    """
    if sensor_dtype not in ('float32', 'float64'):
        raise ValueError("sensor_dtype은 'float32' 또는 'float64'로 지정하세요.")
    columns = list(columns)
    if TIME_COL in columns or BATCH_COL in columns or len(set(columns)) != len(columns):
        raise ValueError('columns에는 중복 없는 센서 열만 넣으세요.')
    dtype = {BATCH_COL: 'string', **{c: sensor_dtype for c in columns}}
    df = pd.read_csv(path, encoding=RAW_ENCODING, usecols=[TIME_COL, BATCH_COL] + columns,
                     dtype=dtype, low_memory=False, skip_blank_lines=False)
    # usecols는 파일의 열 순서를 따르므로 요청 순서로 다시 맞춥니다.
    df = df[[TIME_COL, BATCH_COL] + columns]
    # 원본 데이터의 1번째 기록 = 1(헤더 제외). 02 코드와 같은 번호입니다.
    df.insert(0, '_source_row', np.arange(1, len(df) + 1))
    bad_id = df[BATCH_COL].isna() | df[BATCH_COL].str.strip().eq('').fillna(False)
    if bad_id.any():
        raise ValueError(f'배정번호 결측·공백 {int(bad_id.sum())}행. 원본을 확인하세요.')
    # 형식이 다른 시각이 하나라도 있으면 중단합니다(채우거나 버리지 않음).
    df[TIME_COL] = pd.to_datetime(df[TIME_COL], format=TIME_FORMAT, errors='raise')
    # 빈 칸·'NaT' 같은 결측 시각은 errors='raise'로도 예외 없이 NaT가 되므로 따로 막습니다.
    bad_time = df[TIME_COL].isna()
    if bad_time.any():
        rows = df.loc[bad_time, '_source_row'].head(10).tolist()
        raise ValueError(f'TAG_MIN 결측 {int(bad_time.sum())}행(원본 기록번호 앞 10개: {rows}). 원본을 확인하세요.')
    return df


def add_segments(df, long_gap_sec=LONG_GAP_SEC):
    """작업별 시간순 정렬, 간격 두 종류, 관측 세그먼트를 붙입니다. 행은 늘거나 줄지 않습니다.

    dt_prev = 현재 − 이전 기록(초). 배정번호의 첫 기록은 결측.
    dt_next = 다음 − 현재 기록(초). 같은 세그먼트 안에서만 계산하며 세그먼트 마지막 기록은 결측.
    dt_prev > long_gap_sec 인 기록에서 새 세그먼트가 시작합니다(§4-1).
    """
    n = len(df)
    out = df.sort_values([BATCH_COL, TIME_COL, '_source_row'], kind='mergesort').reset_index(drop=True)
    by_batch = out.groupby(BATCH_COL, sort=False)[TIME_COL]
    out['dt_prev'] = by_batch.diff().dt.total_seconds()
    new_segment = out['dt_prev'].isna() | out['dt_prev'].gt(long_gap_sec)
    seg_no = new_segment.astype(int).groupby(out[BATCH_COL], sort=False).cumsum()
    out['segment_id'] = out[BATCH_COL] + '_' + seg_no.astype(str).str.zfill(2)
    out['dt_next'] = -out.groupby('segment_id', sort=False)[TIME_COL].diff(-1).dt.total_seconds()
    if len(out) != n:
        raise AssertionError('세그먼트 처리 전후 행 수가 다릅니다.')
    return out


def load_quality():
    """품질 XLSX를 읽고 배정번호를 원본과 같은 문자열로 맞춘 뒤 작업일 월·기간을 붙입니다."""
    q = pd.read_excel(QUALITY_XLSX)
    ids = q[BATCH_COL]
    if pd.api.types.is_integer_dtype(ids):
        q[BATCH_COL] = ids.astype('int64').astype(str)
    elif pd.api.types.is_float_dtype(ids) and ids.notna().all() and (ids % 1 == 0).all():
        q[BATCH_COL] = ids.astype('int64').astype(str)
    else:
        q[BATCH_COL] = ids.astype('string').str.strip()
    if q[BATCH_COL].isna().any() or q[BATCH_COL].duplicated().any():
        raise ValueError('품질 파일 배정번호에 결측 또는 중복이 있습니다.')
    q['작업일'] = pd.to_datetime(q['작업일'], errors='raise')
    q['작업일_월'] = q['작업일'].dt.month
    unknown = sorted(set(q['작업일_월']) - set(PERIOD_BY_MONTH))
    if unknown:
        raise ValueError(f'기간을 정하지 않은 작업일 월이 있습니다: {unknown}')
    q['기간'] = q['작업일_월'].map(PERIOD_BY_MONTH)
    return q


# ════════════════════════════════════════════════════════════════════
# 1. 원본 확인 (원래 scripts/01_check_raw_data.py)
#    행·열 수, 앞뒤 5행, 자료형, 결측, 완전 중복, 기초 통계를 봅니다.
# ════════════════════════════════════════════════════════════════════
def step1_raw_check(out):
    out.mkdir(parents=True)
    show, _ = make_reporter(out, 'raw_check_report.txt')
    report_path = out / 'raw_check_report.txt'

    show("원본 데이터 확인 보고서")
    show(f"실행 시각: {datetime.now().isoformat(timespec='seconds')}")
    show(f"Python: {sys.version.split()[0]} / pandas: {pd.__version__}")
    show(f"분석 파일: {RAW_CSV}")
    show("이번 단계는 확인만 수행합니다. 결측치 채우기·삭제·정렬은 하지 않습니다.")

    # 폴더에 있는 파일 목록: 여러 파일을 임의로 합치지 않습니다.
    show("\n[1] data/raw 파일 목록")
    for path in sorted(RAW_DIR.iterdir()):
        if path.is_file():
            show(f"{path.name}: {path.stat().st_size / 1_000_000:,.2f} MB")
    description_path = RAW_DIR / "데이터설명.txt"
    if description_path.is_file():
        show("\n[제공된 데이터 설명]")
        show(description_path.read_text(encoding="utf-8-sig"))

    show("\n[2] data.csv 전체 읽기 시작 (PC에 따라 시간이 걸릴 수 있습니다)")
    df = read_raw_all()
    show("불러오기 완료")
    show(f"전체 행 수: {df.shape[0]:,}")
    show(f"전체 열 수: {df.shape[1]:,}")
    show(f"DataFrame 메모리: {df.memory_usage(deep=True).sum() / 1_000_000:,.2f} MB")
    show("자료형은 pandas의 읽기 결과이며 배정번호만 문자열로 지정했습니다.")

    show("\n[3] 처음 5행")
    show(df.head(5).to_string(index=False))
    show("\n[4] 마지막 5행")
    show(df.tail(5).to_string(index=False))
    show("\n[5] 컬럼명과 자료형")
    for number, column in enumerate(df.columns, start=1):
        show(f"{number:02d}. {column!r} / {df[column].dtype}")
    info_buffer = StringIO()
    df.info(buf=info_buffer, show_counts=True, memory_usage="deep")
    show("\n[6] info() 전체 구조")
    show(info_buffer.getvalue())

    # 결측: 개수와 비율을 함께 보아 규모를 판단합니다.
    missing_table = pd.DataFrame({
        "자료형": df.dtypes.astype(str),
        "결측치_개수": df.isna().sum(),
        "결측률_pct": df.isna().mean().mul(100).round(3),
    })
    show("\n[7] 컬럼별 결측치")
    show(missing_table.to_string())
    show("결측치는 pandas 기본 인식 기준입니다. 공백 문자열·특수 오류값은 별도 점검이 필요합니다.")

    # 완전 중복: 모든 칸이 같은 행 중 첫 행을 뺀 추가 행 수. 같은 시각이라는 이유만으로 중복이라 하지 않습니다.
    show("\n[8] 전체 컬럼 기준 중복 확인 중")
    show(f"완전 중복 추가 행 수: {int(df.duplicated().sum()):,}")
    show("읽힌 값 기준의 중복입니다. 아직 삭제하지 않았습니다.")

    # 숫자 요약: 지우기 위한 기준이 아니라 살펴볼 곳을 찾는 자료입니다.
    show("\n[9] 숫자형 컬럼 기초 통계")
    numeric_df = df.select_dtypes(include="number")
    if len(numeric_df.columns) > 0:
        show(numeric_df.describe().T.to_string())
    else:
        show("숫자형으로 읽힌 컬럼이 없습니다. 인코딩·구분자·자료형을 확인하세요.")

    show("\n[10] 시간 및 배정번호 확인")
    if "TAG_MIN" in df.columns:
        show("TAG_MIN 처음 5개 (파일 저장 순서, 시간 변환 전)")
        show(df["TAG_MIN"].head(5).to_string(index=False))
        show("TAG_MIN 마지막 5개 (파일 저장 순서, 시간 변환 전)")
        show(df["TAG_MIN"].tail(5).to_string(index=False))
        show("위 값이 전체 기간의 최소·최대 시각이라는 뜻은 아닙니다.")
    else:
        show("확인 필요: TAG_MIN 컬럼이 없습니다.")
    if "배정번호" in df.columns:
        show(f"배정번호 종류 수 (결측 제외): {df['배정번호'].nunique():,}")
        show("배정번호별 행 수 상위 10개 (결측 포함)")
        show(df["배정번호"].value_counts(dropna=False).head(10).to_string())
    else:
        show("확인 필요: 배정번호 컬럼이 없습니다.")

    show("\n[완료] 원본 확인이 끝났습니다.")
    show(f"보고서 위치: {report_path}")


# ════════════════════════════════════════════════════════════════════
# 2. 시간 점검 (원래 scripts/02_check_time_series.py)
#    작업(배정번호)마다 시간순으로 줄 세워 간격·긴 공백·같은 시각·연속 결측을 셉니다.
# ════════════════════════════════════════════════════════════════════
def step2_time_check(out):
    long_gap_seconds = 60  # 고장 판정 기준이 아니라 살펴볼 긴 공백을 고르는 기준
    sample_limit = 1000
    out.mkdir(parents=True)
    show, save = make_reporter(out, 'time_check_report.txt')

    show("시계열 구조 점검 보고서")
    show(f'실행: {datetime.now().isoformat(timespec="seconds")}')
    show(f"Python {sys.version.split()[0]} / pandas {pd.__version__}")
    show(f"원본: {RAW_CSV}")
    show("원본 보존. 센서값 수정·행 삭제·보간 없음. 점검용 정렬만 수행.")
    show("\n[1] 원본 읽기")
    df = read_raw_all()
    original_columns = df.columns.tolist()
    if not {"TAG_MIN", "배정번호"}.issubset(df.columns):
        raise ValueError("TAG_MIN 또는 배정번호 컬럼이 없습니다.")
    df["_source_row"] = np.arange(1, len(df) + 1)  # 원본 1번째 기록 = 1(헤더 제외)
    show(f"원본: {len(df):,}행 / {len(original_columns)}열")

    # errors=coerce: 잘못된 시각은 NaT로 표시해 몇 개인지 셉니다. 원본 TAG_MIN은 그대로 둡니다.
    df["_time"] = pd.to_datetime(df["TAG_MIN"], format="%Y-%m-%d %H:%M:%S", errors="coerce")
    bad_time = df["_time"].isna()
    bad_id = df["배정번호"].isna() | df["배정번호"].str.strip().eq("").fillna(False)
    invalid = bad_time | bad_id
    show("\n[2] 시간 변환 및 식별자 확인")
    show(f"시간 결측/변환 실패: {bad_time.sum():,}행")
    show(f"배정번호 결측/공백: {bad_id.sum():,}행")
    show(f"그룹별 시간 점검에서 제외한 행(원본에는 보존): {invalid.sum():,}행")
    show(f'변환 가능한 전체 시각: {df["_time"].min()} ~ {df["_time"].max()}')
    save(df.loc[invalid].head(sample_limit), "invalid_key_samples.csv")
    global_reverse = df.loc[~bad_time, "_time"].diff().lt(pd.Timedelta(0)).sum()
    show(f"원본 전체 순서의 시간 역전: {global_reverse:,}건 (배정번호 전환 영향 가능)")

    # 숫자로 바꿀 수 없는 값·무한대가 있는지 셉니다(값은 바꾸지 않음).
    value_columns = [c for c in original_columns if c not in ["TAG_MIN", "배정번호"]]
    numeric_records = []
    for col in value_columns:
        values = pd.to_numeric(df[col], errors="coerce")
        numeric_records.append({
            "컬럼": col,
            "원래_결측수": int(df[col].isna().sum()),
            "숫자변환_실패수": int((df[col].notna() & values.isna()).sum()),
            "무한대수": int(np.isinf(values).sum()),
        })
    save(pd.DataFrame(numeric_records), "numeric_check.csv")
    show("숫자 변환 실패/무한대 집계: numeric_check.csv (원본 값은 변경하지 않음)")

    batch_records, interval_records, gap_records = [], [], []
    duplicate_records, missing_records, missing_summaries = [], [], []
    reverse_samples = []
    groups = df.loc[~invalid].groupby("배정번호", sort=False)
    show(f"\n[3] 배정번호별 점검 시작: {groups.ngroups}개")
    for group_index, (batch, original) in enumerate(groups, start=1):
        reverse_mask = original["_time"].diff().lt(pd.Timedelta(0))
        if reverse_mask.any():
            reverse_samples.append(original.loc[reverse_mask, ["배정번호", "_source_row", "TAG_MIN"]].head(10))
        # 배정번호끼리 잇지 않고 작업 하나 안에서만 시간순으로 줄 세웁니다.
        ordered = original.sort_values(["_time", "_source_row"]).reset_index(drop=True)
        delta = ordered["_time"].diff().dt.total_seconds()
        positive = delta[delta.gt(0)]
        modes = positive.mode()
        typical = float(modes.iloc[0]) if not modes.empty else np.nan  # 가장 흔한 간격(보통 1초)
        for seconds, count in delta.dropna().value_counts().sort_index().items():
            interval_records.append({"배정번호": batch, "간격_초": seconds, "건수": int(count)})

        duplicate_mask = ordered.duplicated("_time", keep=False)
        duplicate_groups = 0
        for timestamp, same_time in ordered.loc[duplicate_mask].groupby("_time"):
            duplicate_groups += 1
            conflict_columns = [c for c in value_columns if same_time[c].nunique(dropna=False) > 1]
            duplicate_records.append({
                "배정번호": batch, "시각": timestamp, "행수": len(same_time),
                "추가행수": len(same_time) - 1, "값충돌": bool(conflict_columns),
                "충돌컬럼": " | ".join(conflict_columns),
            })
        long_gap = delta.gt(long_gap_seconds)
        for i in np.flatnonzero(long_gap.to_numpy()):
            gap_records.append({
                "배정번호": batch, "이전시각": ordered.loc[i - 1, "_time"],
                "다음시각": ordered.loc[i, "_time"], "간격_초": delta.iloc[i],
                "다음_원본기록번호": ordered.loc[i, "_source_row"],
            })
        batch_records.append({
            "배정번호": batch, "행수": len(ordered),
            "시작": ordered["_time"].min(), "종료": ordered["_time"].max(),
            "원본순서_역전수": int(reverse_mask.sum()),
            "동일시각_그룹수": duplicate_groups,
            "동일시각_추가행수": int(ordered.duplicated("_time").sum()),
            "최빈양수간격_초": typical, "최빈간격_동률후보수": len(modes),
            "양수간격_중앙값_초": positive.median(), "최대간격_초": positive.max(),
            "60초초과_간격수": int(long_gap.sum()),
        })

        # 연속 결측: 가장 흔한 간격 이하로 붙어 있는 기록끼리만 한 덩어리로 봅니다.
        # 같은 시각이나 더 큰 공백에서는 덩어리를 끊어 '오래 비었다'고 과장하지 않습니다.
        boundary = delta.isna() | delta.le(0) | delta.gt(typical)
        if np.isnan(typical):
            boundary[:] = True
        for col in value_columns:
            missing = ordered[col].isna()
            run_start = missing & (~missing.shift(1, fill_value=False) | boundary)
            run_end = missing & (~missing.shift(-1, fill_value=False) | boundary.shift(-1, fill_value=True))
            starts = np.flatnonzero(run_start.to_numpy())
            ends = np.flatnonzero(run_end.to_numpy())
            for start, end in zip(starts, ends):
                span = (ordered.loc[end, "_time"] - ordered.loc[start, "_time"]).total_seconds()
                missing_records.append({
                    "배정번호": batch, "컬럼": col,
                    "시작시각": ordered.loc[start, "_time"], "종료시각": ordered.loc[end, "_time"],
                    "결측행수": int(end - start + 1), "첫끝시각차_초": span,
                    "시작_원본기록번호": ordered.loc[start, "_source_row"],
                    "종료_원본기록번호": ordered.loc[end, "_source_row"],
                })
            missing_summaries.append({
                "배정번호": batch, "컬럼": col, "결측행수": int(missing.sum()),
                "결측구간수": len(starts),
                "최대연속결측행수": int((ends - starts + 1).max()) if len(starts) else 0,
            })
        if group_index % 10 == 0 or group_index == groups.ngroups:
            show(f"진행: {group_index}/{groups.ngroups}")

    batch_table = pd.DataFrame(batch_records)
    save(batch_table, "batch_time_summary.csv")
    save(pd.DataFrame(interval_records, columns=["배정번호", "간격_초", "건수"]), "time_interval_counts.csv")
    save(pd.DataFrame(gap_records, columns=["배정번호", "이전시각", "다음시각", "간격_초", "다음_원본기록번호"]),
         "long_gaps.csv")
    dup_table = pd.DataFrame(duplicate_records, columns=["배정번호", "시각", "행수", "추가행수", "값충돌", "충돌컬럼"])
    save(dup_table, "duplicate_time_groups.csv")
    runs = pd.DataFrame(missing_records, columns=["배정번호", "컬럼", "시작시각", "종료시각", "결측행수",
                                                  "첫끝시각차_초", "시작_원본기록번호", "종료_원본기록번호"])
    save(runs, "missing_runs.csv")
    save(pd.DataFrame(missing_summaries, columns=["배정번호", "컬럼", "결측행수", "결측구간수", "최대연속결측행수"]),
         "missing_by_batch.csv")
    reversals = (pd.concat(reverse_samples, ignore_index=True) if reverse_samples
                 else pd.DataFrame(columns=["배정번호", "_source_row", "TAG_MIN"]))
    save(reversals.head(sample_limit), "time_reverse_samples.csv")

    show("\n[4] 요약")
    show(f"유효 키 행수: {(~invalid).sum():,} / 점검 제외: {invalid.sum():,}")
    if not batch_table.empty:
        show(f'배정번호 내부 시간 역전 합계: {batch_table["원본순서_역전수"].sum():,}')
        show(f'동일 배정번호·시각 추가 행: {batch_table["동일시각_추가행수"].sum():,}')
        show("배정번호별 최빈 양수 간격(초)의 분포:")
        show(batch_table["최빈양수간격_초"].value_counts(dropna=False).to_string())
    show(f'값 충돌이 있는 동일시각 그룹: {int(dup_table["값충돌"].sum()):,}')
    show(f"{long_gap_seconds}초 초과 간격: {len(gap_records):,}")
    show(f"관측된 결측 구간: {len(runs):,}")
    if not runs.empty:
        show("결측행수가 많은 구간 상위 20개:")
        show(runs.sort_values("결측행수", ascending=False).head(20).to_string(index=False))
    show("\n[해석 및 한계]")
    show("최빈 간격은 관측값의 요약이며 설계 측정 주기로 확정할 수 없습니다. 동률이면 가장 작은 간격을 사용했습니다.")
    show("긴 공백은 작업 중단/선별된 데이터/누락 등 원인 미확정. 기대 행수나 손실률로 환산하지 않았습니다.")
    show("결측 구간의 첫끝시각차는 전체 결측 지속시간이 아닙니다. 한 행이면 0초이며 앞뒤 경계는 미확정입니다.")
    show("키가 유효한 행만 그룹 점검했습니다. 변환 실패 행과 중복은 삭제하지 않았습니다.")
    show("원본기록번호는 헤더 제외 1부터 시작. 오류 샘플은 최대 1000행, 역전 샘플은 배정번호별 최대 10행/전체 최대 1000행입니다.")
    show("이번 단계는 고장 탐지나 정상 판정이 아닙니다. 컬럼 의미/배정번호 의미/운전 기록 확인이 필요합니다.")
    # [통합본 수정] 원래 문구 "결측·중복 처리 기준 결정 → 처리 코드 작성"은 옛 계획입니다(§11-3 P3).
    show("처리 기준(회의 결정): 결측은 채우거나 지우지 않고 '판정 불가'로 표시, 60초 넘는 공백에서 구간을 나눔.")
    show(f"\n결과 폴더: {out}")
    show("[완료] 시계열 구조 점검이 끝났습니다.")


# ════════════════════════════════════════════════════════════════════
# 3. 결측·공백 앞뒤 검토 (원래 scripts/03_review_missing_context.py)
#    2번 결과에서 대표 결측 사례와 60초 넘는 공백을 골라 앞뒤 5분을 표·그림으로 남깁니다.
# ════════════════════════════════════════════════════════════════════
def step3_missing_review(out, source):
    window_minutes = 5  # 앞뒤로 볼 범위. 정상/고장 판정 기준이 아닙니다.
    required = ['missing_runs.csv', 'long_gaps.csv', 'batch_time_summary.csv',
                'numeric_check.csv', 'time_interval_counts.csv', 'time_check_report.txt']
    if not all((source / f).is_file() for f in required):
        raise FileNotFoundError(f'2번(시간 점검) 결과 파일이 부족합니다: {source}')
    (out / 'figures').mkdir(parents=True)
    show, save = make_reporter(out, 'missing_review_report.txt')
    korean_font = find_korean_font()
    show('결측·공백 주변 검토 보고서')
    show(f'실행: {datetime.now().isoformat(timespec="seconds")} / pandas {pd.__version__}')
    show(f'02단계 입력: {source}')
    show(f'그림 글꼴: {korean_font or "영문 대체 표기 (센서 번호는 sensor_columns.csv 참조)"}')
    show('원본 수정·보간·삭제 없음. 전후 평균은 관측값의 기술통계이며 정상 기준이 아닙니다.')

    missing = pd.read_csv(source / 'missing_runs.csv', dtype={'배정번호': 'string'})
    gaps = pd.read_csv(source / 'long_gaps.csv', dtype={'배정번호': 'string'})
    batches = pd.read_csv(source / 'batch_time_summary.csv', dtype={'배정번호': 'string'})
    numeric = pd.read_csv(source / 'numeric_check.csv')
    intervals = pd.read_csv(source / 'time_interval_counts.csv')
    dist = intervals.groupby('간격_초', as_index=False)['건수'].sum()
    dist['비율_pct'] = dist['건수'] / dist['건수'].sum() * 100
    save(dist, 'interval_distribution.csv')
    if dist['건수'].sum() != batches['행수'].sum() - len(batches):
        raise ValueError('02단계 행수/시간 간격 합계가 맞지 않습니다. 같은 실행 폴더인지 확인하세요.')
    show('\n[추가 점검]')
    show(dist.to_string(index=False))
    show(f'숫자변환 실패 합계: {numeric["숫자변환_실패수"].sum()} / 무한대 합계: {numeric["무한대수"].sum()}')
    if numeric[['숫자변환_실패수', '무한대수']].to_numpy().sum() > 0:
        raise ValueError('숫자 오류를 먼저 검토해야 합니다. numeric_check.csv를 공유해주세요.')

    # 사례 고르기: 소입1존 OP의 가장 긴 결측(서로 다른 작업 3개) + 다른 센서 최장 1개 + 짧은 결측 1개 + 긴 공백 전부
    selected = (missing.loc[missing['컬럼'].eq('소입1존 OP')].sort_values('결측행수', ascending=False)
                .drop_duplicates('배정번호').head(3))
    other = missing.loc[~missing['컬럼'].eq('소입1존 OP')].sort_values('결측행수', ascending=False).head(1)
    short_candidates = missing.loc[missing['결측행수'].between(2, 5)].merge(batches[['배정번호', '시작', '종료']], on='배정번호')
    internal = ((pd.to_datetime(short_candidates['시작시각'])
                 > pd.to_datetime(short_candidates['시작']) + pd.Timedelta(minutes=window_minutes))
                & (pd.to_datetime(short_candidates['종료시각'])
                   < pd.to_datetime(short_candidates['종료']) - pd.Timedelta(minutes=window_minutes)))
    short = short_candidates.loc[internal, missing.columns].sort_values(['시작시각', '컬럼']).head(1)
    selected = pd.concat([selected, other, short]).drop_duplicates(['배정번호', '컬럼', '시작시각', '종료시각'])
    events = []
    for _, row in selected.iterrows():
        events.append({'유형': 'missing', '배정번호': row['배정번호'], '대상컬럼': row['컬럼'],
                       '시작': pd.Timestamp(row['시작시각']), '종료': pd.Timestamp(row['종료시각']),
                       '결측행수': int(row['결측행수'])})
    for _, row in gaps.iterrows():
        events.append({'유형': 'gap', '배정번호': row['배정번호'], '대상컬럼': '',
                       '시작': pd.Timestamp(row['이전시각']), '종료': pd.Timestamp(row['다음시각']), '결측행수': 0})
    if not events:
        show('[완료] 검토 대상 구간이 없습니다.')
        return
    needed = {e['배정번호'] for e in events}
    show(f'\n[원본 읽기] 대표 결측 {len(selected)}건 + 긴 공백 {len(gaps)}건')
    # 큰 원본을 나눠 읽고 필요한 작업만 남겨 메모리를 아낍니다.
    parts, total_rows = [], 0
    for chunk in pd.read_csv(RAW_CSV, encoding=RAW_ENCODING, dtype={'배정번호': 'string'},
                             chunksize=200000, skip_blank_lines=False):
        total_rows += len(chunk)
        part = chunk.loc[chunk['배정번호'].isin(needed)]
        if not part.empty:
            parts.append(part)
    if total_rows != batches['행수'].sum():
        raise ValueError('원본 행수와 02단계 유효 행수가 다릅니다. 원본/점검 결과를 확인하세요.')
    if not parts:
        raise ValueError('선택된 배정번호가 원본에 없습니다.')
    data = pd.concat(parts, ignore_index=True)
    data['_time'] = pd.to_datetime(data['TAG_MIN'], format='%Y-%m-%d %H:%M:%S', errors='raise')
    cols = [c for c in data.columns if c not in ['TAG_MIN', '배정번호', '_time']]
    for col in cols:
        data[col] = pd.to_numeric(data[col], errors='raise')
    save(pd.DataFrame({'센서번호': [f'S{i+1:02d}' for i in range(len(cols))], '컬럼': cols}), 'sensor_columns.csv')

    stats, event_rows = [], []
    window = pd.Timedelta(minutes=window_minutes)
    for number, event in enumerate(events, start=1):
        event_id = f'E{number:02d}'
        batch, start, end = event['배정번호'], event['시작'], event['종료']
        group = data.loc[data['배정번호'].eq(batch)].sort_values('_time')
        if group.empty or group['_time'].duplicated().any():
            raise ValueError(f'{batch}: 배정번호 없음 또는 중복 시각. 02 결과와 원본을 확인하세요.')
        times = pd.DatetimeIndex(group['_time'])
        if start not in times or end not in times:
            raise ValueError(f'{event_id}: 구간 경계가 원본과 맞지 않습니다.')
        context = group.loc[group['_time'].between(start - window, end + window)].copy()
        t = pd.DatetimeIndex(context['_time'])
        if event['유형'] == 'gap':
            # 공백: 양 끝 기록은 '이전'·'이후'에 넣고, 그 사이에는 기록이 없어야 합니다.
            before_mask, after_mask = t <= start, t >= end
            inside_mask = (t > start) & (t < end)
            if inside_mask.any():
                raise ValueError(f'{event_id}: 공백 안에 원본 기록이 있습니다.')
        else:
            # 결측: 양 끝 결측 기록까지 '구간 안'으로 봅니다.
            before_mask, after_mask = t < start, t > end
            inside_mask = (t >= start) & (t <= end)
            target = context.loc[inside_mask, event['대상컬럼']]
            if len(target) != event['결측행수'] or not target.isna().all():
                raise ValueError(f'{event_id}: 결측 구간이 원본과 맞지 않습니다.')
        save(context.drop(columns='_time'), f'{event_id}_context.csv')
        for col in cols:
            before, after = context.loc[before_mask, col], context.loc[after_mask, col]
            stats.append({'사례': event_id, '배정번호': batch, '컬럼': col,
                          '이전_기록수': len(before), '이전_유효수': before.count(), '이전_평균': before.mean(),
                          '이전_표준편차': before.std(), '이전_최솟값': before.min(), '이전_최댓값': before.max(),
                          '이후_기록수': len(after), '이후_유효수': after.count(), '이후_평균': after.mean(),
                          '이후_표준편차': after.std(), '이후_최솟값': after.min(), '이후_최댓값': after.max(),
                          '평균차_이후빼기이전': after.mean() - before.mean(),
                          '구간내_관측행수': int(inside_mask.sum()),
                          '구간내_해당센서결측수': int(context.loc[inside_mask, col].isna().sum())})
        # 단위가 다른 센서는 칸을 나눠 그림. 점만 찍어 빈 곳을 선으로 잇지 않습니다(보간처럼 보이지 않게).
        plot_cols = list(dict.fromkeys([event['대상컬럼'] or '소입1존 OP', '소입로 온도 1 Zone',
                                       '소입로 온도 2 Zone', '소입로 CP 값']))
        fig, axes = plt.subplots(len(plot_cols) + 1, 1, figsize=(12, 10), sharex=True, layout='constrained')
        for ax, col in zip(axes, plot_cols):
            ax.plot(t, context[col], linestyle='none', marker='.', markersize=2.5, color='#245e91')
            ax.set_ylabel(col if korean_font else f'S{cols.index(col)+1:02d}', fontsize=9)
            ax.ticklabel_format(axis='y', style='plain', useOffset=False)
        axes[-1].plot(t, context[cols].isna().sum(axis=1), '.', color='#6a4585', markersize=3)
        axes[-1].set_ylabel('결측 센서 수' if korean_font else 'Missing sensors')
        axes[-1].set_ylim(-0.5, len(cols) + 0.5)
        for ax in axes:
            ax.axvspan(start, end, color='#ebac47', alpha=.23)
            ax.grid(alpha=.2)
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
        axes[-1].set_xlabel(f'{start:%Y-%m-%d} | time')
        fig.suptitle(f'{event_id} | batch {batch} | {event["유형"]} | {start:%H:%M:%S} - {end:%H:%M:%S}\n'
                     + ('음영: 검토 구간 / 점: 관측값 / 보간 없음' if korean_font
                        else 'Shading: review interval | Dots: observations | No interpolation'))
        fig.savefig(out / 'figures' / f'{event_id}_context.png', dpi=160)
        plt.close(fig)
        event_rows.append({'사례': event_id, **event, '이전_기록수': int(before_mask.sum()),
                           '이후_기록수': int(after_mask.sum()), '구간내_관측행수': int(inside_mask.sum()),
                           '배정시작': times.min(), '배정종료': times.max(),
                           '이전5분_범위부족': bool(start - window < times.min()),
                           '이후5분_범위부족': bool(end + window > times.max())})
        show(f'{event_id}: {batch} / {event["유형"]} / {start} ~ {end} / 전후 기록 {before_mask.sum()}, {after_mask.sum()}')
    save(pd.DataFrame(event_rows), 'review_events.csv')
    save(pd.DataFrame(stats), 'context_statistics.csv')
    show('\n[해석 기준] 전후 5분의 유효 관측값 평균 비교. 기록수/유효수를 함께 확인하세요.')
    show('결측 구간은 양 끝 결측 기록을 포함하고, 공백 구간은 양 끝 관측 기록을 제외한 열린 구간입니다.')
    show('그림의 빈 부분은 보간하지 않았습니다. 공백에는 결측 센서 수 자체도 관측되지 않습니다.')
    show('짧은 결측은 전후 5분이 배정 기간 안에 있는 시간순 첫 사례(최대 1건)로 선택했으며 대표성을 보장하지 않습니다.')
    show('이전/이후 구간에 다른 결측이나 공백이 포함될 수 있습니다. 평균 차이만으로 원인/고장을 확정하지 마세요.')
    show('동시 결측은 공통 수집 문제의 후보 단서일 뿐입니다. 센서 의미와 운전 기록 확인이 필요합니다.')
    # [통합본 수정] 원래 문구 "짧은 결측 보간 후보/긴 결측 유지/시간 공백 분리 기준을 결정"은 옛 계획입니다(§11-3 P3).
    show('처리 기준(회의 결정 6): 보간하지 않음. 결측은 판정 불가, 60초 넘는 공백은 구간 분리.')
    show(f'결과 폴더: {out}')
    show('[완료] 결측·공백 주변 검토가 끝났습니다.')


# ════════════════════════════════════════════════════════════════════
# 4. 5분 평균 개요 (원래 scripts/04_resample_overview.py) — 소개용, 이상 판정에 쓰지 않음
#    작업마다 시계 기준 5분 칸(10:00~10:05 미만 …)으로 묶어 평균과 기록 수를 구합니다.
# ════════════════════════════════════════════════════════════════════
def resample_batch(group, sensor_columns, minutes):
    """배정번호 하나를 시계 기준 구간으로 묶어 평균과 관측 수 계산."""
    ordered = group.sort_values('TAG_MIN').set_index('TAG_MIN')
    # 예: 10:00:00 이상 ~ 10:05:00 미만. 10:05:00은 다음 구간.
    sampler = ordered.resample(f'{minutes}min', origin='start_day', closed='left', label='left')
    means = sampler[sensor_columns].mean()
    counts = sampler[sensor_columns].count()
    quality = pd.DataFrame(index=means.index)
    quality['관측행수'] = sampler.size()
    # 기록이 아예 없는 칸과, 기록은 있으나 센서값이 빈 칸을 구분합니다.
    quality['빈구간'] = quality['관측행수'].eq(0)
    start, end = ordered.index.min(), ordered.index.max()
    quality['배정경계구간'] = ((quality.index == start.floor(f'{minutes}min')) |
                         (quality.index == end.floor(f'{minutes}min')))
    for col in sensor_columns:
        quality[f'{col}__유효수'] = counts[col]
        quality[f'{col}__결측수'] = quality['관측행수'] - counts[col]
    # 묶기 전후 기록 수가 같아야 합니다(빈 칸을 만들어도 원본 기록 수는 그대로).
    if int(quality['관측행수'].sum()) != len(group):
        raise ValueError('리샘플링 전후 기록 수 불일치')
    if not np.array_equal(counts.sum().to_numpy(), group[sensor_columns].count().to_numpy()):
        raise ValueError('센서별 유효값 개수 불일치')
    return means, quality


def step4_overview(out, minutes=5):
    (out / 'figures').mkdir(parents=True)
    show, _ = make_reporter(out, 'overview_report.txt')
    show(f'전체 흐름 소개용 {minutes}분 리샘플링')
    show(f'입력: {RAW_CSV}')
    show(f'Python {sys.version.split()[0]} / pandas {pd.__version__}')
    show('원본 읽기 시작')
    data = read_raw_all()
    if data.empty or not {'TAG_MIN', '배정번호'}.issubset(data.columns):
        raise ValueError('데이터가 비었거나 필수 컬럼이 없습니다.')
    sensor_columns = [c for c in data.columns if c not in ['TAG_MIN', '배정번호']]
    if not sensor_columns:
        raise ValueError('센서 컬럼이 없습니다.')
    data['TAG_MIN'] = pd.to_datetime(data['TAG_MIN'], format='%Y-%m-%d %H:%M:%S', errors='raise')
    if data['TAG_MIN'].isna().any() or data['배정번호'].isna().any() or data['배정번호'].str.strip().eq('').any():
        raise ValueError('시간 또는 배정번호 결측을 먼저 확인해주세요.')
    if data.duplicated(['배정번호', 'TAG_MIN']).any():
        raise ValueError('같은 배정번호·시각의 중복 기록을 먼저 확인해주세요.')
    for col in sensor_columns:
        data[col] = pd.to_numeric(data[col], errors='raise')
        if np.isinf(data[col]).any():
            raise ValueError(f'{col}: 무한대 값을 먼저 확인해주세요.')

    show(f'원본 {len(data):,}행 / 센서 {len(sensor_columns)}개')
    means_list, quality_list = [], []
    groups = data.groupby('배정번호', sort=False)
    for number, (batch, group) in enumerate(groups, start=1):
        means, quality = resample_batch(group, sensor_columns, minutes)
        means.insert(0, '배정번호', batch)
        quality.insert(0, '배정번호', batch)
        means_list.append(means.reset_index())
        quality_list.append(quality.reset_index())
        if number % 20 == 0 or number == groups.ngroups:
            show(f'집계 {number}/{groups.ngroups}')
    result = pd.concat(means_list, ignore_index=True).sort_values(['TAG_MIN', '배정번호'])
    quality = pd.concat(quality_list, ignore_index=True).sort_values(['TAG_MIN', '배정번호'])
    result.to_csv(out / f'overview_{minutes}min_mean.csv', index=False, encoding='utf-8-sig')
    quality.to_csv(out / f'overview_{minutes}min_counts.csv', index=False, encoding='utf-8-sig')

    font = find_korean_font()
    pd.DataFrame({'센서번호': [f'S{i+1:02d}' for i in range(len(sensor_columns))],
                  '컬럼': sensor_columns}).to_csv(out / 'sensor_columns.csv', index=False, encoding='utf-8-sig')
    # 센서를 4개씩 나눠 그림 1장에 칸 4개. 서로 다른 센서의 세로축을 섞지 않습니다.
    for offset in range(0, len(sensor_columns), 4):
        columns = sensor_columns[offset:offset + 4]
        fig, axes = plt.subplots(len(columns), 1, figsize=(14, 2.7 * len(columns)),
                                 sharex=True, squeeze=False, layout='constrained')
        for i, col in enumerate(columns):
            ax = axes[i, 0]
            # 점 하나 = 작업 하나의 5분 평균. 작업 사이·공백을 선으로 잇지 않습니다.
            ax.plot(result['TAG_MIN'], result[col], linestyle='none', marker='.',
                    markersize=2, alpha=.7, color='#23689b')
            ax.set_ylabel(col if font else f'S{offset+i+1:02d}')
            ax.grid(alpha=.2)
            ax.ticklabel_format(axis='y', style='plain', useOffset=False)
        axes[-1, 0].xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))
        axes[-1, 0].set_xlabel('Date')
        fig.suptitle(f'{minutes}분 평균 · 전체 기간 개요' if font else f'{minutes}-minute means | full period overview')
        fig.savefig(out / 'figures' / f'overview_{minutes}min_{offset//4+1:02d}.png', dpi=180)
        plt.close(fig)
    show(f'기간: {data["TAG_MIN"].min()} ~ {data["TAG_MIN"].max()}')
    show(f'배정번호: {groups.ngroups}개 / 집계 구간: {len(result):,}개')
    show(f'배정 기간 내부의 빈 구간: {quality["빈구간"].sum():,}개')
    show('방법: 배정번호별 시계 기준 집계. 시작 시각 포함, 끝 시각 제외. TAG_MIN은 구간 시작.')
    show('평균은 구간 내 유효 관측값의 산술평균이며 시간가중평균이 아닙니다.')
    show('기존 NaN은 평균에서 제외됩니다. 유효값이 하나도 없으면 평균은 NaN입니다.')
    show('배정 첫/마지막 구간은 일부 시간만 관측됐을 수 있습니다. counts 파일의 경계 표시를 확인하세요.')
    show('관측 수의 차이를 함께 기록했으며 최소 관측 수로 평균을 제외하지 않았습니다.')
    show('배정 기간 밖의 빈 구간은 생성하지 않았습니다. 그래프는 공백을 선으로 잇지 않습니다.')
    show('5분보다 짧은 공백은 평균 점에 드러나지 않을 수 있습니다. 시간 공백 전체 목록은 02 결과 참조.')
    show('목적: 데이터 형태 소개. 짧은 온도 이탈은 평균화로 약해질 수 있어 이상 판정에는 사용하지 않습니다.')
    show('보간·원본 수정·불량률 연결·정상/이상 기준 설정은 수행하지 않았습니다.')
    show(f'결과 폴더: {out}')
    show('[완료] 개요용 리샘플링 및 그래프 저장 완료')


# ════════════════════════════════════════════════════════════════════
# 5. 공통 데이터 계약 점검 (원래 stages/1단계_전처리/1단계_전처리_데이터계약점검.py)
#    위 load_raw·add_segments·load_quality를 원본 전체에 적용하고 기존 보고서 값 30개와 맞춰 봅니다.
# ════════════════════════════════════════════════════════════════════
# 분석 대상 11개 열(§3): 솔트조 2, 소입로 4(판정 대상), 소입 OP 4·CP 값(해석 보조)
SENSORS = ['솔트조 온도 1 Zone', '솔트조 온도 2 Zone',
           '소입로 온도 1 Zone', '소입로 온도 2 Zone', '소입로 온도 3 Zone', '소입로 온도 4 Zone',
           '소입1존 OP', '소입2존 OP', '소입3존 OP', '소입4존 OP', '소입로 CP 값']

# 기대값 출처: reports/raw_check/20260921_111027_298294/, reports/time_check/20260921_134157_798824/
EXPECTED_ROWS = 2_939_722
EXPECTED_BATCHES = 136
EXPECTED_MISSING = {'솔트조 온도 1 Zone': 209, '솔트조 온도 2 Zone': 203,
                    '소입로 온도 1 Zone': 130, '소입로 온도 2 Zone': 128,
                    '소입로 온도 3 Zone': 157, '소입로 온도 4 Zone': 170,
                    '소입1존 OP': 4288, '소입2존 OP': 0, '소입3존 OP': 2, '소입4존 OP': 3,
                    '소입로 CP 값': 1}
EXPECTED_INTERVALS = {'1초': 2_877_840, '2초': 61_643, '3~12초': 100, '13~60초': 0, '60초 초과': 3}
EXPECTED_GAPS = [('134495', '2022-05-13 17:29:58', '2022-05-13 17:32:00', 122.0),
                 ('136014', '2022-05-20 17:16:56', '2022-05-20 17:40:57', 1441.0),
                 ('136014', '2022-05-20 18:35:28', '2022-05-20 18:38:08', 160.0)]
EXPECTED_SEGMENTS = EXPECTED_BATCHES + len(EXPECTED_GAPS)
EXPECTED_WORKDAY_MONTHS = {1: 14, 2: 8, 3: 23, 4: 33, 5: 22, 6: 22, 7: 14}


def self_test():
    """불규칙 간격 합성 예제로 dt_prev·dt_next·세그먼트 규칙을 확인합니다(§11-4, R04)."""
    t0 = pd.Timestamp('2022-01-01 00:00:00')
    seconds = [0, 1, 3, 100, 101]  # 3초 → 100초: 97초 공백이라 새 세그먼트
    toy = pd.DataFrame({'_source_row': range(1, 6), BATCH_COL: pd.array(['T'] * 5, dtype='string'),
                        TIME_COL: [t0 + pd.Timedelta(seconds=s) for s in seconds]})
    toy = add_segments(toy.iloc[::-1].reset_index(drop=True))  # 역순 입력도 시간순으로 정렬되는지
    assert toy[TIME_COL].is_monotonic_increasing
    assert toy['segment_id'].tolist() == ['T_01'] * 3 + ['T_02'] * 2
    assert np.isnan(toy.loc[0, 'dt_prev']) and toy.loc[1, 'dt_prev'] == 1 and toy.loc[3, 'dt_prev'] == 97
    assert toy.loc[1, 'dt_next'] == 2 and np.isnan(toy.loc[2, 'dt_next']) and np.isnan(toy.loc[4, 'dt_next'])
    # §4-4 시간 조각: 1초 기록만 양성이면 노출 시간 = 그 기록의 dt_next = 2초(행 수 1로 세지 않음)
    positive = toy[TIME_COL].eq(t0 + pd.Timedelta(seconds=1))
    assert toy.loc[positive, 'dt_next'].sum() == 2

    # 회귀 검사: 시각이 빈 칸이거나 'NaT'인 행은 load_raw가 거부해야 함(통과하면 작업 끝으로 밀려 새 세그먼트가 됨)
    with tempfile.TemporaryDirectory() as tmp:
        for bad in ['', 'NaT']:
            path = Path(tmp) / 'bad_time.csv'
            path.write_text(f'TAG_MIN,배정번호,s1\n2022-01-01 00:00:00,T,1.0\n{bad},T,2.0\n', encoding='cp949')
            try:
                load_raw(['s1'], 'float64', path=path)
            except ValueError as error:
                assert 'TAG_MIN 결측 1행' in str(error)
            else:
                raise AssertionError(f'시각 {bad!r} 행이 load_raw를 통과했습니다.')


def same_as_shared_module():
    """이 파일의 계약 함수·설정값이 src/data_contract.py(와 그 설정 src/project_config.py)와 같은지 확인합니다.

    함수 글자만 같아도 함수가 쓰는 설정값(60초 기준, 월→기간 표, 파일 위치 등)이 다르면
    결과가 달라지므로, 함수 3개의 글자 + 설정값 8개 + 실제로 정해진 기본값을 모두 비교합니다.
    다른 이름 목록을 돌려줍니다(빈 목록 = 모두 같음).
    """
    sys.path.insert(0, str(PROJECT))
    import src.data_contract as shared
    differ = []
    for name in ['load_raw', 'add_segments', 'load_quality']:
        mine, theirs = globals()[name], getattr(shared, name)
        if inspect.getsource(mine) != inspect.getsource(theirs):
            differ.append(f'{name}(글자)')
        if mine.__defaults__ != theirs.__defaults__:  # 예: add_segments의 long_gap_sec, load_raw의 path
            differ.append(f'{name}(기본값)')
    for name in ['TIME_COL', 'BATCH_COL', 'TIME_FORMAT', 'LONG_GAP_SEC', 'PERIOD_BY_MONTH', 'RAW_ENCODING']:
        if globals()[name] != getattr(shared, name):
            differ.append(name)
    for name in ['RAW_CSV', 'QUALITY_XLSX']:  # 파일 위치는 실제 절대 경로로 비교
        if Path(globals()[name]).resolve() != Path(getattr(shared, name)).resolve():
            differ.append(name)
    return differ


def step5_contract(out):
    """기대값이 모두 맞으면 True, 하나라도 다르면 False를 돌려줍니다."""
    out.mkdir(parents=True)
    show, save = make_reporter(out, 'data_contract_report.txt')
    checks = []

    def check(item, expected, actual):
        checks.append({'항목': item, '기대값': str(expected), '실제값': str(actual), '일치': expected == actual})

    show('공통 데이터 계약 점검 보고서 (1단계)')
    show(f'실행: {datetime.now().isoformat(timespec="seconds")} / Python {sys.version.split()[0]} '
         f'/ pandas {pd.__version__} / numpy {np.__version__}')
    show('원본 수정·보간·행 삭제·집계·이상 판정 없음. 근거: docs/plans/ANALYSIS-PLAN.md §4-1, §11-4')

    show('\n[0] 공통 모듈과 같은 내용인지 (src/data_contract.py)')
    differ = same_as_shared_module()
    if differ:
        show(f'[실패] src/data_contract.py와 다른 항목: {differ}. 두 파일을 같게 맞추세요.')
        return False
    show('같음: 함수 3개(load_raw·add_segments·load_quality)의 글자·기본값, '
         '설정값 8개(TIME_COL·BATCH_COL·TIME_FORMAT·LONG_GAP_SEC·PERIOD_BY_MONTH·RAW_ENCODING·RAW_CSV·QUALITY_XLSX)')

    show('\n[1] 합성 예제 단위 검사 (dt_prev·dt_next·세그먼트)')
    self_test()
    show('통과: 0·1·3초 기록에서 1초 기록 dt_prev=1, dt_next=2, 노출 2초 / 97초 공백에서 새 세그먼트 '
         '/ 시각 빈 칸·NaT 행은 읽기 단계에서 거부')

    show('\n[2] 원본 읽기 (센서 11개 열, float64)')
    raw = load_raw(SENSORS, 'float64')
    show(f'{len(raw):,}행 / 배정번호 {raw[BATCH_COL].nunique()}개')
    check('행 수', EXPECTED_ROWS, len(raw))
    check('배정번호 수', EXPECTED_BATCHES, int(raw[BATCH_COL].nunique()))
    for col, n in EXPECTED_MISSING.items():
        check(f'결측: {col}', n, int(raw[col].isna().sum()))
    # 원본 저장 순서 그대로 같은 배정번호 안에서 시각이 뒤로 가는 곳(정렬 전)
    reversal = int(raw.groupby(BATCH_COL, sort=False)[TIME_COL].diff().lt(pd.Timedelta(0)).sum())
    check('배정번호 내부 시간 역전(원본 순서)', 0, reversal)
    check('같은 배정번호·시각 중복', 0, int(raw.duplicated([BATCH_COL, TIME_COL]).sum()))

    # float64로 읽은 값을 float32로 바꿨을 때의 차이 크기(정보용, §11-3 P2).
    f32_rows = []
    for col in SENSORS:
        x = raw[col].to_numpy()
        x = x[~np.isnan(x)]
        err = np.abs(x.astype('float32').astype('float64') - x)
        f32_rows.append({'컬럼': col, '유효값수': len(x), '최대_절대차': float(err.max()),
                         '절대차_1e-4_이상_셀수': int((err >= 1e-4).sum())})

    show('\n[3] 정렬·간격·세그먼트')
    df = add_segments(raw)
    check('세그먼트 처리 후 행 수', EXPECTED_ROWS, len(df))
    gaps = df['dt_prev'].dropna()
    intervals = {'1초': int(gaps.eq(1).sum()), '2초': int(gaps.eq(2).sum()),
                 '3~12초': int(gaps.between(3, 12).sum()), '13~60초': int(gaps.between(13, 60).sum()),
                 '60초 초과': int(gaps.gt(60).sum())}
    other = len(gaps) - sum(intervals.values())  # 0초·음수·정수 아닌 간격
    for k, v in EXPECTED_INTERVALS.items():
        check(f'간격 {k}', v, intervals[k])
    check('간격 분류 밖(0초·음수·소수)', 0, other)
    check('간격 합계 = 행 수 − 배정번호 수', EXPECTED_ROWS - EXPECTED_BATCHES, len(gaps))
    save(pd.DataFrame({'구분': list(intervals), '건수': list(intervals.values())}), 'interval_distribution.csv')

    starts = df.loc[df['dt_prev'].gt(60)].index
    found = [(df.at[i, BATCH_COL], str(df.at[i - 1, TIME_COL]), str(df.at[i, TIME_COL]), float(df.at[i, 'dt_prev']))
             for i in starts]
    check('긴 공백 위치(배정번호, 이전 시각, 다음 시각, 간격초)', EXPECTED_GAPS, found)
    check('세그먼트 수', EXPECTED_SEGMENTS, int(df['segment_id'].nunique()))
    check('dt_next 결측 수 = 세그먼트 수', EXPECTED_SEGMENTS, int(df['dt_next'].isna().sum()))
    seg = (df.groupby('segment_id', sort=True)
             .agg(배정번호=(BATCH_COL, 'first'), 시작=(TIME_COL, 'min'), 종료=(TIME_COL, 'max'),
                  기록수=(TIME_COL, 'size'), 최대간격_초=('dt_next', 'max'))
             .reset_index())
    save(seg, 'segment_summary.csv')

    show('\n[4] 품질 파일 연결과 기간 배정')
    q = load_quality()
    raw_ids, q_ids = set(df[BATCH_COL].unique()), set(q[BATCH_COL])
    check('품질 배정번호 수', EXPECTED_BATCHES, len(q_ids))
    check('원본에만 있는 배정번호 수', 0, len(raw_ids - q_ids))
    check('품질에만 있는 배정번호 수', 0, len(q_ids - raw_ids))
    workday = q['작업일_월'].value_counts().sort_index()
    check('작업일 월별 작업 수(1~7월)', EXPECTED_WORKDAY_MONTHS, {int(k): int(v) for k, v in workday.items()})

    first = df.groupby(BATCH_COL, sort=False)[TIME_COL].min().rename('첫기록시각').reset_index()
    batch = q[[BATCH_COL, '작업일', '작업일_월', '기간']].merge(first, on=BATCH_COL, how='left', validate='one_to_one')
    batch['첫기록_월'] = batch['첫기록시각'].dt.month
    batch['월_일치'] = batch['작업일_월'].eq(batch['첫기록_월'])
    batch = batch.sort_values('첫기록시각')
    save(batch, 'batch_period.csv')
    first_month = batch['첫기록_월'].value_counts().sort_index()
    diff = batch.loc[~batch['월_일치']]

    table = pd.DataFrame(checks)
    save(table, 'expectations.csv')
    save(pd.DataFrame(f32_rows), 'float32_difference.csv')

    show('\n[5] 기대값 대조 (전체 표: expectations.csv)')
    for r in table.itertuples(index=False):
        show(f"{'일치' if r.일치 else '불일치'} | {r.항목} | 기대 {r.기대값} | 실제 {r.실제값}")
    show('\n[참고] 첫 기록 월 기준 월별 작업 수(기대값 없음, 문제정의서 기준과 비교용)')
    show(', '.join(f'{int(k)}월 {int(v)}' for k, v in first_month.items()))
    show(f'작업일 월 ≠ 첫 기록 월인 작업: {len(diff)}개')
    if len(diff):
        show(diff[[BATCH_COL, '작업일', '첫기록시각', '기간']].to_string(index=False))
    show('\n[참고] float64 값을 float32로 바꿨을 때의 차이(동결 재현은 float32 입력, §2-2-1 7단계)')
    show('차이는 작지만, 물리 최소 이탈(0.3℃·3℃) 경계에 걸린 기록은 판정이 바뀔 수 있어 동결 재현에는 float32를 씁니다.')
    show(pd.DataFrame(f32_rows).to_string(index=False))
    show('\n[해석 기준]')
    show('세그먼트 = 같은 배정번호 안에서 60초 넘는 공백으로 나눈 관측 구간. 공백은 설비 정지로 해석하지 않음.')
    show('dt_next는 시간 조각(§4-4) 계산용이며 세그먼트 마지막 기록은 결측. 행 수를 시간으로 쓰지 않음.')
    show('기간은 품질 작업일 월 기준(1~4월 학습 / 5월 조정 / 6~7월 후속적용 = 탐색적·회고적 비교).')
    show(f'결과 폴더: {out}')
    failed = table.loc[~table['일치']]
    if len(failed):
        show(f'\n[실패] 기대값과 다른 항목 {len(failed)}개. 다음 단계로 넘어가지 마세요.')
        return False
    show(f'\n[완료] 기대값 {len(table)}개 모두 일치. 공통 데이터 계약 점검이 끝났습니다.')
    return True


# ════════════════════════════════════════════════════════════════════
# 실행 순서: 1 → 2 → 3(2번 결과 사용) → 4 → 5
# ════════════════════════════════════════════════════════════════════
def main():
    # 프로젝트 전용 파이썬인지는 파일 맨 위(check_python_env)에서 이미 확인했습니다.
    if not RAW_CSV.is_file():
        raise FileNotFoundError(f'원본 파일이 없습니다: {RAW_CSV}\n원본은 data/raw/data.csv에 두세요.')
    root = PROJECT / 'reports' / '1단계_전처리_전체실행' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    steps = [
        ('1_원본확인', step1_raw_check),
        ('2_시간점검', step2_time_check),
        ('3_결측공백검토', lambda out: step3_missing_review(out, root / '2_시간점검')),
        ('4_5분개요', step4_overview),
        ('5_데이터계약', step5_contract),
    ]
    ok = True
    for name, run in steps:
        began = time.time()
        print(f'\n{"=" * 60}\n▶ {name} 시작\n{"=" * 60}', flush=True)
        result = run(root / name)
        print(f'■ {name} 끝 ({time.time() - began:.0f}초)', flush=True)
        if result is False:
            ok = False
    print(f'\n전체 결과 폴더: {root}')
    if not ok:
        print('[실패] 5번 데이터 계약 점검에서 다른 값이 나왔습니다. 다음 단계로 넘어가지 마세요.')
        sys.exit(1)
    print('[완료] 1단계 전처리 전체 실행이 끝났습니다.')


if __name__ == '__main__':
    main()
