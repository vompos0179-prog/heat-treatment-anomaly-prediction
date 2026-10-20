#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""2단계 — 온도가 어느 수준에서 움직였는지 표와 그림으로 정리합니다. (종합본)

종합본이란
  2단계 코드 세 개를 한 파일로 합친 것입니다(팀원 2명 + 보충 1개).
    - 주 코드  2단계_평소모습.py      : 안전 점검, 작업별·월별·기간별·연속구간별 표, 엑셀, 원본 그림
    - 보조 코드 2단계_평소모습_분석.py : 사분위수·IQR·MAD·5%/95% 백분위수, 인접 기록 변화량,
                                       월별 작업 수 확인, 1~4월 온도 분포 그림
    - 보충 코드 2단계_평소모습_보충통계.py : 1.4826×MAD, 0.5%/99.5% 백분위수, 1~4월 시작 구간 곡선
                                       (분석 계획 §4-2 중 팀원 코드에 없던 부분)
  주 코드의 계산은 그대로 두고, 보조·보충 코드에만 있던 계산을 덧붙였습니다.
  보충 계산이 필요한 이유
    - 1.4826×MAD: 3단계 비교 기준(A2)이 '1~4월 중앙값에서 1.4826×MAD의 몇 배 벗어났나'로
      판단합니다. 2단계에서 이 값을 보여 줘야 3단계 기준으로 자연스럽게 이어집니다.
      (예: 1월 솔트조는 표준편차보다 1.4826×MAD가 훨씬 작아 A2가 1월을 많이 표시합니다.)
    - 시작 구간 곡선: '작업 시작 직후를 따로 빼야 하나?'에 답하는 그림입니다.
  보조 코드와 다른 점 하나: 보조 코드의 월별 표(06)는 '기록 날짜의 월'로 나눴지만,
  종합본의 월별 표는 문제정의서대로 '작업 첫 기록 월'로 나눕니다(작업 하나를 두 달로 쪼개지 않음).

이 파일이 하는 일
  1. 팀의 1단계 읽기 함수로 원본 온도 6개를 읽습니다.
  2. 같은 배정번호끼리 시간순으로 정리하고, 긴 기록 공백을 구분합니다.
  3. 작업별·월별·기간별 평균, 중앙값, 표준편차, 최솟값·최댓값을 계산합니다.
     (보조) 같은 표에 Q1·Q3·IQR·MAD·P05·P95 열을 더합니다.
  4. (보조) 월별 작업 수를 문제정의서 숫자와 대조하고, 1~4월 인접 기록 변화량을 요약합니다.
  5. (보충) 같은 표에 1.4826×MAD·P0.5·P99.5 열을 더하고, 1~4월 시작 구간 곡선을 계산합니다.
  6. 온도특성.xlsx, 관찰요약.txt, 원본 온도 그래프, 1~4월 분포·시작 구간 그림을 만듭니다.

하지 않는 일
  원본 수정, 빈칸 채우기, 1초 격자 생성, 새 리샘플링, 정상·이상 판정,
  안정화 시각 자동 판정, 모델 학습, 품질·불량률 관련성 분석.
  이미 만든 5분 그래프는 그대로 사용합니다. 이 코드는 원본 관측값을 봅니다.

파일 위치(팀 구조)
  프로젝트/stages/2단계_평소모습/2단계_평소모습_종합.py

팀 프로젝트 폴더의 터미널에서 실행
  .\\.venv\\Scripts\\python.exe "stages/2단계_평소모습/2단계_평소모습_종합.py"

다른 위치에서 실행할 때
  python "2단계_평소모습_종합.py" --project "<프로젝트 맨 위 폴더>"

원본과 공통 함수 찾는 순서
  원본: data/raw/data.csv → 프로젝트 폴더의 원본 ZIP(data.csv만 읽음).
  함수: src/data_contract.py → 제공받은 1단계_전처리_전체실행.py의 동일 함수.
  두 번째 방법은 1단계 전체를 실행하지 않고 필요한 함수 3개만 가져옵니다.
  함수나 원본이 없으면 다른 규칙을 만들어 대신 실행하지 않고 안내 후 멈춥니다.

결과 위치 (주 코드 결과와 섞이지 않게 폴더 이름을 따로 씁니다)
  reports/2단계_평소모습_종합/실행시각/
    온도특성.xlsx    읽는법, 작업목록, 월별작업수, 작업별온도, 월별온도, 기간별온도,
                     연속구간별온도, 기준기간_인접변화, 기준기간_시작구간곡선, 긴공백, 실행정보
    관찰요약.txt     계산한 사실과 해석 범위
    figures/        01~03 작업별 중앙값·표준편차, 1월 솔트조 원본
                    04~09 1~4월 온도 분포(온도 항목별 1장)
                    10 1~4월 시작 구간 곡선(보충)
                    작업별원본/ 작업별 원본 그림

보조 코드의 결과 파일이 종합본에서 어디에 있는지
  01_작업별_기간구분.csv        → 엑셀 '작업목록' 시트
  02_월별_작업수_기록수.csv     → 엑셀 '월별작업수' 시트
  03_기준기간_센서별_평소수준   → 엑셀 '기간별온도' 시트의 '기준 작성(1~4월)' 행
  04_기준기간_작업별_센서요약   → 엑셀 '작업별온도' 시트에서 기간='기준 작성(1~4월)'로 거른 행
  05_기준기간_인접변화_요약     → 엑셀 '기준기간_인접변화' 시트
  06_월별_센서요약.csv          → 엑셀 '월별온도' 시트(월 기준은 위 설명대로 첫 기록 월)
  figures/센서별 분포 그림      → figures/04~09_기준기간분포_*.png
  2단계_평소모습_요약.txt       → 관찰요약.txt에 같은 표를 넣음

보충 코드의 결과 파일이 종합본에서 어디에 있는지
  01_기간별_퍼짐꼬리.csv        → 엑셀 '기간별온도' 시트의 MAD_1.4826배·P0.5·P99.5 열
  02_월별_퍼짐꼬리.csv          → 엑셀 '월별온도' 시트의 같은 열
  03_작업별_퍼짐꼬리.csv        → 엑셀 '작업별온도' 시트의 같은 열
  04_1~4월_시작구간_곡선.csv    → 엑셀 '기준기간_시작구간곡선' 시트
  04_1~4월_시작구간_곡선.png    → figures/10_기준기간_시작구간곡선.png
  보충통계_요약.txt             → 관찰요약.txt의 [1~4월 시작 구간] 부분

