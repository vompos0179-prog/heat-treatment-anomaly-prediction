r"""3단계 보충 — A1·A2를 "두 방법 모두 판정 가능한 같은 기록"에서 비교하는 표.

왜 필요한가
  3단계 요약(`추가_기간별_설비별_요약.csv`)은 방법마다 자기 판정 가능 시간을 분모로 씁니다.
  A2는 현재 온도만 있으면 판정하고, A1은 직전 10분 기록 300개가 필요하므로 분모가 다릅니다
  (예: 6~7월 솔트조 A1 770,509개 / A2 781,309개 기록). 문제정의서는 "두 방법이 함께 판정할 수 있는
  기록에서 비교"하라고 했으므로, 같은 분모로 다시 센 표를 따로 만듭니다(분석 계획 §15-6 ①, Codex R11-02).

무엇을 하는가 (판정은 바꾸지 않음)
  1. 3단계 ① 재현본이 저장한 기록별 판정(`검증용_기록라벨/작업번호.npz`)을 읽습니다.
     원본 data.csv는 다시 읽지 않습니다. 그래서 몇 초면 끝납니다.
  2. 설비(솔트조 2개 / 소입로 4개)마다
       A1 판정 가능 = 그 설비의 모든 센서가 A1로 판정 가능
       A2 판정 가능 = 그 설비의 모든 센서가 A2로 판정 가능
       공통 범위    = 둘 다 판정 가능한 기록
     공통 범위 안에서 A1 양성·A2 양성·둘 다·한쪽만인 기록 수와 시간을 셉니다.
     양성 = 그 설비 센서 중 하나라도 60초 이상 선정 구간(qual)에 속한 기록.
  3. 시간은 3단계와 같은 "시간 조각"으로 셉니다: 다음 기록까지 5초 이하인 간격만, 앞 기록의 판정으로.
  4. 자기 점검: 방법별 분모·노출 시간을 다시 계산해 3단계 ② 결과의 `추가_기간별_설비별_요약.csv`와
     같은지 확인합니다. 다르면 결과를 완료 처리하지 않습니다.

실행(프로젝트 맨 위 폴더에서):
  .\.venv\Scripts\python.exe "stages/3단계_이상구간/3단계_공통범위_비교.py"
  다른 결과 폴더를 쓰려면(폴더 이름만):
  ... --ref1 (①결과 폴더 이름) --ref2 (②결과 폴더 이름)

출력: reports/3단계_공통범위_비교/(실행시각)/
  01_기간별_설비별_A1A2_공통범위비교.csv   주 결과
  02_작업별_설비별_A1A2_공통범위비교.csv   작업별 같은 표
  03_기존요약과_대조.txt                   자기 점검 결과
  실행정보.txt, 완료.txt(모두 통과했을 때만)
"""
from pathlib import Path
from datetime import datetime
import argparse
import hashlib
import sys

PROJECT = Path(__file__).resolve().parents[2]

# 기본으로 쓰는 3단계 결과(10/7 실행, 두 결과가 서로 같은 것을 확인한 폴더)
DEFAULT_REF1 = '20261007_131646_348915'   # ① 재현본 — 기록별 판정 npz가 있는 폴더
DEFAULT_REF2 = '20261007_134935_263964'   # ② 정리본 — 자기 점검에 쓰는 기존 요약


def check_python_env():
    """Python·패키지 버전이 권장 환경과 다르면 [주의]만 보여 주고 계속합니다(src/env_check.py)."""
    sys.path.insert(0, str(PROJECT))
    from src.env_check import check_python_env as check
    check(PROJECT)


if __name__ == '__main__':
    for stream in (sys.stdout, sys.stderr):  # cp949 화면에서도 특수문자 때문에 멈추지 않게
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')
    check_python_env()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(PROJECT))
from src.data_contract import BATCH_COL, load_quality  # noqa: E402

# ① 재현본과 같은 센서 순서(npz 키의 숫자 = 이 목록의 위치)
SENSORS = ['소입로 온도 1 Zone', '소입로 온도 2 Zone', '소입로 온도 3 Zone', '소입로 온도 4 Zone',
           '솔트조 온도 1 Zone', '솔트조 온도 2 Zone']
