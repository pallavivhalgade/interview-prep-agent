"""
Centralized logger setup.

Every module imports `get_logger(__name__)` instead of configuring
logging separately - keeps log format consistent across the app.
"""

import logging
from src.config import LOG_LEVEL, LOG_FILE


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)

    if not logger.handlers:  # avoid duplicate handlers on Streamlit re-runs
        logger.setLevel(LOG_LEVEL)

        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # Console handler - visible in terminal / Streamlit Cloud logs
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

        # File handler - persists locally for debugging
        try:
            file_handler = logging.FileHandler(LOG_FILE)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except OSError:
            # Streamlit Cloud's filesystem can be read-only in some cases -
            # console logging alone is fine if file logging isn't available
            pass

    return logger