옵션
  --check             원본 온도 분석 없이 실행 준비 상태 확인(결과 출력 없음)
  --plots summary     요약 그림만 생성(작업별 원본 그림은 생략)
  --plots none        표와 글만 생성
  --source 경로       별도 data.csv 또는 원본 ZIP 지정
  --quality 경로      별도 품질 XLSX 지정(월 기준 차이 확인용)

필요한 도구: Python 3.10 이상, pandas, numpy, openpyxl, matplotlib.
팀 .venv가 있으면 그 환경을 사용합니다. 없는 경우에는 현재 Python을 사용하되
버전을 실행정보에 남깁니다. 이 파일이 자동으로 프로그램을 설치하지는 않습니다.

중요한 구분
  * '평소 모습'은 관측된 모습입니다. 모든 값이 정상이라는 뜻이 아닙니다.
  * 작업의 월은 문제정의서대로 '첫 기록 월'입니다. 품질 작업일은 비교용입니다.
  * 5월·6~7월 통계도 설명용으로 만들지만, 이후 모델의 학습값으로 쓰지 않습니다.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager, ExitStack
from datetime import datetime, timezone, timedelta
import hashlib
import importlib
import io
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import zipfile

# 무거운 라이브러리는 실행할 때 불러옵니다. --help는 설치 전에도 볼 수 있습니다.
np = pd = plt = None
TIME = 'TAG_MIN'
BATCH = '배정번호'
SENSORS = ['솔트조 온도 1 Zone', '솔트조 온도 2 Zone',
           '소입로 온도 1 Zone', '소입로 온도 2 Zone',
           '소입로 온도 3 Zone', '소입로 온도 4 Zone']
PERIODS = {1: '기준 작성(1~4월)', 2: '기준 작성(1~4월)',
           3: '기준 작성(1~4월)', 4: '기준 작성(1~4월)',
           5: '조건 점검(5월)', 6: '후속 비교(6~7월)', 7: '후속 비교(6~7월)'}
BASE_PERIOD = PERIODS[1]  # '기준 작성(1~4월)'
# (보조 코드) 최신 문제정의서의 첫 기록 월별 작업 수. 다르면 멈추지 않고 경고만 남깁니다.
EXPECTED_JOBS = {1: 14, 2: 8, 3: 22, 4: 34, 5: 22, 6: 22, 7: 14}
# (보충 코드) 정규분포라면 1.4826×MAD ≈ 표준편차가 되도록 맞추는 상수. 3단계 A2 기준과 같은 값입니다.
MAD_SCALE = 1.4826
CURVE_MINUTES = 60  # (보충 코드) 시작 구간 곡선은 첫 기록 후 60분까지
ZIP_NAME = 'Dataset_열처리 품질보증 AI 데이터셋.zip'
STAGE1 = '1단계_전처리_전체실행.py'


def find_project(given):
    """현재 코드의 위쪽 폴더에서 원본/1단계 파일이 있는 프로젝트를 찾습니다."""
    if given:
        root = Path(given).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f'프로젝트 폴더가 없습니다: {root}')
        return root
    for root in Path(__file__).resolve().parents:
        if ((root / ZIP_NAME).is_file() or (root / 'data/raw/data.csv').is_file()
                or (root / 'src/data_contract.py').is_file()):
            return root
    raise ValueError('프로젝트 위치를 찾지 못했습니다. --project "프로젝트 경로"를 지정하세요.')


def load_libraries(plots):
    """계산·엑셀·그림 도구를 준비합니다. 없으면 필요한 이름을 알려줍니다."""
    global np, pd, plt
    try:
        import numpy as numpy
        import pandas as pandas
        import openpyxl  # noqa: F401
        np, pd = numpy, pandas
        if plots != 'none':
            import matplotlib
            matplotlib.use('Agg')  # 화면 창 대신 PNG 파일로 저장합니다.
            import matplotlib.pyplot as pyplot
            from matplotlib import font_manager
            plt = pyplot
            fonts = {x.name for x in font_manager.fontManager.ttflist}
            font = next((x for x in ['Malgun Gothic', 'AppleGothic', 'NanumGothic',
                                    'Noto Sans CJK KR'] if x in fonts), None)
            if font is None:
                raise ValueError('그림용 한글 글꼴을 찾지 못했습니다. 맑은 고딕 등 한글 글꼴이 필요합니다.')
            plt.rcParams.update({'font.family': font, 'axes.unicode_minus': False,
                                 'font.size': 10, 'savefig.dpi': 140})
    except ImportError as error:
        raise ValueError('필요한 도구가 없습니다. 팀 환경에서 pandas, numpy, openpyxl, '
                         'matplotlib 설치 상태를 확인하세요. 누락: ' + str(error)) from error


def contract_functions(project):
    """팀 공통 모듈을 우선 사용하고, 없으면 제공된 통합본의 함수를 그대로 읽습니다.

    AST는 파일의 '구성 목록'입니다. 전체 파일을 실행하지 않고 함수 정의와
    필요한 상수만 골라 가져오기 위해 사용합니다. 함수의 계산 내용은 수정하지 않습니다.
    """
    shared = project / 'src/data_contract.py'
    if shared.is_file():
        sys.path.insert(0, str(project))
        module = importlib.import_module('src.data_contract')
        if Path(module.__file__).resolve() != shared.resolve():
            raise ValueError('다른 프로젝트의 공통 모듈이 불러와졌습니다. 새 터미널에서 실행하세요.')
        how = f'팀 공통 모듈: {shared}'
        source = shared
    else:
        candidates = [project / STAGE1, project / 'stages/1단계_전처리' / STAGE1]
        source = next((p for p in candidates if p.is_file()), None)
        if source is None:
            raise ValueError('src/data_contract.py 또는 제공받은 1단계_전처리_전체실행.py가 필요합니다.')
        tree = ast.parse(source.read_text(encoding='utf-8-sig'), filename=str(source))
        names = {'load_raw', 'add_segments', 'load_quality'}
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
        constants = {}
        wanted = {'TIME_COL', 'BATCH_COL', 'TIME_FORMAT', 'LONG_GAP_SEC',
                  'RAW_ENCODING', 'PERIOD_BY_MONTH'}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in wanted:
                        constants[target.id] = ast.literal_eval(node.value)
        if {n.name for n in functions} != names or constants.keys() != wanted:
            raise ValueError('1단계 함수 구조가 제공된 버전과 다릅니다. 공통 파일을 확인하세요.')
        # 경로만 현재 프로젝트에 맞춥니다. 읽기·정렬·공백 처리 함수는 원문 그대로입니다.
        namespace = dict(constants, pd=pd, np=np,
                         RAW_CSV=project / 'data/raw/data.csv',
                         QUALITY_XLSX=project / 'data/raw/열처리_품질데이터.xlsx')
        code = compile(ast.Module(body=functions, type_ignores=[]), str(source), 'exec')
        exec(code, namespace)
        module = SimpleNamespace(**namespace)
        how = f'제공된 1단계 통합본의 동일 함수 사용: {source}'
    if (module.TIME_COL != TIME or module.BATCH_COL != BATCH
            or module.LONG_GAP_SEC != 60):
        raise ValueError('시간열·배정번호열·공백 조건이 검토한 1단계와 다릅니다. 팀 기준을 확인하세요.')
    for name in ['load_raw', 'add_segments', 'load_quality']:
        if not callable(getattr(module, name, None)):
            raise ValueError(f'팀 공통 함수가 없습니다: {name}')
    return module, how, hashlib.sha256(source.read_bytes()).hexdigest()


