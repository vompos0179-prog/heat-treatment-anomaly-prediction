"""6단계 — 품질 표기 및 최고 불량 사례 시각화.

목적
- 온도 이상과 불량의 관계를 주장하지 않는다.
- 월별 A1 솔트조 이상 지표와 품질 지표를 나란히 표기한다.
- 불량률 상위 4개 작업의 원본 초 단위 솔트조 온도를 A1 기준선/이상 구간과 함께 보여 준다.
- 발표 5-1용 품질 연결 그림은 A1만 남기고, 그룹 n<5는 박스 대신 점으로 표시한다.

입력
- data/raw/열처리_품질데이터.xlsx
- data/raw/data.csv (사례 4작업만 chunk로 읽음)
- reports/3단계_이상구간/<고정폴더>/추가_작업별_설비별_노출시간.csv
- reports/3단계_이상구간/<고정폴더>/추가_기간별_설비별_요약.csv
- reports/3단계_이상구간/<고정폴더>/03_A1_A2_이상이벤트.csv
- stages/6단계_품질표기/6단계_3단계결과기준.txt

출력
- reports/6단계_품질표기/<실행시각>/

중요 표현 원칙
- 상관계수, p값, 추세선 계산/표시 안 함.
- "이상이 많은 달에 불량률도 높았다" 같은 관계 표현 안 함.
- 사례의 이상 구간을 불량 원인으로 해석하지 않음.
"""

from pathlib import Path
from datetime import datetime
import json
import platform
import sys
import time
import warnings

PROJECT = Path(__file__).resolve().parents[2]
STAGE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = STAGE_DIR / '6단계_3단계결과기준.txt'


def safe_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')


def check_python_env():
    """Python·패키지 버전이 권장 환경과 다르면 [주의]만 보여 주고 계속한다(src/env_check.py)."""
    sys.path.insert(0, str(PROJECT))
    from src.env_check import check_python_env as check
    check(PROJECT)


if __name__ == '__main__':
    safe_console()
    check_python_env()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import matplotlib  # noqa: E402
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.dates as mdates  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

# ------------------------------------------------------------------
# 0. 고정 설정
# ------------------------------------------------------------------
TIME_COL = 'TAG_MIN'
BATCH_COL = '배정번호'
RAW_ENCODING = 'cp949'
RAW_CSV = PROJECT / 'data' / 'raw' / 'data.csv'
QUALITY_XLSX = PROJECT / 'data' / 'raw' / '열처리_품질데이터.xlsx'

SALT_SENSORS = ['솔트조 온도 1 Zone', '솔트조 온도 2 Zone']
CASE_BATCHES = ['128795', '116413', '128800', '140920']
ROLL_SEC = 600
MIN_HISTORY = 300
LONG_GAP_SEC = 60
PLOT_BREAK_GAP_SEC = 5
PNG_DPI = 300

EXPECTED_MONTH_COUNTS = {1: 14, 2: 8, 3: 23, 4: 33, 5: 22, 6: 22, 7: 14}
EXPECTED_MONTH_PPM = {1: 135.9, 2: 467.1, 3: 234.3, 4: 487.1, 5: 250.0, 6: 471.4, 7: 270.5}
EXPECTED_A1_SALT_EVENT_TOTAL = 36
EXPECTED_CASES = {
    '128795': ('2022-04-18', 14925, 55, 3685.1),
    '116413': ('2022-02-28', 13712, 34, 2479.6),
    '128800': ('2022-04-18', 29814, 66, 2213.7),
    '140920': ('2022-06-14', 60290, 120, 1990.4),
}

FOOTNOTE_MONTH = '품질은 작업 합계 한 줄로 불량이 생긴 설비·시각을 알 수 없어, 월별 값을 나란히 표기만 함.'
FOOTNOTE_CASE = '불량이 많았던 작업의 온도 기록을 먼저 살펴보는 방법의 예시이며, 그림의 이상 구간을 불량 원인으로 해석하지 않음.'


