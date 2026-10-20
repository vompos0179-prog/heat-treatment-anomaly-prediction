"""3단계 ② 이상 구간 찾기 (설명용 정리본). 프로젝트 맨 위 폴더에서 실행하세요.

실행:
  .\\.venv\\Scripts\\python.exe "stages/3단계_이상구간/3단계_이상구간_찾기.py"
  ①과 대조까지 하려면 끝에 --compare-with "reports/3단계_이상구간_팀코드재현/(실행시각)" 을 붙입니다.
입력: data/raw/data.csv, data/raw/열처리_품질데이터.xlsx (src/data_contract.py로 읽음)
출력: reports/3단계_이상구간/(실행시각)/

하는 일 (팀 동결 규칙 그대로, 계획 §2-2-1):
  A1 = "직전 10분 평소 온도"에서, A2 = "1~4월 평소 온도"에서
  크게(|Z| ≥ 4 그리고 솔트조 0.3℃·소입로 3℃ 이상) 그리고 오래(60초 이상) 벗어난 구간을 찾습니다.
팀원 20번 코드와 계산이 같아야 하며, 같은지는 ① 재현본 결과와 기록 하나하나까지 대조합니다(§14-3).
라벨을 바꾸지 않는 계산만 더합니다: 실제 시각 길이, 이상 노출 시간(시간 조각), 설비 그룹 이벤트.
원본 수정·보간·행 삭제 없음. 규칙 값을 바꾸지 않습니다(C3).
"""
from pathlib import Path
from datetime import datetime
import sys
import time

PROJECT = Path(__file__).resolve().parents[2]  # stages/3단계_이상구간/ 의 두 단계 위


def check_python_env():
    """Python·패키지 버전이 권장 환경과 다르면 [주의]만 보여 주고 계속합니다(src/env_check.py)."""
    sys.path.insert(0, str(PROJECT))
    from src.env_check import check_python_env as check
    check(PROJECT)


