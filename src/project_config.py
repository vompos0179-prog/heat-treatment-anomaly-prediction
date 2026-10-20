"""모든 팀원이 같은 데이터 위치·인코딩·난수 기준을 사용하기 위한 설정."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / 'data' / 'raw'
INTERIM_DIR = PROJECT_ROOT / 'data' / 'interim'
PROCESSED_DIR = PROJECT_ROOT / 'data' / 'processed'
FIGURES_DIR = PROJECT_ROOT / 'figures'
REPORTS_DIR = PROJECT_ROOT / 'reports'
RAW_CSV = RAW_DIR / 'data.csv'
QUALITY_XLSX = RAW_DIR / '열처리_품질데이터.xlsx'
RAW_ENCODING = 'cp949'
OUTPUT_ENCODING = 'utf-8-sig'
RANDOM_STATE = 42


def set_korean_font():
    """설치된 한글 폰트 선택. 없으면 조용히 깨뜨리지 않고 안내합니다."""
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    available = {font.name for font in font_manager.fontManager.ttflist}
    for name in ['Malgun Gothic', 'AppleGothic', 'NanumGothic', 'Noto Sans CJK KR', 'Noto Sans CJK JP']:
        if name in available:
            plt.rcParams['font.family'] = name
            plt.rcParams['axes.unicode_minus'] = False
            return name
    return None