@contextmanager
def inputs(project, source_arg=None, quality_arg=None):
    """CSV를 읽거나 ZIP 안의 CSV를 직접 읽습니다. 원본을 풀어쓰거나 변경하지 않습니다."""
    source = (Path(source_arg).expanduser().resolve() if source_arg else
              next((p for p in [project / 'data/raw/data.csv', project / ZIP_NAME]
                    if p.is_file()), None))
    if source is None or not source.is_file():
        raise ValueError('원본 data/raw/data.csv 또는 원본 ZIP이 필요합니다. --source로 지정할 수도 있습니다.')
    quality = (Path(quality_arg).expanduser().resolve() if quality_arg else
               project / 'data/raw/열처리_품질데이터.xlsx')
    if quality_arg and not quality.is_file():
        raise ValueError(f'지정한 품질 파일이 없습니다: {quality}')
    with ExitStack() as stack:
        raw_input, quality_input = source, quality if quality.is_file() else None
        raw_label, quality_label = str(source), str(quality) if quality_input else '미제공'
        if source.suffix.lower() == '.zip':
            archive = stack.enter_context(zipfile.ZipFile(source))
            matches = [n for n in archive.namelist() if n.replace('\\', '/').split('/')[-1] == 'data.csv']
            if len(matches) != 1:
                raise ValueError('ZIP 안의 data.csv를 하나로 특정할 수 없습니다.')
            info = archive.getinfo(matches[0])
            raw_input = stack.enter_context(archive.open(info))
            raw_label += f' :: {info.filename} (크기 {info.file_size}, CRC {info.CRC:08x})'
            if quality_input is None:
                books = [n for n in archive.namelist() if n.lower().endswith('.xlsx')]
                if len(books) == 1:
                    quality_input = io.BytesIO(archive.read(books[0]))
                    quality_label = f'{source} :: {books[0]}'
                elif len(books) > 1:
                    raise ValueError('ZIP 안의 품질 XLSX가 여러 개입니다. --quality로 지정하세요.')
        elif source.suffix.lower() != '.csv':
            raise ValueError('--source에는 CSV 또는 ZIP을 지정하세요.')
        yield raw_input, quality_input, raw_label, quality_label


def read_quality(contract, source):
    """품질 수치는 분석하지 않습니다. 작업일과 첫 기록 월의 차이만 확인합니다."""
    if source is None:
        return None
    # 제공된 함수는 인자가 없으므로, 호출 동안만 읽을 파일 위치를 연결합니다.
    environment = contract.load_quality.__globals__
    previous = environment['QUALITY_XLSX']
    try:
        environment['QUALITY_XLSX'] = source
        return contract.load_quality()
    finally:
        environment['QUALITY_XLSX'] = previous


def prepare(raw, contract, quality):
    """원본 보존을 확인하고 작업별 첫 기록 월을 붙입니다. 월 경계에서도 작업을 나누지 않습니다."""
    if raw.empty:
        raise ValueError('원본에 기록이 없습니다.')
    if raw.duplicated([BATCH, TIME]).any():
        raise ValueError('같은 작업·같은 시각의 기록이 중복됩니다. 1단계에서 먼저 확인하세요.')
    if np.isinf(raw[SENSORS].to_numpy()).any():
        raise ValueError('온도에 무한대 값이 있습니다. 임의로 삭제하지 않고 중단합니다.')
    missing_before = raw[SENSORS].isna().sum()
    data = contract.add_segments(raw)
    if len(raw) != len(data) or not missing_before.equals(data[SENSORS].isna().sum()):
        raise ValueError('정렬·구간 구분 전후에 행 수 또는 온도 빈칸 수가 달라졌습니다.')
    jobs = data.groupby(BATCH, sort=False).agg(
        첫기록시각=(TIME, 'min'), 마지막기록시각=(TIME, 'max'),
        원본행수=(TIME, 'size'), 연속구간수=('segment_id', 'nunique')).reset_index()
    if not jobs['첫기록시각'].dt.year.eq(2022).all():
        raise ValueError('2022년 외의 작업이 있습니다. 기간 계획을 확인하세요.')
    jobs['첫기록월'] = jobs['첫기록시각'].dt.month
    jobs['기간'] = jobs['첫기록월'].map(PERIODS)
    if jobs['기간'].isna().any():
        raise ValueError('1~7월 외의 작업이 있습니다. 기간 계획을 확인하세요.')
    jobs['처음끝시각차_초'] = (jobs['마지막기록시각'] - jobs['첫기록시각']).dt.total_seconds()
    # 이 시간은 공백을 포함한 두 시각의 차이입니다. 가동시간으로 부르지 않습니다.
    if quality is not None:
        if set(jobs[BATCH]) != set(quality[BATCH]):
            raise ValueError('원본과 품질표의 배정번호가 다릅니다. 연결 상태를 먼저 확인하세요.')
        jobs = jobs.merge(quality[[BATCH, '작업일', '작업일_월']], on=BATCH,
                          how='left', validate='one_to_one')
        jobs['월기준일치'] = jobs['첫기록월'].eq(jobs['작업일_월'])
        jobs['세기간구분일치'] = jobs['기간'].eq(jobs['작업일_월'].map(PERIODS))
    else:
        jobs['작업일'] = pd.NaT
        jobs['작업일_월'] = pd.NA
        jobs['월기준일치'] = pd.NA
        jobs['세기간구분일치'] = pd.NA
    jobs = jobs.sort_values(['첫기록시각', BATCH]).reset_index(drop=True)
    data = data.merge(jobs[[BATCH, '첫기록월', '기간']],
                      on=BATCH, how='left', sort=False, validate='many_to_one')
    if len(data) != len(raw):
        raise ValueError('월 정보를 붙인 뒤 행 수가 달라졌습니다.')
    previous = data.groupby(BATCH, sort=False)[TIME].shift()
    gapmask = data['dt_prev'].gt(contract.LONG_GAP_SEC)
    gaps = data.loc[gapmask, [BATCH, TIME, 'dt_prev', 'segment_id']].copy()
    gaps.insert(1, '공백전기록', previous.loc[gapmask])
    gaps = gaps.rename(columns={TIME: '공백후기록', 'dt_prev': '앞뒤기록간격_초'})
    return data, jobs, gaps


