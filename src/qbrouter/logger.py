import logging
import os
import sys

logger = logging.getLogger('qbrouter')

logging.basicConfig(
        stream=sys.stdout,
        level=logging.DEBUG if os.environ.get('DEBUG', None) else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%I:%M:%S %p",
    )

