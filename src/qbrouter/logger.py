import logging
import os
import sys

# Configure the root logger
logging.basicConfig(
    stream=sys.stdout,
    level=logging.DEBUG if os.environ.get("DEBUG", None) else logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s]: %(message)s",
    datefmt="%I:%M:%S %p",
)

# Main logger
logger = logging.getLogger("qbrouter")


def get_task_logger(task_name: str) -> logging.Logger:
    """Get a logger for a specific task with task name in the logger name."""
    return logging.getLogger(f"qbrouter.{task_name}")


def get_contextual_logger(context: str) -> logging.Logger:
    """Get a logger with custom context."""
    return logging.getLogger(f"qbrouter.{context}")


class ContextualLoggerAdapter(logging.LoggerAdapter):
    """Logger adapter that adds contextual information to log messages."""

    def __init__(self, logger, context):
        super().__init__(logger, {})
        self.context = context

    def process(self, msg, kwargs):
        return f"[{self.context}] {msg}", kwargs


def get_adapter_logger(task_name: str, context: str = None) -> logging.LoggerAdapter:
    """Get a logger adapter with task and optional context information."""
    base_logger = get_task_logger(task_name)
    if context:
        return ContextualLoggerAdapter(base_logger, context)
    return ContextualLoggerAdapter(base_logger, task_name)
