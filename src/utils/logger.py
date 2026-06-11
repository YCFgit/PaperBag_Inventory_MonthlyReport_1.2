from __future__ import annotations

import logging
from pathlib import Path


class _RunIdFilter(logging.Filter):
    def __init__(self, run_id: str) -> None:
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "run_id"):
            record.run_id = self.run_id
        return True


def configure_logger(runtime_root: Path, run_id: str, logger_name: str = "paper_bag_monthly_report") -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [run_id=%(run_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    run_id_filter = _RunIdFilter(run_id)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(run_id_filter)
    logger.addHandler(console_handler)

    log_dir = runtime_root / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "app.log", encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(run_id_filter)
        logger.addHandler(file_handler)
    except PermissionError:
        logger.warning("Log directory is not writable in current environment; using console logging only.")

    return logging.LoggerAdapter(logger, {"run_id": run_id})