def summarize(data, keys):
    """원본의 실제 숫자만 계산합니다. 값이 0개면 공란, 1개면 표준편차는 공란입니다.

    월/기간 통계는 작업별 평균을 다시 평균낸 값이 아닙니다.
    해당 월/기간 작업에 속한 원본 관측값 전체로 계산합니다(시간가중 평균도 아님).

    (보조 코드에서 가져온 열) Q1·Q3 = 하위 25%·75% 지점, IQR = Q3 − Q1(가운데 절반의 폭),
    MAD = 중앙값에서 떨어진 거리들의 중앙값, P05·P95 = 하위 5%·95% 지점.
    튀는 값 몇 개에 덜 흔들리는 '퍼짐' 숫자입니다. 이상 판정 기준으로 쓰지 않습니다.
    """
    group = data.groupby(keys, sort=True, observed=True)
    key_series = [data[k] for k in keys]
    parts = []
    for sensor in SENSORS:
        numbers = group[sensor]
        tab = numbers.agg(원본행수='size', 유효값수='count', 평균='mean', 중앙값='median',
                          표준편차='std', 최솟값='min', 최댓값='max')
        # 백분위수는 pandas 기본(선형 보간) 방식으로, 보조 코드의 Series.quantile과 같습니다.
        for name, q in [('Q1', .25), ('Q3', .75), ('P05', .05), ('P95', .95),
                        ('P0.5', .005), ('P99.5', .995)]:  # P0.5·P99.5는 보충 코드
            tab[name] = numbers.quantile(q)
        tab['IQR'] = tab['Q3'] - tab['Q1']
        # MAD: 각 값이 '자기 묶음의 중앙값'에서 얼마나 떨어졌는지 구한 뒤 그 거리의 중앙값을 냅니다.
        distance = (data[sensor] - numbers.transform('median')).abs()
        tab['MAD'] = distance.groupby(key_series, sort=True, observed=True).median()
        tab['MAD_1.4826배'] = MAD_SCALE * tab['MAD']  # (보충) 표준편차와 같은 눈금으로 맞춘 MAD
        tab['작업수'] = group[BATCH].nunique()
        tab['빈칸수'] = tab['원본행수'] - tab['유효값수']
        tab['온도빈칸비율_pct'] = tab['빈칸수'] / tab['원본행수'] * 100
        tab['설비'] = '솔트조' if sensor.startswith('솔트조') else '소입로'
        tab['온도항목'] = sensor
        # pandas의 std 기본값 ddof=1: 표본 표준편차입니다. 숫자 1개이면 계산하지 않습니다.
        tab['최대최소차'] = tab['최댓값'] - tab['최솟값']
        if not tab['유효값수'].add(tab['빈칸수']).eq(tab['원본행수']).all():
            raise ValueError('유효값 수와 빈칸 수의 합계가 맞지 않습니다.')
        if int(tab['유효값수'].sum()) != int(data[sensor].count()):
            raise ValueError(f'{sensor}: 요약 전후 실제 값의 개수가 다릅니다.')
        parts.append(tab.reset_index())
    columns = keys + ['설비', '온도항목', '작업수', '원본행수', '유효값수', '빈칸수',
                      '온도빈칸비율_pct', '평균', '중앙값', '표준편차', '최솟값', '최댓값', '최대최소차',
                      'Q1', 'Q3', 'IQR', 'MAD', 'P05', 'P95', 'MAD_1.4826배', 'P0.5', 'P99.5']
    return pd.concat(parts, ignore_index=True)[columns]


def month_counts(jobs):
    """(보조 코드) 첫 기록 월별 작업 수·기록 수를 세고 문제정의서 숫자와 대조합니다."""
    table = (jobs.groupby('첫기록월', as_index=False)
                 .agg(작업수=(BATCH, 'size'), 기록수=('원본행수', 'sum'))
                 .sort_values('첫기록월'))
    actual = dict(zip(table['첫기록월'].astype(int), table['작업수'].astype(int)))
    if actual == EXPECTED_JOBS:
        message = '월별 작업 수가 문제정의서와 같습니다: ' + ' / '.join(map(str, EXPECTED_JOBS.values()))
    else:
        message = f'[주의] 문제정의서의 월별 작업 수와 다릅니다. 기대 {EXPECTED_JOBS} / 실제 {actual}'
    return table, message


def adjacent_changes(data):
    """(보조 코드) 1~4월에 바로 앞 기록과 비교한 온도 변화 크기를 요약합니다.

    같은 연속구간(segment_id) 안에서만 비교합니다. 60초 넘는 공백을 건너뛴 차이는 넣지 않습니다.
    앞이나 지금 기록의 온도가 빈칸이면 그 차이는 계산하지 않습니다. 이상 판정 임계값이 아닙니다.
    """
    base = data.loc[data['기간'].eq(BASE_PERIOD)]
    rows = []
    for sensor in SENSORS:
        change = base.groupby('segment_id', sort=False)[sensor].diff().abs().dropna()
        has = not change.empty
        rows.append({'온도항목': sensor, '유효변화수': len(change),
                     '절대변화_중앙값': change.median() if has else np.nan,
                     '절대변화_P90': change.quantile(.90) if has else np.nan,
                     '절대변화_P95': change.quantile(.95) if has else np.nan,
                     '절대변화_P99': change.quantile(.99) if has else np.nan,
                     '절대변화_최댓값': change.max() if has else np.nan})
    return pd.DataFrame(rows)


