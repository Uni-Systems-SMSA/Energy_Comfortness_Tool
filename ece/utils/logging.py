from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler

def init_logger(name: str,
                log_dir: Path = Path("logs"),
                level: int = logging.INFO,
                max_bytes: int = 2_000_000,
                backup_count: int = 3) -> logging.Logger:

    log_dir.mkdir(exist_ok=True, parents=True)
    logger = logging.getLogger(name)
    if logger.handlers:        # already initialised
        return logger

    logger.setLevel(level)
    fmt = "%(asctime)s — %(levelname)s — %(name)s — %(message)s"
    formatter = logging.Formatter(fmt)

    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    fh = RotatingFileHandler(
        log_dir / f"{name}.log",
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    logger.propagate = False
    return logger
