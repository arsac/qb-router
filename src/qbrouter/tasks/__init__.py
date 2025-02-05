import importlib
import os
import sys

from qbrouter import logger


def get_tasks():
    tasks = []
    tasks_dir = os.path.dirname(__file__)
    for f in os.listdir(tasks_dir):
        if f.startswith("__") or not f.endswith(".py"):
            continue
        try:

            task = f"tasks.{f[:-3]}"
            mod = importlib.import_module(task)
            globals()[task] = mod
        except ImportError:
            logger.error(f"Error loading module: {f[:-3]}", exc_info=True)
            sys.exit(1)
        else:
            tasks.append(mod)
    return tasks
