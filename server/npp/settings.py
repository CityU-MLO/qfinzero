import os
from pathlib import Path
from datetime import timedelta

# 项目路径配置
PROJECT_ROOT = Path(__file__).parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
OUTPUTS_DIR = DATA_DIR / "outputs"

# 数据源配置
FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
STOCKBENCH_DATA_PATH = str(RAW_DATA_DIR / "news_by_day")

# 经济事件配置
ECON_EVENT_IMPORTANCE_THRESHOLD = 2  # 最小重要性阈值 (1-3)
ECON_EVENT_COUNTRIES = ["US", "CN", "EU", "JP", "GB"]  # 关注的国家

# 管道配置
DEFAULT_LOOKBACK_DAYS = 30
MAX_NEWS_ITEMS_PER_DAY = 1000
BATCH_SIZE = 100

# 数据库配置
DATABASE_CONFIG = {
    'raw_news_db': str(OUTPUTS_DIR / "raw_news.db"),
    'trading_day_db': str(OUTPUTS_DIR / "trading_day_collection.db"),
    'earnings_db': str(OUTPUTS_DIR / "earnings.db")
}

# 日志配置
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
    },
    'handlers': {
        'default': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.StreamHandler',
        },
        'file': {
            'level': 'DEBUG',
            'formatter': 'standard',
            'class': 'logging.FileHandler',
            'filename': str(OUTPUTS_DIR / 'pipeline.log'),
            'mode': 'a',
        },
    },
    'loggers': {
        '': {
            'handlers': ['default', 'file'],
            'level': 'INFO',
            'propagate': True
        }
    }
}

# 确保目录存在
for directory in [RAW_DATA_DIR, PROCESSED_DATA_DIR, OUTPUTS_DIR]:
    directory.mkdir(parents=True, exist_ok=True)