def find_korean_font():
    """PNG/PDF 모두에서 한글을 글자로 렌더링할 수 있는 폰트를 선택한다."""
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    # Linux 재현 환경처럼 한글 글꼴이 기본 설치되지 않은 경우를 대비한다.
    # requirements.txt의 koreanize-matplotlib이 있으면 나눔고딕을 자동 등록한다.
    if not fonts.intersection({'Malgun Gothic', 'Noto Sans CJK KR', 'NanumGothic',
                               'NanumBarunGothic', 'AppleGothic'}):
        try:
            import koreanize_matplotlib  # noqa: F401
            fonts = {f.name for f in font_manager.fontManager.ttflist}
        except ImportError:
            pass
    for name in ['Malgun Gothic', 'Noto Sans CJK KR', 'NanumGothic', 'NanumBarunGothic', 'AppleGothic']:
        if name in fonts:
            plt.rcParams['font.family'] = name
            break
    plt.rcParams['axes.unicode_minus'] = False
    # PDF에서 글자를 윤곽선이 아니라 TrueType 글꼴로 저장하도록 설정
    plt.rcParams['pdf.fonttype'] = 42
    plt.rcParams['ps.fonttype'] = 42


def read_config():
    if not CONFIG_PATH.is_file():
        raise FileNotFoundError(f'설정 파일이 없습니다: {CONFIG_PATH}')
    value = None
    for raw in CONFIG_PATH.read_text(encoding='utf-8-sig').splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('3단계결과='):
            value = line.split('=', 1)[1].strip()
    if not value:
        raise ValueError('6단계_3단계결과기준.txt에 3단계결과=실행폴더명 을 적어 주세요.')
    if any(c in value for c in ('/', '\\')):
        raise ValueError('3단계결과에는 전체 경로가 아니라 실행 폴더명만 적습니다.')
    return value


def normalize_batch(s):
    return s.astype('string').str.strip().str.replace(r'\.0$', '', regex=True)


def load_quality():
    q = pd.read_excel(QUALITY_XLSX)
    required = {BATCH_COL, '작업일', '총수량', '불량수량'}
    missing = required - set(q.columns)
    if missing:
        raise ValueError(f'품질 파일 필수 열 누락: {sorted(missing)}')
    q[BATCH_COL] = normalize_batch(q[BATCH_COL])
    if q[BATCH_COL].isna().any() or q[BATCH_COL].duplicated().any():
        raise ValueError('품질 배정번호에 결측 또는 중복이 있습니다.')
    q['작업일'] = pd.to_datetime(q['작업일'], errors='raise')
    q['월'] = q['작업일'].dt.month.astype(int)
    q['작업별불량률_ppm'] = np.where(q['총수량'] > 0, q['불량수량'] / q['총수량'] * 1_000_000, np.nan)
    return q


def load_stage3(stage3_dir):
    files = {
        'exposure': stage3_dir / '추가_작업별_설비별_노출시간.csv',
        'period': stage3_dir / '추가_기간별_설비별_요약.csv',
        'events': stage3_dir / '03_A1_A2_이상이벤트.csv',
    }
    missing = [str(p) for p in files.values() if not p.is_file()]
    if missing:
        raise FileNotFoundError('3단계 필수 결과가 없습니다:\n' + '\n'.join(missing))
    exposure = pd.read_csv(files['exposure'], encoding='utf-8-sig')
    period = pd.read_csv(files['period'], encoding='utf-8-sig')
    events = pd.read_csv(files['events'], encoding='utf-8-sig')
    for df in (exposure, events):
        df[BATCH_COL] = normalize_batch(df[BATCH_COL])
    events['start_time'] = pd.to_datetime(events['start_time'], errors='raise')
    events['end_time'] = pd.to_datetime(events['end_time'], errors='raise')
    return exposure, period, events


def first_record_month_for_batches(target_batches=None):
    """작업일 월 vs 원본 첫 기록 월 자기점검용. 전체 원본은 배정번호/시각 두 열만 읽는다."""
    usecols = [TIME_COL, BATCH_COL]
    first = {}
    for ch in pd.read_csv(RAW_CSV, encoding=RAW_ENCODING, usecols=usecols,
                          dtype={BATCH_COL: 'string'}, chunksize=300_000, low_memory=False):
        ch[BATCH_COL] = normalize_batch(ch[BATCH_COL])
        if target_batches is not None:
            ch = ch[ch[BATCH_COL].isin(target_batches)]
        if ch.empty:
            continue
        ch[TIME_COL] = pd.to_datetime(ch[TIME_COL], format='%Y-%m-%d %H:%M:%S', errors='raise')
        part = ch.groupby(BATCH_COL)[TIME_COL].min()
        for b, t in part.items():
            if b not in first or t < first[b]:
                first[b] = t
    return pd.Series(first, name='첫기록시각')