def write_workbook(path, tables, metadata):
    """작은 결과표를 엑셀 하나의 여러 시트에 모읍니다. 원본 수백만 행은 넣지 않습니다."""
    from openpyxl.styles import Font, PatternFill, Alignment
    explanations = [
        ('분석 목적', '온도 수준과 값의 퍼짐을 관찰합니다. 정상·이상 판정은 하지 않습니다.'),
        ('온도 단위', '평균·중앙값·표준편차·최솟값·최댓값·최대최소차는 ℃입니다.'),
        ('작업별온도', '한 작업·한 온도 항목이 한 줄입니다. 센서끼리 값을 섞지 않습니다.'),
        ('월별온도·기간별온도', '작업 첫 기록 월로 작업 전체를 배정하고 원본 유효값을 모아 계산합니다.'),
        ('평균의 가중', '관측값마다 같은 비중입니다. 오래/많이 기록된 작업의 영향이 큽니다. 시간가중평균이 아닙니다.'),
        ('중앙값', '숫자를 크기순으로 놓았을 때 가운데 값입니다.'),
        ('표준편차', '온도 값이 얼마나 퍼져 있는지 나타냅니다(ddof=1). 2개 미만이면 공란입니다.'),
        ('표준편차의 한계', '큰 값은 흔들림, 완만한 변화, 서로 다른 수준 등에서 생깁니다. 그래프로 구분합니다.'),
        ('Q1·Q3·IQR', '값을 크기순으로 놓았을 때 하위 25%·75% 지점과 그 사이 폭입니다. 가운데 절반이 퍼진 정도입니다.'),
        ('MAD', '중앙값에서 떨어진 거리들의 중앙값입니다. 튀는 값 몇 개에 덜 흔들리는 퍼짐 숫자입니다.'),
        ('P05·P95', '하위 5%·95% 지점입니다. 판정 기준이 아니라 값이 주로 놓인 범위를 보여 줍니다.'),
        ('MAD_1.4826배', 'MAD에 1.4826을 곱해 표준편차와 같은 눈금으로 맞춘 값입니다. 3단계 비교 기준(A2)이 이 값을 씁니다. 표준편차보다 훨씬 작으면 서로 다른 수준이 섞여 있다는 신호일 수 있습니다(예: 1월 솔트조).'),
        ('P0.5·P99.5', '하위·상위 0.5% 지점입니다. 아주 드문 양 끝 값이 어디까지인지 보여 줍니다.'),
        ('기준기간_시작구간곡선', '1~4월 작업들을 첫 기록 후 경과 분(0~59분)별로 모은 온도 중앙값·P25·P75입니다. 개별 작업 판단이 아니며, 첫 기록이 실제 작업 시작과 다를 수 있습니다.'),
        ('월별작업수', '첫 기록 월별 작업 수·기록 수입니다. 실행정보의 월별작업수확인에 문제정의서 숫자와 대조 결과가 있습니다.'),
        ('작업별온도의 기간', '작업 첫 기록 월로 정한 기간입니다. 1~4월 작업만 보려면 이 열로 거릅니다.'),
        ('기준기간_인접변화', '1~4월에 바로 앞 기록과의 온도 차이 크기 요약입니다. 같은 연속구간 안에서만 비교합니다. 이상 판정 임계값이 아닙니다.'),
        ('온도빈칸비율', '존재하는 행 중 해당 온도 칸이 빈 비율입니다. 기록이 없는 초의 비율이 아닙니다.'),
        ('연속구간', '같은 작업에서 인접 기록 간격이 60초를 초과하면 앞뒤를 나눈 구간입니다.'),
        ('처음끝시각차·공백', '관측 시각 사이의 차이입니다. 설비 가동시간·정지시간이 아닙니다.'),
        ('기간 사용', '1~4월만 향후 기준 작성에 사용합니다. 5월·6~7월 표는 설명용이며 정상 정답이 아닙니다.'),
        ('월 기준 비교', '첫 기록 월을 사용합니다. 품질표 작업일 월은 차이 확인용으로만 남깁니다.'),
        ('원본 그림', '실제 관측값을 점으로 표시합니다. 공백을 선으로 연결하거나 보간하지 않습니다.'),
        ('5분 그래프', '기존 팀원 그래프를 사용합니다. 이 코드는 새 5분/30초 자료를 만들지 않습니다.'),
    ]
    contents = {'읽는법': pd.DataFrame(explanations, columns=['항목', '설명']), **tables,
                '실행정보': pd.DataFrame(list(metadata.items()), columns=['항목', '내용'])}
    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        for name, table in contents.items():
            table.to_excel(writer, sheet_name=name, index=False)
            sheet = writer.sheets[name]
            sheet.freeze_panes = 'A2'
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.fill = PatternFill('solid', fgColor='17365D')
                cell.font = Font(name='맑은 고딕', color='FFFFFF', bold=True)
            for column in sheet.columns:
                maxlen = max(len(str(c.value or '')) for c in column)
                sheet.column_dimensions[column[0].column_letter].width = min(75, max(15, maxlen * 1.3))
                for cell in column[1:]:
                    cell.font = Font(name='맑은 고딕', size=10)
                    cell.alignment = Alignment(vertical='top', wrap_text=True)
                    if isinstance(cell.value, float):
                        cell.number_format = '0.0000'
            if name in ('읽는법', '실행정보'):
                sheet.column_dimensions['B'].width = 95
                for row in range(2, sheet.max_row + 1):
                    sheet.row_dimensions[row].height = 32


