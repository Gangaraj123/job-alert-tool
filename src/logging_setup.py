import logging
from pathlib import Path

from .config import ROOT_DIR, load_config


def setup_logging() -> logging.Logger:
    cfg = load_config().get("logging", {})
    level = getattr(logging, cfg.get("level", "INFO").upper(), logging.INFO)
    log_file = ROOT_DIR / cfg.get("file", "job_alert.log")

    logger = logging.getLogger("job_alert")
    if logger.handlers:
        return logger  # already configured (e.g. re-imported in Streamlit)

    logger.setLevel(level)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    console = logging.StreamHandler()
    console.setFormatter(fmt)
    logger.addHandler(console)

    try:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)
    except OSError:
        pass  # read-only filesystem (e.g. some CI/hosting envs) - console only

    return logger