def monthly_table(q, exposure):
    a1_salt = exposure[(exposure['method'] == 'A1') & (exposure['설비'] == '솔트조')].copy()
    needed = {BATCH_COL, '평가가능기록수', '이상기록수', '그룹이벤트수'}
    missing = needed - set(a1_salt.columns)
    if missing:
        raise ValueError(f'추가_작업별_설비별_노출시간.csv 필수 열 누락: {sorted(missing)}')
    if a1_salt[BATCH_COL].duplicated().any():
        raise ValueError('A1 솔트조 작업별 행이 중복됩니다.')

    merged = q[[BATCH_COL, '월', '총수량', '불량수량', '작업별불량률_ppm']].merge(
        a1_salt[[BATCH_COL, '평가가능기록수', '이상기록수', '그룹이벤트수']],
        on=BATCH_COL, how='left', validate='one_to_one'
    )
    if merged[['평가가능기록수', '이상기록수', '그룹이벤트수']].isna().any().any():
        bad = merged.loc[merged['평가가능기록수'].isna(), BATCH_COL].tolist()
        raise ValueError(f'3단계 A1 솔트조 결과가 없는 작업: {bad[:10]}')

    rows = []
    for month in range(1, 8):
        g = merged[merged['월'] == month]
        total = int(g['총수량'].sum())
        defects = int(g['불량수량'].sum())
        valid = int(g['평가가능기록수'].sum())
        anomaly = int(g['이상기록수'].sum())
        events = int(g['그룹이벤트수'].sum())
        rows.append({
            '월': month,
            '기간': ('기준 작성(1~4월)' if month <= 4 else '조건 점검(5월)' if month == 5 else '탐색적·회고적 비교(6~7월)'),
            '작업수': int(g[BATCH_COL].nunique()),
            'A1_솔트조_판정가능기록수': valid,
            'A1_솔트조_이상기록수': anomaly,
            'A1_솔트조_이상비율(%)': (anomaly / valid * 100 if valid else np.nan),
            'A1_솔트조_이상구간수': events,
            '총수량': total,
            '불량수량': defects,
            '월불량률(ppm)': (defects / total * 1_000_000 if total else np.nan),
            '작업별불량률_중앙값(ppm)': float(g['작업별불량률_ppm'].median()),
        })
    return pd.DataFrame(rows), merged


def period_consistency_check(exposure, period):
    """A1 솔트조 기록수·구간수 기간 합이 3단계 기간 요약과 일치하는지 확인한다."""
    a = exposure[(exposure['method'] == 'A1') & (exposure['설비'] == '솔트조')]
    b = period[(period['method'] == 'A1') & (period['설비'] == '솔트조')]
    sums = a.groupby('period')[['평가가능기록수', '이상기록수', '그룹이벤트수']].sum().sort_index()
    ref = b.set_index('period')[['평가가능기록수', '이상기록수', '그룹이벤트수']].astype('int64').sort_index()
    if not sums.index.equals(ref.index) or not sums.astype('int64').equals(ref):
        raise AssertionError('A1 솔트조 기간 합이 3단계 추가_기간별_설비별_요약.csv와 다릅니다.')
    return sums