def save_summary_plots(data, jobs, job_stats, folder):
    """작업별 숫자와 1월 원본을 그림으로 봅니다. 높은 값을 자동으로 이상이라 하지 않습니다."""
    import matplotlib.dates as mdates
    # 종합본의 작업별 표에는 이미 '기간'이 있으므로 시각만 붙입니다.
    merged = job_stats.merge(jobs[[BATCH, '첫기록시각']], on=BATCH, validate='many_to_one')
    for number, metric in [(1, '중앙값'), (2, '표준편차')]:
        fig, axes = plt.subplots(3, 2, figsize=(14, 10), layout='constrained')
        for ax, sensor in zip(axes.flat, SENSORS):
            values = merged.loc[merged['온도항목'].eq(sensor)].sort_values('첫기록시각')
            ax.scatter(values['첫기록시각'], values[metric], s=18, color='#185D85')
            ax.set_title(sensor)
            ax.set_ylabel(f'{metric} (℃)')
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m월'))
            ax.set_xlabel('작업 첫 기록 시각')
            ax.grid(alpha=.2)
        fig.suptitle(f'작업별 온도 {metric} | 점 하나는 작업 하나 · 정상/이상 판정 아님')
        fig.savefig(folder / f'{number:02d}_작업별_{metric}.png')
        plt.close(fig)
    january = data.loc[data['첫기록월'].eq(1)]
    if not january.empty:
        fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True, layout='constrained')
        for ax, sensor in zip(axes, SENSORS[:2]):
            ax.plot(january[TIME], january[sensor], '.', markersize=1, alpha=.45, color='#185D85')
            ax.set_ylabel(f'{sensor}\n온도 (℃)')
            ax.grid(alpha=.2)
        axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        axes[-1].set_xlabel('실제 기록 시각')
        fig.suptitle('1월 작업의 솔트조 원본 기록 | 수준 변화는 점의 흐름으로 확인 · 원인 판정 아님')
        fig.savefig(folder / '03_1월_솔트조_원본.png')
        plt.close(fig)


def start_curve(data, jobs):
    """(보충 코드) 1~4월 작업의 '첫 기록 후 경과 분'별 온도 중앙값을 계산합니다.

    여러 작업을 겹쳐 놓고 0분, 1분, 2분 … 59분마다 가운데 값을 냅니다.
    작업 초반에만 온도가 따로 움직이는지(시작 구간을 따로 다뤄야 하는지) 보기 위한 표입니다.
    비교용으로 같은 작업들의 60분 이후 중앙값도 돌려줍니다.
    """
    base = data.loc[data['기간'].eq(BASE_PERIOD)]
    first = base[BATCH].map(jobs.set_index(BATCH)['첫기록시각'])
    minute = ((base[TIME] - first).dt.total_seconds() // 60).astype(int)  # 0 = 첫 기록 후 0~1분 미만
    early = base.loc[minute.lt(CURVE_MINUTES)].assign(경과분=minute)
    rows = []
    for m, g in early.groupby('경과분', sort=True):
        for sensor in SENSORS:
            v = g[sensor].dropna()
            rows.append({'경과분': int(m), '온도항목': sensor, '작업수': int(g.loc[v.index, BATCH].nunique()),
                         '유효값수': len(v), '중앙값': v.median() if len(v) else np.nan,
                         'P25': v.quantile(.25) if len(v) else np.nan,
                         'P75': v.quantile(.75) if len(v) else np.nan})
    later = base.loc[minute.ge(CURVE_MINUTES)]
    return pd.DataFrame(rows), {s: later[s].median() for s in SENSORS}


def save_start_curve_plot(curve, later_median, folder):
    """(보충 코드) 시작 구간 곡선 그림. 파란 띠는 가운데 50% 범위, 빨간 점선은 60분 이후 중앙값입니다."""
    fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True, layout='constrained')
    for ax, sensor in zip(axes.flat, SENSORS):
        c = curve.loc[curve['온도항목'].eq(sensor)]
        ax.fill_between(c['경과분'], c['P25'], c['P75'], color='#9DC3E6', alpha=.5, label='가운데 50% 범위')
        ax.plot(c['경과분'], c['중앙값'], '.-', color='#185D85', markersize=3, label='분별 중앙값')
        ax.axhline(later_median[sensor], color='#B94735', linestyle='--', linewidth=1, label='60분 이후 중앙값')
        ax.set_title(sensor)
        ax.set_ylabel('온도 (℃)')
        ax.grid(alpha=.2)
    for ax in axes[-1]:
        ax.set_xlabel('첫 기록 이후 경과 시간 (분)')
    axes[0, 0].legend(fontsize=8)
    fig.suptitle('1~4월 작업의 시작 구간 곡선 | 여러 작업을 모은 분별 중앙값 · 정상/이상 판정 아님')
    fig.savefig(folder / '10_기준기간_시작구간곡선.png', dpi=140)
    plt.close(fig)


def save_distribution_plots(data, folder):
    """(보조 코드) 1~4월 온도 값이 어디에 많이 몰려 있는지 막대(히스토그램)로 봅니다.

    막대 하나는 온도 구간 하나이고, 높이는 그 구간에 든 기록 수입니다. 점선은 중앙값입니다.
    전체 흐름 이해용이며 이상 판정에 쓰지 않습니다.
    """
    base = data.loc[data['기간'].eq(BASE_PERIOD)]
    for i, sensor in enumerate(SENSORS, start=4):
        values = base[sensor].dropna()
        if values.empty:
            continue
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.hist(values, bins=80)
        ax.axvline(values.median(), linestyle='--', linewidth=1.5, label=f'median={values.median():.3f}')
        ax.set_title(f'1~4월 기준기간 온도 분포 | {sensor}')
        ax.set_xlabel('온도 (℃)')
        ax.set_ylabel('기록 수')
        ax.legend()
        ax.grid(alpha=0.2)
        fig.tight_layout()
        fig.savefig(folder / f'{i:02d}_기준기간분포_{sensor}.png', dpi=160)
        plt.close(fig)


