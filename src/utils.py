"""
utils.py — Shared utilities for portfolio automation pipeline
"""
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from functools import wraps

# Setup logging
def setup_logger(name="portfolio_automation"):
    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"{datetime.now().strftime('%Y%m%d')}_pipeline.log"

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def retry(max_attempts=3, delay=2, backoff=2, exceptions=(Exception,)):
    """Retry decorator with exponential backoff."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempts, current_delay = 0, delay
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    attempts += 1
                    if attempts == max_attempts:
                        raise
                    time.sleep(current_delay)
                    current_delay *= backoff
            return None
        return wrapper
    return decorator


def get_project_root():
    return Path(__file__).parent.parent


def get_config_path(filename):
    return get_project_root() / "config" / filename


def get_output_path(filename):
    out = get_project_root() / "output"
    out.mkdir(exist_ok=True)
    return out / filename


def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