def plot_monthly(monthly, out):
    find_korean_font()
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12.5, 9.0), sharex=True,
                                   gridspec_kw={'height_ratios': [1, 1.05]})
    months = monthly['월'].to_numpy()

    # 기간 배경: 1~4월 기준작성 / 5월 조건점검 / 6~7월 탐색·회고
    for ax in (ax1, ax2):
        ax.axvspan(0.5, 4.5, alpha=0.07, zorder=0)
        ax.axvspan(4.5, 5.5, alpha=0.10, zorder=0)
        # 6월만이 아니라 6~7월 전체에 같은 빗금
        ax.axvspan(5.5, 7.5, facecolor='none', edgecolor='purple', hatch='///',
                   linewidth=0.0, alpha=0.28, zorder=0)

    bars1 = ax1.bar(months, monthly['A1_솔트조_이상비율(%)'], width=0.62)
    ax1.set_ylabel('A1 솔트조 이상비율 (%)')
    ax1.set_title('월별 A1 솔트조 이상지표와 품질 지표 — 관계를 주장하지 않고 나란히 표기')
    ax1.grid(axis='y', alpha=0.20)
    ymax = float(monthly['A1_솔트조_이상비율(%)'].max())
    ax1.set_ylim(0, max(0.05, ymax * 1.24))

    # 모든 달에 구간 수를 같은 형식으로 표시. 합계는 self-check에서 36인지 확인함.
    for bar, ratio, n_event in zip(bars1, monthly['A1_솔트조_이상비율(%)'], monthly['A1_솔트조_이상구간수']):
        y = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2, y + max(0.006, ymax*0.025),
                 f'{ratio:.3f}%\n({int(n_event)}구간)', ha='center', va='bottom', fontsize=9)

    bars2 = ax2.bar(months, monthly['월불량률(ppm)'], width=0.62, label='월 불량률(ppm)')
    ax2.scatter(months, monthly['작업별불량률_중앙값(ppm)'], marker='o', s=45,
                label='작업별 불량률 중앙값(ppm)', zorder=4)
    ax2.set_ylabel('불량률 (ppm)')
    ax2.set_xlabel('월')
    ax2.set_xticks(months, [f'{m}월' for m in months])
    ax2.grid(axis='y', alpha=0.20)
    ax2.text(7, ax2.get_ylim()[1] * 0.93, '7월: 19일까지', ha='center', va='top', fontsize=9)

    period_handles = [
        Patch(alpha=0.12, label='1~4월 기준 작성'),
        Patch(alpha=0.18, label='5월 조건 점검'),
        Patch(facecolor='none', edgecolor='purple', hatch='///', label='빗금 = 6~7월 탐색적·회고적 비교 기간'),
    ]
    ax1.legend(handles=period_handles, loc='upper left', fontsize=9)
    ax2.legend(loc='upper left', fontsize=9)
    fig.text(0.5, 0.018, FOOTNOTE_MONTH, ha='center', fontsize=9)
    fig.tight_layout(rect=(0.02, 0.045, 0.98, 0.98))
    fig.savefig(out / '02_월별_이상지표_불량률.png', dpi=PNG_DPI, bbox_inches='tight')
    fig.savefig(out / '02_월별_이상지표_불량률.pdf', bbox_inches='tight')
    plt.close(fig)


def load_case_raw():
    parts = []
    usecols = [TIME_COL, BATCH_COL] + SALT_SENSORS
    dtype = {BATCH_COL: 'string', **{s: 'float32' for s in SALT_SENSORS}}
    for ch in pd.read_csv(RAW_CSV, encoding=RAW_ENCODING, usecols=usecols, dtype=dtype,
                          chunksize=250_000, low_memory=False):
        ch[BATCH_COL] = normalize_batch(ch[BATCH_COL])
        x = ch[ch[BATCH_COL].isin(CASE_BATCHES)].copy()
        if not x.empty:
            parts.append(x)
    if not parts:
        raise ValueError('사례 작업 원본 기록을 찾지 못했습니다.')
    raw = pd.concat(parts, ignore_index=True)
    raw[TIME_COL] = pd.to_datetime(raw[TIME_COL], format='%Y-%m-%d %H:%M:%S', errors='raise')
    return raw.sort_values([BATCH_COL, TIME_COL]).reset_index(drop=True)


def rolling_baseline_for_case(g):
    """A1 그림용 직전 10분 중앙값. 60초 초과 공백에서 기준 창을 새로 시작한다."""
    g = g.sort_values(TIME_COL).reset_index(drop=True).copy()
    gap = g[TIME_COL].diff().dt.total_seconds()
    g['_segment'] = (gap.isna() | (gap > LONG_GAP_SEC)).cumsum()
    out = pd.DataFrame(index=g.index, columns=SALT_SENSORS, dtype='float64')
    for _, idx in g.groupby('_segment', sort=False).groups.items():
        sub = g.loc[idx, [TIME_COL] + SALT_SENSORS].set_index(TIME_COL)
        rb = sub[SALT_SENSORS].rolling(f'{ROLL_SEC}s', closed='left', min_periods=MIN_HISTORY).median()
        out.loc[idx, SALT_SENSORS] = rb.to_numpy()
    return g, out


def plot_broken_line(ax, times, values, label, color, linewidth=0.75, linestyle='-'):
    """기록 공백이 5초를 넘으면 선을 끊되, 조각마다 같은 색을 유지한다."""
    times = pd.Series(times).reset_index(drop=True)
    values = pd.Series(values).reset_index(drop=True)
    breaks = times.diff().dt.total_seconds().gt(PLOT_BREAK_GAP_SEC).fillna(False)
    group = breaks.cumsum()
    first = True
    for _, idx in group.groupby(group).groups.items():
        ax.plot(times.iloc[idx], values.iloc[idx], color=color,
                linewidth=linewidth, linestyle=linestyle,
                label=label if first else None)
        first = False


