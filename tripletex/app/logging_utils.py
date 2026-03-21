from __future__ import annotations

import logging
import os
from contextvars import ContextVar, Token


_request_id_var: ContextVar[str] = ContextVar("tripletex_request_id", default="-")
_configured = False


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_var.get("-")
        return True


def configure_logging() -> None:
    global _configured
    if _configured:
        return

    level_name = os.getenv("LOG_LEVEL", "DEBUG").upper()
    level = getattr(logging, level_name, logging.DEBUG)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s request_id=%(request_id)s %(name)s %(message)s",
        force=True,
    )
    request_filter = RequestIdFilter()
    root_logger = logging.getLogger()
    root_logger.addFilter(request_filter)
    for handler in root_logger.handlers:
        handler.addFilter(request_filter)

    # Keep application logs at DEBUG while preventing dependency wire logs from flooding Cloud Run.
    for logger_name, logger_level in (
        ("google", logging.INFO),
        ("google.auth", logging.INFO),
        ("google_genai", logging.WARNING),
        ("httpcore", logging.INFO),
        ("httpx", logging.INFO),
        ("urllib3", logging.INFO),
    ):
        logging.getLogger(logger_name).setLevel(logger_level)

    _configured = True


def set_request_id(request_id: str) -> Token[str]:
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str]) -> None:
    _request_id_var.reset(token)


def get_request_id() -> str:
    return _request_id_var.get("-")
