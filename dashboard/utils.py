import pandas as pd
import os
import logging
from poc.logging_utils import INGESTION_LOG_PATH, SEARCH_LOG_PATH, GENERATION_LOG_PATH

logger = logging.getLogger(__name__)

def load_ingestion_data() -> pd.DataFrame:
    if not os.path.exists(INGESTION_LOG_PATH):
        return pd.DataFrame()
    try:
        df = pd.read_csv(INGESTION_LOG_PATH)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        return df
    except Exception as e:
        logger.error(f"Error loading ingestion data: {e}")
        return pd.DataFrame()

def load_search_data() -> pd.DataFrame:
    if not os.path.exists(SEARCH_LOG_PATH):
        return pd.DataFrame()
    try:
        df = pd.read_csv(SEARCH_LOG_PATH)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        return df
    except Exception as e:
        logger.error(f"Error loading search data: {e}")
        return pd.DataFrame()

def load_generation_data() -> pd.DataFrame:
    if not os.path.exists(GENERATION_LOG_PATH):
        return pd.DataFrame()
    try:
        df = pd.read_csv(GENERATION_LOG_PATH)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
        return df
    except Exception as e:
        logger.error(f"Error loading generation data: {e}")
        return pd.DataFrame()
