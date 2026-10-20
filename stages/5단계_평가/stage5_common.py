"""5단계 공통 읽기·검사. IF를 다시 학습하거나 판정 조건을 다시 계산하지 않는다."""
from pathlib import Path
import configparser
import hashlib
import importlib.metadata
import json
import platform
from datetime import datetime

import numpy as np
import pandas as pd

SENSORS = ['솔트조 온도 1 Zone', '솔트조 온도 2 Zone']
ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(part)
    return h.hexdigest()

def read_csv(path, **kwargs):
    return pd.read_csv(path, encoding='utf-8-sig', **kwargs)

def save_csv(table, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False, encoding='utf-8-sig')

def runtime_info():
    versions = {}
    for name in ['pandas', 'numpy', 'matplotlib', 'scipy', 'scikit-learn', 'xgboost', 'joblib']:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = '미설치'
    return {'실행시각': datetime.now().isoformat(), 'PC': platform.node(),
            'OS': platform.platform(), 'Python': platform.python_version(), '도구버전': versions}

def load_config(config_path=None):
    path = Path(config_path or HERE / '5단계_결과기준.txt').resolve()
    parser = configparser.ConfigParser(interpolation=None)
    with path.open(encoding='utf-8-sig') as f:
        parser.read_file(f)
    cfg = {'root': ROOT, 'config_path': path}
    if parser.has_option('입력', 'project_root'):
        p = Path(parser['입력']['project_root'])
        cfg['root'] = (ROOT / p).resolve() if not p.is_absolute() else p.resolve()
    for key in ['stage3_a', 'stage3_b', 'stage4', 'iqr', 'stage4_previous', 'old_stage5']:
        value = parser['입력'].get(key, '').strip()
        p = Path(value) if value else None
        cfg[key] = ((cfg['root'] / 'reports' / p).resolve() if not p.is_absolute() else p.resolve()) if p else None
    cfg['raw_csv'] = cfg['root'] / 'data/raw/data.csv'
    # 선택: 분류별 대표 사례 지정([사례] 공통/A1만/IF만 = 배정번호). 없으면 규칙으로 고름
    # configparser는 키를 소문자로 바꾸므로(A1만 → a1만) 분류 이름으로 되돌린다
    names = {'공통': '공통', 'a1만': 'A1만', 'if만': 'IF만'}
    cfg['fixed_cases'] = {names.get(k.lower(), k): int(v) for k, v in parser['사례'].items() if v.strip()} if parser.has_section('사례') else {}
    cfg['mode'] = parser.get('검증', 'mode', fallback='production')
    if cfg['mode'] not in ['production', 'historical_test', 'synthetic_test']:
        raise ValueError('검증 mode는 production/historical_test/synthetic_test 중 하나여야 합니다.')
    cfg['expected_base_sha256_prefix'] = parser.get('검증', 'base_sha256_prefix', fallback='a83490a6')
    cfg['expected_jobs'] = parser.getint('검증', 'followup_jobs', fallback=36)
    return cfg

def default_output(config, run_id, part):
    return config['root'] / 'reports/5단계_평가' / run_id / part

def label_dir(config, kind):
    parent = config['stage3_a'] if kind == 'stage3' else config['stage4']
    names = ['검증용_기록라벨', '기록라벨'] if kind == 'stage3' else ['IF_기록별판정']
    if kind == 'stage4' and config['mode'] != 'production':
        names.append('기록별_판정')
    found = [parent / name for name in names if parent is not None and (parent / name).is_dir()]
    if len(found) != 1:
        raise FileNotFoundError(f'{parent}: {names} 중 판정 폴더 하나가 필요합니다. 발견={found}')
    return found[0]