def save_job_plots(data, folder):
    """한 작업의 온도 6개를 한 그림에 표시합니다. 시간축은 첫 관측 이후 경과 분입니다.

    첫 기록은 실제 작업 시작과 다를 수 있습니다. 빈 온도는 바닥의 빨간 표시로,
    60초 초과 기록 공백은 음영으로 보여 줍니다. 없는 온도값을 만들어 그리지 않습니다.
    """
    folder.mkdir()
    groups = data.groupby(BATCH, sort=False)
    for i, (batch, job) in enumerate(groups, 1):
        job = job.sort_values(TIME)
        start = job[TIME].iloc[0]
        minutes = (job[TIME] - start).dt.total_seconds() / 60
        fig, axes = plt.subplots(3, 2, figsize=(14, 10), sharex=True, layout='constrained')
        for ax, sensor in zip(axes.flat, SENSORS):
            ax.plot(minutes, job[sensor], '.', markersize=1.8, color='#185D85')
            missing = job[sensor].isna()
            if missing.all():
                ax.text(.5, .5, '기록된 온도 값 없음', ha='center', va='center',
                        transform=ax.transAxes, color='#B94735')
            ax.plot(minutes.loc[missing], np.full(int(missing.sum()), .035), '|',
                    color='#B94735', transform=ax.get_xaxis_transform(), markersize=5)
            for now, dt in zip(minutes.loc[job['dt_prev'].gt(60)], job.loc[job['dt_prev'].gt(60), 'dt_prev']):
                ax.axvspan(now - dt / 60, now, color='#DCA64D', alpha=.20)
            ax.set_title(sensor)
            ax.set_ylabel('온도 (℃)')
            ax.set_xlabel('첫 기록 이후 경과 시간 (분)')
            ax.grid(alpha=.2)
        fig.suptitle(f'배정번호 {batch} | 첫 기록 {start:%Y-%m-%d %H:%M:%S}\n'
                     '점: 원본 관측 · 바닥 빨간 표시: 온도 빈칸 · 음영: 60초 초과 기록 공백')
        safe = re.sub(r'[^A-Za-z0-9_-]', '_', str(batch))
        # 번호도 붙여 파일명 정리 과정에서 서로 다른 배정번호가 덮어써지는 것을 막습니다.
        fig.savefig(folder / f'{i:03d}_{safe}_원본.png')
        plt.close(fig)
        if i % 10 == 0 or i == groups.ngroups:
            print(f'  작업별 원본 그림 {i}/{groups.ngroups}', flush=True)