def case_events(events, batch, sensor):
    return events[(events['method'] == 'A1') & (events[BATCH_COL] == batch) & (events['sensor'] == sensor)].copy()


def draw_case_on_axes(axes, batch, g, base, qrow, events, compact=False):
    ppm = float(qrow['작업별불량률_ppm'])
    title = (f"작업 {batch} · {qrow['작업일']:%Y-%m-%d} · 총수량 {int(qrow['총수량']):,} · "
             f"불량수량 {int(qrow['불량수량']):,} · {ppm:,.1f} ppm")
    axes[0].set_title(title, fontsize=10.5 if compact else 12)

    total_events = 0
    for ax, sensor in zip(axes, SALT_SENSORS):
        plot_broken_line(
            ax, g[TIME_COL], g[sensor], '원본 초 단위 온도',
            color='#2563EB', linewidth=0.72,
        )
        plot_broken_line(
            ax, g[TIME_COL], base[sensor], 'A1 기준선(직전 10분 중앙값)',
            color='#F59E0B', linewidth=1.05, linestyle='--',
        )
        ev = case_events(events, batch, sensor)
        total_events += len(ev)
        for _, r in ev.iterrows():
            ax.axvspan(
                r['start_time'], r['end_time'], color='#DC2626', alpha=0.18,
                label='A1 이상 구간' if _ == ev.index[0] else None,
            )
        ax.set_ylabel(sensor.replace('솔트조 온도 ', 'Zone ').replace(' Zone', '') + ' (℃)', fontsize=8.5 if compact else 9.5)
        ax.grid(alpha=0.18)
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
        if not compact:
            ax.legend(loc='best', fontsize=8)

    if total_events == 0:
        axes[0].text(0.5, 0.84, 'A1 이상 구간 없음', transform=axes[0].transAxes,
                     ha='center', va='center', fontsize=11, fontweight='bold')
    if batch == '140920':
        axes[0].text(0.99, 0.95, '6~7월 탐색적·회고적 비교', transform=axes[0].transAxes,
                     ha='right', va='top', fontsize=9, fontweight='bold')
        # 76초 구간은 전체 작업 시간에 비해 매우 짧아 음영만으로 놓치기 쉽다.
        # 실제 이벤트가 있는 Zone 축에 화살표와 시간을 함께 표시한다.
        all_ev = events[
            (events['method'] == 'A1')
            & (events[BATCH_COL] == batch)
            & events['sensor'].isin(SALT_SENSORS)
        ].sort_values('start_time')
        if not all_ev.empty:
            first_ev = all_ev.iloc[0]
            sensor_index = SALT_SENSORS.index(first_ev['sensor'])
            event_ax = axes[sensor_index]
            middle = first_ev['start_time'] + (first_ev['end_time'] - first_ev['start_time']) / 2
            valid_y = g[first_ev['sensor']].dropna()
            y_target = float(valid_y.median()) if len(valid_y) else 0.0
            seconds = int(round(float(first_ev['실제길이_sec'])))
            event_ax.annotate(
                f'A1 이상 {seconds}초',
                xy=(middle, y_target), xycoords='data',
                xytext=(0.70, 0.78), textcoords='axes fraction',
                arrowprops={'arrowstyle': '->', 'color': '#B91C1C', 'lw': 1.4},
                color='#991B1B', fontsize=9 if compact else 10,
                fontweight='bold', ha='center', va='center',
                bbox={'boxstyle': 'round,pad=0.25', 'fc': 'white', 'ec': '#FCA5A5', 'alpha': 0.92},
            )
    axes[-1].set_xlabel('시간')