def readiness(config, include_raw=True, scope='all'):
    missing = []
    for key in ['stage3_a', 'stage3_b', 'stage4'] + (['iqr'] if scope != 'main' else []):
        p = config.get(key)
        if p is None or not p.is_dir():
            missing.append(f'{key}: {p}')
    if include_raw and not config['raw_csv'].is_file():
        missing.append(f"원본 CSV: {config['raw_csv']}")
    for kind in ['stage3', 'stage4']:
        if config.get('stage3_a' if kind == 'stage3' else 'stage4'):
            try:
                label_dir(config, kind)
            except FileNotFoundError as e:
                missing.append(str(e))
    if config['mode'] == 'production' and config.get('stage4'):
        receipt = config['stage4'] / 'IF_저장정보.json'
        if not receipt.is_file():
            missing.append(f'최신 4단계 원본 코드·300개 조건 확인용 저장정보: {receipt}')
        else:
            meta = json.loads(receipt.read_text(encoding='utf-8-sig'))
            if not str(meta.get('base_code_sha256', '')).startswith(config['expected_base_sha256_prefix']):
                missing.append('4단계 원본 코드 SHA256이 지정된 보완본2와 다릅니다.')
            if meta.get('min_history_valid_count') != 300:
                missing.append('4단계 저장정보의 최소 과거 기록 조건이 300개가 아닙니다.')
            files = meta.get('files_sha256', {})
            if not files:
                missing.append('4단계 저장정보에 모델·학습행·NPZ 해시 목록이 없습니다.')
            for rel, digest in files.items():
                p = (config['stage4'] / rel).resolve()
                if not p.is_relative_to(config['stage4'].resolve()):
                    raise ValueError('저장정보의 파일 경로가 4단계 결과 폴더를 벗어납니다.')
                if not p.is_file() or sha256(p) != digest:
                    missing.append(f'4단계 저장 파일 없거나 해시 불일치: {rel}')
            if sum(str(x).endswith('.joblib') for x in files) != 2:
                missing.append('4단계 학습 모델 2개의 해시가 필요합니다.')
            if not any('학습행' in str(x) for x in files):
                missing.append('4단계 학습행 목록의 해시가 필요합니다.')
            for path in (config['stage4'] / 'IF_기록별판정').glob('*.npz'):
                rel = path.relative_to(config['stage4']).as_posix()
                if rel not in {str(x).replace('\\', '/') for x in files}:
                    missing.append(f'4단계 NPZ의 해시 누락: {rel}')
    return missing

def _npz(path):
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k].copy() for k in z.files}

def _bool(a, key, n):
    a = np.asarray(a)
    if a.shape != (n,) or a.dtype.kind != 'b':
        raise ValueError(f'{key}: 길이 {n}인 bool 배열이 필요합니다. {a.shape}, {a.dtype}')
    return a

def normalize_if(z, n):
    """센서 번호 표기만 통일한다. 점수·판정 값은 일절 바꾸지 않는다."""
    normalized = dict(z)
    schema = '4_5' if 'IF_4_valid' in z else '0_1'
    for k, index in enumerate([4, 5]):
        source = index if schema == '4_5' else k
        for field in ['valid', 'score', 'cand', 'qual']:
            aliases = [field] + ({'cand': ['candidate'], 'qual': ['qualified']}.get(field, []))
            keys = [f'IF_{source}_{a}' for a in aliases if f'IF_{source}_{a}' in z]
            if not keys:
                raise ValueError(f'센서 {index}: IF_{source}_{field} 배열이 없습니다.')
            if len(keys) > 1 and not np.array_equal(z[keys[0]], z[keys[1]], equal_nan=True):
                raise ValueError(f'동일 판정의 별칭 값이 다릅니다: {keys}')
            a = np.asarray(z[keys[0]])
            if a.shape != (n,):
                raise ValueError(f'{keys[0]}: 시각 배열과 길이가 다릅니다.')
            normalized[f'IF_{index}_{field}'] = a if field == 'score' else _bool(a, keys[0], n)
        valid, cand, qual = (normalized[f'IF_{index}_{f}'] for f in ['valid', 'cand', 'qual'])
        if np.any(cand & ~valid) or np.any(qual & ~cand):
            raise ValueError('IF는 qual ⊆ cand ⊆ valid 관계를 만족해야 합니다.')
        if not np.isfinite(normalized[f'IF_{index}_score'][valid]).all():
            raise ValueError('판정 가능한 IF 기록의 점수가 비어 있습니다.')
        availability = z.get(f'IF_{source}_qualified_available')
        if availability is not None and not np.asarray(availability).all():
            raise ValueError('이 작업의 IF 구간 판정이 저장되지 않았습니다.')
    return normalized

