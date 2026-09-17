from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
IMAGE_DIR = PROJECT_ROOT / "images"
RESULT_DIR = PROJECT_ROOT / "results"

# 실제 데이터 확인 후 아래 값을 수정합니다.
TARGET_COLUMN = None
TIME_COLUMN = None
EQUIPMENT_ID_COLUMN = None