def plot_cases(q, events, out):
    raw = load_case_raw()
    qidx = q.set_index(BATCH_COL)
    case_summary = []
    prepared = {}

    for batch in CASE_BATCHES:
        g0 = raw[raw[BATCH_COL] == batch].copy()
        if g0.empty:
            raise AssertionError(f'사례 작업 {batch} 원본 기록 없음')
        g, base = rolling_baseline_for_case(g0)
        prepared[batch] = (g, base)
        row = qidx.loc[batch]
        ev = events[(events['method'] == 'A1') & (events[BATCH_COL] == batch) & events['sensor'].isin(SALT_SENSORS)]
        case_summary.append({
            BATCH_COL: batch,
            '작업일': row['작업일'].date().isoformat(),
            '총수량': int(row['총수량']),
            '불량수량': int(row['불량수량']),
            '불량률(ppm)': float(row['작업별불량률_ppm']),
            'A1_솔트조_이상구간수': int(len(ev)),
            'A1_솔트조_총이상시간_sec': float(ev['실제길이_sec'].sum()) if len(ev) else 0.0,
            'A1_솔트조_최대이상점수': float(ev['max_score'].max()) if len(ev) else np.nan,
        })

        fig, axes = plt.subplots(2, 1, figsize=(14, 7.5), sharex=True)
        draw_case_on_axes(axes, batch, g, base, row, events, compact=False)
        fig.text(0.5, 0.018, FOOTNOTE_CASE, ha='center', fontsize=9)
        fig.tight_layout(rect=(0.02, 0.045, 0.98, 0.98))
        fig.savefig(out / f'03_사례_{batch}.png', dpi=PNG_DPI, bbox_inches='tight')
        plt.close(fig)

    # 발표용 2x2 묶음: 각 작업마다 Zone1/Zone2 두 축을 유지
    fig = plt.figure(figsize=(18, 12.5))
    outer = fig.add_gridspec(2, 2, hspace=0.28, wspace=0.16)
    for pos, batch in enumerate(CASE_BATCHES):
        r, c = divmod(pos, 2)
        inner = outer[r, c].subgridspec(2, 1, hspace=0.06)
        ax_top = fig.add_subplot(inner[0, 0])
        ax_bot = fig.add_subplot(inner[1, 0], sharex=ax_top)
        plt.setp(ax_top.get_xticklabels(), visible=False)
        row = qidx.loc[batch]
        g, base = prepared[batch]
        draw_case_on_axes([ax_top, ax_bot], batch, g, base, row, events, compact=True)
    fig.suptitle('최고 불량 4사례 — 솔트조 원본 온도와 A1 기준/이상 구간', fontsize=15, y=0.995)
    legend_items = [
        Line2D([0], [0], color='#2563EB', lw=1.3, label='원본 초 단위 온도'),
        Line2D([0], [0], color='#F59E0B', lw=1.4, ls='--', label='A1 기준선(직전 10분 중앙값)'),
        Patch(facecolor='#DC2626', alpha=0.18, label='A1 이상 구간'),
    ]
    fig.legend(handles=legend_items, loc='upper center', bbox_to_anchor=(0.5, 0.972),
               ncol=3, frameon=False, fontsize=9)
    fig.text(0.5, 0.031, '주의: 세로축 범위가 그림마다 다름', ha='center',
             fontsize=9.5, fontweight='bold', color='#7F1D1D')
    fig.text(0.5, 0.012, FOOTNOTE_CASE, ha='center', fontsize=9)
    fig.savefig(out / '03_사례_4개_묶음.png', dpi=PNG_DPI, bbox_inches='tight')
    plt.close(fig)

    return pd.DataFrame(case_summary)


def plot_quality_link_a1(q, merged, out):
    """발표 5-1용. 6~7월 A1 솔트조 이상 있음/없음만 표시.

    n >= 5 그룹은 Boxplot, n < 5 그룹은 개별 점만 표시한다.
    상관계수·p값·추세선은 계산하지 않는다.
    """
    m = merged[merged['월'].isin([6, 7])].copy()
    m['이상발생'] = np.where(m['그룹이벤트수'] > 0, '이상 있음', '이상 없음')
    order = ['이상 없음', '이상 있음']

    fig, ax = plt.subplots(figsize=(8.6, 6.2))
    rng = np.random.default_rng(42)
    summary = []
    for i, label in enumerate(order, start=1):
        vals = m.loc[m['이상발생'] == label, '작업별불량률_ppm'].dropna().to_numpy(float)
        n = len(vals)
        med = float(np.median(vals)) if n else np.nan
        summary.append({'구분': label, '작업수': n, '중앙값_ppm': med, '평균_ppm': float(np.mean(vals)) if n else np.nan})
        if n >= 5:
            # 이상치는 아래 색 점으로 이미 한 번 표시하므로 빈 원을 따로 그리지 않는다.
            ax.boxplot([vals], positions=[i], widths=0.48, patch_artist=False, showfliers=False)
            # 원자료 위치도 약하게 보여 표본 수를 숨기지 않음
            jitter = rng.uniform(-0.08, 0.08, size=n)
            ax.scatter(np.full(n, i) + jitter, vals, s=23, alpha=0.55, zorder=3)
        else:
            jitter = rng.uniform(-0.08, 0.08, size=n)
            ax.scatter(np.full(n, i) + jitter, vals, s=48, zorder=3)
            if n:
                ax.hlines(med, i-0.16, i+0.16, linewidth=1.5)

    labels = []
    for row in summary:
        labels.append(f"{row['구분']}\nn={row['작업수']}\n중앙값 {row['중앙값_ppm']:.1f} ppm")
    ax.set_xticks([1, 2], labels)
    ax.set_ylabel('작업별 불량률 (ppm)')
    ax.set_title('6~7월 A1 솔트조 조사 후보 유무에 따른 작업 불량률 분포')
    ax.grid(axis='y', alpha=0.20)
    ax.text(0.02, 0.98, '5작업 미만 그룹은 Boxplot 대신 개별 점으로 표시', transform=ax.transAxes,
            ha='left', va='top', fontsize=9)
    fig.text(0.5, 0.018,
             '품질은 작업 합계 한 줄이므로 이 그림만으로 이상 구간을 불량 원인으로 해석하지 않음.',
             ha='center', fontsize=9)
    fig.tight_layout(rect=(0.02, 0.05, 0.98, 0.98))
    fig.savefig(out / '00_발표5-1_A1_이상유무_불량률.png', dpi=PNG_DPI, bbox_inches='tight')
    fig.savefig(out / '00_발표5-1_A1_이상유무_불량률.pdf', bbox_inches='tight')
    plt.close(fig)
    return pd.DataFrame(summary)