GROUPS = {'솔트조': [4, 5], '소입로': [0, 1, 2, 3]}
PIECE_MAX_GAP = 5   # 시간 조각: 다음 기록까지 5초 이하만 시간으로 셈(3단계와 같음)
# 공통 모듈의 기간 이름 → 3단계 결과의 기간 이름(3단계와 같은 품질 작업일 월 기준)
TEAM_PERIOD = {'학습(1~4월)': '기준작성(1~4월)', '조정(5월)': '조정(5월)', '후속적용(6~7월)': '후속비교(6~7월)'}
PERIOD_ORDER = ['기준작성(1~4월)', '조정(5월)', '후속비교(6~7월)']


def time_pieces(times_ns):
    """기록 i의 시간 조각 = 다음 기록까지 간격(5초 이하일 때만), 마지막 기록은 0초.

    3단계는 같은 연속구간 안에서만 조각을 세는데, 연속구간 경계는 60초 넘는 공백이라
    5초 이하 조건에 이미 걸러집니다. 그래서 시각만으로 3단계와 같은 값이 나옵니다.
    """
    piece = np.zeros(len(times_ns), dtype='float64')
    if len(times_ns) > 1:
        gap = np.diff(times_ns) / 1e9
        piece[:-1] = np.where(gap <= PIECE_MAX_GAP, gap, 0.0)
    return piece


def one_batch(z):
    """작업 하나의 설비별 집계. z = npz(기록별 판정)."""
    t = z['TAG_MIN_ns']
    piece = time_pieces(t)
    rows = {}
    for grp, ks in GROUPS.items():
        v1 = np.logical_and.reduce([z[f'A1_{k}_valid'] for k in ks])   # A1 판정 가능(설비 전 센서)
        v2 = np.logical_and.reduce([z[f'A2_{k}_valid'] for k in ks])
        q1 = np.logical_or.reduce([z[f'A1_{k}_qual'] for k in ks])     # A1 양성(센서 하나라도)
        q2 = np.logical_or.reduce([z[f'A2_{k}_qual'] for k in ks])
        c = v1 & v2                                                    # 공통 범위
        cnt = lambda m: int(m.sum())                                   # noqa: E731
        sec = lambda m: float(piece[m].sum())                          # noqa: E731
        rows[grp] = {
            # 기존 방식(방법별 자기 범위) — 3단계 요약과 대조용
            'A1_자기범위_기록수': cnt(v1), 'A1_자기범위_시간_sec': sec(v1),
            'A1_자기범위_양성기록수': cnt(q1 & v1), 'A1_자기범위_양성시간_sec': sec(q1 & v1),
            'A2_자기범위_기록수': cnt(v2), 'A2_자기범위_시간_sec': sec(v2),
            'A2_자기범위_양성기록수': cnt(q2 & v2), 'A2_자기범위_양성시간_sec': sec(q2 & v2),
            # 공통 범위
            '공통범위_기록수': cnt(c), '공통범위_시간_sec': sec(c),
            'A1양성_기록수': cnt(q1 & c), 'A1양성_시간_sec': sec(q1 & c),
            'A2양성_기록수': cnt(q2 & c), 'A2양성_시간_sec': sec(q2 & c),
            '둘다양성_기록수': cnt(q1 & q2 & c), '둘다양성_시간_sec': sec(q1 & q2 & c),
            'A1만_기록수': cnt(q1 & ~q2 & c), 'A1만_시간_sec': sec(q1 & ~q2 & c),
            'A2만_기록수': cnt(q2 & ~q1 & c), 'A2만_시간_sec': sec(q2 & ~q1 & c),
            # 공통 범위 밖으로 빠진 것(판정을 정상으로 바꾸지 않고 따로 셈)
            'A1만판정가능_제외기록수': cnt(v1 & ~v2), 'A2만판정가능_제외기록수': cnt(v2 & ~v1),
            'A2만판정가능_제외시간_sec': sec(v2 & ~v1),
            '제외범위_A2양성기록수': cnt(q2 & v2 & ~v1), '제외범위_A1양성기록수': cnt(q1 & v1 & ~v2),
        }
    return rows


