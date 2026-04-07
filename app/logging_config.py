import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import settings

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


TEXT_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


class EventAwareTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict):
            original_msg = record.msg
            original_args = record.args
            record.msg = " ".join(f"{key}={value}" for key, value in event_data.items())
            record.args = ()
            try:
                return super().format(record)
            finally:
                record.msg = original_msg
                record.args = original_args

        return super().format(record)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        event_data = getattr(record, "event_data", None)
        if isinstance(event_data, dict):
            payload.update(event_data)

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False)


def _get_formatter() -> logging.Formatter:
    if settings.LOG_JSON_FORMAT:
        return JsonFormatter()
    return EventAwareTextFormatter(TEXT_LOG_FORMAT)


def _create_file_handler(path: Path, level: int, formatter: logging.Formatter) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=settings.LOG_ROTATION_MAX_BYTES,
        backupCount=settings.LOG_ROTATION_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setLevel(level)
    handler.setFormatter(formatter)
    return handler


def _resolve_log_dir() -> Path:
    log_dir = Path(settings.LOG_DIR)
    if not log_dir.is_absolute():
        log_dir = _PROJECT_ROOT / log_dir
    return log_dir


def configure_logging() -> None:
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    formatter = _get_formatter()
    log_dir = _resolve_log_dir()

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if settings.LOG_FILE_ENABLED:
        log_dir.mkdir(parents=True, exist_ok=True)
        root_logger.addHandler(_create_file_handler(log_dir / "app.log", log_level, formatter))
        root_logger.addHandler(_create_file_handler(log_dir / "error.log", logging.ERROR, formatter))

    access_logger = logging.getLogger("app.access")
    access_logger.setLevel(logging.INFO)
    access_logger.handlers.clear()
    access_logger.propagate = False

    if settings.LOG_ACCESS_ENABLED:
        if settings.LOG_FILE_ENABLED:
            log_dir.mkdir(parents=True, exist_ok=True)
            access_logger.addHandler(_create_file_handler(log_dir / "access.log", logging.INFO, formatter))
        else:
            access_handler = logging.StreamHandler()
            access_handler.setLevel(logging.INFO)
            access_handler.setFormatter(formatter)
            access_logger.addHandler(access_handler)

    for logger_name in ("uvicorn", "uvicorn.error"):
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()
        logger.propagate = True
        logger.setLevel(log_level)

    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    uvicorn_access_logger.handlers.clear()
    uvicorn_access_logger.propagate = False
    uvicorn_access_logger.disabled = not settings.LOG_UVICORN_ACCESS_ENABLED


def get_access_logger() -> logging.Logger:
    return logging.getLogger("app.access")