def self_checks(q, monthly, exposure, period, events):
    checks = []

    counts = monthly.set_index('월')['작업수'].astype(int).to_dict()
    ok = counts == EXPECTED_MONTH_COUNTS
    checks.append(('월별 작업 수 = 14/8/23/33/22/22/14, 합계 136', ok, str(counts)))

    got_ppm = monthly.set_index('월')['월불량률(ppm)'].round(1).to_dict()
    ok = got_ppm == EXPECTED_MONTH_PPM
    checks.append(('월불량률(ppm) 기준값 일치', ok, str(got_ppm)))

    event_total = int(monthly['A1_솔트조_이상구간수'].sum())
    checks.append((f'A1 솔트조 이상구간수 월 합계 = {EXPECTED_A1_SALT_EVENT_TOTAL}',
                   event_total == EXPECTED_A1_SALT_EVENT_TOTAL, str(event_total)))

    try:
        period_sums = period_consistency_check(exposure, period)
        checks.append(('A1 솔트조 기간별 기록수/이상수/구간수가 3단계 기간요약과 일치', True,
                       period_sums.to_string().replace('\n', ' | ')))
    except Exception as e:
        checks.append(('A1 솔트조 기간별 기록수/이상수/구간수가 3단계 기간요약과 일치', False, str(e)))

    qidx = q.set_index(BATCH_COL)
    case_ok = True
    detail = []
    for b, (date, total, defect, ppm) in EXPECTED_CASES.items():
        if b not in qidx.index:
            case_ok = False
            detail.append(f'{b}: 없음')
            continue
        r = qidx.loc[b]
        got = (r['작업일'].date().isoformat(), int(r['총수량']), int(r['불량수량']), round(float(r['작업별불량률_ppm']), 1))
        exp = (date, total, defect, ppm)
        if got != exp:
            case_ok = False
        detail.append(f'{b}:{got}')
    checks.append(('최고 불량 4사례 작업번호·작업일·수량·ppm 일치', case_ok, '; '.join(detail)))

    # 작업일 월과 첫 기록 월 비교: 반드시 124532 한 건만 달라야 함
    first = first_record_month_for_batches(set(q[BATCH_COL]))
    t = q[[BATCH_COL, '월']].copy().set_index(BATCH_COL)
    t['첫기록월'] = first.dt.month
    mismatch = t[t['월'] != t['첫기록월']]
    mismatch_ids = mismatch.index.tolist()
    ok = mismatch_ids == ['124532'] or set(mismatch_ids) == {'124532'}
    checks.append(('작업일 월 기준, 첫 기록 월과 다른 작업 1개(124532)', ok,
                   mismatch.reset_index().to_dict(orient='records').__repr__()))

    return checks