def add_ratios(df):
    """공통 범위 시간에 대한 비율(%)과 두 방법 겹침 정도."""
    base = df['공통범위_시간_sec'].replace(0, np.nan)
    for k in ['A1양성', 'A2양성', '둘다양성', 'A1만', 'A2만']:
        df[f'{k}_시간비율_pct'] = df[f'{k}_시간_sec'] / base * 100
    union = df['둘다양성_기록수'] + df['A1만_기록수'] + df['A2만_기록수']
    df['겹침정도_자카드'] = df['둘다양성_기록수'] / union.replace(0, np.nan)   # 둘 다 ÷ 하나라도
    df['A1자기범위_시간비율_pct'] = df['A1_자기범위_양성시간_sec'] / df['A1_자기범위_시간_sec'].replace(0, np.nan) * 100
    df['A2자기범위_시간비율_pct'] = df['A2_자기범위_양성시간_sec'] / df['A2_자기범위_시간_sec'].replace(0, np.nan) * 100
    return df


def self_check(period_tab, ref2_dir):
    """방법별 자기 범위 값이 3단계 ② 요약과 같은지 확인합니다."""
    old = pd.read_csv(ref2_dir / '추가_기간별_설비별_요약.csv', encoding='utf-8-sig')
    lines, ok = [], True
    for _, r in old.iterrows():
        m = r['method']
        mine = period_tab.loc[period_tab['period'].eq(r['period']) & period_tab['설비'].eq(r['설비'])]
        if len(mine) != 1:
            lines.append(f"[불일치] {r['period']} {m} {r['설비']}: 새 표에 행이 없음")
            ok = False
            continue
        mine = mine.iloc[0]
        checks = [('평가가능기록수', mine[f'{m}_자기범위_기록수'], r['평가가능기록수']),
                  ('이상기록수', mine[f'{m}_자기범위_양성기록수'], r['이상기록수']),
                  ('평가가능시간_sec', mine[f'{m}_자기범위_시간_sec'], r['평가가능시간_hr'] * 3600),
                  ('이상노출시간_sec', mine[f'{m}_자기범위_양성시간_sec'], r['이상노출시간_sec'])]
        for name, new, ref in checks:
            good = abs(float(new) - float(ref)) <= 1e-6 * max(1.0, abs(float(ref)))
            ok &= good
            lines.append(f"[{'통과' if good else '불일치'}] {r['period']} {m} {r['설비']} {name}: 새 {new:,.3f} / 기존 {float(ref):,.3f}")
    return ok, lines