def observation_text(data, jobs, gaps, job_stats, metadata, extras):
    """계산으로 확인한 사실만 적습니다. 온도 변화의 원인·고장을 만들어 쓰지 않습니다.

    extras: 보조 코드 요약에 있던 표(월별 작업 수, 1~4월 센서별 요약, 1~4월 인접 변화량)와 대조 문구.
    """
    lines = ['2단계 온도 모습 관찰 요약', '',
             f'원본 기록 {len(data):,}행 / 작업 {len(jobs):,}개 / 온도 항목 6개',
             f'기록 범위: {data[TIME].min()} ~ {data[TIME].max()}',
             f'60초 초과 기록 공백: {len(gaps)}곳',
             '이 글과 표는 관측된 모습을 설명한다. 이상 구간을 판정한 결과가 아니다.', '',
             '[작업을 나눈 기준] 첫 기록 월에 작업 전체를 배정한다. 월 경계에서 작업을 나누지 않는다.']
    for month, n in jobs['첫기록월'].value_counts().sort_index().items():
        lines.append(f'  {month}월: {n}개 작업')
    if jobs['월기준일치'].notna().all():
        different = jobs.loc[~jobs['월기준일치'].astype(bool), BATCH].tolist()
        lines.append(f'품질 작업일 월과 첫 기록 월이 다른 작업: {different or "없음"}')
        lines.append(f'1~4월/5월/6~7월 소속도 다른 작업: {jobs.loc[~jobs["세기간구분일치"].astype(bool), BATCH].tolist() or "없음"}')
    else:
        lines.append('품질표 미제공: 작업일 월과의 비교는 하지 않았다. 첫 기록 월은 계산했다.')
    lines += ['', '[작업별 온도 수준의 범위] 아래 범위는 작업별 중앙값들 중 가장 작고 큰 값이다.']
    for sensor in SENSORS:
        med = job_stats.loc[job_stats['온도항목'].eq(sensor), '중앙값'].dropna()
        if med.empty:
            lines.append(f'  {sensor}: 실제 온도 값이 없어 계산하지 못했다.')
        else:
            lines.append(f'  {sensor}: {med.min():.3f} ~ {med.max():.3f}℃')
    show = ['온도항목', '유효값수', '빈칸수', '평균', '중앙값', '표준편차', 'Q1', 'Q3', 'IQR', 'MAD',
            'P05', 'P95', 'MAD_1.4826배', 'P0.5', 'P99.5', '최솟값', '최댓값']
    lines += ['', '[월별 작업 수] 첫 기록 월 기준', extras['month_message'],
              extras['month_table'].to_string(index=False),
              '', '[1~4월 센서별 평소 수준] 1~4월 작업의 원본 관측값 전체로 계산',
              extras['base_table'][show].round(4).to_string(index=False),
              '', '[1~4월 인접 기록 변화량] 같은 연속구간 안에서 바로 앞 기록과의 차이 크기(℃)',
              extras['change_table'].round(4).to_string(index=False),
              '', '[1~4월 시작 구간] 첫 기록 후 0분·10분·30분·59분 중앙값 vs 60분 이후 중앙값']
    curve = extras['curve']
    for sensor in SENSORS:
        c = curve.loc[curve['온도항목'].eq(sensor)].set_index('경과분')['중앙값']
        pick = ' / '.join(f'{m}분 {c.get(m, np.nan):.3f}' for m in (0, 10, 30, 59))
        lines.append(f'  {sensor}: {pick} | 60분 이후 {extras["later_median"][sensor]:.3f}')
    lines += ['  곡선은 여러 작업을 모은 모습이다. 개별 작업은 작업별 원본 그림으로 본다.']
    lines += ['', '[표와 그림에서 확인할 질문]',
              '1. 작업마다 대표적인 온도 수준이 다른가?',
              '2. 값이 넓게 퍼진 작업은 원본에서 흔들리는가, 한 방향으로 변하는가?',
              '3. 첫 관측 직후와 이후 모습이 다른가? 실제 작업 시작 시각과 같다고 단정하지 않는다.',
              '4. 1월 원본에서 온도 수준이 달라지는 모습이 보이는가? 특정 날짜/온도를 미리 결론내리지 않는다.',
              '5. 보이는 빈 부분이 온도 빈칸인지, 기록 행 전체가 없는 시간인지 구분할 수 있는가?',
              '', '[해석 범위]',
              '평균은 실제 관측값의 산술평균이다. 시간가중 평균이나 작업별 평균의 평균이 아니다.',
              '표준편차는 값의 퍼짐이며, 급격한 변화나 고장을 직접 뜻하지 않는다.',
              '온도 빈칸 비율은 존재하는 행 기준이다. 기록 없는 시간의 비율이 아니다.',
              'IQR·MAD·P05·P95와 인접 변화량은 퍼짐을 설명하는 숫자이며 이상 판정 임계값이 아니다.',
              '1.4826×MAD는 정규분포 가정에서 표준편차에 맞춘 값이다. 3단계 A2가 같은 값을 쓰지만, 이 표 자체는 판정이 아니다.',
              '월별 표는 작업 첫 기록 월 기준이다. 기록 날짜 월로 나눈 표(보조 코드 06)와는 월을 넘는 작업에서 숫자가 다르다.',
              '5월·6~7월 통계는 설명용이다. 이후 학습 기준에는 1~4월 자료만 사용한다.',
              '6~7월은 이미 살펴본 과거 자료이며 독립 최종 검증이 아니다.',
              '새 리샘플링, 보간, 고장·불량 판정, 안정화 시각 판정은 하지 않았다.',
              '', '[실행 정보]']
    lines += [f'{k}: {v}' for k, v in metadata.items()]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--project', help='프로젝트 맨 위 폴더')
    parser.add_argument('--source', help='원본 CSV 또는 ZIP 경로')
    parser.add_argument('--quality', help='작업일 월 비교에 사용할 품질 XLSX 경로')
    parser.add_argument('--plots', choices=['all', 'summary', 'none'], default='all')
    parser.add_argument('--check', action='store_true', help='준비 상태만 확인하고 종료')
    args = parser.parse_args()
    project = find_project(args.project)
    # 1단계와 같은 원칙: Python·패키지 버전이 권장 환경과 다르면 [주의]만 보여 주고 계속합니다(src/env_check.py).
    sys.path.insert(0, str(project))
    from src.env_check import check_python_env
    check_python_env(project)
    load_libraries(args.plots)
    contract, contract_label, digest = contract_functions(project)
    with inputs(project, args.source, args.quality) as (raw_file, quality_file, raw_label, quality_label):
        print(f'[읽기 규칙] {contract_label}')
        print(f'[원본] {raw_label}')
        print('[월 구분] 문제정의서의 첫 기록 월 사용 / 품질 작업일 월은 비교용')
        if args.check:
            print('[준비 확인 완료] 원본 분석 및 결과 파일 생성은 하지 않았습니다.')
            return
        print('[1/4] 원본 온도 6개를 읽습니다. 전체 원본을 메모리에 읽으므로 시간이 걸릴 수 있습니다.', flush=True)
        raw = contract.load_raw(SENSORS, 'float64', path=raw_file)
        quality = read_quality(contract, quality_file)
    print('[2/4] 작업을 정리하고 온도 요약표를 계산합니다.', flush=True)
    data, jobs, gaps = prepare(raw, contract, quality)
    del raw
    by_job = summarize(data, [BATCH])
    # 1~4월 작업만 거를 수 있도록 작업별 표에 기간을 붙입니다(보조 코드 04번 표 대신).
    by_job.insert(1, '기간', by_job[BATCH].map(jobs.set_index(BATCH)['기간']))
    by_month = summarize(data, ['첫기록월'])
    by_period = summarize(data, ['기간'])
    by_segment = summarize(data, [BATCH, 'segment_id'])
    month_table, month_message = month_counts(jobs)
    print(f'  {month_message}', flush=True)
    change_table = adjacent_changes(data)
    curve, later_median = start_curve(data, jobs)
    # 실제 실행한 시간은 한국 시각으로 남깁니다. 기존 결과를 덮어쓰지 않습니다.
    now = datetime.now(timezone(timedelta(hours=9)))
    output = project / 'reports/2단계_평소모습_종합' / now.strftime('%Y%m%d_%H%M%S_%f')
    output.mkdir(parents=True, exist_ok=False)
    metadata = {'실행시각_KST': now.isoformat(timespec='seconds'), '원본': raw_label,
                '품질표_월확인용': quality_label, '공통함수': contract_label,
                '공통함수파일_SHA256': digest,
                '2단계코드_SHA256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'Python': sys.version.split()[0], 'pandas': pd.__version__, 'numpy': np.__version__,
                '온도자료형': 'float64', '표준편차': '표본 표준편차(ddof=1)',
                '월배정': '작업 첫 기록 월에 작업 전체 배정', '공백구분': '60초 초과',
                '그림옵션': args.plots, '정상_이상판정': '수행하지 않음',
                '새리샘플링': '수행하지 않음', '온도항목': ' / '.join(SENSORS),
                '종합본_구성': '주 코드 2단계_평소모습.py + 보조 코드 2단계_평소모습_분석.py',
                '월별작업수확인': month_message,
                'MAD배율': f'{MAD_SCALE} (MAD_1.4826배 열)',
                '시작구간곡선': f'1~4월, 첫 기록 후 0~{CURVE_MINUTES - 1}분'}
    tables = {'작업목록': jobs, '월별작업수': month_table, '작업별온도': by_job, '월별온도': by_month,
              '기간별온도': by_period, '연속구간별온도': by_segment,
              '기준기간_인접변화': change_table, '기준기간_시작구간곡선': curve, '긴공백': gaps}
    extras = {'month_table': month_table, 'month_message': month_message,
              'base_table': by_period.loc[by_period['기간'].eq(BASE_PERIOD)],
              'change_table': change_table, 'curve': curve, 'later_median': later_median}
    print('[3/4] 엑셀과 관찰 요약을 저장합니다.', flush=True)
    write_workbook(output / '온도특성.xlsx', tables, metadata)
    (output / '관찰요약.txt').write_text(observation_text(data, jobs, gaps, by_job, metadata, extras),
                                      encoding='utf-8-sig')
    print('[4/4] 원본과 요약 숫자의 그래프를 만듭니다.', flush=True)
    if args.plots != 'none':
        folder = output / 'figures'
        folder.mkdir()
        save_summary_plots(data, jobs, by_job, folder)
        save_distribution_plots(data, folder)
        save_start_curve_plot(curve, later_median, folder)
        if args.plots == 'all':
            save_job_plots(data, folder / '작업별원본')
    # 중간에 실패하면 이 파일이 없습니다. 일부 결과만 생긴 것을 전체 완료로 오해하지 않게 합니다.
    (output / '완료.txt').write_text('요청한 표·설명·그림 저장을 완료했습니다. 이상 판정은 하지 않았습니다.\n', encoding='utf-8-sig')
    print(f'[완료] 결과 폴더: {output}')


if __name__ == '__main__':
    # Windows의 오래된 콘솔도 지원합니다. 출력할 수 없는 기호 때문에 분석이 멈추지 않게 합니다.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(errors='replace')
    try:
        main()
    except (ValueError, FileNotFoundError, ImportError, KeyError) as error:
        print(f'[중단] {error}', file=sys.stderr)
        sys.exit(1)