def iter_aligned(config):
    s3, s4 = label_dir(config, 'stage3'), label_dir(config, 'stage4')
    selected = []
    for path in sorted(s3.glob('*.npz')):
        z3 = _npz(path)
        t = np.asarray(z3['TAG_MIN_ns'])
        if t.ndim != 1 or not len(t) or t.dtype != np.dtype('int64') or np.any(t[1:] <= t[:-1]):
            raise ValueError(f'{path}: TAG_MIN_ns는 중복 없이 증가하는 정수 나노초여야 합니다.')
        first = pd.Timestamp(int(t[0]), unit='ns')
        if first.year == 2022 and first.month in [6, 7]:
            selected.append((int(path.stem), path))
    if len(selected) != config['expected_jobs']:
        raise ValueError(f"6~7월 첫 기록 작업 수 {len(selected)} != 설정 {config['expected_jobs']}")
    for job, path in selected:
        z3 = _npz(path); t = z3['TAG_MIN_ns']; n = len(t)
        z4 = _npz(s4 / f'{job}.npz')
        t4 = np.asarray(z4['TAG_MIN_ns'])
        if t4.ndim != 1 or t4.dtype != np.dtype('int64') or t4.shape != t.shape or np.any(t4[1:] <= t4[:-1]):
            raise ValueError(f'{job}: IF 시각은 중복 없이 증가하는 int64 나노초 배열이어야 합니다.')
        if not np.array_equal(t, t4):
            raise ValueError(f'{job}: 3단계와 4단계의 기록 시각/행 순서가 다릅니다.')
        z4 = normalize_if(z4, n)
        mask = np.ones(n, dtype=bool)
        for method in ['A1', 'A2']:
            for index in [4, 5]:
                v = _bool(z3[f'{method}_{index}_valid'], f'{method}_{index}_valid', n)
                q = _bool(z3[f'{method}_{index}_qual'], f'{method}_{index}_qual', n)
                if np.any(q & ~v):
                    raise ValueError(f'{job}: {method} 후보가 판정 불가 기록에 포함되어 있습니다.')
                mask &= v
        mask &= z4['IF_4_valid'] & z4['IF_5_valid']
        yield job, t, z3, z4, mask

def raw_jobs(config, job_ids):
    """원본은 읽기만 한다. 작업별 시각 정렬 이외의 보간·리샘플링을 하지 않는다."""
    ids = set(map(int, job_ids)); collected = []
    names = ['배정번호', 'TAG_MIN'] + SENSORS
    source = config['raw_csv']
    with source.open('rb') as f:
        header = f.readline()
    try:
        header.decode('utf-8-sig'); encoding = 'utf-8-sig'
    except UnicodeDecodeError:
        encoding = 'cp949'
    for chunk in pd.read_csv(source, encoding=encoding, usecols=names, chunksize=250000):
        batch = pd.to_numeric(chunk['배정번호'], errors='raise')
        if not np.isfinite(batch).all() or np.any(batch != batch.astype('int64')):
            raise ValueError('원본 배정번호가 정수가 아닙니다.')
        chunk['배정번호'] = batch.astype('int64')
        sub = chunk[chunk['배정번호'].isin(ids)].copy()
        if len(sub):
            sub['TAG_MIN'] = pd.to_datetime(sub['TAG_MIN'], errors='raise')
            for sensor in SENSORS:
                sub[sensor] = pd.to_numeric(sub[sensor], errors='raise')
            collected.append(sub)
    result = {}
    if collected:
        for job, part in pd.concat(collected, ignore_index=True).groupby('배정번호'):
            part = part.sort_values('TAG_MIN', kind='stable').reset_index(drop=True)
            if part['TAG_MIN'].duplicated().any():
                raise ValueError(f'{job}: 원본 시각 중복')
            result[int(job)] = part
    if set(result) != ids:
        raise ValueError(f'원본에서 찾지 못한 작업: {ids - set(result)}')
    return result

def input_manifest(config):
    files = [config['config_path']]
    if config['raw_csv'].is_file():
        files.append(config['raw_csv'])
    for key in ['stage3_a', 'stage3_b', 'stage4', 'iqr', 'stage4_previous', 'old_stage5']:
        p = config.get(key)
        if p and p.is_dir():
            files += [x for x in p.rglob('*') if x.is_file() and x.suffix.lower() in ['.csv', '.npz', '.json', '.txt', '.joblib', '.gz']]
    return [{'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha256(p)} for p in sorted(set(files))]
