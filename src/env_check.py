"""실행 환경 확인 — 권장 환경과 다르면 경고만 보여 주고 실행은 계속합니다.

권장 환경: Python 3.12 + requirements.txt에 적힌 패키지 버전.
버전이 다르면 계산 결과(특히 소수점 끝자리, 경계에 걸린 기록 판정)가 README 기대값과 조금 다를 수 있어 알려 줍니다.
가상환경(.venv)·conda·시스템 파이썬 어느 것으로 실행해도 됩니다.
pandas 등이 없어도 이 안내가 먼저 나오도록 표준 라이브러리만 씁니다.
"""
import sys
from importlib import metadata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
# 모든 단계가 쓰는 패키지(xgboost는 5단계 품질 예측만 쓰므로 그 코드에서 따로 확인)
CORE_PACKAGES = ['numpy', 'pandas', 'matplotlib', 'scipy', 'scikit-learn', 'openpyxl', 'joblib']


def required_versions(project=PROJECT_ROOT):
    """requirements.txt에서 `이름==버전` 줄만 읽어 {이름: 버전}으로 돌려줍니다."""
    pins = {}
    req = Path(project) / 'requirements.txt'
    if req.is_file():
        for line in req.read_text(encoding='utf-8-sig').splitlines():
            line = line.split('#')[0].strip()
            if '==' in line:
                name, version = line.split('==', 1)
                pins[name.strip()] = version.strip()
    return pins


def check_python_env(project=PROJECT_ROOT, packages=CORE_PACKAGES):
    """권장 환경과 다른 점을 찾아 [주의]로 보여 줍니다. 멈추지 않고, 다른 점 목록을 돌려줍니다."""
    pins = required_versions(project)
    problems = []
    if sys.version_info[:2] != (3, 12):
        problems.append(f'Python {sys.version.split()[0]} (권장 3.12)')
    for name in packages:
        want = pins.get(name)
        try:
            have = metadata.version(name)
        except metadata.PackageNotFoundError:
            problems.append(f'{name}: 설치되지 않음' + (f' (권장 {want})' if want else ''))
            continue
        if want and have != want:
            problems.append(f'{name} {have} (권장 {want})')
    if problems:
        print('[주의] 권장 실행 환경과 다른 점이 있습니다. 실행은 계속합니다.')
        for item in problems:
            print(f'  - {item}')
        print('  결과 숫자가 README 기대값과 조금 다를 수 있습니다. 권장 환경 만들기:')
        print('    python -m pip install -r requirements.txt   (Python 3.12에서)')
    return problems