def main():
    ap = argparse.ArgumentParser(description='3단계 A1·A2 공통 범위 비교표')
    ap.add_argument('--ref1', default=DEFAULT_REF1, help='① 재현본 결과 폴더 이름(reports/3단계_이상구간_팀코드재현/ 아래)')
    ap.add_argument('--ref2', default=DEFAULT_REF2, help='② 정리본 결과 폴더 이름(reports/3단계_이상구간/ 아래)')
    args = ap.parse_args()
    for name in (args.ref1, args.ref2):
        if any(ch in name for ch in '/\\:'):
            sys.exit(f'[중단] 폴더 이름만 적어 주세요(전체 경로 아님): {name}')
    ref1 = PROJECT / 'reports' / '3단계_이상구간_팀코드재현' / args.ref1
    ref2 = PROJECT / 'reports' / '3단계_이상구간' / args.ref2
    label_dir = ref1 / '검증용_기록라벨'
    if not label_dir.is_dir():
        sys.exit(f'[중단] 기록별 판정 폴더가 없습니다: {label_dir}\n  ① 재현본을 저장 켬으로 실행한 폴더여야 합니다.')
    if not (ref2 / '추가_기간별_설비별_요약.csv').is_file():
        sys.exit(f'[중단] 자기 점검용 3단계 ② 요약이 없습니다: {ref2}')

    print('1) 작업별 기간 읽기(품질 작업일 월 — 3단계와 같음)')
    q = load_quality()
    period_map = dict(zip(q[BATCH_COL], q['기간'].map(TEAM_PERIOD)))

    print('2) 작업별 기록 판정 읽고 설비별로 세기')
    files = sorted(label_dir.glob('*.npz'))
    if {f.stem for f in files} != set(period_map):
        sys.exit('[중단] 판정 파일의 작업 목록이 품질 데이터의 작업 목록과 다릅니다.')
    rows = []
    for f in files:
        with np.load(f) as z:
            need = {'TAG_MIN_ns'} | {f'{m}_{k}_{x}' for m in ('A1', 'A2') for k in range(6) for x in ('valid', 'qual')}
            missing = need - set(z.files)
            if missing:
                sys.exit(f'[중단] {f.name}에 필요한 배열이 없습니다: {sorted(missing)[:5]}')
            for grp, r in one_batch(z).items():
                rows.append({BATCH_COL: f.stem, 'period': period_map[f.stem], '설비': grp, **r})
    by_batch = pd.DataFrame(rows)

    num_cols = [c for c in by_batch.columns if c not in (BATCH_COL, 'period', '설비')]
    by_period = by_batch.groupby(['period', '설비'], as_index=False)[num_cols].sum()
    by_period.insert(2, '작업수', by_batch.groupby(['period', '설비'])[BATCH_COL].nunique().to_numpy())
    by_period['period'] = pd.Categorical(by_period['period'], PERIOD_ORDER, ordered=True)
    by_period = add_ratios(by_period.sort_values(['period', '설비']).reset_index(drop=True))
    by_period['period'] = by_period['period'].astype(str)
    by_batch = add_ratios(by_batch)

    # 논리 검사: 둘다 + A1만 = A1양성, 공통 ⊆ 각 자기 범위
    assert (by_batch['둘다양성_기록수'] + by_batch['A1만_기록수'] == by_batch['A1양성_기록수']).all()
    assert (by_batch['둘다양성_기록수'] + by_batch['A2만_기록수'] == by_batch['A2양성_기록수']).all()
    assert (by_batch['공통범위_기록수'] <= by_batch[['A1_자기범위_기록수', 'A2_자기범위_기록수']].min(axis=1)).all()

    print('3) 자기 점검: 방법별 값이 3단계 ② 요약과 같은지')
    ok, check_lines = self_check(by_period, ref2)

    out = PROJECT / 'reports' / '3단계_공통범위_비교' / datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    out.mkdir(parents=True)
    by_period.to_csv(out / '01_기간별_설비별_A1A2_공통범위비교.csv', index=False, encoding='utf-8-sig')
    by_batch.to_csv(out / '02_작업별_설비별_A1A2_공통범위비교.csv', index=False, encoding='utf-8-sig')
    (out / '03_기존요약과_대조.txt').write_text(
        ('전부 통과\n' if ok else '불일치 있음 — 결과를 쓰지 마세요\n') + '\n'.join(check_lines) + '\n', encoding='utf-8-sig')
    sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out / '실행정보.txt').write_text('\n'.join([
        f'실행 시각: {out.name}', f'Python {sys.version.split()[0]} / pandas {pd.__version__} / numpy {np.__version__}',
        f'코드 SHA256: {sha}', f'① 결과(기록별 판정): {ref1}', f'② 결과(자기 점검): {ref2}',
        f'작업 수: {by_batch[BATCH_COL].nunique()}', '기간: 품질 작업일 월(3단계와 같음, 첫 기록 월과 세 기간 작업 집합 동일)',
        '판정(라벨)은 바꾸지 않고 집계만 다시 함']) + '\n', encoding='utf-8')

    show = ['period', '설비', '공통범위_기록수', 'A1_자기범위_기록수', 'A2_자기범위_기록수',
            'A1양성_시간비율_pct', 'A2양성_시간비율_pct', '둘다양성_기록수', '겹침정도_자카드']
    print(by_period[show].round(4).to_string(index=False))
    if not ok:
        print('[불일치] 03_기존요약과_대조.txt를 확인하세요. 완료.txt를 만들지 않았습니다.')
        print(f'결과 폴더: {out}')
        sys.exit(2)
    (out / '완료.txt').write_text('A1·A2 공통 범위 비교표 작성 완료. 자기 점검 전부 통과.\n', encoding='utf-8-sig')
    print(f'[완료] 결과 폴더: {out}')


if __name__ == '__main__':
    main()