def safe_console():
    """화면 출력이 cp949여도 특수문자 때문에 멈추지 않게 합니다(표현 못 하는 글자만 '?')."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')


if __name__ == '__main__':
    safe_console()
    check_python_env()  

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(PROJECT))
from src.data_contract import TIME_COL, BATCH_COL, LONG_GAP_SEC, load_raw, add_segments, load_quality  # noqa: E402

# ════════════════════════════════════════════════════════════════════
# 0. 규칙 값 — 팀 동결 값 그대로 (20번 코드 16~22행과 같음). 바꾸면 C3 위반입니다.
# ════════════════════════════════════════════════════════════════════
SENSORS = ['소입로 온도 1 Zone', '소입로 온도 2 Zone', '소입로 온도 3 Zone', '소입로 온도 4 Zone',
           '솔트조 온도 1 Zone', '솔트조 온도 2 Zone']
GROUPS = {'솔트조': SENSORS[4:], '소입로': SENSORS[:4]}      # 설비 그룹(발표 주 결과 = 솔트조)
PHYS = {s: (0.3 if '솔트조' in s else 3.0) for s in SENSORS}  # 물리 최소 이탈(℃)
ROLL_SEC = 600        # A1 기준: 직전 600초(10분) 중앙값
MIN_HISTORY = 300     # 창 안에 기록이 300개 이상일 때만 기준을 만듦
Z_LIMIT = 4.0         # |Z| ≥ 4
EVENT_GAP = 2         # 후보 사이 간격이 2초 이하면 한 이벤트로 이음
MIN_DURATION = 60     # (마지막 − 첫 후보 + 1초) ≥ 60초인 이벤트만 남김
PIECE_MAX_GAP = 5     # 시간 조각: 이웃 기록 간격이 5초 이하인 것만 시간으로 셈(§4-4)
assert LONG_GAP_SEC == 60  # 60초 넘는 공백에서 기준 창을 새로 시작(팀 코드 LONG_GAP과 같음)

# 공통 모듈의 기간 이름 → 팀 코드의 기간 이름(①과 결과를 비교하려고 팀 이름을 씀)
TEAM_PERIOD = {'학습(1~4월)': '기준작성(1~4월)', '조정(5월)': '조정(5월)', '후속적용(6~7월)': '후속비교(6~7월)'}
TRAIN_PERIOD = '기준작성(1~4월)'


# ════════════════════════════════════════════════════════════════════
# 1. 기준선 — "평소 온도"를 어떻게 정하나
# ════════════════════════════════════════════════════════════════════
def past_median_baseline(g):
    """A1 기준: 같은 구간(60초 넘는 공백 없이 이어진 기록) 안에서 '지금 기록 직전 600초'의 중앙값.

    closed='left' = 지금 기록은 빼고 과거만 봄. min_periods=300 = 과거 기록이 300개 미만이면 기준 없음(NaN).
    팀 코드 rolling_baseline()과 같은 호출입니다. 온도는 float32로 읽은 값 그대로 넣습니다.
    """
    out = pd.DataFrame(index=g.index, columns=SENSORS, dtype='float64')
    for _, idx in g.groupby('segment_id', sort=False).groups.items():
        sub = g.loc[idx, [TIME_COL] + SENSORS].set_index(TIME_COL)
        rb = sub[SENSORS].rolling(f'{ROLL_SEC}s', closed='left', min_periods=MIN_HISTORY).median()
        out.loc[idx, SENSORS] = rb[SENSORS].to_numpy()
    return out


def robust_center_scale(arr):
    """중앙값과 1.4826×MAD(흔들림 크기). MAD가 0에 가까우면 표준편차로 대신합니다(팀 코드와 같음)."""
    med = float(np.nanmedian(arr))
    mad = float(np.nanmedian(np.abs(arr - med)))
    scale = 1.4826 * mad
    if not np.isfinite(scale) or scale < 1e-9:
        scale = float(np.nanstd(arr))
    return med, float(scale)


def fit_reference(batches, train_batches, df):
    """1~4월 작업만으로 기준값을 고정합니다(5~7월 값은 보지 않음).

    A1: (값 − 직전 600초 중앙값)인 '잔차'의 중심과 척도. 잔차는 팀 코드처럼 float32로 모았다가 계산합니다.
    A2: 1~4월 온도 자체의 중앙값과 척도(np.median — 팀 코드 A2와 같은 함수).
    batches = {작업: (작업 기록, 직전 600초 기준선)}
    """
    resid_store = {s: [] for s in SENSORS}
    for b, (g, base) in batches.items():
        if b not in train_batches:
            continue
        for s in SENSORS:
            r = (g[s].astype('float64').to_numpy() - base[s].to_numpy())
            r = r[np.isfinite(r)]
            if len(r):
                resid_store[s].append(r.astype('float32'))
    train_mask = df[BATCH_COL].isin(train_batches)
    ref = {}
    for s in SENSORS:
        a1_center, a1_scale = robust_center_scale(np.concatenate(resid_store[s]).astype('float64'))
        x = df.loc[train_mask, s].dropna().astype('float64').to_numpy()
        a2_center = float(np.median(x))
        a2_mad = float(np.median(np.abs(x - a2_center)))
        a2_scale = 1.4826 * a2_mad
        if not np.isfinite(a2_scale) or a2_scale < 1e-9:
            a2_scale = float(np.std(x))
        ref[s] = {'A1_center': a1_center, 'A1_scale': a1_scale, 'A2_center': a2_center, 'A2_scale': a2_scale}
    return ref


# ════════════════════════════════════════════════════════════════════
# 2. 후보 → 이벤트 — 기록 하나하나를 판정하고 60초 이상 이어진 것만 남김
# ════════════════════════════════════════════════════════════════════
def candidates(method, x, base, r):
    """기록마다 '후보(크게 벗어남)'인지 판정합니다.

    valid = 판정할 수 있는 기록(값과 기준이 모두 있음).
    A1: Z = (값 − 직전 600초 중앙값 − 잔차 중심) ÷ 잔차 척도, 물리 조건은 |값 − 직전 600초 중앙값|.
    A2: Z = (값 − 1~4월 중앙값) ÷ 1~4월 척도, 물리 조건은 |값 − 1~4월 중앙값|.
    후보 = valid 그리고 |Z| ≥ 4 그리고 물리 조건 ≥ 최소 이탈.
    반환하는 dev는 팀 코드 max_abs_deviation 계산에 쓰는 값(A1은 잔차 중심을 뺀 값)입니다.
    """
    if method == 'A1':
        dev = x - base - r['A1_center']
        score = np.abs(dev) / r['A1_scale']
        valid = np.isfinite(x) & np.isfinite(base) & np.isfinite(score)
        cand = valid & (score >= Z_LIMIT) & (np.abs(x - base) >= r['phys'])
    else:
        dev = x - r['A2_center']
        score = np.abs(dev) / r['A2_scale']
        valid = np.isfinite(x) & np.isfinite(score)
        cand = valid & (score >= Z_LIMIT) & (np.abs(dev) >= r['phys'])
    return valid, cand, score, dev


def link_events(times_ns, cand):
    """후보 기록을 이벤트로 잇고, 60초 이상인 이벤트의 후보 기록만 최종 양성(qual)으로 남깁니다.

    잇는 규칙: 이웃한 후보끼리 시각 차이가 2초 이하면 같은 이벤트(사이에 정상·결측 기록이 끼어도 이음).
    길이 = 마지막 후보 시각 − 첫 후보 시각 + 1초 (팀 규칙, 60초 판정에 사용).
    반환: qual(기록별 True/False), 이벤트 목록[(첫 위치, 마지막 위치, +1초 길이, 후보 수)]
    """
    qual = np.zeros(len(cand), dtype=bool)
    events = []
    pos = np.flatnonzero(cand)
    if len(pos) == 0:
        return qual, events
    t_sec = times_ns[pos] // 1_000_000_000  # 나노초 → 초
    cuts = np.r_[0, np.flatnonzero(np.diff(t_sec) > EVENT_GAP) + 1, len(pos)]
    for a, b in zip(cuts[:-1], cuts[1:]):
        p = pos[a:b]
        dur = (times_ns[p[-1]] - times_ns[p[0]]) / 1e9 + 1
        if dur >= MIN_DURATION:
            qual[p] = True
            events.append((int(p[0]), int(p[-1]), float(dur), int(len(p))))
    return qual, events


# ════════════════════════════════════════════════════════════════════
# 3. 라벨을 바꾸지 않는 추가 계산 — 실제 시간 (계획 §2-2-1 "측정 방식 처리", §4-4)
# ════════════════════════════════════════════════════════════════════
def time_pieces(times_ns, segment_codes):
    """시간 조각: 같은 구간에서 바로 이웃한 두 기록 i, i+1 사이 시간 [t_i, t_{i+1}).

    간격이 5초 이하인 조각만 시간으로 세고, 조각의 상태는 기록 i의 판정을 따릅니다.
    각 구간의 마지막 기록과 5초 넘는 간격 앞 기록은 조각 길이 0입니다.
    """
    n = len(times_ns)
    piece = np.zeros(n, dtype='float64')
    if n > 1:
        gap = np.diff(times_ns) / 1e9
        same_seg = segment_codes[1:] == segment_codes[:-1]
        piece[:-1] = np.where(same_seg & (gap <= PIECE_MAX_GAP), gap, 0.0)
    return piece


def group_exposure(piece, valid_by_sensor, qual_by_sensor):
    """설비 그룹의 이상 노출 시간(§4-4 통합).

    E = 그룹의 모든 센서가 판정 가능한 조각(공통 평가 가능 시간).
    그룹 이상 = 센서 중 하나라도 최종 양성인 조각 중 E 안에 있는 것.
    검사(Codex R10-01): max_s |A_s∩E| ≤ |(∪A_s)∩E| ≤ Σ_s |A_s∩E|.
    """
    common = np.logical_and.reduce(valid_by_sensor)
    any_qual = np.logical_or.reduce(qual_by_sensor)
    e_sec = float(piece[common].sum())
    expo = float(piece[any_qual & common].sum())
    per_sensor_in_e = [float(piece[q & common].sum()) for q in qual_by_sensor]
    assert max(per_sensor_in_e) - 1e-6 <= expo <= sum(per_sensor_in_e) + 1e-6, '그룹 노출 시간 검사 실패'
    assert expo <= e_sec + 1e-6, '노출 시간이 평가 가능 시간보다 큼'
    return e_sec, expo, int(common.sum()), int((any_qual & common).sum())


def event_attributes(times_ns, st, en, cand, valid, raw_dev, t0_ns, span_sec):
    """이벤트 하나의 설명 속성(§4-4 구간 속성 — 라벨·경계는 바꾸지 않음, Codex S3-R2-01).

    방향: 후보 기록의 원시 이탈(A1은 값 − 직전 600초 중앙값, A2는 값 − 1~4월 중앙값) 부호.
          모두 +면 상승, 모두 −면 하락, 섞이면 혼합.
    내부 간격: 첫~마지막 후보 사이 이웃 기록 간 최대 간격(관측이 성긴 구간 구분용)과
              후보끼리의 최대 간격(2초 이하로 이어진 정도).
    사이에 낀 기록: 이벤트 안이지만 후보가 아닌 기록 수(그중 판정 불가 = 값·기준 없음).
    작업 내 위치: 작업 첫 기록부터 이벤트 시작까지 경과 분, 작업 기록 시간 대비 %.
    """
    in_span = slice(st, en + 1)
    c = cand[in_span]
    sign = np.sign(raw_dev[in_span][c])
    direction = '상승' if (sign > 0).all() else ('하락' if (sign < 0).all() else '혼합')
    t = times_ns[in_span]
    tc = t[c]
    elapsed = (times_ns[st] - t0_ns) / 1e9
    return {
        '방향': direction,
        '최대이탈_원시_℃': float(np.max(np.abs(raw_dev[in_span][c]))),
        '내부_최대기록간격_sec': float(np.diff(t).max() / 1e9) if len(t) > 1 else 0.0,
        '후보간_최대간격_sec': float(np.diff(tc).max() / 1e9) if len(tc) > 1 else 0.0,
        '사이에_낀_비후보기록수': int((~c).sum()),
        '그중_판정불가기록수': int((~valid[in_span]).sum()),
        '작업시작후_경과분': elapsed / 60,
        '작업내_위치_pct': elapsed / span_sec * 100 if span_sec > 0 else np.nan,
        '시작_시간대': int(pd.Timestamp(times_ns[st]).hour),
        '시작_월': int(pd.Timestamp(times_ns[st]).month),
    }


def merge_group_events(intervals):
    """같은 그룹 센서들의 이벤트 [첫 후보, 마지막 후보]가 겹치거나 2초 이하로 붙으면 하나로 합칩니다(§2-2-1 5)."""
    merged = []
    for st, en, sensor in sorted(intervals):
        if merged and (st - merged[-1][1]) / 1e9 <= EVENT_GAP:
            merged[-1][1] = max(merged[-1][1], en)
            merged[-1][2].add(sensor)
        else:
            merged.append([st, en, {sensor}])
    return merged


# ════════════════════════════════════════════════════════════════════
# 4. 작은 예제로 규칙 확인 (실행할 때마다 먼저 돌림, 1초도 안 걸림)
# ════════════════════════════════════════════════════════════════════
def self_test():
    sec = 1_000_000_000
    t = np.arange(0, 101, dtype='int64') * sec          # 0~100초, 1초 간격 기록 101개
    seg = np.zeros(len(t), dtype='int64')
    piece = time_pieces(t, seg)
    # (1) §9 예: 1 Zone 100초 이상, 2 Zone은 그중 20초 결측 → 1 Zone 노출 100초, 그룹 80초
    v1 = np.ones(101, bool); q1 = np.ones(101, bool)
    v2 = np.ones(101, bool); v2[40:60] = False; q2 = np.zeros(101, bool)
    assert piece[q1 & v1].sum() == 100
    e, expo, _, _ = group_exposure(piece, [v1, v2], [q1, q2])
    assert (e, expo) == (80.0, 80.0), (e, expo)
    # (2) 첫~마지막 차이 59초(후보 60개) → +1초 규칙으로 60초, 양성 유지. 실제 길이는 59초
    c = np.zeros(101, bool); c[0:60] = True
    qual, ev = link_events(t, c)
    assert len(ev) == 1 and ev[0][2] == 60.0 and qual[:60].all() and (t[59] - t[0]) / sec == 59
    # (3) 첫~마지막 차이 58초 → 59초 < 60초, 탈락(짧은 이탈)
    c = np.zeros(101, bool); c[0:59] = True
    assert not link_events(t, c)[0].any()
    # (4) 1 Zone 40초 후보 직후 2 Zone 40초 후보 → 센서별 60초 필터가 먼저라 그룹 양성 0
    c1 = np.zeros(101, bool); c1[0:40] = True
    c2 = np.zeros(101, bool); c2[40:80] = True
    assert not (link_events(t, c1)[0] | link_events(t, c2)[0]).any()
    # (5) 2초 간격은 이어짐: 0~30초, 32~61초 후보(31초 빠짐) → 한 이벤트 62초
    c = np.zeros(101, bool); c[0:31] = True; c[32:62] = True
    qual, ev = link_events(t, c)
    assert len(ev) == 1 and ev[0][2] == 62.0 and not qual[31]
    print('작은 예제 5개 통과')


# ════════════════════════════════════════════════════════════════════
# 5. 전체 실행
# ════════════════════════════════════════════════════════════════════
def run(out_dir):
    t0 = time.time()
    print('1) 원본·품질 읽기 (온도는 팀 코드처럼 float32)')
    df = add_segments(load_raw(SENSORS, sensor_dtype='float32'))
    q = load_quality()
    q['period'] = q['기간'].map(TEAM_PERIOD)
    q['불량률(%)'] = np.where(q['총수량'] > 0, q['불량수량'] / q['총수량'] * 100, np.nan)
    period_map = dict(zip(q[BATCH_COL], q['period']))
    date_map = dict(zip(q[BATCH_COL], q['작업일']))
    train_batches = set(q.loc[q['period'] == TRAIN_PERIOD, BATCH_COL])
    print(f'   기록 {len(df):,}행, 작업 {df[BATCH_COL].nunique()}개, 1~4월 작업 {len(train_batches)}개')

    print('2) 작업별 직전 600초 기준선 (가장 오래 걸리는 단계)')
    batches = {}
    for i, (b, g) in enumerate(df.groupby(BATCH_COL, sort=False), 1):
        g = g.reset_index(drop=True)
        batches[b] = (g, past_median_baseline(g))
        if i % 20 == 0:
            print(f'   {i}개 작업 완료')

    print('3) 1~4월로 기준값 고정')
    ref = fit_reference(batches, train_batches, df)
    for s in SENSORS:
        ref[s]['phys'] = PHYS[s]
    pd.DataFrame({
        'sensor': SENSORS,
        'A1_residual_center': [ref[s]['A1_center'] for s in SENSORS],
        'A1_residual_scale': [ref[s]['A1_scale'] for s in SENSORS],
        'A2_fixed_median': [ref[s]['A2_center'] for s in SENSORS],
        'A2_fixed_scale': [ref[s]['A2_scale'] for s in SENSORS],
        'physical_min_deviation': [PHYS[s] for s in SENSORS],
    }).to_csv(out_dir / '01_고정된_기준값.csv', index=False, encoding='utf-8-sig')

    print('4) 136개 작업에 A1·A2 적용')
    labels = {}            # (작업) → {키: 배열} — ①과 기록 단위 대조용
    event_rows, batch_rows, sensor_rows, group_rows, gevent_rows = [], [], [], [], []
    attr_rows = []         # 이벤트 설명 속성(§4-4)
    for b, (g, base) in batches.items():
        per_dirs = {}      # (method, 센서) → 이벤트별 방향 목록
        times_ns = g[TIME_COL].to_numpy(dtype='datetime64[ns]').astype('int64')
        seg_codes = pd.factorize(g['segment_id'])[0]
        piece = time_pieces(times_ns, seg_codes)
        span = (times_ns[-1] - times_ns[0]) / 1e9
        period = period_map.get(b, '')
        lab = {'TAG_MIN_ns': times_ns}
        row = {BATCH_COL: b, '작업일': date_map.get(b, pd.NaT), 'period': period, 'raw_rows': len(g)}
        sensor_counts = {}     # 센서별 이벤트 수(팀 파일처럼 맨 뒤 열에 붙임)
        for method in ['A1', 'A2']:
            valid_all = np.ones(len(g), bool)
            union = np.zeros(len(g), bool)
            n_events = 0
            per = {}
            for k, s in enumerate(SENSORS):
                x = g[s].astype('float64').to_numpy()
                bl = base[s].to_numpy(dtype='float64')
                valid, cand, score, dev = candidates(method, x, bl, ref[s])
                qual, evs = link_events(times_ns, cand)
                lab[f'{method}_{k}_valid'], lab[f'{method}_{k}_cand'], lab[f'{method}_{k}_qual'] = valid, cand, qual
                per[s] = (valid, qual, evs)
                valid_all &= valid
                union |= qual
                n_events += len(evs)
                sensor_counts[f'{method}_{s.replace(" ", "_")}_event_count'] = len(evs)
                raw_dev = x - bl if method == 'A1' else dev   # 물리 조건에 쓰는 원시 이탈
                ev_dirs = []
                for st, en, dur, npts in evs:
                    real = (times_ns[en] - times_ns[st]) / 1e9
                    assert real == dur - 1, '실제 길이 검사 실패'
                    event_rows.append({
                        'method': method, BATCH_COL: b, 'period': period, 'sensor': s,
                        'start_time': g[TIME_COL].iloc[st], 'end_time': g[TIME_COL].iloc[en],
                        'duration_sec': dur, 'anomaly_sample_count': npts,
                        'max_score': float(np.nanmax(score[st:en + 1])),
                        'max_abs_deviation': float(np.nanmax(np.abs(dev[st:en + 1]))),
                        '실제길이_sec': real,
                    })
                    attr = event_attributes(times_ns, st, en, cand, valid, raw_dev, times_ns[0], span)
                    ev_dirs.append(attr['방향'])
                    attr_rows.append({'method': method, BATCH_COL: b, 'period': period, 'sensor': s,
                                      'start_time': g[TIME_COL].iloc[st], '실제길이_sec': real, **attr})
                per_dirs[(method, s)] = ev_dirs
                e_s = float(piece[valid].sum())
                expo_s = float(piece[qual & valid].sum())
                assert expo_s <= e_s + 1e-6
                sensor_rows.append({
                    BATCH_COL: b, 'period': period, 'method': method, 'sensor': s,
                    '평가가능시간_sec': e_s, '이상노출시간_sec': expo_s,
                    '평가가능기록수': int(valid.sum()), '이상기록수': int((qual & valid).sum()),
                    '이벤트수': len(evs),
                })
            # 팀 방식 6개 센서 전체 집계(②가 ①의 02·04와 같은지 비교용)
            denom = int(valid_all.sum()); anom = int((union & valid_all).sum())
            row.update({f'{method}_valid_sec': denom, f'{method}_anomaly_sec': anom,
                        f'{method}_anomaly_ratio_pct': anom / denom * 100 if denom else np.nan,
                        f'{method}_event_count': n_events})
            row[f'_{method}_union'] = union; row[f'_{method}_valid'] = valid_all
            # 설비 그룹(솔트조·소입로)
            for grp, members in GROUPS.items():
                e_sec, expo, e_n, a_n = group_exposure(piece, [per[s][0] for s in members],
                                                       [per[s][1] for s in members])
                sensor_iv = [(times_ns[st], times_ns[en], s, d)
                             for s in members for (st, en, _, _), d in zip(per[s][2], per_dirs[(method, s)])]
                merged = merge_group_events([(a, z, s) for a, z, s, _ in sensor_iv])
                for st, en, ss in merged:
                    inside = [iv for iv in sensor_iv if st <= iv[0] and iv[1] <= en]
                    # 두 구역 동시: 서로 다른 센서의 이벤트 시간이 실제로 겹침(2초 이하로 붙기만 한 것은 아님)
                    both = any(p[2] != r[2] and p[0] <= r[1] and r[0] <= p[1] for p in inside for r in inside)
                    dirs = {iv[3] for iv in inside}
                    elapsed = (st - times_ns[0]) / 1e9
                    gevent_rows.append({BATCH_COL: b, 'period': period, 'method': method, '설비': grp,
                                        'start_time': pd.Timestamp(st), 'end_time': pd.Timestamp(en),
                                        '실제길이_sec': (en - st) / 1e9,
                                        '포함센서': ', '.join(s for s in members if s in ss),
                                        '두구역이상_동시': both,
                                        '방향': dirs.pop() if len(dirs) == 1 else '혼합',
                                        '작업시작후_경과분': elapsed / 60,
                                        '작업내_위치_pct': elapsed / span * 100 if span > 0 else np.nan,
                                        '시작_시간대': int(pd.Timestamp(st).hour)})
                group_rows.append({BATCH_COL: b, 'period': period, 'method': method, '설비': grp,
                                   '작업기록시간_sec': span, '평가가능시간_sec': e_sec, '이상노출시간_sec': expo,
                                   '평가가능기록수': e_n, '이상기록수': a_n, '그룹이벤트수': len(merged)})
        common = row.pop('_A1_valid') & row.pop('_A2_valid')
        u1, u2 = row.pop('_A1_union'), row.pop('_A2_union')
        overlap = int((u1 & u2 & common).sum()); unionc = int(((u1 | u2) & common).sum())
        row.update({'A1_A2_overlap_sec': overlap, 'A1_A2_union_sec': unionc,
                    'A1_A2_jaccard': overlap / unionc if unionc else np.nan})
        row.update(sensor_counts)
        batch_rows.append(row)
        labels[b] = lab

    print('5) 결과 저장')
    events = pd.DataFrame(event_rows)
    events.to_csv(out_dir / '03_A1_A2_이상이벤트.csv', index=False, encoding='utf-8-sig')
    res = pd.DataFrame(batch_rows).merge(q[[BATCH_COL, '양품수량', '불량수량', '총수량', '불량률(%)']],
                                         on=BATCH_COL, how='left')
    res.to_csv(out_dir / '02_배정번호별_A1_A2_결과.csv', index=False, encoding='utf-8-sig')
    summ = []
    for period, sub in res.groupby('period', sort=False):
        for method in ['A1', 'A2']:
            valid = sub[f'{method}_valid_sec'].sum(); anom = sub[f'{method}_anomaly_sec'].sum()
            summ.append({'period': period, 'method': method, 'batch_count': sub[BATCH_COL].nunique(),
                         'valid_sec': int(valid), 'anomaly_sec': int(anom),
                         'anomaly_ratio_pct': anom / valid * 100 if valid else np.nan,
                         'event_count': int(sub[f'{method}_event_count'].sum()),
                         'median_batch_ratio_pct': sub[f'{method}_anomaly_ratio_pct'].median()})
    pd.DataFrame(summ).to_csv(out_dir / '04_기간별_A1_A2_요약.csv', index=False, encoding='utf-8-sig')
    (events.groupby(['period', 'method', 'sensor'], as_index=False)
     .agg(event_count=('duration_sec', 'size'), total_duration_sec=('duration_sec', 'sum'),
          median_duration_sec=('duration_sec', 'median'), max_duration_sec=('duration_sec', 'max'))
     ).to_csv(out_dir / '05_센서별_이벤트요약.csv', index=False, encoding='utf-8-sig')

    # 새로 더한 결과(실제 시간 기준) — 이름 앞에 "추가_"
    sens = pd.DataFrame(sensor_rows)
    sens.to_csv(out_dir / '추가_작업별_센서별_노출시간.csv', index=False, encoding='utf-8-sig')
    grp = pd.DataFrame(group_rows)
    grp.to_csv(out_dir / '추가_작업별_설비별_노출시간.csv', index=False, encoding='utf-8-sig')
    attr = pd.DataFrame(attr_rows)
    assert len(attr) == len(events)  # 이벤트마다 속성 한 줄
    attr.to_csv(out_dir / '추가_이벤트_속성.csv', index=False, encoding='utf-8-sig')
    gev = pd.DataFrame(gevent_rows)
    gev.to_csv(out_dir / '추가_설비그룹_이벤트.csv', index=False, encoding='utf-8-sig')
    gsum = grp.groupby(['period', 'method', '설비'], sort=False, as_index=False).agg(
        작업수=(BATCH_COL, 'nunique'), 그룹이벤트수=('그룹이벤트수', 'sum'),
        작업기록시간_hr=('작업기록시간_sec', lambda v: v.sum() / 3600),
        평가가능시간_hr=('평가가능시간_sec', lambda v: v.sum() / 3600),
        이상노출시간_sec=('이상노출시간_sec', 'sum'),
        평가가능기록수=('평가가능기록수', 'sum'), 이상기록수=('이상기록수', 'sum'))
    gsum['이상노출시간비율_pct'] = gsum['이상노출시간_sec'] / (gsum['평가가능시간_hr'] * 3600) * 100
    gsum['이상기록비율_pct'] = gsum['이상기록수'] / gsum['평가가능기록수'] * 100
    gsum['관측가능비율_pct'] = gsum['평가가능시간_hr'] / gsum['작업기록시간_hr'] * 100
    gev_len = gev.groupby(['period', 'method', '설비'], sort=False)['실제길이_sec'].agg(
        ['median', 'max']).rename(columns={'median': '그룹이벤트_실제길이_중앙값_sec',
                                           'max': '그룹이벤트_실제길이_최대_sec'}).reset_index()
    gsum = gsum.merge(gev_len, on=['period', 'method', '설비'], how='left')
    gsum.to_csv(out_dir / '추가_기간별_설비별_요약.csv', index=False, encoding='utf-8-sig')
    ssum = sens.groupby(['period', 'method', 'sensor'], sort=False, as_index=False).agg(
        이벤트수=('이벤트수', 'sum'), 평가가능시간_sec=('평가가능시간_sec', 'sum'),
        이상노출시간_sec=('이상노출시간_sec', 'sum'))
    ssum['이상노출시간비율_pct'] = ssum['이상노출시간_sec'] / ssum['평가가능시간_sec'] * 100
    if len(events):
        real = events.groupby(['period', 'method', 'sensor'], sort=False)['실제길이_sec'].agg(
            ['sum', 'median', 'max']).rename(columns={'sum': '실제길이_합_sec', 'median': '실제길이_중앙값_sec',
                                                      'max': '실제길이_최대_sec'}).reset_index()
        ssum = ssum.merge(real, on=['period', 'method', 'sensor'], how='left')
    ssum.to_csv(out_dir / '추가_기간별_센서별_요약.csv', index=False, encoding='utf-8-sig')
    print(f'   걸린 시간 {time.time() - t0:.0f}초')
    return labels


# ════════════════════════════════════════════════════════════════════
# 6. ①과 대조 (계획 §14-3 통과 기준 a0·a1·a·b)
# ════════════════════════════════════════════════════════════════════
def compare_with(ref_dir, out_dir, labels):
    lines, ok = [], True

    def say(text, good):
        nonlocal ok
        ok &= bool(good)
        lines.append(f'[{"통과" if good else "불일치"}] {text}')

    # a0. 기록 단위 valid·cand·qual — 반드시 있어야 할 37개 항목을 정해 두고, 빠진 것도 불일치로 셈(Codex S3-01)
    required = {'TAG_MIN_ns'} | {f'{m}_{k}_{kind}' for m in ['A1', 'A2'] for k in range(len(SENSORS))
                                 for kind in ['valid', 'cand', 'qual']}
    files = {f.stem: f for f in (ref_dir / '검증용_기록라벨').glob('*.npz')}
    say(f'a0 작업 목록: ① {len(files)}개, ② {len(labels)}개, 같은 작업 집합 {set(files) == set(labels)}',
        set(files) == set(labels))
    bad = []
    n_rec = 0
    for b in sorted(set(files) | set(labels)):
        if b not in files or b not in labels:
            bad.append((b, '한쪽에만 있는 작업')); continue
        z, mine = np.load(files[b]), labels[b]
        for side, keys in (('①', set(z.files)), ('②', set(mine))):
            if keys != required:
                bad.append((b, f'{side} 항목 차이: 빠짐 {sorted(required - keys)[:3]}, 남음 {sorted(keys - required)[:3]}'))
        n = len(mine['TAG_MIN_ns'])
        for key in sorted(required & set(z.files) & set(mine)):
            if len(z[key]) != n or len(mine[key]) != n or not np.array_equal(z[key], mine[key]):
                bad.append((b, key))
        n_rec += n
    say(f'a0 기록 단위 라벨(시각·valid·cand·qual × A1·A2 × 6센서): 기록 {n_rec:,}개, 다른 항목 {len(bad)}개 {bad[:5]}',
        not bad)

    def read(p):
        return pd.read_csv(p, encoding='utf-8-sig', dtype={BATCH_COL: str})

    # a1. 기준값
    r1, r2 = read(ref_dir / '01_고정된_기준값.csv'), read(out_dir / '01_고정된_기준값.csv')
    d = (r1.drop(columns='sensor') - r2.drop(columns='sensor')).abs().to_numpy().max()
    say(f'a1 01_고정된_기준값: 최대 차이 {d:.3g} (기준 1e-9 이하)', (r1['sensor'] == r2['sensor']).all() and d <= 1e-9)

    # a. 이벤트 목록
    key = ['method', BATCH_COL, 'sensor', 'start_time']
    e1 = read(ref_dir / '03_A1_A2_이상이벤트.csv').sort_values(key).reset_index(drop=True)
    e2 = read(out_dir / '03_A1_A2_이상이벤트.csv').sort_values(key).reset_index(drop=True)
    same_rows = len(e1) == len(e2)
    exact_cols = ['method', BATCH_COL, 'period', 'sensor', 'start_time', 'end_time', 'duration_sec',
                  'anomaly_sample_count']
    exact = same_rows and all((e1[c] == e2[c]).all() for c in exact_cols)
    near = same_rows and all(((e1[c] - e2[c]).abs() <= 1e-9).all() for c in ['max_score', 'max_abs_deviation'])
    say(f'a 03 이벤트 목록: ① {len(e1)}행, ② {len(e2)}행, 정확히 같은 열 {exact}, 최댓값 열(1e-9) {near}',
        exact and near)

    # b. 02·04·05
    for name, k in [('02_배정번호별_A1_A2_결과.csv', [BATCH_COL]), ('04_기간별_A1_A2_요약.csv', ['period', 'method']),
                    ('05_센서별_이벤트요약.csv', ['period', 'method', 'sensor'])]:
        t1 = read(ref_dir / name).sort_values(k).reset_index(drop=True)
        t2 = read(out_dir / name).sort_values(k).reset_index(drop=True)
        cols_ok = list(t1.columns) == list(t2.columns) and len(t1) == len(t2)
        diff_cells = 0
        if cols_ok:
            for c in t1.columns:
                if pd.api.types.is_numeric_dtype(t1[c]):
                    a, b2 = t1[c].to_numpy(dtype='float64'), t2[c].to_numpy(dtype='float64')
                    diff_cells += int((~(np.isclose(a, b2, rtol=0, atol=1e-9) | (np.isnan(a) & np.isnan(b2)))).sum())
                else:
                    diff_cells += int((t1[c].fillna('') != t2[c].fillna('')).sum())
        say(f'b {name}: 열·행 같음 {cols_ok}, 다른 칸 {diff_cells}개', cols_ok and diff_cells == 0)

    text = f'① 결과 폴더: {ref_dir}\n② 결과 폴더: {out_dir}\n' + '\n'.join(lines) + \
        f'\n종합: {"모두 통과 — ②는 팀 규칙을 바꾸지 않았음" if ok else "불일치 있음 — ①이 기준, 원인 확인 필요"}\n'
    (out_dir / '①과_대조결과.txt').write_text(text, encoding='utf-8')
    print(text)
    return ok


def main():
    self_test()
    ref_dir = None
    if '--compare-with' in sys.argv:
        ref_dir = Path(sys.argv[sys.argv.index('--compare-with') + 1])
        if not ref_dir.is_absolute():
            ref_dir = PROJECT / ref_dir
        if not (ref_dir / '검증용_기록라벨').is_dir():
            print(f'[중단] ① 결과 폴더에 검증용_기록라벨이 없습니다: {ref_dir}')
            sys.exit(1)
    out_dir = PROJECT / 'reports' / '3단계_이상구간' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    out_dir.mkdir(parents=True, exist_ok=False)
    labels = run(out_dir)
    print('결과 폴더:', out_dir)
    if ref_dir is not None and not compare_with(ref_dir, out_dir, labels):
        sys.exit(1)


if __name__ == '__main__':
    main()