def write_readme_copy(out, stage3_name, monthly, quality_link, checks):
    """결과 폴더에도 실행 당시 자기점검 요약을 남긴다."""
    lines = [
        '# 6단계 품질 표기 — 실행 결과 요약', '',
        f'- 사용한 3단계 결과: `{stage3_name}`',
        '- 분석 원칙: 온도 이상과 불량의 관계를 주장하지 않고 월별 표기와 사례 소개까지만 수행',
        '- 월별 기준: **품질 작업일 월**',
        '- 작업일 월 기준, 첫 기록 월과 다른 작업 1개(124532)', '',
        '## 자기 점검',
    ]
    for title, ok, detail in checks:
        lines.append(f"- [{'x' if ok else ' '}] {title}")
        lines.append(f'  - 확인값: {detail}')
    lines += ['', '## 발표 5-1 A1 품질 연결 요약', '```text\n' + quality_link.to_string(index=False) + '\n```', '',
              '## 월별 표', '```text\n' + monthly.to_string(index=False) + '\n```', '',
              f'> {FOOTNOTE_MONTH}', '', f'> {FOOTNOTE_CASE}', '']
    (out / 'README_실행결과.md').write_text('\n'.join(lines), encoding='utf-8-sig')


def main():
    t0 = time.time()
    find_korean_font()
    stage3_name = read_config()
    stage3_dir = PROJECT / 'reports' / '3단계_이상구간' / stage3_name
    if not stage3_dir.is_dir():
        raise FileNotFoundError(f'설정한 3단계 결과 폴더가 없습니다: {stage3_dir}')

    out = PROJECT / 'reports' / '6단계_품질표기' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    out.mkdir(parents=True, exist_ok=False)
    try:
        print('1) 품질/3단계 결과 읽기')
        q = load_quality()
        exposure, period, events = load_stage3(stage3_dir)

        print('2) 월별 표 계산')
        monthly, merged = monthly_table(q, exposure)
        monthly.to_csv(out / '01_월별_이상지표_불량률.csv', index=False, encoding='utf-8-sig')

        print('3) 자기 점검')
        checks = self_checks(q, monthly, exposure, period, events)
        failed = [(a, c) for a, ok, c in checks if not ok]
        check_text = '\n'.join([f"[{'PASS' if ok else 'FAIL'}] {a}\n  {c}" for a, ok, c in checks])
        (out / '자기점검.txt').write_text(check_text, encoding='utf-8-sig')
        if failed:
            raise AssertionError('자기 점검 실패:\n' + '\n'.join(f'- {a}: {c}' for a, c in failed))

        print('4) 발표 5-1 A1 품질 연결 그림')
        quality_link = plot_quality_link_a1(q, merged, out)
        quality_link.to_csv(out / '00_발표5-1_A1_이상유무_요약.csv', index=False, encoding='utf-8-sig')

        print('5) 월별 2단 그림')
        plot_monthly(monthly, out)

        print('6) 최고 불량 4사례 그림')
        case_summary = plot_cases(q, events, out)
        case_summary.to_csv(out / '04_사례_요약.csv', index=False, encoding='utf-8-sig')

        # 사례 그림 생성 후 값 재검사
        if set(case_summary[BATCH_COL]) != set(CASE_BATCHES):
            raise AssertionError('사례 요약에 4작업이 모두 들어가지 않았습니다.')

        elapsed = time.time() - t0
        info = {
            '실행시각': datetime.now().isoformat(timespec='seconds'),
            'Python': sys.version.split()[0],
            'platform': platform.platform(),
            'pandas': pd.__version__,
            'numpy': np.__version__,
            'matplotlib': matplotlib.__version__,
            '사용한_3단계_결과': stage3_name,
            '품질파일': str(QUALITY_XLSX.relative_to(PROJECT)),
            '원본파일': str(RAW_CSV.relative_to(PROJECT)),
            'PNG_DPI': PNG_DPI,
            '실행시간_sec': round(elapsed, 2),
            '표현원칙': '상관계수/p값/추세선 미사용, 인과관계 주장 안 함',
        }
        (out / '실행정보.txt').write_text('\n'.join(f'{k}={v}' for k, v in info.items()), encoding='utf-8-sig')
        write_readme_copy(out, stage3_name, monthly, quality_link, checks)
        (out / '완료.txt').write_text('모든 자기 점검 통과 후 정상 완료\n', encoding='utf-8-sig')
        print('완료:', out)
    except Exception as e:
        (out / '오류.txt').write_text(f'{type(e).__name__}: {e}\n', encoding='utf-8-sig')
        print('[실패]', e)
        print('오류 기록:', out / '오류.txt')
        raise


if __name__ == '__main__':
    main()
