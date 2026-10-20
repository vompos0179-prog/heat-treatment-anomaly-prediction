"""분석 단계가 공통으로 쓰는 원본 읽기 규칙(데이터 계약).

근거: docs/plans/ANALYSIS-PLAN.md §4-1, §11-4.
원본 수정·보간·행 삭제·집계·이상 판정을 하지 않습니다.
"""
import numpy as np
import pandas as pd

from src.project_config import QUALITY_XLSX, RAW_CSV, RAW_ENCODING

TIME_COL = 'TAG_MIN'
BATCH_COL = '배정번호'
TIME_FORMAT = '%Y-%m-%d %H:%M:%S'
LONG_GAP_SEC = 60  # 같은 작업 안에서 이 간격을 넘으면 새 세그먼트(회의 결정·02 결과와 같은 기준)

# 품질 `작업일`의 월 → 기간(B1). 6~7월은 탐색적·회고적 비교 구간이다(§4-6-0).
PERIOD_BY_MONTH = {1: '학습(1~4월)', 2: '학습(1~4월)', 3: '학습(1~4월)', 4: '학습(1~4월)',
                   5: '조정(5월)', 6: '후속적용(6~7월)', 7: '후속적용(6~7월)'}


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
